import base64
import io
import json
import threading
import time
import unittest
import zipfile
import uuid
import copy
import urllib.request
import urllib.error
from datetime import datetime
from unittest.mock import patch
from urllib.error import HTTPError
from email.message import Message

import product_downloads as downloads
from local_service import TaskManager, TaskStore, ServiceConflictError, ServiceInputError, RecordingSettings, create_http_server
from recorder_core import RecordingResult
from test_local_service import scratch_dir, payload
from test_product_evidence import card, detail, event

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aS1sAAAAASUVORK5CYII=')


def independent_request():
    snapshot = detail()
    for key in ('card_observation_id', 'association', 'clicked_at_epoch_ms'):
        snapshot.pop(key, None)
    snapshot['source'] = 'user_selected_current_product_panel'
    return dict(request_id=str(uuid.uuid4()), room_url='https://live.douyin.com/123456',
                observed_at_epoch_ms=time.time()*1000, snapshot=snapshot)


class ProductDownloadTests(unittest.TestCase):
    def test_independent_endpoint_requires_auth_and_uses_separate_status_route(self):
        with scratch_dir() as root:
            manager=TaskManager(store=TaskStore(root/'state.sqlite3'),output_root=root/'out')
            manager.product_downloads.runner=lambda *a,**k: {'state':'complete_observed','image_saved':0}
            token='synthetic-token-with-at-least-32-characters'
            server=create_http_server(host='127.0.0.1',port=0,manager=manager,token=token)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            body=independent_request()
            def post(headers):
                return urllib.request.urlopen(urllib.request.Request(base+'/v1/product-downloads',data=json.dumps(body).encode(),headers={'Content-Type':'application/json',**headers}),timeout=2)
            try:
                with self.assertRaises(urllib.error.HTTPError) as refused: post({})
                self.assertEqual(refused.exception.code,401);refused.exception.close()
                with self.assertRaises(urllib.error.HTTPError) as blocked: post({'Origin':'https://example.test','X-BrandBAI-Token':token})
                self.assertEqual(blocked.exception.code,403);blocked.exception.close()
                with post({'X-BrandBAI-Token':token}) as response:
                    self.assertEqual(response.status,202)
                    self.assertEqual(json.load(response)['product_download']['request_id'],body['request_id'])
                manager.product_downloads.thread.join(2)
                with urllib.request.urlopen(urllib.request.Request(base+'/v1/product-downloads/'+body['request_id'],headers={'X-BrandBAI-Token':token}),timeout=2) as response:
                    self.assertEqual(json.load(response)['product_download']['state'],'complete_observed')
                self.assertEqual(manager.list(),[])
            finally: server.shutdown();server.server_close();thread.join(2)

    def test_independent_requires_initial_location_and_freezes_it_for_running_job(self):
        entered,release=threading.Event(),threading.Event()
        with scratch_dir() as root:
            settings=RecordingSettings(root/'settings.json',default_output_root=root/'first')
            manager=TaskManager(store=TaskStore(root/'state.sqlite3'),output_root=root/'first',recording_settings=settings)
            body=independent_request()
            with self.assertRaises(ServiceConflictError): manager.download_current_product(body)
            manager.confirm_default_output_root()
            captured=[]
            def runner(path, *args, **kwargs):
                captured.append(path);entered.set();release.wait(2);return {'state':'complete_observed'}
            manager.product_downloads.runner=runner
            try:
                manager.download_current_product(body);self.assertTrue(entered.wait(1))
                settings._write(root/'second')
                self.assertEqual(captured,[root/'first'])
            finally: release.set();manager.product_downloads.thread.join(3)

    def test_independent_product_without_recording_and_snapshot_idempotency(self):
        with scratch_dir() as root:
            manager = TaskManager(store=TaskStore(root/'state.sqlite3'), output_root=root/'out')
            captured=[]
            manager.product_downloads.runner=lambda path, events, **kwargs: (captured.append((path, events)) or {'state':'complete_observed','image_saved':1})
            body=independent_request()
            manager.download_current_product(body); manager.product_downloads.thread.join(3)
            manager.download_current_product(body)
            self.assertEqual(manager.list(), [])
            self.assertEqual(len(captured), 1)
            observation=captured[0][1][0]
            self.assertEqual(observation['event_type'], 'product_material')
            self.assertNotIn('recording_offset_seconds', observation)
            self.assertNotIn('card_observation_id', observation['payload'])
            self.assertEqual(manager.current_product_download(body['request_id'])['image_saved'],1)
            changed=copy.deepcopy(body); changed['snapshot']['price_texts']=['¥999']
            with self.assertRaises(ServiceConflictError): manager.download_current_product(changed)

    def test_independent_snapshot_rejects_paths_private_fields_old_time_and_forged_live_binding(self):
        with scratch_dir() as root:
            manager = TaskManager(store=TaskStore(root/'state.sqlite3'), output_root=root/'out')
            changes=[{'path':'C:/outside'}, {'observed_at_epoch_ms':0}, {'room_url':'https://example.test'},
                     {'request_id':'../escape'}, {'observed_at_epoch_ms':float('nan')}]
            for changeset in changes:
                with self.subTest(changeset=changeset), self.assertRaises(ServiceInputError):
                    manager.download_current_product(independent_request() | changeset)
            for field,value in [('card_observation_id','card-fake'),('shop_name','收货地址：不要保存'),
                                ('images',[{'url':'https://127.0.0.1/a','kind':'unclassified_product_image'}])]:
                body=independent_request();body['snapshot'][field]=value
                with self.subTest(field=field), self.assertRaises(ServiceInputError): manager.download_current_product(body)
            self.assertEqual(manager.list(),[])
            self.assertIsNone(manager.product_downloads.thread)

    def test_independent_package_keeps_prompt_ready_sources_without_fake_live_event(self):
        body=independent_request()
        source=dict(event_type='product_material', material_observation_id=body['request_id'],
                    room_url=body['room_url'], observed_at='2026-01-01T00:00:00+08:00', payload=body['snapshot'])
        with scratch_dir() as root:
            result=downloads.build_product_package(root,[source],stop=threading.Event(),fetcher=lambda *a,**k:PNG)
            self.assertIn('商品资料',result['output_dir'])
            self.assertNotIn('05_',result['output_dir'])
            with zipfile.ZipFile(result['archive']) as archive:
                data=json.loads(archive.read('商品资料.json'))
                self.assertEqual(data['collection_mode'],'independent_product')
                self.assertEqual(data['transaction_snapshots'][0]['price_texts'],['¥49'])
                self.assertEqual(data['coverage']['full_page'],'not_verified')
                self.assertNotIn('recording_offset_seconds', data['observations'][0])
                self.assertNotIn('card_observation_id',data['observations'][0]['payload'])
                self.assertIn('无需先录屏',archive.read('商品资料.md').decode())

    def test_recording_stop_does_not_stop_independent_download(self):
        entered,download_entered,release = threading.Event(),threading.Event(),threading.Event()
        def recorder(config, *, stop_event):
            config.output_root.mkdir(parents=True,exist_ok=True); entered.set();stop_event.wait(3)
            return RecordingResult(task_id='ignored',session_id='synthetic',outcome='recorded',completion_status='partial_service_stop',valid_mp4_count=1,segment_count=1,actual_media_duration_seconds=2,output_root=str(config.output_root),test_only=True)
        def download_runner(*args,stop,**kwargs):
            download_entered.set();release.wait(3)
            return {'state':'partial' if stop.is_set() else 'complete_observed'}
        with scratch_dir() as root:
            manager=TaskManager(store=TaskStore(root/'state.sqlite3'),output_root=root/'out',recorder=recorder,min_free_space_gb=0)
            manager.product_downloads.runner=download_runner
            task,_=manager.create(payload())
            try:
                self.assertTrue(entered.wait(1))
                body=independent_request();manager.download_current_product(body)
                self.assertTrue(download_entered.wait(1))
                self.assertEqual(manager.get(task['task_id'])['state'],'recording')
                manager.stop(task['task_id']);self.assertTrue(manager.wait_for_idle(3))
                self.assertFalse(manager.product_downloads.stop.is_set())
                self.assertEqual(manager.current_product_download(body['request_id'])['state'],'running')
            finally:
                release.set();manager.product_downloads.thread.join(3);manager.stop(task['task_id']);manager.wait_for_idle(3)
            self.assertEqual(manager.current_product_download(body['request_id'])['state'],'complete_observed')

    def test_real_files_zip_mapping_and_separate_prices_with_url_dedup(self):
        first, second = card(), detail()
        second['images'] = [{'url': first['images'][0]['url'], 'kind': 'unclassified_product_image'}]
        called = []
        def fetch(url, **kwargs): called.append(url); return PNG
        with scratch_dir() as root:
            result = downloads.build_product_package(root, [event(first), event(second, 'product_detail', 3000, 2)], stop=threading.Event(), fetcher=fetch)
            self.assertEqual(result['image_saved'], 1)
            self.assertEqual(len(called), 1)
            with zipfile.ZipFile(result['archive']) as zf:
                self.assertIsNone(zf.testzip())
                media = [n for n in zf.namelist() if n.endswith('.png')]
                self.assertEqual(zf.read(media[0]), PNG)
                data = json.loads(zf.read('商品资料.json'))
                self.assertEqual(data['observations'][0]['payload']['display_price'], '¥39')
                self.assertEqual(data['observations'][1]['payload']['price_texts'], ['¥49'])
                self.assertEqual(data['assets'][0]['file'], media[0])
                md = zf.read('商品资料.md').decode('utf-8')
                self.assertIn('50g', md)
                self.assertIn(media[0], md)
                self.assertNotIn(str(root), md)

    def test_invalid_response_is_partial_without_fake_image_file(self):
        with scratch_dir() as root:
            result = downloads.build_product_package(root, [event(card())], stop=threading.Event(), fetcher=lambda *a, **k: b'<html>Login required</html>')
            self.assertEqual(result['state'], 'partial')
            self.assertEqual(result['image_failed'], 1)
            with zipfile.ZipFile(result['archive']) as zf:
                self.assertFalse(any(n.startswith('图片/') for n in zf.namelist()))
                self.assertIn('商品资料.json', zf.namelist())

    def test_limits_cancel_and_no_private_data_in_product_package(self):
        p = card(); p['images'].append({'url': 'https://p3.ecombdimg.com/second.webp', 'kind': 'card_image'})
        comment = event({'text': '不得打入商品包的评论正文'}, 'comment_visible')
        with scratch_dir() as root, patch.object(downloads, 'MAX_IMAGES', 1):
            result = downloads.build_product_package(root, [event(p), comment], stop=threading.Event(), fetcher=lambda *a, **k: PNG)
            self.assertEqual((result['image_saved'], result['image_skipped'], result['state']), (1, 1, 'partial'))
            with zipfile.ZipFile(result['archive']) as zf:
                self.assertNotIn('评论正文', zf.read('商品资料.json').decode('utf-8'))
        stop = threading.Event(); stop.set()
        with scratch_dir() as root:
            result = downloads.build_product_package(root, [event(p)], stop=stop, fetcher=lambda *a, **k: self.fail('must not request after cancel'))
            self.assertEqual(result['image_saved'], 0)
            self.assertEqual(result['state'], 'partial')

    def test_private_destination_rejected_before_request(self):
        with patch.object(downloads.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaises(ValueError): downloads.validate_remote('https://p3.ecombdimg.com/image.png')
        for url in ['http://127.0.0.1/a.png', 'https://p3.ecombdimg.com/a?token=x', 'https://evil.example/a.png']:
            with self.subTest(url=url), self.assertRaises(ValueError): downloads.validate_remote(url)

    def test_redirect_to_private_or_unapproved_url_is_never_requested(self):
        headers = Message(); headers['Location'] = 'http://127.0.0.1/private'
        error = HTTPError('https://p3.ecombdimg.com/a.png', 302, 'redirect', headers, io.BytesIO())
        with patch.object(downloads, 'validate_remote'), patch.object(downloads, 'build_opener') as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaises(ValueError):
                downloads.fetch_image('https://p3.ecombdimg.com/a.png', stop=threading.Event(), deadline=time.monotonic()+3)
            self.assertEqual(opener.return_value.open.call_count, 1)

    def test_duplicate_start_keeps_one_worker_and_exceptions_are_redacted(self):
        entered, release = threading.Event(), threading.Event()
        def runner(*args, **kwargs):
            entered.set(); release.wait(3); raise RuntimeError('Cookie and proxy password must not escape')
        jobs = downloads.ProductDownloadJobs(runner)
        try:
            self.assertEqual(jobs.start(('room', 'run'), '.', [])['state'], 'running')
            self.assertTrue(entered.wait(1))
            self.assertEqual(jobs.start(('room', 'run'), '.', [])['state'], 'running')
            with self.assertRaises(ValueError): jobs.start(('room', 'other_run'), '.', [])
        finally:
            release.set(); jobs.thread.join(3)
        self.assertEqual(jobs.status(('room', 'run')), {'state': 'failed', 'reason': 'product_package_failed'})

    def test_manager_freezes_current_session_and_refuses_client_urls_or_running_recording(self):
        entered = threading.Event()
        def recorder(config, *, stop_event):
            config.output_root.mkdir(parents=True, exist_ok=True); entered.set(); stop_event.wait(3)
            return RecordingResult(task_id='ignored', session_id='synthetic', outcome='recorded', completion_status='partial_service_stop', valid_mp4_count=1, segment_count=1, actual_media_duration_seconds=2, output_root=str(config.output_root), test_only=True)
        with scratch_dir() as root:
            manager = TaskManager(store=TaskStore(root/'state.sqlite3'), output_root=root/'out', recorder=recorder, min_free_space_gb=0)
            task, _ = manager.create(payload(collect_product_cards=True))
            try:
                self.assertTrue(entered.wait(1))
                task=manager.get(task['task_id']); body={'started_at':task['started_at']}
                with self.assertRaises(ServiceConflictError): manager.download_products(task['task_id'], body)
                at=datetime.fromisoformat(task['started_at']).timestamp()*1000
                e=event(card(), at=at+10)
                batch={'collector_session_id':'page-test-123', 'events':[{k:e[k] for k in ('sequence','event_type','observed_at_epoch_ms','room_url','payload')}]}
                manager.ingest_visible_events(task['task_id'], batch)
                manager.stop(task['task_id']); self.assertTrue(manager.wait_for_idle(3))
                with self.assertRaises(ServiceInputError): manager.download_products(task['task_id'], dict(body, url='https://example.test'))
                with self.assertRaises(ServiceConflictError): manager.download_products(task['task_id'], {'started_at':'old-run'})
                captured=[]
                manager.product_downloads.runner=lambda path, events, **kwargs: (captured.append((path, events)) or {'state':'complete_observed','image_saved':1})
                manager.download_products(task['task_id'], body); manager.product_downloads.thread.join(3)
                self.assertEqual(len(captured), 1)
                self.assertEqual(str(captured[0][0]), task['output_dir'])
                self.assertEqual(captured[0][1][0]['event_type'], 'product_state')
                self.assertEqual(manager.get(task['task_id'])['product_download']['image_saved'], 1)
            finally:
                manager.stop(task['task_id']); manager.wait_for_idle(3)


if __name__ == '__main__': unittest.main()
