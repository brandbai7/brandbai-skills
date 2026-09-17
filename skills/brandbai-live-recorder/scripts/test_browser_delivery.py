import json
import threading
import time
import unittest
import urllib.request
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch
from browser_delivery import BrowserDeliveries, DeliveryError
from local_service import TaskManager, TaskStore, RecordingSettings, create_http_server, ServiceInputError
from test_product_downloads import independent_request, PNG
from test_local_service import scratch_dir, payload, visible_batch
from recorder_core import RecordingResult
from test_product_reviews import request as review_request, row as review_row
from product_downloads import build_product_package

CLIENT='abcdefghijklmnopabcdefghijklmnop'
TOKEN='synthetic-service-token-that-is-long-enough'

class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=scratch_dir();self.root=self.tmp.__enter__()
        self.clock=100000.;self.jobs=BrowserDeliveries(self.root/'cache',now=lambda:self.clock,reserve_bytes=0)
    def tearDown(self):
        while self.jobs.workers: time.sleep(.01)
        self.tmp.__exit__(None,None,None)
    def package(self,kind='recording'):
        item=self.jobs.create(kind,'synthetic:'+str(len(self.jobs.jobs)))
        ident=item['id'];folder=self.jobs.work_root(ident)/'合成资料包';folder.mkdir()
        (folder/'03_直播录屏').mkdir();(folder/'03_直播录屏'/'sample.mp4').write_bytes(b'fake-media'*4096)
        (folder/'05_直播互动').mkdir();(folder/'05_直播互动'/'直播互动记录.md').write_text('合成评论',encoding='utf-8')
        (folder/'data.json').write_text('{"product_id":null}',encoding='utf-8')
        (folder/'incomplete.pending').write_bytes(b'ignored')
        self.jobs.source(ident,folder);self.jobs.pack(ident,material_status='partial_time_limit')
        while self.jobs.workers: time.sleep(.01)
        self.assertEqual(self.jobs.public(ident)['state'],'ready')
        return ident,folder
    def claim(self,ident):return self.jobs.claim(ident,CLIENT)
    def report(self,claimed,state='completed',**extra):
        return self.jobs.report(claimed['id'],dict(attempt_id=claimed['attempt_id'],download_id=12,state=state,
            bytes_received=claimed['bytes_total'] if state=='completed' else 0,reason=None)|extra,CLIENT)
    def test_zip_stored_unicode_ledger_partial_and_private_boundary(self):
        ident,folder=self.package();claimed=self.claim(ident)
        with self.jobs.open_archive(ident,claimed['attempt_id'],claimed['ticket'],CLIENT) as stream,zipfile.ZipFile(stream) as z:
            self.assertIsNone(z.testzip());self.assertIn('05_直播互动/直播互动记录.md',z.namelist())
            self.assertNotIn('incomplete.pending',z.namelist())
            self.assertTrue(all(info.compress_type==zipfile.ZIP_STORED for info in z.infolist()))
            self.assertEqual(json.loads(z.read('交付状态.json'))['material_status'],'partial_time_limit')
            self.assertFalse(any('delivery.json' in n or 'auth_token' in n for n in z.namelist()))
        self.assertRegex(claimed['filename'],r'^抖音_直播记录_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.zip$')
        self.assertNotIn(str(self.root),json.dumps(self.jobs.public(ident)))
    def test_ticket_scoped_expiring_and_no_duplicate_claim(self):
        ident,_=self.package();c=self.claim(ident)
        self.assertNotIn('ticket',self.claim(ident))
        self.assertNotIn(c['ticket'],(self.root/'cache'/ident/'delivery.json').read_text())
        for attempt,ticket,client in [(c['attempt_id'],'bad',CLIENT),('a'*32,c['ticket'],CLIENT),(c['attempt_id'],c['ticket'],'b'*32)]:
            with self.assertRaises(DeliveryError):self.jobs.open_archive(ident,attempt,ticket,client)
        self.clock+=86401
        with self.assertRaises(DeliveryError):self.jobs.open_archive(ident,c['attempt_id'],c['ticket'],CLIENT)
    def test_received_bytes_and_attempt_required_for_completed(self):
        ident,_=self.package();c=self.claim(ident)
        with self.assertRaises(DeliveryError):self.report(c,bytes_received=1)
        with self.assertRaises(DeliveryError):self.report(c,attempt_id='b'*32)
        self.assertEqual(self.report(c)['state'],'completed')
        self.assertEqual(self.report(c,'downloading')['state'],'completed')
    def test_canceled_requires_explicit_retry_no_overwrite(self):
        ident,folder=self.package();c=self.claim(ident);self.report(c,'canceled',reason='USER_CANCELED')
        with self.assertRaises(DeliveryError):self.claim(ident)
        d=self.jobs.claim(ident,CLIENT,retry=True)
        self.assertNotEqual(d['attempt_id'],c['attempt_id']);self.assertTrue(folder.exists())
    def test_restart_recovers_pending_and_keeps_transfer(self):
        ident,_=self.package();c=self.claim(ident)
        pending=self.jobs.create('product','pending')
        restored=BrowserDeliveries(self.root/'cache',now=lambda:self.clock,reserve_bytes=0)
        self.assertEqual(restored.public(pending['id'])['state'],'interrupted')
        self.assertEqual(restored.public(ident)['state'],'starting')
        with restored.open_archive(ident,c['attempt_id'],c['ticket'],CLIENT) as stream:self.assertTrue(stream.read(2))
    def test_cleanup_only_completed_owned_cache_after_grace(self):
        ident,folder=self.package();pending=self.jobs.create('reviews','keep-pending')
        unrelated=self.root/'historical';unrelated.mkdir();(unrelated/'keep').write_text('old')
        c=self.claim(ident);self.report(c);self.jobs.cleanup_completed();self.assertTrue(folder.exists())
        self.clock+=86401;self.jobs.cleanup_completed()
        self.assertFalse(folder.exists());self.assertTrue(self.jobs.work_root(pending['id']).exists())
        self.assertTrue((unrelated/'keep').exists());self.assertFalse(self.jobs.public(ident)['recoverable'])
    def test_paths_and_external_archives_are_rejected(self):
        ident,_=self.package();outside=self.root/'external.zip';outside.write_bytes(b'zip')
        with self.assertRaises(DeliveryError):self.jobs.finish_existing(ident,{'archive':str(outside)})
        for relative in ('../external.zip',str(outside)):
            with self.assertRaises(DeliveryError):self.jobs._file(ident,relative)
        with self.assertRaises(DeliveryError):self.jobs.public('../bad')
    def test_low_space_preserves_material_for_retry(self):
        item=self.jobs.create('recording','space');ident=item['id'];folder=self.jobs.work_root(ident)/'包';folder.mkdir()
        (folder/'media.mp4').write_bytes(b'x'*10);self.jobs.source(ident,folder)
        with patch('browser_delivery.shutil.disk_usage',return_value=type('Disk',(),{'free':0})()):
            self.jobs.pack(ident)
            while self.jobs.workers:time.sleep(.01)
        self.assertEqual(self.jobs.public(ident)['reason'],'delivery_storage_low');self.assertTrue((folder/'media.mp4').exists())
    def test_late_data_repack_retains_previous_archive(self):
        ident,folder=self.package();c=self.claim(ident);self.report(c)
        original=self.jobs.jobs[ident]['archive'];(folder/'data.json').write_text('{"late":true}')
        self.jobs.mark_late_data(ident);self.assertTrue(self.jobs.public(ident)['late_data_available'])
        self.jobs.pack(ident,material_status='partial_time_limit')
        while self.jobs.workers:time.sleep(.01)
        self.assertNotEqual(original,self.jobs.jobs[ident]['archive']);self.assertTrue(self.jobs._file(ident,original).exists())

class DeliveryHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=scratch_dir();self.root=self.tmp.__enter__()
        settings=RecordingSettings(self.root/'state'/'recording_settings.json',default_output_root=self.root/'old-output')
        self.manager=TaskManager(store=TaskStore(self.root/'state'/'state.sqlite3'),output_root=self.root/'old-output',recording_settings=settings)
        self.server=create_http_server(host='127.0.0.1',port=0,manager=self.manager,token=TOKEN)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        if self.manager.product_downloads.thread:self.manager.product_downloads.thread.join(3)
        self.manager.shutdown();self.server.shutdown();self.server.server_close();self.thread.join(3);self.tmp.__exit__(None,None,None)
    def request(self,path,body=None,headers=None):
        request=urllib.request.Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,
            headers={'X-BrandBAI-Token':TOKEN,'X-BrandBAI-Client':CLIENT,'X-BrandBAI-Delivery':'browser-zip',
                     'Content-Type':'application/json',**(headers or {})})
        return urllib.request.urlopen(request,timeout=3)
    def test_browser_mode_needs_no_location_confirmation_does_not_write_settings(self):
        with self.request('/v1/settings') as r:self.assertEqual(json.load(r)['storage']['mode'],'browser-zip')
        self.assertFalse((self.root/'state'/'recording_settings.json').exists())
    def test_invalid_review_never_allocates_cache(self):
        body=review_request();body['observed_at_epoch_ms']=time.time()*1000;body['limit']=100000
        with self.assertRaises(ServiceInputError):self.manager.review_request(body,browser_delivery=True)
        self.assertEqual(self.manager.deliveries.list(),[])
    def test_recording_zip_contains_readable_interaction_and_no_old_output(self):
        release=threading.Event()
        def recorder(config,**kwargs):
            root=config.output_root;root.mkdir(parents=True,exist_ok=True)
            (root/'recording.mp4').write_bytes(b'synthetic-recording')
            release.wait(3)
            return RecordingResult(task_id='synthetic',session_id='synthetic',test_only=True,
                outcome='recorded',completion_status='partial_time_limit',segment_count=1,
                valid_mp4_count=1,actual_media_duration_seconds=60,output_root=str(root))
        self.manager.recorder=recorder
        task,_=self.manager.create(payload(collect_comments=True),browser_delivery=True,single_active_task=True)
        while not self.manager.get(task['task_id']).get('started_at'):time.sleep(.01)
        self.manager.ingest_visible_events(task['task_id'],visible_batch(time.time()*1000))
        release.set();self.manager.wait_for_idle(4)
        entry=task['delivery'];limit=time.time()+8
        while self.manager.deliveries.workers and time.time()<limit:time.sleep(.03)
        final=self.manager.deliveries.public(entry['id']);self.assertEqual(final['state'],'ready',final)
        archive=self.manager.deliveries._file(entry['id'],self.manager.deliveries.jobs[entry['id']]['archive'])
        with zipfile.ZipFile(archive) as z:
            self.assertIn('05_直播互动/直播互动记录.csv',z.namelist())
            self.assertIn('还能补测试库存吗',z.read('05_直播互动/直播互动记录.csv').decode('utf-8-sig'))
            self.assertEqual(json.loads(z.read('交付状态.json'))['material_status'],'partial_time_limit')
        self.assertFalse(list((self.root/'old-output').iterdir()))
        self.manager.product_downloads.runner=lambda root,events,**kw:build_product_package(root,events,fetcher=lambda *a,**k:(PNG,'.png'),**kw)
        with self.request('/v1/product-downloads',independent_request()) as r:item=json.load(r)['product_download']['delivery']
        self.manager.product_downloads.thread.join(3)
        self.assertEqual(self.manager.deliveries.public(item['id'])['state'],'ready')
        self.assertFalse(list((self.root/'old-output').iterdir()))
        self.assertFalse((self.root/'state'/'recording_settings.json').exists())
    def test_review_finish_registers_same_product_package(self):
        body=review_request();body['observed_at_epoch_ms']=time.time()*1000
        with self.request('/v1/product-reviews',body) as r:task=json.load(r)['task']
        event=dict(lease=body['lease'],sequence=1,action='batch',rows=[review_row()],done_reason='',exhausted=False,empty_confirmed=False)
        with self.request('/v1/product-reviews/'+task['id']+'/events',event) as r:self.assertEqual(json.load(r)['task']['reviewCount'],1)
        with self.request('/v1/product-reviews/'+task['id']+'/stop',{'room_url':body['room_url']}) as r:final=json.load(r)['task']
        self.assertEqual(final['delivery']['state'],'ready');self.assertEqual(final['completeness'],'partial_user_paused')
        self.assertEqual(final['product_identity'],task['product_identity'])
    def test_authenticated_range_stream_and_foreign_origin_rejected(self):
        jobs=self.manager.deliveries;item=jobs.create('product','http');ident=item['id'];folder=jobs.work_root(ident)/'包';folder.mkdir()
        (folder/'商品资料.md').write_text('合成资料');archive=folder.with_suffix('.zip')
        with zipfile.ZipFile(archive,'w') as z:z.write(folder/'商品资料.md','商品资料.md')
        jobs.finish_existing(ident,{'archive':str(archive),'state':'partial'})
        with self.request('/v1/deliveries/'+ident+'/claim',{'retry':False}) as r:c=json.load(r)['delivery']
        headers={'X-BrandBAI-Token':'','X-BrandBAI-FileTicket':c['ticket'],'Range':'bytes=2-9'}
        with self.request(c['file_route'],headers=headers) as r:
            self.assertEqual(r.status,206);self.assertEqual(r.read(),archive.read_bytes()[2:10])
        self.assertEqual(jobs.public(ident)['state'],'starting')
        for extra in ({'X-BrandBAI-FileTicket':'bad'},{'Origin':'https://example.test'},{'X-BrandBAI-Client':'b'*32}):
            with self.assertRaises(urllib.error.HTTPError) as caught:self.request(c['file_route'],headers=headers|extra)
            caught.exception.close()
        with self.request(c['file_route'],headers={'X-BrandBAI-FileTicket':c['ticket']}) as r:self.assertEqual(r.read(),archive.read_bytes())
        self.assertNotIn(c['ticket'],json.dumps(jobs.list()))

if __name__=='__main__':unittest.main()
