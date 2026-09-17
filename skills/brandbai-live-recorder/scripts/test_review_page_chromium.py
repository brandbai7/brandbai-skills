"""Synthetic browser + real local persistence. No user profile or platform requests."""
import json
import os
import re
import unittest
from pathlib import Path
from product_reviews import ProductReviewJobs
from test_local_service import scratch_dir
import test_live_products_chromium as fixtures
EXT=fixtures.EXT

HTML='''<!doctype html><meta charset="utf-8"><style>
.eRfaxg7R{width:650px;height:500px;overflow-y:scroll}.header{height:160px}
.Ez3MC6d7{padding:20px;min-height:100px}.yVU8TMWn{height:44px}
</style><div class="lqrK15Gt"><div class="eRfaxg7R" data-product-id="123456789012345">
<div class="header"><div class="AjnzIIcY">合成旗舰店</div><span class="vs9hmvGz">合成商品测试标题</span><p>保障 物流</p></div>
<div class="NGeinxLS"><div class="yVU8TMWn"><span>商品详情</span><button id="reviewtab">商品评价(9000)</button></div>
<div class="FDag2E0P" hidden><span class="YLWPPuPR SrtfuQFU">全部</span><span class="NtPaXoT7 mFEHKTxv">综合</span>
<div class="PEzhiR4O"></div></div></div></div></div><script>
const list=document.querySelector('.PEzhiR4O'),panel=document.querySelector('.eRfaxg7R');
window.tabClicks=0;window.scrollEvents=0;window.appended=false;
function addReview(i){const card=document.createElement('div');card.className='Ez3MC6d7';card.dataset.reviewId='synthetic-'+i;
card.innerHTML='<div class="ji7a60UU"><div class="sVIJnLfX"><span>合成用户'+i+'</span></div><div class="Xug6qnCc">3个月前</div></div>'
+'<div class="bFXVK94u">已购:50g</div><div class="mgNuPdjB">'+(i===2?'':'合成评价'+i)+'</div>'
+'<div class="AdYl5cnz">'+(i===2?'<img src="https://p3.douyinpic.com/test.jpg?signature=NEVER_EXPORT">':'')+'</div>'
+'<div class="swfDpKGt">浏览100 <span class="X2TC7MK5">18</span></div>';list.append(card);}
for(let i=1;i<=6;i++)addReview(i);const footer=document.createElement('div');footer.className='Ao_Mqy8Y';footer.textContent='加载中';list.append(footer);
document.querySelector('#reviewtab').onclick=()=>{tabClicks++;document.querySelector('.FDag2E0P').hidden=false};
panel.onscroll=()=>{scrollEvents++;if(!appended&&panel.scrollTop+panel.clientHeight>=panel.scrollHeight-10){appended=true;footer.remove();for(let i=7;i<=9;i++)addReview(i);footer.textContent='没有更多评价';list.append(footer)}};
</script>'''

@unittest.skipUnless(os.getenv('BRANDBAI_RUN_BROWSER_TESTS')=='1','Opt-in isolated Chromium')
class ReviewPageTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.LiveProductChromiumTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.LiveProductChromiumTests.tearDownClass.__func__)
    def setUp(self):
        self.temp=scratch_dir();self.root=self.temp.__enter__();self.jobs=ProductReviewJobs();self.messages=[]
        self.context=self.browser.new_context(viewport={'width':1000,'height':800})
        self.context.route('**/*',lambda r:r.fulfill(status=200,content_type='text/html',body=HTML) if r.request.url.startswith('http://localhost:9876') else r.abort())
        self.page=self.context.new_page();self.page.goto('http://localhost:9876/')
        def bridge(message):
            self.messages.append(message)
            if message['action']=='start':return {'task':self.jobs.start(message['body'],self.root)}
            return {'task':self.jobs.accept(message['request_id'],message['body'])}
        self.page.expose_function('bridge',bridge)
        # Exercise the real extension background route, not just the parser.
        # Storage round trips deliberately reorder nested object fields.
        self.page.add_script_tag(content='''(()=>{
          const sorted=v=>Array.isArray(v)?v.map(sorted):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,sorted(v[k])])):v;
          const stored={}, event={addListener(){}};
          const chrome={runtime:{id:'synthetic-extension',onInstalled:event,onStartup:event,onMessage:event},sidePanel:{async setPanelBehavior(){}},
            tabs:{onRemoved:event},storage:{session:{async get(k){return sorted({[k]:stored[k]})},async set(v){Object.assign(stored,sorted(v))},async remove(k){delete stored[k]}}}};
        '''+(EXT/'background.js').read_text(encoding='utf-8')+'''
          api=async(path,opts)=>window.bridge(path==='/v1/product-reviews'?{action:'start',body:opts.body}:
            {action:'event',request_id:path.split('/')[3],body:opts.body});
          window.reviewSend=message=>handleMessage(message,{id:chrome.runtime.id,tab:{id:1,url:window.room},url:window.room,documentId:'synthetic-document'});
        })();''')
        for filename in ('douyin-commerce-dom.js','product-identity.js','live-products.js','product-review-collector.js','review-page.js','page-materials.js'):
            self.page.add_script_tag(content=(EXT/filename).read_text(encoding='utf-8'))
        self.page.evaluate('''()=>{
          document.querySelector('#reviewtab').textContent='商品评价(22.9万)';
          window.room='https://live.douyin.com/123456';window.materialBusy=false;window.pauseCalls=0;
          HTMLMediaElement.prototype.pause=function(){pauseCalls++};
          const rendered=n=>!!n?.isConnected&&!n.closest('[hidden]')&&n.getBoundingClientRect().width>0;
          const visible=n=>{if(!rendered(n))return false;const r=n.getBoundingClientRect();return r.bottom>0&&r.top<innerHeight};
          document.querySelector('.header').insertAdjacentHTML('beforeend','<img style="width:100px;height:60px" src="https://p3.ecombdimg.com/synthetic-main.png">');
          window.inspector=BrandbaiDouyinCommerceDom.createInspector({document,window,isVisible:visible,isRendered:rendered});
          window.reader=BrandbaiLiveProducts.createCollector({document,inspector,isVisible:visible,roomUrl:()=>room,newId:()=>crypto.randomUUID(),emit(){}});
          window.reviews=BrandbaiLiveReviews.create({document,window,roomUrl:()=>room,isRendered:rendered,isVisible:visible,
            inspector,getProductContext:()=>reader.identityCurrent(),send:m=>window.reviewSend(m),materialBusy:()=>window.materialBusy});
        }''')
    def tearDown(self):
        self.context.close();self.jobs.shutdown();self.temp.__exit__(None,None,None)
    def open(self):self.page.click('#reviewtab')
    def start(self,limit=200):
        return self.page.evaluate('(limit)=>reviews.start({expected:reviews.preview(),limit,request_id:crypto.randomUUID()})',limit)
    def finish(self):
        self.page.wait_for_function("reviews.status().job?.state!=='collecting'",timeout=30000)
        return self.page.evaluate('reviews.status().job')
    def test_read_only_preview_requires_manual_open(self):
        p=self.page.evaluate('reviews.preview()');self.assertFalse(p['ready'])
        self.assertEqual(self.page.evaluate('window.tabClicks'),0);self.assertEqual(self.messages,[])
        self.open();p=self.page.evaluate('reviews.preview()');self.assertTrue(p['ready']);self.assertEqual(p['declared_count_text'],'22.9万')

    def test_rehashed_tab_content_sibling_and_unprefixed_sku(self):
        self.open()
        self.page.evaluate('''()=>{
          document.querySelector('.FDag2E0P').style.color='rgb(255,40,80)';
          for(const card of document.querySelectorAll('.Ez3MC6d7')){
            card.querySelector('.ji7a60UU').insertAdjacentHTML('afterbegin','<img src="https://p3.douyinpic.com/avatar.png">');
            card.querySelector('.bFXVK94u').textContent='50g 礼盒装';
            card.querySelector('.swfDpKGt').innerHTML='<span>浏览100</span><div><svg></svg><span>18</span></div>';
          }
          for(const node of document.querySelectorAll('.NGeinxLS,.NGeinxLS *'))node.className='changed-layout-'+node.tagName;
        }''')
        p=self.page.evaluate('reviews.preview()');self.assertTrue(p['ready'],p)
        self.assertEqual(p['loaded_count'],6);self.assertEqual(p['declared_count_text'],'22.9万')
        self.assertIn('综合',p['filter_label'])
        self.start(3);job=self.finish();self.assertEqual(job['reviewCount'],3,job)
        rows=[json.loads(line) for line in (Path(job['output_dir'])/'商品评价.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertTrue(all(r['purchased_sku']=='50g 礼盒装' for r in rows))
        self.assertEqual(self.page.evaluate('tabClicks'),1)

    def test_review_end_inside_fixed_portal_is_visible_despite_collapsed_page(self):
        self.open()
        self.page.evaluate('''()=>{const panel=document.querySelector('.lqrK15Gt');
          const collapsed=document.createElement('main');collapsed.style='height:0;overflow:hidden';
          panel.before(collapsed);collapsed.append(panel);panel.style='position:fixed;top:0;left:0';}''')
        self.start();job=self.finish()
        self.assertEqual(job['doneReason'],'source_exhausted',job);self.assertEqual(job['reviewCount'],9)

    def test_saved_review_of_other_product_moves_out_of_current_card(self):
        self.sidebar();self.page.click('#review-start')
        self.page.wait_for_function('backendJob?.state==="collecting"')
        self.page.click('#review-stop');self.page.wait_for_function("!document.querySelector('#review-copy').hidden")
        self.page.evaluate('''()=>{currentProduct={...currentProduct,snapshot:{...currentProduct.snapshot,
          product_identity:{...identity,product_id:'999999999999999',product_ref:'douyin:product:999999999999999'}}};
          window.dispatchEvent(new Event('brandbai-current-product-changed'));}''')
        self.page.wait_for_function("document.querySelector('#review-history-result #review-result')!==null")
        self.assertEqual(self.page.locator('#single-product-card #review-result').count(),0)
        self.assertFalse(self.page.is_hidden('#review-preview'))
        self.assertIn('其他商品评价',self.page.text_content('#review-result-title'))
    def test_scrolling_checkpoint_privacy_and_independent_output(self):
        self.open();self.start();job=self.finish()
        self.assertEqual(job['reviewCount'],9,job);self.assertEqual(job['state'],'saved')
        self.assertEqual(self.page.evaluate('window.pauseCalls'),0);self.assertEqual(self.page.evaluate('window.tabClicks'),1)
        self.assertGreater(self.page.evaluate('window.scrollEvents'),0)
        sent=json.dumps(self.messages,ensure_ascii=False);self.assertNotIn('合成用户',sent);self.assertNotIn('NEVER_EXPORT',sent)
        rows=[json.loads(line) for line in (Path(job['output_dir'])/'商品评价.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertTrue(all(r['purchased_sku']=='已购:50g' for r in rows));self.assertTrue(Path(job['zip_path']).is_file())
    def test_filter_change_and_limit_are_partial(self):
        self.open();self.start(2);job=self.finish();self.assertEqual(job['reviewCount'],2)
        self.assertTrue(job['completeness'].startswith('partial'))
        self.assertEqual(job['doneReason'],'target_reached');self.assertFalse(job['can_continue'])

    def test_continue_after_pause_keeps_same_product_dedupes_and_preserves_old_package(self):
        self.open();self.start();self.page.wait_for_function('reviews.status().job.reviewCount>0')
        self.page.evaluate('reviews.stop()');first=self.finish()
        self.assertEqual(first['doneReason'],'user_paused');self.assertLess(first['reviewCount'],9)
        original=Path(first['zip_path']).read_bytes()
        self.page.wait_for_function('reviews.preview().resumable_job_id===reviews.status().job.id')
        self.page.evaluate('reviews.start({expected:reviews.preview(),limit:200,request_id:crypto.randomUUID(),resume_from:reviews.status().job.id})')
        final=self.finish()
        self.assertEqual(final['reviewCount'],9,final);self.assertNotEqual(final['id'],first['id'])
        self.assertEqual(final['baseline_count'],first['reviewCount']);self.assertEqual(final['anonymization_id'],first['id'])
        self.assertEqual(final['product_identity'],first['product_identity'])
        self.assertEqual(Path(first['zip_path']).read_bytes(),original)
        old=[json.loads(r) for r in (Path(first['output_dir'])/'商品评价.jsonl').read_text(encoding='utf-8').splitlines()]
        new=[json.loads(r) for r in (Path(final['output_dir'])/'商品评价.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len({r['review_id'] for r in new}),9)
        self.assertTrue(all(r in new for r in old));self.assertEqual(self.page.evaluate('pauseCalls'),0)

    def test_changed_filter_invalidates_continue_without_creating_job(self):
        self.open();self.start();self.page.wait_for_function('reviews.status().job.reviewCount>0')
        self.page.evaluate('reviews.stop()');self.finish()
        self.page.wait_for_function('!!reviews.preview().resumable_job_id')
        self.page.evaluate("document.querySelector('.NtPaXoT7').textContent='最新'")
        self.assertIsNone(self.page.evaluate('reviews.preview().resumable_job_id'))
        result=self.page.evaluate('async()=>{try{await reviews.start({expected:reviews.preview(),limit:200,request_id:crypto.randomUUID(),resume_from:reviews.status().job.id});return false}catch(_){return true}}')
        self.assertTrue(result);self.assertEqual(len(self.jobs.jobs),1)
    def test_changed_source_does_not_start(self):
        self.open();self.page.evaluate('window.expected=reviews.preview();window.room="https://live.douyin.com/999999"')
        result=self.page.evaluate('async()=>{try{await reviews.start({expected,limit:10,request_id:crypto.randomUUID()});return false}catch(_){return true}}')
        self.assertTrue(result);self.assertEqual(self.messages,[])

    def test_detail_and_reviews_use_same_identity_and_id_change_stops(self):
        before=self.page.evaluate('reader.previewCurrent().snapshot.product_identity')
        self.open();preview=self.page.evaluate('reviews.preview()')
        self.assertEqual(before,preview['product_identity'])
        self.start();self.page.wait_for_function('reviews.status().job.reviewCount>0')
        self.page.evaluate("document.querySelector('.eRfaxg7R').dataset.productId='999999999999999'")
        job=self.finish();self.assertEqual(job['doneReason'],'product_or_work_changed')
        self.assertEqual(job['product_identity']['product_id'],before['product_id'])
    def test_filter_switch_during_collection_stops_and_keeps_rows(self):
        self.open();self.start()
        self.page.wait_for_function('reviews.status().job.reviewCount>0')
        self.page.evaluate("document.querySelector('.NtPaXoT7').textContent='最新'")
        job=self.finish();self.assertGreater(job['reviewCount'],0)
        self.assertEqual(job['doneReason'],'surface_or_filter_changed');self.assertTrue(Path(job['zip_path']).is_file())
    def test_user_stop_saves_partial_without_hiding_product(self):
        self.open();self.start();self.page.wait_for_function('reviews.status().job.reviewCount>0')
        self.page.evaluate('reviews.stop()');job=self.finish()
        self.assertEqual(job['doneReason'],'user_paused');self.assertGreater(job['reviewCount'],0)
        self.assertTrue(self.page.is_visible('.eRfaxg7R'))
    def test_material_operation_blocks_review_start(self):
        self.open();self.page.evaluate('window.materialBusy=true')
        result=self.page.evaluate('async()=>{try{await reviews.start({expected:reviews.preview(),limit:10,request_id:crypto.randomUUID()});return false}catch(_){return true}}')
        self.assertTrue(result);self.assertEqual(self.messages,[])
    def test_visibility_wait_returns_to_same_page_without_exporting_early(self):
        self.open();self.start();self.page.wait_for_function('reviews.status().job.reviewCount>0')
        self.page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});document.dispatchEvent(new Event('visibilitychange'))")
        self.page.wait_for_function("reviews.status().job.phase==='waiting_page'")
        count=self.page.evaluate('reviews.status().job.reviewCount');scrolls=self.page.evaluate('scrollEvents')
        self.page.wait_for_timeout(1600)
        self.assertEqual(self.page.evaluate('reviews.status().job.state'),'collecting')
        self.assertEqual(self.page.evaluate('reviews.status().job.reviewCount'),count)
        self.assertEqual(self.page.evaluate('scrollEvents'),scrolls)
        self.page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});document.dispatchEvent(new Event('visibilitychange'))")
        final=self.finish();self.assertEqual(final['reviewCount'],9);self.assertEqual(final['doneReason'],'source_exhausted')
        self.assertEqual(len(self.jobs.jobs),1)

    def test_stop_while_waiting_for_page_remains_immediate(self):
        self.open();self.start();self.page.wait_for_function('reviews.status().job.reviewCount>0')
        self.page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'})")
        self.page.wait_for_function("reviews.status().job.phase==='waiting_page'")
        self.page.evaluate('reviews.stop()');self.assertEqual(self.finish()['doneReason'],'user_paused')

    def test_download_history_is_collapsed_and_selected_result_isolated(self):
        self.sidebar()
        self.page.evaluate('''()=>{
          window.deliveries=Array.from({length:25},(_,i)=>({id:'test-'+i,kind:'reviews',state:'completed',created_at:1789460000-i,
            filename:'抖音_合成店_商品评价_2026-09-17_19-00-'+i+'.zip'}));
          const api=window.api;window.api=async path=>path==='/v1/deliveries'?{deliveries}:api(path);
          window.downloadCommands=[];chrome.runtime={async sendMessage(m){downloadCommands.push(m);return {ok:true}}};
        }''')
        self.page.add_script_tag(content=(EXT/'download-panel.js').read_text(encoding='utf-8'))
        self.page.wait_for_function("document.querySelector('.download-history')")
        self.assertFalse(self.page.evaluate("document.querySelector('#storage-settings').open"))
        self.assertFalse(self.page.evaluate("document.querySelector('.download-history').open"))
        self.assertEqual(self.page.locator('.browser-delivery-item').count(),5)
        self.page.evaluate("BrandbaiDownloads.reveal('test-12')")
        self.assertTrue(self.page.evaluate("document.querySelector('#storage-settings').open"))
        self.assertEqual(self.page.locator('#browser-delivery-list > .browser-delivery-item[open]').count(),1)
        self.assertFalse(self.page.evaluate("document.querySelector('.download-history').open"))
        self.page.locator('#browser-delivery-list > .browser-delivery-item button').click()
        self.assertEqual(self.page.evaluate("downloadCommands.filter(m=>m.action==='show').at(-1).id"),'test-12')
        for width in (320,380,480):
            self.page.set_viewport_size({'width':width,'height':900})
            self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth>innerWidth'))
        if os.getenv('BRANDBAI_HISTORY_PREVIEW'):self.page.locator('#storage-settings').screenshot(path=os.environ['BRANDBAI_HISTORY_PREVIEW'])

    def test_browser_history_for_another_product_is_not_repeated_on_product_page(self):
        self.sidebar();self.page.click('#review-start');self.page.wait_for_function('backendJob?.state==="collecting"')
        self.page.evaluate("backendJob={...backendJob,state:'saved',doneReason:'target_reached',reviewCount:200,delivery:{id:'synthetic'}}")
        self.page.wait_for_function("document.querySelector('#review-result-title').textContent==='已读满目标条数'")
        self.page.evaluate("currentProduct=null;window.dispatchEvent(new Event('brandbai-current-product-changed'))")
        self.page.wait_for_function("document.querySelector('#review-result').hidden")
        self.assertTrue(self.page.is_hidden('#product-history'))

    def test_sidebar_wait_state_explains_return_instead_of_failed_download(self):
        self.sidebar();self.page.click('#review-start');self.page.wait_for_function('backendJob?.state==="collecting"')
        self.page.evaluate("backendJob={...backendJob,phase:'waiting_page',reviewCount:60}")
        self.page.wait_for_function("document.querySelector('#review-result-title').textContent==='等待返回评价页'")
        self.assertIn('已读取 60 / 200 条',self.page.text_content('#review-count'))
        self.assertFalse(self.page.is_disabled('#review-stop'))
        self.assertTrue(self.page.is_hidden('#review-copy'))
        if os.getenv('BRANDBAI_WAIT_PREVIEW'):self.page.locator('#review-card').screenshot(path=os.environ['BRANDBAI_WAIT_PREVIEW'])
    def test_stop_acknowledges_even_while_batch_is_waiting(self):
        self.open()
        self.page.evaluate('''()=>{const send=window.reviewSend;window.reviewSend=m=>{
          if(m.action==='event'&&m.body.action==='batch')return new Promise(resolve=>{window.releaseBatch=()=>resolve(send(m));});
          return send(m);
        };}''')
        current=self.start();self.page.wait_for_function('!!window.releaseBatch')
        result=self.page.evaluate('''()=>{const began=performance.now();const result=reviews.stop({request_id:reviews.status().job.id});return {elapsed:performance.now()-began,...result}}''')
        self.assertTrue(result['stopping']);self.assertLess(result['elapsed'],200)
        self.assertEqual(self.page.evaluate('scrollEvents'),0)
        self.page.evaluate('window.releaseBatch()');job=self.finish()
        self.assertEqual(job['doneReason'],'user_paused');self.assertGreater(job['reviewCount'],0)
    def test_stale_stop_does_not_stop_other_review_job(self):
        self.open();self.start()
        stopped=self.page.evaluate('''()=>{try{reviews.stop({request_id:'other-job'});return true}catch(_){return false}}''')
        self.assertFalse(stopped);self.assertEqual(self.finish()['doneReason'],'source_exhausted')
    def test_short_tail_crop_coverage(self):
        self.assertFalse(self.page.evaluate('BrandbaiPageMaterials.completeCropTiles(["https://p3.ecombdimg.com/test_www1500-3066~tplv-test-xy:0:0:1500:3000.jpeg"])'))
        self.assertTrue(self.page.evaluate('BrandbaiPageMaterials.completeCropTiles(["https://p3.ecombdimg.com/test_www1500-3066~tplv-test-xy:0:0:1500:3000.jpeg","https://p3.ecombdimg.com/test_www1500-3066~tplv-test-xy:0:3000:1500:3066.jpeg"])'))

    def sidebar(self, restore=False):
        html=re.sub(r'<script src="[^"]+"></script>', '', (EXT/'popup.html').read_text(encoding='utf-8'))
        self.page.set_content(html)
        self.page.add_style_tag(content=(EXT/'design-tokens.css').read_text(encoding='utf-8'))
        self.page.add_style_tag(content=(EXT/'sidepanel.css').read_text(encoding='utf-8'))
        self.page.set_viewport_size({'width':480,'height':900})
        self.page.evaluate('''()=>{
          document.body.classList.add('product-mode');document.querySelector('#product-workspace').hidden=false;
          window.sessionToken='synthetic';window.storageSettings={configured:true,mode:'browser-zip'};window.backendJob=null;window.recordingStarts=0;
          window.canonicalRoomUrl=()=> 'https://live.douyin.com/123456';window.ensureCurrentTabContentScript=async()=>true;
          window.connectService=async()=>true;window.refreshStorageSettings=async()=>{};window.getConnectionIssue=()=>null;
          window.identity={platform:'douyin',product_id:'123456789012345',product_ref:'douyin:product:123456789012345',identity_status:'verified'};
          window.currentProduct={panel_key:'synthetic:1',snapshot:{product_title:'合成商品 <img onerror=alert(1)>',product_identity:identity}};
          window.BrandbaiCurrentProduct={get:()=>currentProduct,inspect:async()=>currentProduct,hold:p=>{currentProduct=p}};
          window.api=async path=>path==='/v1/health'?{independent_product_reviews:true,shared_product_identity:true,review_stop_save:true,browser_zip_delivery:true,review_target_continuation:true,review_visibility_wait:true}:{task:backendJob};
          window.chrome={storage:{session:{async get(){return {}},async set(){},async remove(){}}},tabs:{
            async query(){return [{id:1,url:'https://live.douyin.com/123456'}]},async sendMessage(id,m){
              if(m.type==='brandbai-review-preview')return {ready:true,product_identity:identity,product:{title:'合成商品 <img onerror=alert(1)>',shop_name:'合成店',product_id:'123456789012345'},lease:{id:'synthetic'},filter_label:'全部 · 综合',declared_count_text:'22.9万',loaded_count:20};
              if(m.type==='brandbai-review-start'){backendJob={id:m.request_id,runId:m.request_id,state:'collecting',product:m.expected.product,filter_label:'全部 · 综合',reviewCount:3,limit:m.limit,elapsed_seconds:5};return {job:backendJob};}
              if(m.type==='brandbai-review-stop'){backendJob={...backendJob,state:'saved',doneReason:'user_paused',completeness:'partial_user_paused',output_dir:'synthetic'};return {job:backendJob};}
            }}};
        }''')
        self.page.add_script_tag(content=(EXT/'product-identity.js').read_text(encoding='utf-8'))
        if restore:
            self.page.evaluate('''()=>{
              backendJob={id:'synthetic-restored',runId:'synthetic-restored',state:'collecting',reviewCount:100,limit:200,product: {title:'合成商品'},product_identity:identity,current_product:currentProduct};
              chrome.storage.session.get=async()=>({'brandbai.reviewJob':{...backendJob}});
              window.statusConnected=false;const statusApi=window.api;
              window.api=async path=>{if(!statusConnected)throw Error('synthetic pairing pending');return statusApi(path)};
            }''')
        self.page.add_script_tag(content=(EXT/'review-panel.js').read_text(encoding='utf-8'))
    def test_real_sidebar_controls_progress_stop_and_escaped_titles(self):
        self.sidebar()
        self.assertEqual(self.page.locator('#single-product-card #review-card').count(),1)
        self.assertEqual(self.page.locator('#review-refresh').count(),0)
        self.page.click('#refresh-product');self.page.wait_for_function("document.querySelector('#review-preview').textContent.includes('评价已识别')")
        self.assertEqual(self.page.locator('#review-preview img').count(),0)
        self.page.click('#review-start');self.page.wait_for_function("document.querySelector('#review-count').textContent.includes('已读取 3 /')")
        self.assertTrue(self.page.is_disabled('#review-start'));self.assertTrue(self.page.is_disabled('#review-limit'))
        self.assertTrue(self.page.is_hidden('#review-preview'));self.assertTrue(self.page.is_hidden('#review-start'))
        self.assertTrue(self.page.is_hidden('#review-limit-field'))
        self.page.evaluate('backendJob.reviewCount=40')
        self.page.wait_for_function("document.querySelector('#review-count').textContent.includes('已读取 40 /')")
        self.page.click('#review-stop');self.page.wait_for_function("!document.querySelector('#review-copy').hidden")
        self.assertIn('不代表全部历史评价',self.page.text_content('#review-result-note'));self.assertFalse(self.page.is_disabled('#review-start'))
        if os.getenv('BRANDBAI_UI_PREVIEW'):self.page.locator('#review-card').screenshot(path=os.environ['BRANDBAI_UI_PREVIEW'])
    def test_sidebar_stop_unresponsive_page_uses_authenticated_save_fallback(self):
        self.sidebar()
        self.page.evaluate('''()=>{const send=chrome.tabs.sendMessage;chrome.tabs.sendMessage=(id,m)=>m.type==='brandbai-review-stop'?new Promise(()=>{}):send(id,m);
          const api=window.api;window.stopCalls=0;window.api=async(path,opts)=>{
            if(path.endsWith('/stop')){stopCalls++;backendJob={...backendJob,state:'saved',doneReason:'user_paused',completeness:'partial_user_paused',output_dir:'synthetic'};return {task:backendJob};}return api(path,opts);
          };}''')
        self.page.click('#review-start');self.page.wait_for_function("document.querySelector('#review-count').textContent.includes('已读取 3 /')")
        self.page.click('#review-stop');self.assertTrue(self.page.is_disabled('#review-stop'))
        self.assertIn('正在停止',self.page.text_content('#review-stop'))
        self.page.wait_for_function("!document.querySelector('#review-copy').hidden",timeout=7000)
        self.assertEqual(self.page.evaluate('stopCalls'),1)
        self.assertIn('已读取 3 /',self.page.text_content('#review-count'))
    def test_sidebar_stop_failure_releases_retry_button_and_keeps_job(self):
        self.sidebar()
        self.page.evaluate('''()=>{const send=chrome.tabs.sendMessage;chrome.tabs.sendMessage=(id,m)=>m.type==='brandbai-review-stop'?Promise.reject(Error('disconnected')):send(id,m);
          const api=window.api;window.api=async(path,opts)=>{if(path.endsWith('/stop'))throw Error('synthetic save failure');return api(path,opts)};
        }''')
        self.page.click('#review-start');self.page.wait_for_function("document.querySelector('#review-count').textContent.includes('已读取 3 /')")
        self.page.click('#review-stop');self.page.wait_for_function("document.querySelector('#review-stop').textContent==='重试停止并保存'")
        self.assertFalse(self.page.is_disabled('#review-stop'));self.assertTrue(self.page.is_disabled('#review-start'))
        self.assertTrue(self.page.is_hidden('#review-copy'))
        self.assertIn('尚未确认',self.page.text_content('#review-message'))
    def test_sidebar_spacing_and_narrow_width(self):
        self.sidebar()
        for width in (320,380,480):
            self.page.set_viewport_size({'width':width,'height':900})
            sizes=self.page.evaluate('''()=>{
              const rect=id=>document.getElementById(id).getBoundingClientRect(),label=document.querySelector('.review-limit-field span').getBoundingClientRect();
              return {overflow:document.documentElement.scrollWidth>innerWidth,gap:Math.max(rect('review-limit').top-label.bottom,rect('review-limit').left-label.right),
                button:rect('review-start').height,select:rect('review-limit').height};}''')
            self.assertFalse(sizes['overflow'],sizes);self.assertGreaterEqual(sizes['gap'],8)
            self.assertGreaterEqual(sizes['button'],44);self.assertGreaterEqual(sizes['select'],40)

    def test_shared_help_is_last_collapsed_and_contacts_fit_both_workspaces(self):
        self.sidebar()
        self.page.add_script_tag(content=(EXT/'help-panel.js').read_text(encoding='utf-8'))
        self.assertFalse(self.page.evaluate("document.querySelector('#help-contact').open"))
        self.assertEqual(self.page.locator('#single-product-card .product-help, #catalog-card .product-help').count(),0)
        self.assertEqual(self.page.locator('#help-contact #review-budget-note').count(),1)
        self.assertEqual(self.page.evaluate("document.querySelector('main').lastElementChild.previousElementSibling.id"),'help-contact')
        self.page.locator('#help-contact > summary').click()
        self.page.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value=>{window.copiedContact=value}}})")
        for mode in (True,False):
            self.page.evaluate("v=>document.body.classList.toggle('product-mode',v)",mode)
            self.assertTrue(self.page.is_visible('#help-contact'))
            for width in (320,380,480):
                self.page.set_viewport_size({'width':width,'height':900})
                self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth>innerWidth'))
                self.assertGreaterEqual(self.page.locator('#copy-support-email').bounding_box()['height'],40)
        self.page.click('#copy-official-account')
        self.assertEqual(self.page.evaluate('copiedContact'),'布兰德老白BrandBai')
        self.page.click('#copy-support-email')
        self.assertEqual(self.page.evaluate('copiedContact'),'brandlaobai@163.com')
        self.assertEqual(self.page.text_content('#contact-status'),'邮箱已复制')
        self.page.evaluate("document.body.classList.add('product-mode')")
        self.page.set_viewport_size({'width':380,'height':900})
        if os.getenv('BRANDBAI_HELP_PREVIEW'):
            self.page.locator('#help-contact').screenshot(path=os.environ['BRANDBAI_HELP_PREVIEW'])

    def test_sidebar_status_warning_clears_when_progress_recovers_without_restart(self):
        self.sidebar();self.page.click('#review-start')
        self.page.wait_for_function("document.querySelector('#review-count').textContent.includes('已读取 3 /')")
        original=self.page.evaluate('backendJob.id')
        self.page.evaluate("()=>{window.realStatusApi=window.api;window.api=async()=>{throw Error('synthetic reconnect')}}")
        self.page.wait_for_function("document.querySelector('#review-result-title').textContent==='正在恢复进度连接'")
        self.assertTrue(self.page.is_hidden('#review-message'))
        self.assertFalse(self.page.locator('#review-message').evaluate("el=>el.classList.contains('error')"))
        self.assertIn('上次确认 3 /',self.page.text_content('#review-count'))
        self.assertIn('暂时无法确认是否仍在读取',self.page.text_content('#review-result-note'))
        self.assertTrue(self.page.is_hidden('#review-progress'))
        self.assertFalse(self.page.is_disabled('#review-stop'))
        self.page.evaluate('()=>{backendJob.reviewCount=140;window.api=realStatusApi}')
        self.page.wait_for_function("document.querySelector('#review-count').textContent.includes('已读取 140 /')")
        self.assertEqual(self.page.text_content('#review-message'),'')
        self.assertEqual(self.page.text_content('#review-result-title'),'正在读取并保存')
        self.assertEqual(self.page.evaluate('backendJob.id'),original)
        self.assertEqual(self.page.evaluate('recordingStarts'),0)

    def test_reopened_sidebar_restores_task_before_connection_without_duplicate_start(self):
        self.sidebar(restore=True)
        self.page.wait_for_function("document.querySelector('#review-result-title').textContent==='正在恢复进度连接'")
        self.assertIn('上次确认 100 /',self.page.text_content('#review-count'))
        self.assertTrue(self.page.is_hidden('#review-start'))
        self.page.evaluate('()=>{backendJob.reviewCount=160;statusConnected=true}')
        self.page.wait_for_function("document.querySelector('#review-count').textContent.includes('已读取 160 /')")
        self.assertEqual(self.page.text_content('#review-message'),'')
        self.page.evaluate("backendJob={...backendJob,state:'saved',reviewCount:200,doneReason:'target_reached',delivery:{id:'synthetic'}}")
        self.page.wait_for_function("document.querySelector('#review-result-title').textContent==='已读满目标条数'")
        self.assertEqual(self.page.evaluate('backendJob.id'),'synthetic-restored')
        self.assertEqual(self.page.evaluate('recordingStarts'),0)

    def test_sidebar_time_limit_and_continue_have_one_live_counter(self):
        self.sidebar()
        self.page.evaluate('''()=>{const send=chrome.tabs.sendMessage;window.continuedFrom=null;
          chrome.tabs.sendMessage=async(id,m)=>{
            if(m.type==='brandbai-review-preview')return {...await send(id,m),resumable_job_id:backendJob?.can_continue?backendJob.id:null};
            if(m.type==='brandbai-review-start'&&m.resume_from){continuedFrom=m.resume_from;backendJob={...backendJob,id:m.request_id,runId:m.request_id,state:'collecting',doneReason:'in_progress',reviewCount:61,baseline_count:60,resume_from:m.resume_from,can_continue:false,time_limit_seconds:600};return {job:backendJob};}
            return send(id,m);
          };}''')
        self.page.click('#review-start');self.page.wait_for_function('backendJob?.state==="collecting"')
        original=self.page.evaluate('backendJob.id')
        self.page.evaluate("backendJob={...backendJob,state:'saved',reviewCount:60,doneReason:'time_limit',completeness:'partial_time_limit',can_continue:true,delivery:{id:'synthetic'},time_limit_seconds:600,elapsed_seconds:600}")
        self.page.wait_for_function("!document.querySelector('#review-continue').disabled")
        self.assertIn('已保存部分评价',self.page.text_content('#review-result-title'))
        self.assertIn('本轮时间上限',self.page.text_content('#review-result-note'))
        self.assertTrue(self.page.is_hidden('#review-preview'))
        self.page.click('#review-continue')
        self.page.wait_for_function("document.querySelector('#review-count').textContent.includes('已读取 61 /')")
        self.assertEqual(self.page.evaluate('continuedFrom'),original)
        self.assertTrue(self.page.is_hidden('#review-preview'));self.assertTrue(self.page.is_hidden('#review-start'))
        self.assertIn('原有 60 条及本轮新增 1 条',self.page.text_content('#review-result-note'))
        if os.getenv('BRANDBAI_UI_PREVIEW'):
            self.page.locator('#review-card').screenshot(path=os.environ['BRANDBAI_UI_PREVIEW'])
