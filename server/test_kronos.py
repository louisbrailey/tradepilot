import io
import json
import math
import subprocess
import unittest
from email.message import Message
from unittest.mock import patch, Mock
import kronos_service as k
import server


def bars():
    return [dict(t=1700000000000+i*86400000, o=100+i, h=102+i, l=99+i, c=101+i, v=1000) for i in range(160)]


class KronosTests(unittest.TestCase):
    def test_holdout_prices_never_enter_model_and_baseline_is_last_input(self):
        rows = bars()
        def model(history, dates, samples):
            self.assertEqual(history, rows[-133:-5])
            self.assertEqual(dates, [b['t'] for b in rows[-5:]])
            self.assertEqual(samples, 3)
            return {'paths': [[history[-1]['c']]*5]*3}
        with patch.object(k, 'fetch_bars', return_value=rows), patch.object(k, 'infer', side_effect=model):
            result = k.replay({'ticker':'AAPL','horizon':5})
        self.assertEqual(result['mae'], 3)
        self.assertEqual(result['mae'], result['baseline_mae'])
        self.assertEqual(result['points'][0]['date'], k.day(rows[-5]['t']))
        self.assertEqual(result['input_end'], k.day(rows[-6]['t']))
        self.assertEqual(result['mode'], 'historical_replay')

    def test_invalid_requests_do_no_work(self):
        with patch.object(k,'fetch_bars') as fetch:
            for payload in [[], None, {'ticker':'../private'}, {'ticker':'AAPL','horizon':True},
                            {'ticker':'AAPL','horizon':120}, {'ticker':'AAPL','file_path':'x'}]:
                with self.assertRaises(ValueError): k.replay(payload)
        fetch.assert_not_called()

    def test_lock_recovers_after_failure(self):
        with patch.object(k,'fetch_bars', side_effect=k.KronosError('failed')):
            for _ in range(2):
                with self.assertRaisesRegex(k.KronosError,'failed'): k.replay({'ticker':'AAPL'})

    def test_busy_is_explicit(self):
        k._LOCK.acquire()
        try:
            with self.assertRaisesRegex(k.KronosError,'already running'): k.replay({'ticker':'AAPL'})
        finally: k._LOCK.release()

    def test_subprocess_does_not_inherit_credentials(self):
        completed = Mock(returncode=0, stdout=json.dumps({'paths':[[1]*5]*3}))
        with patch.dict(k.os.environ, {'WEBULL_APP_SECRET':'must-not-leak','MASSIVE_API_KEY':'private'}), \
             patch.object(k,'status', return_value={'configured':True}), patch.object(k.subprocess,'run',return_value=completed) as run:
            k.infer(bars()[:128], [1]*5, 3)
        env = run.call_args.kwargs['env']
        self.assertNotIn('WEBULL_APP_SECRET',env)
        self.assertNotIn('MASSIVE_API_KEY',env)
        self.assertEqual(env['HF_HUB_OFFLINE'],'1')

    def test_invalid_model_output_and_timeout_are_sanitized(self):
        with patch.object(k,'status',return_value={'configured':True}):
            for val in [float('nan'), float('inf'), -1, True]:
                completed=Mock(returncode=0,stdout=json.dumps({'paths':[[val]*5]*3}))
                with patch.object(k.subprocess,'run',return_value=completed), self.assertRaises(k.KronosError):
                    k.infer([], [1]*5, 3)
            with patch.object(k.subprocess,'run',side_effect=subprocess.TimeoutExpired('secret',90)), self.assertRaisesRegex(k.KronosError,'timed out'):
                k.infer([], [1]*5, 3)

    def test_market_data_rejects_partial_and_unadjusted(self):
        with patch.object(k,'Massive') as provider:
            for source in [{'available':False}, {'available':True,'partial_page':True,'adjusted':True},
                           {'available':True,'adjusted':False}]:
                provider.return_value.get.return_value=source
                with self.assertRaises(k.KronosError): k.fetch_bars('AAPL')

    def test_gateway_authentication_and_no_broker_calls(self):
        for auth, expected in [(False,401),(True,200)]:
            handler=server.Handler.__new__(server.Handler); handler.path='/v1/kronos/replay'
            handler.headers=Message()
            if auth: handler.headers['Authorization']='Bearer '+'x'*32
            raw=b'{"ticker":"AAPL","horizon":5}'
            handler.headers['Content-Type']='application/json';handler.headers['Content-Length']=str(len(raw))
            handler.rfile=io.BytesIO(raw); responses=[]
            handler.reply=lambda code,payload:responses.append(code)
            with patch.dict(server.os.environ,{'APP_ACCESS_TOKEN':'x'*32}), \
                 patch.object(server,'kronos_request',return_value={}) as kr, patch.object(server,'broker') as broker:
                handler.do_POST()
            self.assertEqual(responses,[expected]);self.assertEqual(kr.called,auth);broker.assert_not_called()


if __name__ == '__main__': unittest.main()
