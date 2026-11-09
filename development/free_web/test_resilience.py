"""Failure injection for restart, transport and history preparation boundaries."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
import threading
import time
import os
from unittest.mock import patch
from resilience import retry, Journal, atomic_json
from history_preflight import check, ready


class ResilienceTests(unittest.TestCase):
    def test_large_file_rpc_response_and_identity(self):
        from operation_runner import ConnectorRPC
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'JRA_RPC_DIRECTORY':root}):
            transport=ConnectorRPC()
            def broker():
                request=Path(root)/'request-1.json'
                while not request.exists():time.sleep(.01)
                data=json.loads(request.read_text(encoding='utf-8'))
                self.assertEqual(data['method'],'fetch')
                atomic_json(Path(root)/'response-1.json',{'id':1,'result':{'large':'x'*200000}})
            worker=threading.Thread(target=broker);worker.start()
            value=transport('fetch',{'url':'https://example.test'})
            worker.join(timeout=3)
            self.assertEqual(len(value['large']),200000)
    def test_retry_transport_but_not_validation_or_access_denied(self):
        calls=[]
        def work():
            calls.append(1)
            if len(calls)<3:raise TimeoutError('timeout')
            return 'ok'
        delays=[]
        self.assertEqual(retry(work,sleep=delays.append),'ok')
        self.assertEqual(delays,[2,4])
        for error in (ValueError('stale'),urllib.error.HTTPError('https://example.test',403,'Forbidden',{},None)):
            with self.assertRaises(type(error)),patch('resilience.time.sleep'):
                retry(lambda:(_ for _ in ()).throw(error),sleep=lambda _:self.fail('Permanent failure retried'))

    def test_bounded_attempts_and_guard(self):
        calls=[]
        def fail():calls.append(1);raise ConnectionResetError('reset')
        with self.assertRaises(ConnectionResetError):retry(fail,sleep=lambda _:None)
        self.assertEqual(len(calls),4)
        with self.assertRaises(ValueError):retry(lambda:self.fail('Guard bypassed'),guard=lambda:(_ for _ in ()).throw(ValueError('expired')))

    def test_restart_hash_lock_and_release(self):
        with tempfile.TemporaryDirectory() as root:
            first=Journal(root,'race')
            with first.locked():
                first.save('prepared',{'race':'original'})
                with self.assertRaises(OSError):
                    with Journal(root,'race').locked():pass
            second=Journal(root,'race')
            with second.locked():self.assertEqual(second.prepared(),{'race':'original'})
            data=json.loads(second.path.read_text(encoding='utf-8'))
            data['payload']['record']['race']='changed'
            atomic_json(second.path,data)
            with self.assertRaisesRegex(ValueError,'hash mismatch'):second.prepared()

    def test_history_missing_day_stops_preflight_and_changed_bytes_stop_live(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)
            (path/'history.parquet').write_bytes(b'private historical bytes')
            atomic_json(path/'coverage_manifest.json',{'history_sha256':hashlib.sha256(b'private historical bytes').hexdigest(),'history_complete_through':'2026-11-01'})
            def gap(*args):raise ValueError('History missing completed JRA race days: 2026-11-07')
            with self.assertRaisesRegex(ValueError,'missing completed'):check(root,'2026-11-07',gap)
            self.assertFalse((path/'preflight.json').exists())
            check(root,'2026-11-06',lambda *args:('2026-11-06',[{'source':'calendar'}]))
            self.assertEqual(ready(root,'2026-11-06')[0],'2026-11-06')
            with self.assertRaises(ValueError):ready(root,'2026-11-07')
            (path/'history.parquet').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'changed'):ready(root,'2026-11-06')

    def test_uncertain_github_write_reconciles_without_duplicate(self):
        from operation_runner import GitHub
        class Remote(GitHub):
            def __init__(self):
                self.saved=None;self.writes=0;self.stage=None;self.write_guard=None
                self.call=self.rpc
            def optional(self,path):return self.saved
            def rpc(self,method,args):
                self.writes+=1;self.saved=args['content']
                raise TimeoutError('response lost after successful create')
            def get(self,suffix):return [{'sha':'a'*40}]
            def verify(self,path,content,sha):return content,content,'2026-11-09T00:00:00Z'
        remote=Remote()
        with patch('operation_runner.retry',side_effect=lambda f:retry(f,sleep=lambda _:None)):
            sha,verified=remote.save('test.txt','original','test')
        self.assertEqual(sha,'a'*40);self.assertEqual(remote.writes,1)
        with self.assertRaisesRegex(ValueError,'append-only'):remote.save('test.txt','changed','test')

    def test_write_guard_runs_before_each_new_file(self):
        from operation_runner import GitHub
        class Remote(GitHub):
            def optional(self,path):return None
        remote=Remote(lambda *args:self.fail('Late write'))
        remote.write_guard=lambda:(_ for _ in ()).throw(ValueError('deadline'))
        with self.assertRaisesRegex(ValueError,'deadline'):remote.save('path','body','test')


if __name__=='__main__':unittest.main()
