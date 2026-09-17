"""Opt-in headless synthetic DOM test. No user profile or live network."""
import json
import os
import re
import unittest
from pathlib import Path

EXT = Path(__file__).resolve().parent.parent / "assets/chrome-extension"
HTML = '''<!doctype html><meta charset="utf-8"><style>
body{font:16px Arial}#card{width:230px;height:220px} img{width:140px;height:110px}
#panel{position:absolute;top:10px;left:260px;width:510px;height:720px;background:white}
h1{font-size:20px}.tabs{display:flex;gap:30px}</style>
<div id="card"><h2 data-role="product-title">合成商品完整测试标题</h2><span>¥39</span><p>7天无理由退货</p>
<img src="https://p3.ecombdimg.com/synthetic.webp?signature=DO_NOT_EXPORT"></div>
<div id="panel" hidden><div><h1 data-role="product-title">合成商品完整测试标题</h1>
<p>合成旗舰店</p><span>¥49</span></div><div class="tabs"><span>商品详情</span><span>商品评价(9)</span></div>
<img src="https://p3.ecombdimg.com/synthetic-detail.webp">
<div><span>容量</span><button aria-checked="true">50g</button><button>100g</button></div>
<div><span>产品参数</span><span>品名</span><span>合成样品</span></div>
<div>收货地址：私有内容不得保存</div></div>'''
SETUP = '''() => {
 window.records=[]; window.clock=1000; window.room='https://live.douyin.com/123456';
 const visible=n=>!n.closest('[hidden]')&&n.getBoundingClientRect().width>0;
 window.inspect=BrandbaiDouyinCommerceDom.createInspector({document,window,isVisible:visible,isRendered:visible});
 let id=0; window.collector=BrandbaiLiveProducts.createCollector({document,isVisible:visible,inspector:inspect,
 roomUrl:()=>window.room,emit:(event_type,payload)=>records.push({event_type,payload,at:clock}),now:()=>clock,newId:()=>`card-test-${++id}`,
 catalogEnabled:()=>window.catalogEnabled===true});
 window.scan=()=>collector.scan({element:document.querySelector('#card'),product_title:'合成商品完整测试标题',display_price:window.price||'¥39'});
 document.addEventListener('click',e=>collector.clicked(e),true);
 document.querySelector('#card').addEventListener('click',()=>document.querySelector('#panel').hidden=false);
}'''
CATALOG = '''() => {
 window.catalogEnabled=true;
 document.querySelector('#card').hidden=true;
 const entry=document.createElement('button');entry.id='entry';entry.dataset.e2e='yellowCart-container';entry.textContent='全部商品';document.body.append(entry);
 const list=document.createElement('div');list.id='catalog';list.hidden=true;
 list.style.cssText='position:absolute;left:270px;top:20px;width:490px;height:340px;overflow:auto;background:white';
 list.innerHTML=[1,2,3].map(i=>`<article class="item" style="width:470px;height:160px"><img style="float:left" src="https://p3.ecombdimg.com/list-${i}.webp"><span>${i}</span><h3 data-role="product-title">合成列表第${i}号完整商品标题</h3>${i===1?'<span>讲解中</span>':''}<span>券后价¥29起</span><p>券 满50减20</p><button>去抢购</button></article>`).join('');
 document.body.append(list);
 entry.onclick=()=>{list.hidden=!list.hidden};
 list.querySelectorAll('.item').forEach(item=>item.onclick=()=>{
   document.querySelector('#panel h1').textContent=item.querySelector('h3').textContent;document.querySelector('#panel').hidden=false;
 });
 window.scan=()=>collector.scan(null);
}'''
# A promoted first row has a nested price box containing a shop badge. That
# box is not a product row even though it has an image, coupon and buy button.
PROMOTED_ROW = '''() => {
 const row=document.querySelector('#catalog .item');row.style.height='220px';
 row.innerHTML=`<img class="thumbnail" style="float:left;width:140px;height:140px" src="https://p3.ecombdimg.com/list-1.webp">
 <span>1</span><h3 data-role="product-title" style="margin-left:145px">合成列表第1号完整商品标题</h3>
 <div class="price-box" style="margin-left:145px;width:310px;height:120px">
 <img class="badge" style="float:left;width:102px;height:28px" src="https://p3.ecombdimg.com/img/eden-cn/synthetic/product_opt/4x/aweme_flagship.png">
 <div style="margin-left:110px"><span>满1000减20</span></div><div style="margin-left:110px"><span>¥49起</span></div>
 <p>讲解中</p><button>去抢购</button></div>`;
}'''


@unittest.skipUnless(os.getenv("BRANDBAI_RUN_BROWSER_TESTS") == "1", "Opt-in isolated synthetic Chromium")
class LiveProductChromiumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        args = {"headless": True}
        if os.getenv("BRANDBAI_TEST_CHROMIUM"): args["executable_path"] = os.environ["BRANDBAI_TEST_CHROMIUM"]
        cls.browser = cls.pw.chromium.launch(**args)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1000, "height": 900})
        self.context.route("**/*", lambda route: route.abort())
        self.page = self.context.new_page()
        self.page.set_content(HTML)
        for file in ("douyin-commerce-dom.js", "live-products.js"):
            self.page.add_script_tag(content=(EXT / file).read_text(encoding="utf-8"))
        self.page.evaluate(SETUP)

    def tearDown(self): self.context.close()

    def test_card_price_change_hide_and_restore_are_separate(self):
        self.page.evaluate("scan();scan();price='¥29';scan();collector.scan(null);collector.scan(null);scan()")
        rows = self.page.evaluate("records")
        self.assertEqual([r["payload"]["change_kind"] for r in rows], ["baseline_visible", "visible_info_changed", "temporarily_not_visible", "restored_visible"])
        self.assertNotIn("signature=", str(rows))
        self.assertEqual(rows[0]["payload"]["offer_texts"], ["7天无理由退货"])

    def test_standalone_accepts_preopened_panel_without_live_collection_or_private_fields(self):
        self.page.evaluate("document.querySelector('#panel').hidden=false")
        data=self.page.evaluate('collector.previewCurrent()')
        self.assertEqual(data['status'],'recognized')
        self.assertEqual(data['snapshot']['source'],'user_selected_current_product_panel')
        self.assertEqual(data['snapshot']['price_texts'],['¥49'])
        self.assertNotIn('card_observation_id', data['snapshot'])
        self.assertNotIn('私有内容',str(data))
        self.assertEqual(self.page.evaluate('records'),[])

    def test_standalone_panel_replacement_changes_identity_and_duplicate_is_rejected(self):
        self.page.evaluate("document.querySelector('#panel').hidden=false")
        first=self.page.evaluate('collector.previewCurrent()')
        self.page.evaluate("document.querySelector('#panel').replaceWith(document.querySelector('#panel').cloneNode(true))")
        second=self.page.evaluate('collector.previewCurrent()')
        self.assertNotEqual(first['panel_key'],second['panel_key'])
        self.page.evaluate("const clone=document.querySelector('#panel').cloneNode(true);clone.id='second-panel';clone.style.left='0';document.body.append(clone)")
        self.assertNotEqual(self.page.evaluate('collector.previewCurrent().status'),'recognized')

    def test_review_count_formats_recognize_the_same_public_detail_panel(self):
        self.page.evaluate("document.querySelector('#panel').hidden=false")
        for label in ('商品评价', '商品评价(9)', '商品评价（22.9万）', '商品评价(22.9万)',
                      '商品评价 (1,234+)', '商品评价（1.2亿）', '商品评价 999+'):
            with self.subTest(label=label):
                self.page.locator('#panel .tabs span').nth(1).evaluate('(n,v)=>n.textContent=v',label)
                self.assertEqual(self.page.evaluate('collector.previewCurrent().status'),'recognized')
                self.assertEqual(self.page.evaluate('inspect.diagnose().reviewTabCount'),1)

    def test_review_label_does_not_accept_chatter_or_malformed_count(self):
        self.page.evaluate("document.querySelector('#panel').hidden=false")
        for label in ('商品评价很好', '商品评价(9) 快来购买', '商品评价(9', '商品评价(22..9万)', '用户说商品评价(9)'):
            with self.subTest(label=label):
                self.page.locator('#panel .tabs span').nth(1).evaluate('(n,v)=>n.textContent=v',label)
                self.assertNotEqual(self.page.evaluate('collector.previewCurrent().status'),'recognized')

    def test_promoted_catalog_uses_whole_row_not_badge_and_coupon_box(self):
        self.page.evaluate(CATALOG);self.page.evaluate(PROMOTED_ROW)
        self.page.locator('#entry').click();self.page.evaluate('scan();scan()')
        first=self.page.evaluate('collector.catalogSurface().rows[0].data')
        self.assertEqual(first['list_position'],1)
        self.assertEqual(first['product_title'],'合成列表第1号完整商品标题')
        self.assertEqual(first['thumbnail'],'https://p3.ecombdimg.com/list-1.webp')
        self.assertEqual(first['display_price'],'¥49起')
        self.assertTrue(first['explaining'])
        event=self.page.evaluate("records.find(r=>r.event_type==='product_list_item').payload")
        self.assertEqual(event['product_title'],first['product_title'])
        self.assertEqual(event['images'],[{'url':first['thumbnail'],'kind':'list_image'}])

    def test_catalog_badge_only_row_is_unreadable_not_a_product(self):
        self.page.evaluate(CATALOG);self.page.evaluate(PROMOTED_ROW)
        self.page.evaluate("document.querySelector('.thumbnail').remove();document.querySelector('#catalog').style.height='640px';document.querySelector('#catalog').hidden=false")
        result=self.page.evaluate('(()=>{const s=collector.catalogSurface();return {unreadable:s.unreadable_count,rows:s.rows.map(r=>r.data)}})()')
        self.assertGreater(result['unreadable'],0)
        self.assertFalse(any(row['list_position']==1 for row in result['rows']))
        self.assertNotIn('满1000',str(result['rows']))

    def test_catalog_tiny_generic_image_and_promotion_cannot_be_a_row(self):
        self.page.evaluate(CATALOG);self.page.evaluate(PROMOTED_ROW)
        self.page.evaluate("document.querySelector('.thumbnail').remove();document.querySelector('.badge').src='https://p3.ecombdimg.com/synthetic-small.png';document.querySelector('#catalog').style.height='640px';document.querySelector('#catalog').hidden=false")
        result=self.page.evaluate('(()=>{const s=collector.catalogSurface();return {unreadable:s.unreadable_count,rows:s.rows.map(r=>r.data)}})()')
        self.assertGreater(result['unreadable'],0)
        self.assertNotIn('满1000',str(result['rows']))

    def test_download_reference_price_labels_and_short_parameter_pairs(self):
        self.page.evaluate('''() => {
          document.querySelector('#panel').hidden=false;
          document.querySelector('#panel>div>span').innerHTML='<span>原价</span><i>¥</i><b>99</b><span>券后</span><i>¥</i><b>49</b><em>起</em>';
          const heading=[...document.querySelectorAll('#panel span')].find(n=>n.textContent==='产品参数');
          heading.parentElement.innerHTML='<h3>产品参数</h3><div><span>品牌</span><div><span>合成</span></div></div><div><span>是否进口</span><div><span>否</span></div></div>';
        }''')
        value=self.page.evaluate('collector.previewCurrent().snapshot')
        self.assertIn('原价¥99',value['price_texts'])
        self.assertIn('券后¥49起',value['price_texts'])
        self.assertEqual(value['parameter_texts'],['产品参数','品牌','合成','是否进口','否'])

    def setup_product_workspace(self, *, recording=False):
        self.page.set_content((EXT/'popup.html').read_text(encoding='utf-8'))
        self.page.add_style_tag(content=(EXT/'design-tokens.css').read_text(encoding='utf-8'))
        self.page.add_style_tag(content=(EXT/'sidepanel.css').read_text(encoding='utf-8'))
        popup=(EXT/'popup.js').read_text(encoding='utf-8')
        self.page.add_script_tag(content=re.search(r'function canonicalRoomUrl\([\s\S]*?\n}',popup).group(0))
        self.page.add_script_tag(content=r'''
          const memory={};window.calls=[];window.tab={id:12,url:'https://live.douyin.com/123456',active:true};
          crypto.randomUUID=()=> '11111111-1111-4111-8111-111111111111';
          window.sample={status:'recognized',room_url:tab.url,panel_key:'document-1:1',observed_at_epoch_ms:Date.now(),snapshot:{product_title:'合成商品完整测试标题',shop_name:'合成旗舰店',price_texts:['¥49'],images:[],sku_groups:[],parameter_texts:[],offer_texts:[],source:'user_selected_current_product_panel',identity_status:'unconfirmed',product_url:null,completeness:'visible_snapshot_only'}};
          sample.snapshot.product_identity={platform:'douyin',product_id:'123456789012345',product_ref:'douyin:product:123456789012345',identity_status:'verified'};
          window.chrome={tabs:{query:async()=>[structuredClone(tab)],sendMessage:async(id,msg)=>{
            if(msg.type==='brandbai-material-start') { window.capture={request_id:msg.request_id,room_url:msg.roomUrl,phase:window.capturePhase,state:window.holdMaterials?'collecting':'ready',result:msg.kind==='catalog'?{catalog:{rows:[{list_position:1,product_title:'合成目录商品标题',display_price:'券后¥29起',thumbnail:null,product_url:null,explaining:null,observed_at_epoch_ms:Date.now()}],complete:true,stop_reason:null},observed_at_epoch_ms:Date.now()}:{snapshot:structuredClone(sample.snapshot),observed_at_epoch_ms:Date.now()}};return capture; }
            if(msg.type==='brandbai-material-status')return window.capture;
            if(msg.type==='brandbai-material-ack')return {ok:true};
            const value=structuredClone({...sample,observed_at_epoch_ms:Date.now()});
            if(window.holdPreview)await new Promise(resolve=>window.releasePreview=resolve);
            return value;
          },onActivated:{addListener(fn){window.activated=fn}},onUpdated:{addListener(){}}},storage:{session:{get:async k=>Object.fromEntries((Array.isArray(k)?k:[k]).map(key=>[key,memory[key]])),set:async v=>Object.assign(memory,v)}}};
          window.setInterval=fn=>{window.productTick=fn;return 1};
          const ensureCurrentTabContentScript=async()=>window.stallAccess?new Promise(()=>{}):!window.noAccess;
          let sessionToken='synthetic-token';let storageSettings={configured:true,mode:'browser-zip'};
          window.recording=false;const activeTask=()=>recording?{state:'recording'}:null;
          const connectService=async()=>!window.offline, refreshStorageSettings=async()=>{};
          const getConnectionIssue=()=>window.connectionIssue||'';
          const readCurrentTab=async()=>{},beginAssistantLaunch=async()=>new Promise(resolve=>window.resolveLaunch=resolve),revealStorageSettings=()=>{window.storageShown=true};
          const cancelAssistantLaunch=async()=>resolveLaunch(false);
          const api=async(path,opts={})=>{
            calls.push({path,...opts});if(path==='/v1/health')return window.testHealth||{independent_product_downloads:true,full_product_materials:true,independent_product_catalogs:true,all_visible_product_skus:true,shared_product_identity:true,catalog_number_verification:true,browser_zip_delivery:true};
            if(window.failStatus)throw new Error('synthetic connection failure');
            return {product_download:window.jobResponse||{state:'complete_observed',image_saved:0,output_dir:'synthetic-output'}};
          };
        ''')
        self.page.evaluate(f'window.recording={str(recording).lower()}')
        self.page.add_script_tag(content=(EXT/'product-identity.js').read_text(encoding='utf-8'))
        self.page.add_script_tag(content=(EXT/'product-panel.js').read_text(encoding='utf-8'))
        self.page.locator('#product-view').click()
        self.page.wait_for_function("!document.querySelector('#download-current-product').disabled")

    def test_direct_search_live_product_preview_and_download_canonicalize_room(self):
        self.setup_product_workspace()
        self.page.evaluate("tab.url='https://www.douyin.com/search/synthetic?live_web_rid=123456&type=live&tracking=DO_NOT_EXPORT'")
        self.page.locator('#refresh-product').click()
        self.page.wait_for_function("document.querySelector('#product-message').textContent.includes('商品已识别')")
        self.page.locator('#download-current-product').click()
        self.page.wait_for_function("calls.some(c=>c.path==='/v1/product-downloads' && c.method==='POST')")
        posted=self.page.evaluate("calls.find(c=>c.path==='/v1/product-downloads' && c.method==='POST').body")
        self.assertEqual(posted['room_url'],'https://live.douyin.com/123456')
        self.assertNotIn('DO_NOT_EXPORT',json.dumps(posted))
        self.assertNotIn('/search/',json.dumps(posted))

    def test_recognition_failures_explain_reason_without_claiming_detail_closed(self):
        self.setup_product_workspace()
        for status,expected in [('incomplete','已检测到商品面板'),('ambiguous','多个商品面板'),('identity_conflict','商品身份信息有冲突')]:
            with self.subTest(status=status):
                self.page.evaluate('(status)=>{sample.status=status}',status)
                self.page.locator('#refresh-product').click()
                self.page.wait_for_function('(label)=>document.querySelector("#product-message").textContent.includes(label)',arg=expected)
                self.assertEqual(self.page.get_attribute('#product-message','role'),'alert')
                self.assertTrue(self.page.locator('#download-current-product').is_disabled())
                self.assertNotIn('尚未打开商品详情',self.page.locator('#product-message').inner_text())
        self.page.evaluate("tab.url='https://www.douyin.com/search/synthetic?type=video'")
        self.page.locator('#refresh-product').click()
        self.page.wait_for_function("document.querySelector('#product-message').textContent.includes('当前标签页未确认')")
        self.assertFalse(self.page.evaluate("calls.some(c=>c.method==='POST')"))

    def test_recognition_page_access_failure_requests_existing_temporary_permission(self):
        self.setup_product_workspace();self.page.evaluate('noAccess=true')
        self.page.locator('#refresh-product').click()
        self.page.wait_for_function("document.querySelector('#product-message').textContent.includes('无法连接当前商品页')")
        self.assertTrue(self.page.locator('#download-current-product').is_disabled())
        self.assertFalse(self.page.evaluate("calls.some(c=>c.method==='POST')"))

    def test_connection_refusal_does_not_launch_or_collect_and_retry_is_available(self):
        self.setup_product_workspace()
        self.page.evaluate("offline=true;connectionIssue='助手已运行，但未允许当前插件连接。请先结束录制和下载，再重启助手。'")
        self.page.locator('#download-product-catalog').click()
        self.page.wait_for_function("document.querySelector('#catalog-feedback #product-message').textContent.includes('助手已运行')")
        self.assertFalse(self.page.evaluate("typeof resolveLaunch==='function'"))
        self.assertFalse(self.page.evaluate('Boolean(window.capture)'))
        self.assertFalse(self.page.locator('#download-product-catalog').is_disabled())
        self.assertFalse(self.page.evaluate("calls.some(c=>c.method==='POST')"))
        self.page.evaluate("offline=false;connectionIssue=''")
        self.page.locator('#download-product-catalog').click()
        self.page.wait_for_function("calls.some(c=>c.path==='/v1/product-downloads' && c.method==='POST')")

    def test_connection_refused_after_launch_shows_cause_not_permission_timeout(self):
        self.setup_product_workspace();self.page.evaluate('offline=true')
        self.page.locator('#download-product-catalog').click()
        self.page.wait_for_function('typeof resolveLaunch === "function"')
        self.page.evaluate("connectionIssue='助手已运行，但未允许当前插件连接。';resolveLaunch(false)")
        self.page.wait_for_function("document.querySelector('#catalog-feedback #product-message').textContent.includes('助手已运行')")
        self.assertNotIn('浏览器确认',self.page.locator('#catalog-feedback #product-message').inner_text())
        self.assertFalse(self.page.locator('#download-product-catalog').is_disabled())
        self.assertFalse(self.page.evaluate('Boolean(window.capture)'))

    def test_standalone_ui_downloads_during_recording_without_recording_post(self):
        self.setup_product_workspace(recording=True)
        self.assertTrue(self.page.locator('#product-recording-status').is_visible())
        self.page.locator('#download-current-product').click()
        self.page.wait_for_function("calls.some(c=>c.method==='POST')")
        posts=self.page.evaluate("calls.filter(c=>c.method==='POST')")
        self.assertEqual(len(posts),1)
        self.assertEqual(posts[0]['path'],'/v1/product-downloads')
        self.assertEqual(set(posts[0]['body']),{'request_id','room_url','observed_at_epoch_ms','snapshot'})
        self.assertTrue(self.page.evaluate('recording'))
        self.page.wait_for_selector('#product-download-result .product-copy')

    def test_catalog_ui_posts_catalog_not_detail_or_recording(self):
        self.setup_product_workspace()
        self.page.locator('#download-product-catalog').click()
        self.page.wait_for_function("calls.some(c=>c.method==='POST')")
        posts=self.page.evaluate("calls.filter(c=>c.method==='POST')")
        self.assertEqual(len(posts),1);self.assertIn('catalog',posts[0]['body']);self.assertNotIn('snapshot',posts[0]['body'])
        self.page.wait_for_function("document.querySelector('#product-download-result h3').textContent==='商品编号目录已保存'")

    def test_number_hint_ui_keeps_all_products_and_posts_no_guessed_position(self):
        self.setup_product_workspace()
        self.page.evaluate('''() => {
          const send=chrome.tabs.sendMessage;
          chrome.tabs.sendMessage=async(id,msg)=>{
            const value=await send(id,msg);
            if(msg.type==='brandbai-material-start' && msg.kind==='catalog'){
              const original=value.result.catalog.rows[0];
              value.result.catalog.rows=Array.from({length:16},(_,i)=>({...original,list_position:i?i+1:null,explaining:i?null:true,product_title:`合成商品标题${i+1}`}));
              value.result.number_hints={0:{candidate:1,status:'inferred_unverified'}};
            }return value;
          };
          jobResponse={state:'partial',image_saved:16,item_count:16,output_dir:'synthetic-output',
            number_coverage:{observed:15,missing:1,inferred:1,reverified:0,complete:false}};
        }''')
        self.page.locator('#download-product-catalog').click()
        self.page.wait_for_function("document.querySelector('#product-download-result h3').textContent.includes('部分编号待核验')")
        self.assertEqual(self.page.locator('#catalog-rows .catalog-row').count(),16)
        self.assertIn('推测 1 号 · 待核验',self.page.locator('#catalog-rows').inner_text())
        self.assertIn('15 件编号已确认，1 件待核验',self.page.locator('#catalog-overview-title').inner_text())
        posted=self.page.evaluate("calls.find(c=>c.method==='POST').body.catalog.rows[0]")
        self.assertIsNone(posted['list_position']);self.assertNotIn('number_inference',posted)

    def test_catalog_number_capability_missing_blocks_before_collection(self):
        self.setup_product_workspace()
        self.page.evaluate('testHealth={independent_product_downloads:true,full_product_materials:true,independent_product_catalogs:true,all_visible_product_skus:true,shared_product_identity:true,browser_zip_delivery:true}')
        self.page.locator('#download-product-catalog').click()
        self.page.wait_for_function("document.querySelector('#product-message').textContent.includes('商品编号核验需要新版助手')")
        self.assertIsNone(self.page.evaluate('window.capture'))
        self.assertFalse(self.page.evaluate("calls.some(c=>c.method==='POST')"))

    def test_full_collection_rejects_old_helper_without_page_actions(self):
        self.setup_product_workspace()
        self.page.evaluate('testHealth={independent_product_downloads:true}')
        self.page.locator('#download-current-product').click()
        self.page.wait_for_function("document.querySelector('#product-message').textContent.includes('更新本机助手')")
        self.assertFalse(self.page.evaluate("calls.some(c=>c.method==='POST')"))
        self.assertIsNone(self.page.evaluate('window.capture'))

    def test_shared_card_stays_locked_while_reviews_run_and_view_changes(self):
        self.setup_product_workspace()
        self.assertEqual(self.page.locator('#single-product-card #review-card').count(),1)
        self.assertEqual(self.page.get_by_role('button',name='重新识别',exact=True).count(),1)
        self.page.evaluate("window.BrandbaiReviewsBusy=()=>true;sample.snapshot.product_title='另一件商品不能覆盖';productTick()")
        self.page.click('#recording-view');self.page.click('#product-view')
        self.assertIn('合成商品完整测试标题',self.page.text_content('#product-preview'))
        self.assertTrue(self.page.is_disabled('#refresh-product'));self.assertTrue(self.page.is_disabled('#download-current-product'))
        if os.getenv('BRANDBAI_IDENTITY_UI_PREVIEW'):
            self.page.set_viewport_size({'width':480,'height':1150})
            self.page.locator('#single-product-card').screenshot(path=os.environ['BRANDBAI_IDENTITY_UI_PREVIEW'])

    def test_search_entry_live_room_uses_canonical_id_for_catalog(self):
        self.setup_product_workspace()
        self.page.evaluate("tab.url='https://www.douyin.com/jingxuan/search/synthetic?live_web_rid=123456&type=live';sample.status='not_found';activated()")
        self.page.locator('#download-product-catalog').click()
        self.page.wait_for_function("calls.some(c=>c.method==='POST')")
        body=self.page.evaluate("calls.find(c=>c.method==='POST').body")
        self.assertEqual(body['room_url'],'https://live.douyin.com/123456')
        self.assertIn('catalog',body)
        self.assertNotIn('jingxuan',str(body))
        self.assertNotIn('live_web_rid',str(body))

    def test_catalog_page_access_failure_has_strong_retryable_prompt_before_helper(self):
        self.setup_product_workspace();self.page.evaluate('noAccess=true;offline=true')
        self.page.locator('#download-product-catalog').click()
        error=self.page.locator('#catalog-feedback .product-message.error')
        self.page.wait_for_function("document.querySelector('#product-message').textContent.includes('工具栏')")
        self.assertEqual(error.get_attribute('role'),'alert')
        self.assertEqual(error.evaluate("n=>getComputedStyle(n).borderLeftWidth"),'3px')
        self.assertTrue(self.page.locator('#download-product-catalog').is_enabled())
        self.assertFalse(self.page.evaluate("typeof resolveLaunch==='function'"))
        self.assertEqual(self.page.evaluate('calls'),[])
        self.page.evaluate('noAccess=false;offline=false')
        self.page.locator('#download-product-catalog').click()
        self.page.wait_for_function("calls.some(c=>c.method==='POST')")

    def test_catalog_unresponsive_page_access_releases_button(self):
        self.setup_product_workspace();self.page.evaluate('stallAccess=true')
        self.page.locator('#download-product-catalog').click()
        self.page.wait_for_function("document.querySelector('#product-message').textContent.includes('暂时无法读取')",timeout=12000)
        self.assertTrue(self.page.locator('#download-product-catalog').is_enabled())
        self.assertEqual(self.page.evaluate('calls'),[])

    def test_catalog_opening_and_failed_open_have_distinct_feedback(self):
        self.setup_product_workspace();self.page.evaluate("holdMaterials=true;capturePhase='opening_catalog'")
        self.page.locator('#download-product-catalog').click()
        self.page.wait_for_function("document.querySelector('#product-download-result h3').textContent==='正在展开全部商品'")
        self.assertIn('正在等待列表显示',self.page.locator('#product-download-result').inner_text())
        self.page.evaluate("capture.state='failed';capture.reason='catalog_open_failed';productTick()")
        self.page.wait_for_function("document.querySelector('#product-message').textContent.includes('请手动展开列表')")
        self.assertTrue(self.page.locator('#catalog-feedback .product-message.error').is_visible())
        self.assertTrue(self.page.locator('#download-product-catalog').is_enabled())
        self.assertFalse(self.page.evaluate("calls.some(c=>c.method==='POST')"))

    def test_catalog_is_primary_above_detail_and_available_without_detail(self):
        self.setup_product_workspace()
        self.page.set_viewport_size({'width':340,'height':820})
        self.page.evaluate("sample.status='not_found';activated()")
        self.assertTrue(self.page.locator('#download-product-catalog').is_enabled())
        self.assertLess(self.page.locator('#download-product-catalog').bounding_box()['y'],
                        self.page.locator('#download-current-product').bounding_box()['y'])
        self.page.locator('#download-product-catalog').click()
        self.page.wait_for_selector('#catalog-overview:not([hidden])')
        self.assertIn('1 号链接',self.page.locator('#catalog-rows').inner_text())
        self.assertIn('券后¥29起',self.page.locator('#catalog-rows').inner_text())
        self.assertEqual(self.page.locator('#catalog-explaining').count(),0)
        self.assertTrue(self.page.locator('#catalog-feedback #product-download-result').is_visible())
        self.assertNotIn('本次',self.page.locator('#catalog-observed-note').inner_text())
        self.page.evaluate("tab.url='https://live.douyin.com/999999';activated()")
        self.page.wait_for_function("document.querySelector('#catalog-observed-note').textContent.includes('不是当前直播间')")

    def test_catalog_startup_progress_does_not_mislabel_single_product(self):
        self.setup_product_workspace();self.page.evaluate('offline=true')
        self.page.locator('#download-product-catalog').click()
        self.page.wait_for_function('typeof resolveLaunch === "function"')
        self.assertIn('正在准备商品目录',self.page.locator('#download-product-catalog').inner_text())
        self.assertEqual(self.page.locator('#download-current-product').inner_text(),'下载图片与规格')
        self.assertEqual(self.page.locator('#download-current-product').get_attribute('aria-busy'),'false')
        self.page.get_by_role('button',name='取消本次启动',exact=True).click()
        self.page.wait_for_function("document.querySelector('#product-message').textContent.includes('已取消')")
        self.assertTrue(self.page.locator('#download-product-catalog').is_enabled())
        self.assertFalse(self.page.evaluate("calls.some(c=>c.method==='POST')"))

    def test_catalog_timeout_is_retryable_and_room_change_during_launch_is_rejected(self):
        self.setup_product_workspace();self.page.evaluate('offline=true')
        self.page.locator('#download-product-catalog').click()
        self.page.wait_for_function('typeof resolveLaunch === "function"')
        self.page.evaluate('resolveLaunch(false)')
        self.page.wait_for_function("document.querySelector('#product-message').textContent.includes('等待已结束')")
        self.assertTrue(self.page.locator('#download-product-catalog').is_enabled())
        self.page.evaluate('resolveLaunch=null')
        self.page.locator('#download-product-catalog').click()
        self.page.wait_for_function('typeof resolveLaunch === "function"')
        self.page.evaluate("tab.url='https://live.douyin.com/999999';resolveLaunch(true)")
        self.page.wait_for_function("document.querySelector('#product-message').textContent.includes('直播间或标签页已变化')")
        self.assertFalse(self.page.evaluate("calls.some(c=>c.method==='POST')"))

    def test_catalog_snapshot_remains_when_downloading_focus_product(self):
        self.setup_product_workspace()
        self.page.locator('#download-product-catalog').click()
        self.page.wait_for_function("document.querySelector('#product-download-result h3').textContent==='商品编号目录已保存'")
        self.page.locator('#download-current-product').click()
        self.page.wait_for_function("calls.filter(c=>c.method==='POST').length===2")
        self.assertTrue(self.page.locator('#catalog-recent-result').is_visible())
        self.assertIn('历史下载 · 目录已保存',self.page.locator('#catalog-recent-result').inner_text())
        self.assertIn('1 号链接',self.page.locator('#catalog-rows').inner_text())
        self.assertTrue(self.page.locator('#product-feedback #product-download-result').is_visible())

    def test_collecting_disables_actions_until_page_capture_finishes(self):
        self.setup_product_workspace();self.page.evaluate('holdMaterials=true')
        self.page.locator('#download-current-product').click()
        self.page.wait_for_function("document.querySelector('#product-download-result h3').textContent==='正在补齐主图'")
        self.assertTrue(self.page.locator('#download-current-product').is_disabled())
        self.assertTrue(self.page.locator('#download-product-catalog').is_disabled())
        self.assertFalse(self.page.evaluate("calls.some(c=>c.method==='POST')"))
        self.page.evaluate("capture.state='ready';productTick()")
        self.page.wait_for_function("calls.some(c=>c.method==='POST')")

    def test_standalone_ui_revalidates_product_and_clears_switched_tab(self):
        self.setup_product_workspace()
        self.page.evaluate("sample.snapshot.product_title='已经换成另外一个合成商品'")
        self.page.locator('#download-current-product').click()
        self.page.wait_for_function("document.querySelector('#product-message').textContent.includes('已变化')")
        self.assertFalse(self.page.evaluate("calls.some(c=>c.method==='POST')"))
        self.page.evaluate("tab={id:19,url:'https://example.test',active:true};activated()")
        self.assertTrue(self.page.locator('#download-current-product').is_disabled())

    def test_finished_product_result_moves_to_history_on_identity_change(self):
        self.setup_product_workspace()
        self.page.locator('#download-current-product').click()
        self.page.wait_for_function("!document.querySelector('#product-download-result').hidden && document.querySelector('#product-download-result h3').textContent.includes('已保存')")
        # Even an identical title with a different ID is a different product.
        self.page.evaluate("sample.snapshot.product_identity={...sample.snapshot.product_identity,product_id:'999999999999999',product_ref:'douyin:product:999999999999999'};productTick()")
        self.page.wait_for_function("document.querySelector('#product-download-result').hidden && !document.querySelector('#product-recent-result').hidden")
        self.assertEqual(self.page.locator('#single-product-card #product-recent-result').count(),0)
        self.page.locator('#product-history summary').click()
        self.assertIn('其他商品资料',self.page.locator('#product-recent-result').inner_text())
        self.assertTrue(self.page.locator('#download-current-product').is_enabled())
        self.page.evaluate("sample.status='incomplete'")
        self.page.locator('#refresh-product').click()
        self.page.wait_for_function("document.querySelector('#product-message').textContent.includes('尚未确认')")
        self.page.evaluate('productTick()')
        self.assertIn('尚未确认',self.page.text_content('#product-message'))

    def test_unknown_gallery_total_is_not_reported_as_proven_missing_image(self):
        self.setup_product_workspace()
        self.page.evaluate("jobResponse={state:'partial',image_total:4,image_saved:4,output_dir:'synthetic',image_coverage:{main_observed:1,main_expected:null,detail_observed:3,main_complete:false,detail_complete:true,stop_reason:'coverage_unconfirmed'}}")
        self.page.locator('#download-current-product').click()
        self.page.wait_for_function("document.querySelector('#product-download-result h3').textContent.includes('完整性待核验')")
        self.assertNotIn('资料待补齐',self.page.text_content('#product-download-result h3'))

    def test_standalone_narrow_sidebar_has_no_horizontal_overflow(self):
        self.setup_product_workspace()
        self.page.set_viewport_size({'width':340,'height':820})
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),340)
        if os.getenv('BRANDBAI_PRODUCT_PREVIEW_PNG'):
            self.page.screenshot(path=os.environ['BRANDBAI_PRODUCT_PREVIEW_PNG'],full_page=True)

    def test_silent_preview_does_not_dim_button_or_block_click(self):
        self.setup_product_workspace()
        self.page.evaluate('holdPreview=true;productTick()')
        self.page.wait_for_function('typeof releasePreview === "function"')
        self.assertTrue(self.page.locator('#download-current-product').is_enabled())
        self.page.evaluate('holdPreview=false')
        self.page.locator('#download-current-product').click()
        # The button accepts the click, but a pending read must finish before
        # another identity check starts. Never queue competing DOM scans.
        self.assertFalse(self.page.evaluate("calls.some(c=>c.method==='POST')"))
        self.page.evaluate('releasePreview()')
        self.page.wait_for_function("calls.some(c=>c.method==='POST')")
        self.page.wait_for_selector('#product-download-result .product-copy:visible')
        self.assertEqual(self.page.evaluate("calls.filter(c=>c.method==='POST').length"),1)

    def test_one_unstable_scan_is_tolerated_but_download_still_revalidates(self):
        self.setup_product_workspace()
        self.page.evaluate("sample.status='not_found';productTick()")
        self.page.wait_for_timeout(100)
        self.assertTrue(self.page.locator('#download-current-product').is_enabled())
        self.page.locator('#download-current-product').click()
        self.page.wait_for_function("document.querySelector('#product-message').textContent.includes('已变化')")
        self.assertFalse(self.page.evaluate("calls.some(c=>c.method==='POST')"))
        self.assertTrue(self.page.locator('#download-current-product').is_disabled())

    def test_slow_scan_cannot_restore_preview_after_tab_change(self):
        self.setup_product_workspace()
        self.page.evaluate('holdPreview=true;productTick()')
        self.page.wait_for_function('typeof releasePreview === "function"')
        self.page.evaluate("tab={id:19,url:'https://example.test',active:true};activated();holdPreview=false;releasePreview()")
        self.page.wait_for_timeout(400)
        self.assertTrue(self.page.locator('#download-current-product').is_disabled())
        self.assertNotIn('合成商品完整测试标题',self.page.locator('#product-preview').inner_text())

    def start_progress_job(self):
        self.setup_product_workspace()
        self.page.evaluate("sample.snapshot.images=[1,2,3].map(i=>({url:'https://p3.ecombdimg.com/synthetic-'+i+'.webp'}))")
        self.page.locator('#refresh-product').click()
        self.page.wait_for_function("document.querySelector('#product-preview').textContent.includes('3 张')")
        self.page.evaluate("window.jobResponse={state:'running',image_saved:0,image_total:0}")
        self.page.locator('#download-current-product').click()
        self.page.wait_for_function("calls.some(c=>c.method==='POST') && document.querySelector('#download-current-product').textContent.includes('进度见下方')")

    def test_progress_from_first_image_through_packaging_and_completion(self):
        self.start_progress_job()
        self.assertIn('已保存 0 / 3',self.page.locator('.product-progress-counts').inner_text())
        self.assertEqual(self.page.locator('#download-current-product').get_attribute('aria-busy'),'true')
        self.assertEqual(self.page.locator('.product-download-progress').get_attribute('value'),'0')
        self.page.evaluate("window.progressNode=document.querySelector('.product-download-progress');jobResponse={state:'running',image_saved:1,image_total:3};productTick()")
        self.page.wait_for_function("document.querySelector('.product-progress-counts').textContent.includes('1 / 3')")
        self.assertTrue(self.page.evaluate("progressNode===document.querySelector('.product-download-progress')"))
        self.page.set_viewport_size({'width':340,'height':820})
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),340)
        if os.getenv('BRANDBAI_PRODUCT_PROGRESS_PNG'):
            self.page.screenshot(path=os.environ['BRANDBAI_PRODUCT_PROGRESS_PNG'],full_page=True)
        self.page.evaluate("jobResponse={state:'running',image_saved:3,image_total:3};productTick()")
        self.page.wait_for_function("document.querySelector('#product-download-result h3').textContent.includes('压缩包')")
        self.assertTrue(self.page.locator('#download-current-product').is_disabled())
        self.page.evaluate("jobResponse={state:'complete_observed',image_saved:3,image_total:3,output_dir:'synthetic-output'};productTick()")
        self.page.wait_for_function("document.querySelector('#product-download-result h3').textContent.includes('已保存')")
        self.assertTrue(self.page.locator('#product-download-result .product-copy').last.is_visible())
        self.assertEqual(self.page.locator('#product-message').inner_text(),'')

    def test_progress_failure_and_partial_do_not_report_missing_images_as_saved(self):
        self.start_progress_job()
        self.page.evaluate('failStatus=true;productTick()')
        self.page.wait_for_selector('.product-sync-warning:visible')
        self.assertIn('保留最后进度',self.page.locator('.product-sync-warning').inner_text())
        self.assertTrue(self.page.locator('#download-current-product').is_disabled())
        self.page.evaluate("failStatus=false;jobResponse={state:'partial',image_saved:1,image_total:3,image_failed:1,image_skipped:1,output_dir:'synthetic-output'}")
        self.page.get_by_role('button',name='重新查询下载状态').click()
        self.page.wait_for_function("document.querySelector('#product-download-result h3').textContent==='部分资料已保存'")
        self.assertIn('已保存 1 / 3 张图片 · 1 张失败 · 1 张未下载',self.page.locator('.product-progress-counts').inner_text())
        self.assertEqual(self.page.evaluate("calls.filter(c=>c.method==='POST').length"),1)

    def test_images_complete_sku_unknown_is_separate_from_confirmed_single_sku(self):
        self.start_progress_job()
        self.page.evaluate("jobResponse={state:'partial',image_saved:45,image_total:45,image_coverage:{main_complete:true,detail_complete:true,main_observed:5,main_expected:5,detail_observed:40,stop_reason:null},sku_materials:{status:'not_observed',variants:[]},output_dir:'synthetic-output'};productTick()")
        self.page.wait_for_function("document.querySelector('#product-download-result h3').textContent==='图片已保存 · 规格待确认'")
        self.assertIn('规格数量未确认',self.page.text_content('#product-download-result'))
        self.assertNotIn('商品资料未收齐',self.page.text_content('#product-download-result'))
    def test_confirmed_single_sku_has_no_unknown_warning(self):
        # A separately confirmed visible single-option snapshot has no unknown warning.
        self.setup_product_workspace()
        self.page.evaluate("jobResponse={state:'complete_observed',image_saved:45,image_total:45,image_coverage:{main_complete:true,detail_complete:true,main_observed:5,main_expected:5,detail_observed:40},sku_materials:{status:'complete_all_visible_skus',selection_restored:true,variants:[{state:'observed'}]},output_dir:'synthetic-output'}")
        self.page.click('#download-current-product')
        self.page.wait_for_function("document.querySelector('#product-download-result').textContent.includes('已确认 1 个页面可选规格')")
        self.assertNotIn('规格数量未确认',self.page.text_content('#product-download-result'))

    def test_preparation_is_visible_immediately_even_before_server_job_exists(self):
        self.setup_product_workspace()
        self.page.evaluate('holdPreview=true')
        self.page.locator('#download-current-product').click()
        self.page.wait_for_function('typeof releasePreview === "function"')
        self.assertEqual(self.page.locator('#product-download-result h3').inner_text(),'正在准备下载')
        self.assertTrue(self.page.locator('#download-current-product').is_disabled())
        self.assertTrue(self.page.locator('#product-download-result').is_visible())
        self.assertFalse(self.page.evaluate("calls.some(c=>c.method==='POST')"))
        self.page.evaluate('holdPreview=false;releasePreview()')
        self.page.wait_for_function("calls.some(c=>c.method==='POST')")

    def test_uncertain_submission_only_queries_and_requires_confirmation_for_new_download(self):
        self.setup_product_workspace()
        self.page.evaluate('failStatus=true')
        self.page.locator('#download-current-product').click()
        self.page.wait_for_function("document.querySelector('#product-download-result h3').textContent==='下载状态待确认'")
        self.assertTrue(self.page.locator('#download-current-product').is_disabled())
        self.page.get_by_role('button',name='重新查询下载状态').click()
        self.assertEqual(self.page.evaluate("calls.filter(c=>c.method==='POST').length"),1)
        self.page.wait_for_function("!document.querySelector('#product-download-result .product-status-check').disabled")
        self.page.once('dialog',lambda dialog:dialog.dismiss())
        self.page.get_by_role('button',name='检查后重新下载').click()
        self.assertEqual(self.page.evaluate("calls.filter(c=>c.method==='POST').length"),1)
        self.page.evaluate("failStatus=false;jobResponse={state:'complete_observed',image_saved:0,output_dir:'synthetic-output'}")
        self.page.get_by_role('button',name='重新查询下载状态').click()
        self.page.wait_for_function("document.querySelector('#product-download-result h3').textContent==='当前识别资料已保存'")
        self.assertEqual(self.page.evaluate("calls.filter(c=>c.method==='POST').length"),1)

    def test_user_click_captures_fresh_structured_detail_without_changing_card_price(self):
        self.page.evaluate("scan(); clock=1500")
        self.page.locator("#card h2").click()
        self.page.evaluate("clock=2000;scan();clock=3000;scan()")
        rows = self.page.evaluate("records")
        self.assertEqual(len(rows), 2, self.page.evaluate("inspect.diagnose()"))
        detail = rows[-1]["payload"]
        self.assertEqual(rows[-1]["event_type"], "product_detail")
        self.assertEqual(detail["card_observation_id"], rows[0]["payload"]["card_observation_id"])
        self.assertEqual(detail["price_texts"], ["¥49"])
        self.assertEqual(rows[0]["payload"]["display_price"], "¥39")
        self.assertEqual(detail["sku_groups"][0]["options"][0], {"value": "50g", "selected": True})
        self.assertIn("合成样品", detail["parameter_texts"])
        self.assertNotIn("私有内容", str(rows))

    def test_preopened_panel_and_room_switch_never_bind(self):
        self.page.evaluate("document.querySelector('#panel').hidden=false;scan()")
        self.page.locator("#card h2").click()
        self.page.evaluate("scan();scan()")
        self.assertEqual(len(self.page.evaluate("records")), 0)
        self.page.evaluate("collector.reset();records=[];document.querySelector('#panel').hidden=true;scan()")
        self.page.locator("#card h2").click()
        self.page.evaluate("room='https://live.douyin.com/654321';scan();scan()")
        self.assertFalse(any(e["event_type"] == "product_detail" for e in self.page.evaluate("records")))

    def test_mismatched_title_never_binds(self):
        self.page.evaluate("scan()")
        self.page.locator("#card h2").click()
        self.page.evaluate("document.querySelector('#panel h1').textContent='另一个商品的测试标题';scan();scan()")
        self.assertFalse(any(e["event_type"] == "product_detail" for e in self.page.evaluate("records")))

    def test_large_image_snapshot_is_bounded_and_marked_partial(self):
        result = self.page.evaluate('''() => {
          const card = document.querySelector('#card');
          for(let i=0;i<40;i++) {const img=document.createElement('img');img.style='position:absolute;left:0;top:0';img.src='https://p3.ecombdimg.com/'+i+'x'.repeat(1800)+'.webp';card.append(img);}
          const data=collector.snapshot(card,'合成商品完整测试标题','¥39');
          return {size:new TextEncoder().encode(JSON.stringify(data)).length, limited:data.fields_limited};
        }''')
        self.assertLessEqual(result["size"], 40000)
        self.assertTrue(result["limited"])

    def test_content_script_requires_server_capability_before_using_new_schema(self):
        self.page.evaluate('''() => {
          window.chrome={runtime:{onMessage:{addListener(){}},sendMessage(message,cb){cb({active:false,collectorOptions:{enabled:false}})}}};
        }''')
        source=(EXT / "content.js").read_text(encoding="utf-8")
        source=source.rsplit('})();',1)[0]+"globalThis.inspectForTest=code=>eval(code);\n})();"
        self.page.add_script_tag(content=source)
        self.assertTrue(self.page.evaluate("inspectForTest('getProductCollector() === null')"))
        self.assertTrue(self.page.evaluate("inspectForTest('productSnapshotSupport=true; Boolean(getProductCollector())')"))
        self.assertTrue(self.page.evaluate("inspectForTest('productSnapshotSupport=false; getProductCollector() === null')"))

    def test_timeout_never_binds(self):
        self.page.evaluate("collector.reset();records=[];document.querySelector('#panel').hidden=true;scan()")
        self.page.locator("#card h2").click()
        self.page.evaluate("clock=20000;scan();scan()")
        self.assertFalse(any(e["event_type"] == "product_detail" for e in self.page.evaluate("records")))

    def open_catalog(self):
        self.page.evaluate(CATALOG)
        self.page.locator('#entry').click()
        self.page.evaluate('scan();scan()')

    def test_list_is_separate_from_popup_and_clipped_rows_are_not_captured(self):
        self.open_catalog()
        records = self.page.evaluate('records')
        self.assertEqual(len(records), 2, records)
        self.assertEqual({e['event_type'] for e in records}, {'product_list_item'})
        first, second = [r['payload'] for r in records]
        self.assertEqual(first['list_position'], 1)
        self.assertIs(first['explaining'], True)
        self.assertIsNone(second['explaining'])
        self.assertEqual(first['display_price'], '券后价¥29起')
        self.assertIn('券 满50减20', first['offer_texts'])
        self.page.evaluate("document.querySelector('#catalog').scrollTop=320;scan();scan()")
        self.assertEqual(len(self.page.evaluate('records')), 3)

    def test_detail_binds_to_clicked_list_item_not_first_or_popup(self):
        self.open_catalog()
        self.page.locator('#catalog .item').nth(1).locator('h3').click()
        self.page.evaluate('clock=2000;scan();clock=3000;scan()')
        rows = self.page.evaluate('records')
        detail = [e['payload'] for e in rows if e['event_type'] == 'product_detail']
        self.assertEqual(len(detail), 1, rows)
        self.assertEqual(detail[0]['list_observation_id'], rows[1]['payload']['list_observation_id'])
        self.assertNotIn('card_observation_id', detail[0])
        self.assertEqual(detail[0]['association'], 'fresh_panel_after_list_click')

    def test_generic_list_name_precedes_promotion_and_closed_list_is_not_enumerated(self):
        self.page.evaluate(CATALOG)
        self.page.evaluate('''() => {
          document.querySelectorAll('#catalog h3').forEach(n=>{
            const title=document.createElement('div');title.style='margin-left:145px';title.textContent=n.textContent;
            const promotion=document.createElement('p');promotion.textContent='【合成促销】多层材料舒适体验';promotion.style='margin-left:145px';
            n.replaceWith(title);title.after(promotion);
          });
          scan();scan();
        }''')
        self.assertEqual(self.page.evaluate('records'), [])
        self.page.locator('#entry').click()
        self.page.evaluate('scan();scan()')
        rows = self.page.evaluate('records')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['payload']['product_title'], '合成列表第1号完整商品标题')
        self.page.locator('#entry').click()
        self.page.evaluate("document.querySelector('#catalog div').textContent='关闭后不采集的商品标题';scan();scan()")
        self.assertEqual(len(self.page.evaluate('records')), 2)

    def test_visual_highlight_alone_is_not_reported_as_confirmed_selection(self):
        self.page.evaluate("document.querySelector('#panel [aria-checked]').removeAttribute('aria-checked');document.querySelector('#panel button').style='border:1px solid red;color:red';scan()")
        self.page.locator('#card h2').click()
        self.page.evaluate('scan();scan()')
        detail = next(r['payload'] for r in self.page.evaluate('records') if r['event_type'] == 'product_detail')
        self.assertFalse(any(o['selected'] for g in detail['sku_groups'] for o in g['options']))

    def test_list_requires_new_service_and_user_open_not_synthetic_click(self):
        self.page.evaluate(CATALOG)
        self.page.evaluate("document.querySelector('#entry').click();scan();scan()")
        self.assertEqual(self.page.evaluate('records'), [])
        self.page.evaluate("document.querySelector('#catalog').hidden=true;catalogEnabled=false")
        self.page.locator('#entry').click()
        self.page.evaluate('scan();scan()')
        self.assertEqual(self.page.evaluate('records'), [])

    def test_identical_rows_do_not_share_an_observation_id(self):
        self.page.evaluate(CATALOG)
        self.page.evaluate('''() => {
          const items=document.querySelectorAll('#catalog .item');items[1].innerHTML=items[0].innerHTML;
        }''')
        self.page.locator('#entry').click()
        self.page.evaluate('scan();scan()')
        rows=self.page.evaluate('records')
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]['payload']['list_observation_id'], rows[1]['payload']['list_observation_id'])

    def test_recycled_list_row_rejected_until_new_observation_and_reorder_preserved(self):
        self.open_catalog()
        self.page.evaluate("document.querySelector('#catalog h3').textContent='合成列表被替换的商品标题'")
        self.page.locator('#catalog h3').first.click()
        self.page.evaluate('scan();scan()')
        self.assertFalse(any(e['event_type'] == 'product_detail' for e in self.page.evaluate('records')))
        self.page.evaluate("document.querySelector('#panel').hidden=true;scan();scan()")
        self.assertEqual(len(self.page.evaluate('records')), 3)

    def test_list_overlay_is_not_mistaken_for_popup_or_controller_hide(self):
        self.page.evaluate('scan()')
        self.open_catalog()
        self.page.evaluate("collector.scan({element:document.querySelector('#catalog .item'),product_title:'列表不是弹窗',display_price:'¥29'});scan()")
        kinds = [e['event_type'] for e in self.page.evaluate('records')]
        self.assertEqual(kinds.count('product_state'), 1)

    def test_right_sku_only_from_owned_modal_and_never_address_payment(self):
        self.page.evaluate('''() => {
          const panel=document.querySelector('#panel'), modal=document.createElement('div');
          modal.setAttribute('role','dialog');modal.style='position:absolute;left:260px;top:0;width:730px;height:850px';
          document.body.append(modal);modal.append(panel);panel.style='position:static;width:340px';
          const right=document.createElement('aside');right.style='position:absolute;left:350px;top:0;width:320px';
          right.innerHTML='<section><h3>尺寸规格</h3><div><button aria-checked="true">单只装 枕芯加蓝色枕套</button><button>双只装 两个枕芯加枕套</button></div></section><div>收货地址：禁止输出合成街道</div><button>支付¥29</button>';
          modal.append(right);
          const other=document.createElement('div');other.setAttribute('role','dialog');other.innerHTML='<section><span>颜色分类</span><button>无关商品选项</button></section>';document.body.append(other);
          scan();
        }''')
        self.page.locator('#card h2').click()
        self.page.evaluate('scan();scan()')
        rows = self.page.evaluate('records')
        detail = next(e['payload'] for e in rows if e['event_type'] == 'product_detail')
        group = next(g for g in detail['sku_groups'] if g['name'] == '尺寸规格')
        self.assertEqual(len(group['options']), 2)
        self.assertTrue(group['options'][0]['selected'])
        for private in ('合成街道', '支付', '无关商品选项'):
            self.assertNotIn(private, str(rows))

    def test_recording_has_one_bundle_receipt_and_no_separate_product_download(self):
        source = (EXT / 'popup.js').read_text(encoding='utf-8')
        code = source[source.index('function taskElement('):source.index('function renderTasks(')]
        self.page.add_script_tag(content='''
          const ACTIVE_STATES=new Set(['recording','checking','queued','stopping']);
          const formatTaskTime=()=> '测试', taskStatePresentation=()=>({tone:'ok',label:'已结束'});
          const formatCompactDuration=()=> '1分钟', qualityLabel=()=> '标清', formatHumanDuration=()=> '1分钟';
          const copyOutputPath=()=>{}, setMessage=(text,error)=>{window.notice={text,error}};
          const refreshTasks=async()=>{}, api=async(path,body)=>{window.posted={path,body}};
        ''' + code)
        self.page.evaluate('''() => {
          document.body.innerHTML='';
          window.testTask={task_id:'dy-synthetic',state:'partial',started_at:'2026-01-01T00:00:00',output_dir:'synthetic-output',product_download_available:true};
          document.body.append(taskElement(testTask));
        }''')
        self.assertEqual(self.page.get_by_role('button', name='下载商品资料', exact=True).count(),0)
        self.page.evaluate("document.body.innerHTML='';document.body.append(taskElement({...testTask,product_download:{state:'complete_observed',image_saved:3}}))")
        self.assertEqual(self.page.get_by_role('button', name='商品资料已下载').count(),0)
        self.page.evaluate("document.body.innerHTML='';document.body.append(taskElement({...testTask,delivery:{id:'bundle'},visible_event_count:5,recording_sections_available:true,popup_observation_group_count:2}))")
        self.assertEqual(self.page.locator('.inline-delivery').count(),1)
        self.assertEqual(self.page.locator('.inline-delivery').get_attribute('data-delivery-id'),'bundle')
        self.assertEqual(self.page.get_by_role('button', name='下载商品资料', exact=True).count(),0)
        self.assertIn('2 个卡片观察组', self.page.locator('body').inner_text())


if __name__ == "__main__": unittest.main()
