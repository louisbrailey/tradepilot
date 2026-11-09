"""Synthetic ownership refusals and a separate owned loopback process."""
import os
import queue
import socket
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch

import service_preflight as check

LOCAL=('127.0.0.1',50222)
REMOTE=('127.0.0.1',11434)
ROWS=[(LOCAL,REMOTE,100),(REMOTE,LOCAL,200)]
HOST=(1,'20261108160000.000000-480','pythonservice.exe')
CHILD=(10,'20261108160100.000000-480','ollama.exe')
PROCESSES={10:HOST,200:CHILD}


class ConnectedOwnerTests(unittest.TestCase):
    def test_requires_both_unique_directions_and_own_client_pid(self):
        self.assertEqual(check.connected_owner(ROWS,LOCAL,REMOTE,100),200)
        cases=[ROWS[:1],ROWS[1:],ROWS+[ROWS[0]],ROWS+[ROWS[1]],
               [(LOCAL,REMOTE,101),ROWS[1]],[ROWS[0],(REMOTE,LOCAL,100)],
               [ROWS[0],(REMOTE,('127.0.0.1',50223),200)],
               [ROWS[0],(('0.0.0.0',11434),LOCAL,200)]]
        for rows in cases:
            with self.subTest(rows=rows),self.assertRaises(ValueError):
                check.connected_owner(rows,LOCAL,REMOTE,100)

    def test_stable_service_ancestry_includes_creation_identity(self):
        check.stable_descendant(PROCESSES,dict(PROCESSES),10,200)
        for pid,record in [(200,(10,'20261108160200.000000-480','ollama.exe')),
                           (200,(99,CHILD[1],CHILD[2])),(10,(1,HOST[1],'other.exe'))]:
            changed=dict(PROCESSES);changed[pid]=record
            with self.subTest(record=record),self.assertRaises(ValueError):
                check.stable_descendant(PROCESSES,changed,10,200)
        for records in ({10:HOST}, {10:HOST,200:(200,CHILD[1],CHILD[2])},
                        {10:HOST,200:(10,'20261108155900.000000-480','ollama.exe')},
                        {10:HOST,200:(10,'','ollama.exe')},
                        {10:HOST,200:(10,CHILD[1],'impostor.exe')}):
            with self.subTest(records=records),self.assertRaises(ValueError):
                check.stable_descendant(records,dict(records),10,200)

    def test_service_pid_change_and_peer_change_fail(self):
        probe=Mock();probe.__enter__=Mock(return_value=probe);probe.__exit__=Mock(return_value=False)
        probe.getsockname.return_value=LOCAL;probe.getpeername.return_value=REMOTE
        with patch.object(check.socket,'socket',return_value=probe),patch.object(check,'process_snapshot',return_value=PROCESSES),patch.object(check,'tcp_owners',return_value=ROWS),patch.object(check.os,'getpid',return_value=100):
            with patch.object(check,'ollama_service_pid',side_effect=[10,11]),self.assertRaises(ValueError):
                check.ollama_service_listener()
            with patch.object(check,'ollama_service_pid',return_value=10):
                self.assertEqual(check.ollama_service_listener(),{'service_pid':10,'listener_pid':200,'proof':'held_connected_tcp_pair'})
                probe.getpeername.side_effect=[REMOTE,('127.0.0.1',11435)]
                with self.assertRaises(ValueError):check.ollama_service_listener()
        self.assertTrue(probe.__exit__.called)

    def test_creation_time_requires_a_real_wmi_timestamp(self):
        self.assertEqual(check.created_at(HOST[1]).isoformat(),'2026-11-09T00:00:00+00:00')
        for value in ('','20261108160000','20261108160000.000000***'):
            with self.subTest(value=value),self.assertRaises(ValueError):check.created_at(value)

    @unittest.skipUnless(os.name=='nt','Windows native TCP owner table')
    def test_real_owned_socket_pair_identifies_separate_child(self):
        code="import socket,os; s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(1); print(s.getsockname()[1],os.getpid(),flush=True); c,_=s.accept(); c.recv(1); c.close(); s.close()"
        child=subprocess.Popen([sys.executable,'-I','-B','-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        ready=queue.Queue()
        reader=threading.Thread(target=lambda:ready.put(child.stdout.readline(32)),daemon=True)
        reader.start()
        try:
            port,server_pid=map(int,ready.get(timeout=5).split())
            with socket.create_connection(('127.0.0.1',port),timeout=3) as probe:
                local,remote=probe.getsockname(),probe.getpeername()
                import time
                deadline=time.monotonic()+2
                while True:
                    try:owner=check.connected_owner(check.tcp_owners(),local,remote,os.getpid());break
                    except ValueError:
                        if time.monotonic()>=deadline:raise
                        time.sleep(.05)
                self.assertNotEqual(server_pid,os.getpid())
                self.assertEqual(owner,server_pid)
            child.wait(3)
        finally:
            if child.poll() is None:child.kill();child.wait(3)
            reader.join(1)
            child.stdout.close();child.stderr.close()


if __name__=='__main__':unittest.main()
