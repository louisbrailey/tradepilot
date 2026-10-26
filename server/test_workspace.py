import io
import json
import os
import tempfile
import time
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
import server
import workspace_service as workspace
from paper_service import PaperService
from webull_service import BrokerError


class WorkspaceTests(unittest.TestCase):
    def test_network_restart_drains_requests_and_returns_failure_for_launchd(self):
        import threading
        ready, shutdown = threading.Event(), threading.Event()
        events = []
        class FakeServer:
            def serve_forever(self):
                ready.set()
                if not shutdown.wait(2): raise AssertionError('watcher did not shut down')
                events.append('serve stopped')
            def shutdown(self):
                if not ready.wait(2): raise AssertionError('server did not start')
                shutdown.set()
            def server_close(self): events.append('workers drained')
        def watch(interface, address, stopped, restart):
            self.assertEqual(interface, 'en0'); restart()
        self.assertEqual(server.serve_with_network_watch(FakeServer(), '192.168.1.20', 'en0', watch), 75)
        self.assertEqual(events, ['serve stopped', 'workers drained'])
        self.assertFalse(server.GatewayHTTPServer.daemon_threads)

    def test_all_workspace_routes_require_auth_before_any_provider(self):
        for path in workspace.WORKSPACE_ROUTES:
            h = server.Handler.__new__(server.Handler)
            h.path, h.headers = path, Message()
            replies = []
            h.reply = lambda code, result: replies.append(code)
            with patch.dict(os.environ, {'APP_ACCESS_TOKEN': 'x'*32}), patch.object(server, 'workspace_request') as dispatch:
                h.do_POST()
            self.assertEqual(replies, [401])
            dispatch.assert_not_called()

    def test_strict_read_requests_do_not_initialize_or_contact_services(self):
        for route in ('/v1/paper/state', '/v1/paper/mark', '/v1/coinbase/state'):
            with patch.object(workspace, 'paper') as ledger, patch.object(workspace, 'CoinbaseAdapter') as coinbase:
                with self.assertRaises(BrokerError):
                    workspace.workspace_request(route, {'path': '/private/file'})
            ledger.assert_not_called(); coinbase.assert_not_called()

    def test_paper_review_cannot_supply_price_and_quote_is_server_owned(self):
        request = dict(symbol='AAPL', side='buy', quantity='2', client_id='request-1234')
        quote = dict(symbol='AAPL', price='100', as_of=time.time()-3600, source='test quote', delayed=True)
        with tempfile.TemporaryDirectory() as folder:
            service = PaperService(Path(folder)/'paper.sqlite3')
            with patch.object(workspace, 'paper', return_value=service), patch.object(workspace, 'paper_quote', return_value=quote) as fetch:
                with self.assertRaises(BrokerError):
                    workspace.workspace_request('/v1/paper/review', {**request, 'price':'1'})
                fetch.assert_not_called()
                review = workspace.workspace_request('/v1/paper/review', request)
                self.assertEqual(service.state()['cash'], '10000')
                receipt = workspace.workspace_request('/v1/paper/confirm', {'id':review['id'],'token':review['token'],'approved':True})
                again = workspace.workspace_request('/v1/paper/confirm', {'id':review['id'],'token':review['token'],'approved':True})
            self.assertEqual(receipt, again)
            self.assertEqual(service.state()['cash'], '9799.800')
            self.assertEqual(service.state()['positions'][0]['quantity'], '2')

    def test_strategy_request_cannot_use_arbitrary_paths_or_symbols(self):
        with patch.object(workspace, 'recent_bars') as bars:
            for payload in ({'ticker':'../key'}, {'ticker':'AAPL','path':'private'}, {'ticker':True}, []):
                with self.assertRaises(BrokerError):
                    workspace.workspace_request('/v1/strategies', payload)
        bars.assert_not_called()

    def test_coinbase_only_reads_explicit_private_config(self):
        with patch.dict(os.environ, {'COINBASE_API_KEY_NAME':'test-name','COINBASE_API_PRIVATE_KEY':'test-private'}, clear=True), patch.object(workspace, 'CoinbaseAdapter') as adapter:
            adapter.return_value.state.return_value = {'broker':'coinbase','read_only':True}
            result = workspace.workspace_request('/v1/coinbase/state', {})
            adapter.assert_called_once_with('test-name','test-private')
        self.assertTrue(result['read_only'])

    def test_completed_daily_reference_requires_confirmed_unadjusted_data(self):
        from datetime import datetime, timedelta, timezone
        stamp = datetime.combine(datetime.now(timezone.utc).date()-timedelta(days=1), datetime.min.time(), timezone.utc).timestamp()*1000
        bars = [{'t':stamp,'o':1e-8,'h':1e-8,'l':1e-8,'c':1e-8}]
        with patch.object(workspace, 'Massive') as provider:
            provider.return_value.get.return_value = {'available':True,'adjusted':True,'results':bars}
            with self.assertRaises(BrokerError): workspace.paper_quote('AAPL')
            provider.return_value.get.return_value['adjusted'] = False
            quote = workspace.paper_quote('AAPL')
        self.assertEqual(quote['price'], '0.00000001')
        self.assertTrue(quote['delayed'])
        from zoneinfo import ZoneInfo
        close = datetime.fromtimestamp(stamp/1000, timezone.utc).date()
        expected = datetime.combine(close, datetime.min.time(), ZoneInfo('America/New_York')).replace(hour=16).timestamp()
        self.assertEqual(quote['as_of'], expected)

    def test_reference_close_survives_monday_holiday(self):
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        new_york = ZoneInfo('America/New_York')
        friday = datetime(2026, 9, 4, tzinfo=timezone.utc).timestamp()*1000  # before Labor Day
        tuesday_open = datetime(2026, 9, 8, 10, tzinfo=new_york).timestamp()
        bars = [{'t':friday,'o':100,'h':101,'l':99,'c':100}]
        with patch.object(workspace, 'Massive') as provider, patch.object(workspace, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 9, 8, 14, tzinfo=timezone.utc)
            provider.return_value.get.return_value = {'available':True,'adjusted':False,'results':bars}
            quote = workspace.paper_quote('AAPL')
        with tempfile.TemporaryDirectory() as folder:
            service = PaperService(Path(folder)/'paper.sqlite', clock=lambda: tuesday_open)
            review = service.create_review(dict(symbol='AAPL', side='buy', quantity='1', client_id='holiday_01'), quote)
        self.assertEqual(review['status'], 'REVIEW')

    def test_authenticated_route_exercises_actual_paper_dispatch(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'TRADEPILOT_RUNTIME':folder,'APP_ACCESS_TOKEN':'x'*32}):
            h = server.Handler.__new__(server.Handler); h.path='/v1/paper/state'; h.headers=Message()
            for k,v in [('Authorization','Bearer '+'x'*32),('Content-Type','application/json'),('Content-Length','2')]:h.headers[k]=v
            h.rfile=io.BytesIO(b'{}'); replies=[];h.reply=lambda code,result:replies.append((code,result))
            h.do_POST()
            self.assertEqual(replies[0][0],200);self.assertEqual(replies[0][1]['mode'],'paper')
            self.assertEqual(replies[0][1]['cash'],'10000')
            workspace._services.pop(Path(folder).resolve(),None)

if __name__ == '__main__': unittest.main()
