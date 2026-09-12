#!/usr/bin/env python3
"""Pure client regression tests; no debugger or application is launched."""
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import debugger

class ClientContractTests(unittest.TestCase):
    def test_early_stop_is_not_lost(self):
        state={'ok':True,'state':'stopped','stop_token':'new','breakpoint_ids':[7]}
        with patch.object(debugger,'exchange',return_value=state):
            self.assertTrue(debugger.wait_stop('unused','old',.1,7)['ok'])

    def test_partial_coverage_is_not_definite_breakpoint_miss(self):
        state={'ok':True,'state':'stopped','stop_token':'new','breakpoint_ids':[], 'stop_reason_coverage_complete':False}
        with patch.object(debugger,'exchange',return_value=state):
            r=debugger.wait_stop('unused','old',.1,7)
            self.assertFalse(r['ok']); self.assertIn('incomplete',r['error'])

    def test_unexpected_stop_is_not_auto_resumed(self):
        state={'ok':True,'state':'stopped','stop_token':'new','breakpoint_ids':[8], 'stop_reason_coverage_complete':True}
        with patch.object(debugger,'exchange',return_value=state) as exchange:
            r=debugger.wait_stop('unused','old',.1,7)
            self.assertIn('different stop',r['error'])
            self.assertEqual(exchange.call_args.args[1],{'op':'status'})

    def test_wait_timeout_does_not_cancel_process(self):
        state={'ok':True,'state':'running','stop_token':None}
        with patch.object(debugger,'exchange',return_value=state) as exchange:
            r=debugger.wait_stop('unused','old',.03)
            self.assertFalse(r['ok']); self.assertIn('NOT canceled',r['error'])
            self.assertTrue(all(c.args[1]=={'op':'status'} for c in exchange.call_args_list))

    def test_exit_is_terminal_not_requested_stop(self):
        with patch.object(debugger,'exchange',return_value={'ok':True,'state':'exited'}):
            self.assertFalse(debugger.wait_stop('unused','old',.1)['ok'])

    def test_fragmented_response_and_literal_lldb_prompt(self):
        with tempfile.TemporaryDirectory(prefix='code-state-client-test-') as folder, socket.socket() as server:
            server.bind(('127.0.0.1',0));server.listen(1)
            Path(folder,'connection.json').write_text(json.dumps({'port':server.getsockname()[1],'token':'artificial-test-token'}))
            expected={'ok':True,'output':'literal (lldb) is ordinary app text\nnot framing'}
            errors=[]
            def serve_once():
                try:
                    with server.accept()[0] as conn:
                        request=bytearray()
                        while b'\n' not in request:request.extend(conn.recv(4096))
                        self.assertEqual(json.loads(request)['request'],{'op':'output'})
                        payload=json.dumps(expected).encode()+b'\n'
                        for i in range(0,len(payload),3):conn.sendall(payload[i:i+3])
                except BaseException as e:errors.append(e)
            thread=threading.Thread(target=serve_once);thread.start()
            self.assertEqual(debugger.exchange(folder,{'op':'output'}),expected)
            thread.join(2);self.assertFalse(thread.is_alive());self.assertFalse(errors)

if __name__=='__main__':unittest.main()
