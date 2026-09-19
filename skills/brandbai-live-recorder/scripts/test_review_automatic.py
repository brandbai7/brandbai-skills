"""Automatic review lifecycle; synthetic records, no platform/network access."""
import json
import unittest
import uuid
import zipfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock
from product_reviews import ProductReviewJobs, AUTO_PAUSES
from test_product_reviews import request, row
from test_local_service import scratch_dir
from local_service import TaskManager, TaskStore, create_http_server


class AutomaticReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = scratch_dir(); self.root = self.tmp.__enter__()
        self.clock = 1789460000; self.finished = []
        self.jobs = ProductReviewJobs(now=lambda: self.clock, on_finish=lambda *v: self.finished.append(v))
        self.body = request() | {'collection_mode': 'automatic', 'limit': None}
        self.job = self.jobs.start(self.body, self.root)
        self.id = self.job['id']; self.run = self.job['runId']

    def tearDown(self):
        self.jobs.shutdown(); self.tmp.__exit__(None, None, None)

    def event(self, action='batch', sequence=1, **kw):
        return dict(lease=self.body['lease'], run_id=self.run, sequence=sequence, action=action,
                    rows=[row()] if action=='batch' else [], done_reason='', exhausted=False, empty_confirmed=False) | kw

    def control(self): return {'room_url': self.body['room_url'], 'run_id': self.run}
    def resume_body(self): return self.control() | {'lease': self.body['lease'], 'next_run_id': str(uuid.uuid4())}

    def test_pause_same_task_resume_deduplicates_and_packages_only_on_finish(self):
        self.jobs.accept(self.id, self.event())
        paused = self.jobs.accept(self.id, self.event('finish', 2, done_reason='user_paused'))
        self.assertEqual(paused['state'], 'paused'); self.assertIsNone(paused['zip_path'])
        self.assertEqual(self.finished, []); self.assertTrue(paused['can_continue'])
        old_run = self.run; body = self.resume_body()
        continued = self.jobs.resume(self.id, body); self.run = continued['runId']
        self.assertEqual(continued['id'], self.id); self.assertNotEqual(self.run, old_run)
        self.assertEqual(self.jobs.resume(self.id, body)['runId'], self.run)
        self.jobs.accept(self.id, self.event(rows=[row(), row() | {'review_id': 'c'*64}]))
        final = self.jobs.stop(self.id, self.control())
        self.assertEqual(final['reviewCount'], 2); self.assertEqual(len(self.finished), 1)
        self.assertEqual(self.jobs.stop(self.id, self.control())['zip_path'], final['zip_path'])
        self.assertEqual(len(self.finished), 1)
        with zipfile.ZipFile(final['zip_path']) as archive:
            self.assertIsNone(archive.testzip())
            manifest = json.loads(archive.read('完整性.json'))
            self.assertIsNone(manifest['target_count']); self.assertIsNone(manifest['limit'])
            self.assertEqual(manifest['collection_mode'], 'automatic')
            self.assertNotIn('None', archive.read('阅读说明.md').decode())
            self.assertNotIn('"run_id"', archive.read('商品评价.jsonl').decode())
            self.assertNotIn('documentToken', archive.read('商品评价.jsonl').decode())

    def test_old_run_batches_and_controls_cannot_affect_resumed_task(self):
        old_event=self.event(); old_control=self.control()
        self.jobs.pause(self.id, old_control)
        resumed=self.jobs.resume(self.id, self.resume_body()); self.run=resumed['runId']
        for operation in (lambda:self.jobs.accept(self.id, old_event),
                          lambda:self.jobs.pause(self.id, old_control), lambda:self.jobs.stop(self.id, old_control)):
            with self.assertRaises(ValueError): operation()
        self.assertEqual(self.jobs.status(self.id)['state'], 'collecting')
        self.assertEqual(self.jobs.status(self.id)['reviewCount'], 0)

    def test_resume_rejects_changed_lease_room_and_unrequested_new_job(self):
        self.jobs.pause(self.id, self.control())
        for change in ({'lease': self.body['lease'] | {'filterKey':'other'}}, {'room_url':'https://live.douyin.com/999'}, {'extra':'no'}):
            with self.subTest(change=change), self.assertRaises(ValueError): self.jobs.resume(self.id, self.resume_body() | change)
        with self.assertRaises(ValueError): self.jobs.start(self.body | {'request_id':str(uuid.uuid4()),'resume_from':self.id}, self.root)

    def test_pause_survives_long_wait_and_rejects_late_rows(self):
        self.jobs.accept(self.id, self.event())
        self.jobs.pause(self.id, self.control()); self.clock += 36000
        state=self.jobs.status(self.id)
        self.assertEqual(state['state'], 'paused'); self.assertEqual(state['reviewCount'],1)
        with self.assertRaises(ValueError): self.jobs.accept(self.id, self.event(sequence=2))
        self.assertEqual(self.finished, [])

    def test_disconnect_and_hidden_timeout_pause_without_auto_export(self):
        self.jobs.accept(self.id, self.event()); self.clock += 46
        self.assertEqual(self.jobs.status(self.id)['state'], 'paused')
        self.run=self.jobs.resume(self.id, self.resume_body())['runId']
        self.jobs.accept(self.id, self.event('progress', phase='waiting_page'))
        self.clock += 301
        self.assertEqual(self.jobs.status(self.id)['doneReason'], 'page_hidden')
        self.assertEqual(self.jobs.status(self.id)['state'], 'paused'); self.assertEqual(self.finished, [])

    def test_all_recoverable_finishes_pause(self):
        for reason in AUTO_PAUSES:
            with self.subTest(reason=reason):
                self.jobs.accept(self.id, self.event('finish', done_reason=reason))
                self.assertEqual(self.jobs.status(self.id)['state'], 'paused')
                self.run=self.jobs.resume(self.id, self.resume_body())['runId']
        self.assertEqual(self.finished, [])

    def test_folded_footer_is_current_list_boundary_not_all_history(self):
        self.jobs.accept(self.id, self.event())
        final=self.jobs.accept(self.id, self.event('finish', 2, done_reason='source_folded', exhausted=True))
        self.assertEqual(final['state'],'saved'); self.assertEqual(final['completeness'],'complete_visible_panel_exhausted')
        with zipfile.ZipFile(final['zip_path']) as archive:
            manifest=json.loads(archive.read('完整性.json'))
            self.assertTrue(manifest['platform_folded_reviews_not_collected'])
            self.assertIn('平台折叠的评价未采集',archive.read('阅读说明.md').decode())

    def test_folded_footer_does_not_erase_unparsed_gaps(self):
        final=self.jobs.accept(self.id,self.event('finish',done_reason='source_folded',exhausted=True,empty_confirmed=True,unparsed_count=1))
        self.assertEqual(final['completeness'],'partial_selector_drift')

    def test_no_preset_200_or_500_cutoff(self):
        for batch in range(6):
            self.jobs.accept(self.id, self.event(sequence=batch+1,rows=[row() | {'review_id':f'{batch*100+i:064x}'} for i in range(100)]))
        current=self.jobs.status(self.id)
        self.assertEqual(current['state'],'collecting'); self.assertEqual(current['reviewCount'],600)
        self.assertEqual(self.finished, [])

    def test_write_failure_does_not_ack_pause_or_resume(self):
        with mock.patch.object(self.jobs,'_checkpoint',side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):self.jobs.pause(self.id,self.control())
        self.assertEqual(self.jobs.status(self.id)['state'],'collecting')
        self.jobs.pause(self.id,self.control()); body=self.resume_body()
        with mock.patch.object(self.jobs,'_checkpoint',side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):self.jobs.resume(self.id,body)
        self.assertEqual(self.jobs.status(self.id)['state'],'paused')
        self.assertEqual(self.jobs.resume(self.id,body)['state'],'collecting')

    def test_source_change_finishes_partial_and_shutdown_exports_paused_checkpoint(self):
        final=self.jobs.accept(self.id,self.event('finish',done_reason='product_or_work_changed'))
        self.assertEqual(final['state'],'saved');self.assertFalse(final['can_continue'])
        another=self.body | {'request_id':str(uuid.uuid4())}
        second=self.jobs.start(another,self.root)
        self.jobs.pause(second['id'],{'room_url':second['room_url'],'run_id':second['runId']})
        self.jobs.shutdown()
        self.assertTrue(Path(self.jobs.status(second['id'])['zip_path']).is_file())


class AutomaticReviewHttpTests(unittest.TestCase):
    def test_controls_require_auth_origin_current_run_and_same_lease(self):
        with scratch_dir() as root:
            manager = TaskManager(store=TaskStore(root/'state.sqlite3'), output_root=root/'out')
            token = 'synthetic-token-at-least-32-characters'
            server = create_http_server(host='127.0.0.1', port=0, manager=manager, token=token)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            def call(path, body, headers=None):
                request_headers = {'Content-Type': 'application/json'}
                request_headers.update({'X-BrandBAI-Token': token} if headers is None else headers)
                with urllib.request.urlopen(urllib.request.Request(base+path,
                        data=json.dumps(body).encode(), headers=request_headers), timeout=3) as response:
                    return json.load(response)['task']
            try:
                body = request() | {'collection_mode':'automatic', 'limit':None, 'observed_at_epoch_ms':time.time()*1000}
                task = call('/v1/product-reviews', body); ident = task['id']
                control = {'room_url':body['room_url'], 'run_id':task['runId']}
                prefix = f'/v1/product-reviews/{ident}'
                for action in ('pause', 'resume'):
                    for headers, status in (({},401), ({'X-BrandBAI-Token':token,'Origin':'https://example.test'},403)):
                        with self.subTest(action=action,status=status), self.assertRaises(urllib.error.HTTPError) as error:
                            call(prefix+'/'+action,control,headers)
                        self.assertEqual(error.exception.code,status); error.exception.close()
                with self.assertRaises(urllib.error.HTTPError) as error:
                    call(prefix+'/pause',control | {'run_id':str(uuid.uuid4())})
                self.assertEqual(error.exception.code,400); error.exception.close()
                paused = call(prefix+'/pause',control)
                self.assertEqual(paused['state'],'paused'); self.assertIsNone(paused['zip_path'])
                resume = control | {'lease':body['lease'], 'next_run_id':str(uuid.uuid4())}
                with self.assertRaises(urllib.error.HTTPError) as error:
                    call(prefix+'/resume',resume | {'lease':body['lease'] | {'filterKey':'other'}})
                self.assertEqual(error.exception.code,400); error.exception.close()
                continued = call(prefix+'/resume',resume)
                self.assertEqual(continued['id'],ident); self.assertEqual(continued['state'],'collecting')
                self.assertEqual(continued['runId'],resume['next_run_id'])
                with self.assertRaises(urllib.error.HTTPError) as error: call(prefix+'/stop',control)
                self.assertEqual(error.exception.code,400); error.exception.close()
                self.assertEqual(call(prefix+'/stop',control | {'run_id':continued['runId']})['state'],'saved')
                self.assertEqual(manager.list(),[])
            finally:
                server.shutdown(); server.server_close(); thread.join(2); manager.shutdown()


if __name__ == '__main__': unittest.main()
