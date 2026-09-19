import copy
import json
import tempfile
import threading
import time
import urllib.request
import urllib.error
import unittest
import uuid
import zipfile
from unittest import mock
from pathlib import Path
from product_reviews import ProductReviewJobs, LEASE, time_budget
from material_contract import complete_crop_tiles, validate_coverage
from test_local_service import scratch_dir
from local_service import TaskManager, TaskStore, create_http_server

def request():
    return dict(request_id=str(uuid.uuid4()),room_url='https://live.douyin.com/123456',observed_at_epoch_ms=1789460000000,
                lease={key:'https://live.douyin.com/123456' if key in ('contextKey','sourceWorkId') else 'synthetic-'+key for key in LEASE},product=dict(title='合成商品标题',shop_name='合成店',product_id=''),
                filter_label='全部 · 综合',declared_count_text='22.9万',limit=200)

def row():
    return dict(review_id='a'*64,reviewer='买家_'+'b'*12,date_text='3个月前',purchased_sku='历史款规格',content='合成评价',
                content_status='text_observed',image_count=2,helpful_count=None,followups=[],followup_status='not_observed',merchant_reply='')

class ReviewTests(unittest.TestCase):
    def test_followup_only_is_valid_but_empty_and_misclassified_payloads_are_not(self):
        from product_reviews import validate_row
        data=row()|dict(content='',image_count=0,content_status='followup_only',followup_status='observed',
                        followups=[dict(content='合成追评',date_text='用户当天追评',image_count=3)])
        self.assertEqual(validate_row(data),data)
        for patch in (dict(followups=[]),dict(content='不应混为初评'),dict(followup_status='unparsed'),dict(image_count=3)):
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate_row(data|patch)

    def test_gaps_are_written_and_exhaustion_cannot_hide_them(self):
        self.jobs.accept(self.id,self.event(unparsed_count=1))
        final=self.jobs.accept(self.id,self.event('finish',2,done_reason='source_exhausted',exhausted=True,unparsed_count=1))
        self.assertEqual(final['completeness'],'partial_selector_drift')
        with zipfile.ZipFile(final['zip_path']) as archive:
            self.assertEqual(json.loads(archive.read('完整性.json'))['unparsed_count'],1)
            self.assertIn('1 个未能确认',archive.read('阅读说明.md').decode())

    def test_gap_counts_are_bounded_and_do_not_relax_the_lease(self):
        for count in (-1,True,10001,'1'):
            with self.subTest(count=count),self.assertRaises(ValueError):self.jobs.accept(self.id,self.event(unparsed_count=count))
        event=self.event(unparsed_count=1);event['lease']={**event['lease'],'filterKey':'other'}
        with self.assertRaises(ValueError):self.jobs.accept(self.id,event)
    def setUp(self):
        self.tmp=scratch_dir();self.root=self.tmp.__enter__();self.clock=1789460000
        self.jobs=ProductReviewJobs(now=lambda:self.clock);self.request=request();self.id=self.request['request_id']
        self.jobs.start(self.request,self.root)
    def tearDown(self): self.jobs.shutdown();self.tmp.__exit__(None,None,None)
    def event(self, action='batch', sequence=1, **values):
        return dict(lease=self.request['lease'],sequence=sequence,action=action,rows=[row()] if action=='batch' else [],
                    done_reason='',exhausted=False,empty_confirmed=False)|values
    def test_ack_follows_checkpoint_and_zip_is_independent(self):
        result=self.jobs.accept(self.id,self.event());self.assertEqual(result['reviewCount'],1)
        data=json.loads((Path(result['output_dir'])/'商品评价.jsonl').read_text(encoding='utf-8'))
        self.assertEqual(data['purchased_sku'],'历史款规格');self.assertNotIn('lease',data)
        final=self.jobs.accept(self.id,self.event('finish',2,done_reason='run_budget'))
        with zipfile.ZipFile(final['zip_path']) as z:
            self.assertIsNone(z.testzip());self.assertEqual(len(z.namelist()),7)
            info=json.loads(z.read('导出信息.json'))
            self.assertEqual(info['package_name'],Path(final['output_dir']).name)
            self.assertEqual(info['export_id'],self.id)
            self.assertIsNone(json.loads(z.read('商品身份.json'))['product_id'])
            self.assertNotIn(b'sourceWorkId',b''.join(z.read(n) for n in z.namelist()))
            self.assertEqual(json.loads(z.read('完整性.json'))['completeness'],'partial_run_budget')
    def test_idempotent_retries_and_changed_batch_rejected(self):
        self.jobs.accept(self.id,self.event());self.jobs.accept(self.id,self.event())
        self.assertEqual(self.jobs.start(self.request,self.root)['reviewCount'],1)
        bad=self.event();bad['rows'][0]['content']='changed'
        with self.assertRaises(ValueError):self.jobs.accept(self.id,bad)
    def test_source_and_unknown_fields_rejected(self):
        for mutate in ('lease','private','sequence'):
            e=copy.deepcopy(self.event())
            if mutate=='lease':e['lease']['filterKey']='changed'
            elif mutate=='sequence':e['sequence']=9
            else:e['rows'][0]['address']='must not be accepted'
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):self.jobs.accept(self.id,e)
        self.assertEqual(self.jobs.status(self.id)['reviewCount'],0)
    def test_limit_and_incomplete_are_never_total(self):
        self.jobs.jobs[self.id]['limit']=1
        second=row()|{'review_id':'c'*64}
        with self.assertRaises(ValueError):self.jobs.accept(self.id,self.event(rows=[row(),second]))
        final=self.jobs.accept(self.id,self.event('finish',1,done_reason='no_growth',exhausted=True))
        self.assertTrue(final['completeness'].startswith('partial'))
    def test_explicit_end_and_empty(self):
        final=self.jobs.accept(self.id,self.event('finish',1,done_reason='source_exhausted',exhausted=True,empty_confirmed=True))
        self.assertEqual(final['completeness'],'complete_visible_panel_exhausted')
    def test_source_timeout_packages_checkpoint(self):
        self.jobs.accept(self.id,self.event());self.clock+=46
        final=self.jobs.status(self.id);self.assertEqual(final['doneReason'],'page_disconnected')
        self.assertTrue(Path(final['zip_path']).is_file())
    def test_hidden_wait_does_not_expire_at_45_seconds_and_return_can_continue(self):
        self.jobs.accept(self.id,self.event())
        self.jobs.accept(self.id,self.event('progress',2,phase='waiting_page'))
        self.clock+=60
        self.assertEqual(self.jobs.status(self.id)['state'],'collecting')
        self.assertEqual(self.jobs.status(self.id)['phase'],'waiting_page')
        self.jobs.accept(self.id,self.event('progress',3,phase='reading'))
        self.assertEqual(self.jobs.status(self.id)['phase'],'reading')
        self.assertEqual(self.jobs.status(self.id)['reviewCount'],1)

    def test_hidden_watchdog_saves_without_heartbeat_and_allows_same_lease_continue(self):
        self.jobs.accept(self.id,self.event())
        self.jobs.accept(self.id,self.event('progress',2,phase='waiting_page'))
        self.clock+=301
        final=self.jobs.status(self.id)
        self.assertEqual(final['doneReason'],'page_hidden');self.assertTrue(final['can_continue'])
        self.assertTrue(Path(final['zip_path']).is_file())
        late=self.jobs.accept(self.id,self.event('progress',3,phase='waiting_page'))
        self.assertEqual(late['state'],'saved')
        with self.assertRaises(ValueError):self.jobs.accept(self.id,self.event(sequence=3))
        resumed=copy.deepcopy(self.request);resumed.update(request_id=str(uuid.uuid4()),resume_from=self.id,observed_at_epoch_ms=self.clock*1000,product_identity=final['product_identity'])
        self.assertEqual(self.jobs.start(resumed,self.root)['reviewCount'],1)

    def test_hidden_heartbeat_cannot_extend_original_budget_or_relax_fields(self):
        self.clock+=550
        self.jobs.accept(self.id,self.event('progress',1,phase='waiting_page'))
        self.clock+=51
        self.assertEqual(self.jobs.status(self.id)['doneReason'],'time_limit')
        for event in (self.event('progress',2,phase='arbitrary'),self.event(sequence=2,phase='waiting_page')):
            with self.assertRaises(ValueError):self.jobs.accept(self.id,event)
    def test_stop_saves_acknowledged_rows_without_waiting_for_page(self):
        self.jobs.accept(self.id,self.event())
        body={'room_url':self.request['room_url']}
        final=self.jobs.stop(self.id,body)
        self.assertEqual(final['reviewCount'],1);self.assertEqual(final['doneReason'],'user_paused')
        self.assertEqual(self.jobs.stop(self.id,body),final)
        with zipfile.ZipFile(final['zip_path']) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(json.loads(archive.read('完整性.json'))['completeness'],'partial_user_paused')
        # Delayed page batches cannot reopen or change a stopped download.
        with self.assertRaises(ValueError):self.jobs.accept(self.id,self.event(sequence=2))
    def test_stop_wrong_room_unknown_fields_and_disk_error_are_not_success(self):
        for body in ({'room_url':'https://live.douyin.com/999'},{'room_url':self.request['room_url'],'path':'other'}):
            with self.assertRaises(ValueError):self.jobs.stop(self.id,body)
        with mock.patch.object(self.jobs,'_checkpoint',side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):self.jobs.stop(self.id,{'room_url':self.request['room_url']})
        self.assertEqual(self.jobs.status(self.id)['state'],'collecting')
    def test_phone_redaction_and_csv_formula(self):
        r=row()|{'content':'=合成公式','merchant_reply':'请联系13812345678'}
        final=self.jobs.accept(self.id,self.event(rows=[r]));root=Path(final['output_dir'])
        self.assertNotIn('13812345678',(root/'商品评价.jsonl').read_text(encoding='utf-8'))
        self.assertIn("'=合成公式",(root/'商品评价.csv').read_text(encoding='utf-8-sig'))
    def test_restart_cannot_silently_reuse_an_existing_directory(self):
        other=ProductReviewJobs(now=lambda:self.clock)
        with self.assertRaises(FileExistsError):other.start(self.request,self.root)
    def test_failed_checkpoint_is_not_acknowledged_and_can_retry(self):
        with mock.patch.object(self.jobs,'_checkpoint',side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):self.jobs.accept(self.id,self.event())
        self.assertEqual(self.jobs.status(self.id)['reviewCount'],0)
        self.assertEqual(self.jobs.accept(self.id,self.event())['reviewCount'],1)
        with mock.patch.object(self.jobs,'_checkpoint',side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):self.jobs.accept(self.id,self.event('finish',2,done_reason='user_paused'))
        self.assertEqual(self.jobs.status(self.id)['state'],'collecting')
        self.assertEqual(self.jobs.accept(self.id,self.event('finish',2,done_reason='user_paused'))['state'],'saved')

    def test_heartbeat_does_not_rewrite_material_and_end_time_is_frozen(self):
        with mock.patch.object(self.jobs,'_checkpoint') as checkpoint:
            self.jobs.accept(self.id,self.event('progress'))
            checkpoint.assert_not_called()
        self.clock+=120
        end=self.jobs.accept(self.id,self.event('finish',2,done_reason='time_limit'))
        self.assertEqual(end['elapsed_seconds'],120)
        self.clock+=400
        self.assertEqual(self.jobs.status(self.id)['elapsed_seconds'],120)
        self.assertEqual([time_budget(n) for n in (50,200,500)],[180,600,600])

    def continuation(self):
        self.jobs.accept(self.id,self.event())
        end=self.jobs.accept(self.id,self.event('finish',2,done_reason='time_limit'))
        return copy.deepcopy(self.request)|{'request_id':str(uuid.uuid4()),'resume_from':self.id,
            'product_identity':end['product_identity']},end

    def test_continue_creates_cumulative_version_dedupes_and_keeps_old_zip(self):
        request,end=self.continuation();old=Path(end['zip_path']).read_bytes()
        new=self.jobs.start(request,self.root);ident=new['id']
        self.assertEqual(new['reviewCount'],1);self.assertEqual(new['baseline_count'],1)
        self.assertEqual(new['anonymization_id'],self.id)
        self.assertEqual(self.jobs.start(request,self.root)['id'],ident)
        self.jobs.accept(ident,self.event(rows=[row(),row()|{'review_id':'c'*64}]))
        with self.assertRaisesRegex(ValueError,'target not reached'):
            self.jobs.accept(ident,self.event('finish',2,done_reason='target_reached'))
        new=self.jobs.accept(ident,self.event('finish',2,done_reason='time_limit'))
        self.assertEqual(new['reviewCount'],2);self.assertTrue(new['can_continue'])
        self.assertEqual(Path(end['zip_path']).read_bytes(),old)
        with zipfile.ZipFile(new['zip_path']) as z:
            info=json.loads(z.read('完整性.json'))
            self.assertEqual(info['continuation']['inherited_count'],1)
            self.assertEqual(info['continuation']['new_count'],1)
            self.assertNotIn(b'documentToken',z.read('完整性.json'))
        other=request|{'request_id':str(uuid.uuid4())}
        with self.assertRaises(ValueError):self.jobs.start(other,self.root)

    def test_continue_rejects_changed_document_product_filter_goal_and_restart(self):
        request,_=self.continuation()
        for key in ('lease','product_identity','product','filter_label','limit'):
            changed=copy.deepcopy(request)
            if key=='lease':changed[key]['documentToken']='another-document'
            elif key=='product_identity':changed[key]['product_ref']='douyin:observation:'+str(uuid.uuid4())
            elif key=='product':changed[key]['title']='其他合成商品'
            elif key=='limit':changed[key]=500
            else:changed[key]='最新'
            with self.subTest(key=key),self.assertRaises(ValueError):self.jobs.start(changed,self.root)
        with self.assertRaises(ValueError):ProductReviewJobs(now=lambda:self.clock).start(request,self.root)

    def test_continue_stale_or_unfinished_job_is_rejected(self):
        body=copy.deepcopy(self.request)|{'request_id':str(uuid.uuid4()),'resume_from':self.id,
             'product_identity':self.jobs.status(self.id)['product_identity']}
        with self.assertRaises(ValueError):self.jobs.start(body,self.root)
        self.jobs.accept(self.id,self.event('finish',1,done_reason='surface_or_filter_changed'))
        with self.assertRaises(ValueError):self.jobs.start(body,self.root)

class CropTests(unittest.TestCase):
    def test_missing_short_tail_downgrades_completeness(self):
        base='https://p3.ecombdimg.com/synthetic_www1500-3066~tplv-test-xy:0:'
        images=[dict(kind='product_detail',url=base+f'{top}:1500:{bottom}.jpeg') for top,bottom in [(0,1000),(1000,2000),(2000,3000)]]
        self.assertFalse(complete_crop_tiles(images))
        coverage=dict(mode='single_product_full',main_expected=None,main_observed=0,detail_observed=3,main_complete=False,
                      detail_complete=True,detail_end_evidence='explicit_end',stop_reason=None,fields_observed_at_epoch_ms=1000)
        self.assertFalse(validate_coverage(coverage,images)['detail_complete'])
        images.append(dict(kind='product_detail',url=base+'3000:1500:3066.jpeg'))
        self.assertTrue(complete_crop_tiles(images))

class ReviewHttpTests(unittest.TestCase):
    def test_auth_scope_routes_and_no_recording_created(self):
        with scratch_dir() as root:
            manager=TaskManager(store=TaskStore(root/'state.sqlite3'),output_root=root/'out')
            token='synthetic-token-at-least-32-characters'
            server=create_http_server(host='127.0.0.1',port=0,manager=manager,token=token)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            def call(path,body=None,headers=None):
                return urllib.request.urlopen(urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),
                    headers={'Content-Type':'application/json',**({'X-BrandBAI-Token':token} if headers is None else headers)}),timeout=3)
            try:
                body=request();body['observed_at_epoch_ms']=time.time()*1000;ident=body['request_id']
                with self.assertRaises(urllib.error.HTTPError) as e:call('/v1/product-reviews',body,{})
                self.assertEqual(e.exception.code,401);e.exception.close()
                with self.assertRaises(urllib.error.HTTPError) as e:call('/v1/product-reviews',body,{'Origin':'https://example.test','X-BrandBAI-Token':token})
                self.assertEqual(e.exception.code,403);e.exception.close()
                with call('/v1/product-reviews',body) as r:self.assertEqual(json.load(r)['task']['state'],'collecting')
                event=dict(lease=body['lease'],sequence=1,action='batch',rows=[row()],done_reason='',exhausted=False,empty_confirmed=False)
                with call(f'/v1/product-reviews/{ident}/events',event) as r:self.assertEqual(json.load(r)['task']['reviewCount'],1)
                for headers,body,status in [({}, {'room_url':body['room_url']},401),
                        (None,{'room_url':'https://live.douyin.com/999'},400)]:
                    with self.assertRaises(urllib.error.HTTPError) as e:call(f'/v1/product-reviews/{ident}/stop',body,headers)
                    self.assertEqual(e.exception.code,status);e.exception.close()
                with call(f'/v1/product-reviews/{ident}/stop',{'room_url':event['lease']['contextKey']}) as r:self.assertEqual(json.load(r)['task']['state'],'saved')
                with call(f'/v1/product-reviews/{ident}') as r:self.assertEqual(json.load(r)['task']['reviewCount'],1)
                self.assertEqual(manager.list(),[])
            finally:server.shutdown();server.server_close();thread.join(2);manager.shutdown()
