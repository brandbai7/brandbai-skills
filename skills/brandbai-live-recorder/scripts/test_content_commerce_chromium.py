"""Production content-message integration; synthetic DOM and no live network."""
import json
import os
import unittest

import test_live_products_chromium as fixtures
from test_review_page_chromium import HTML as REVIEW_HTML

EXT = fixtures.EXT


@unittest.skipUnless(os.getenv('BRANDBAI_RUN_BROWSER_TESTS') == '1', 'Opt-in isolated Chromium')
class ContentCommerceTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.LiveProductChromiumTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.LiveProductChromiumTests.tearDownClass.__func__)

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1000})
        self.context.route('**/*', lambda r: r.fulfill(status=200, content_type='text/html', body=REVIEW_HTML)
                           if r.request.url == 'https://live.douyin.com/123456' else r.abort())
        self.page = self.context.new_page()
        self.page.goto('https://live.douyin.com/123456')
        self.page.evaluate('''() => {
          window.contentListeners=[];window.sent=[];window.caught=[];
          window.chrome={runtime:{id:'synthetic-extension',getManifest:()=>({version:'synthetic'}),
            onMessage:{addListener:l=>contentListeners.push(l)},
            sendMessage:(m,cb)=>{sent.push(m);const r={status:'ok',active:false};cb?.(r);return Promise.resolve(r)}}};
          window.dispatchContent = m => new Promise(resolve=>{
            let answered=false;
            for(const listener of contentListeners){
              try {listener(m,{},r=>{answered=true;resolve(r)});}
              catch(e){caught.push(e.name+':'+e.message);resolve({exception:e.name+':'+e.message})}
            }
            setTimeout(()=>{if(!answered)resolve({no_response:true})},1000);
          });
          document.querySelector('.header').insertAdjacentHTML('beforeend',
            '<div><span>¥</span><b>399</b></div><img style="width:140px;height:100px" src="https://p3.ecombdimg.com/synthetic-main.png">');
          document.querySelector('.header').style.height='300px';
          document.querySelector('.eRfaxg7R').style.height='850px';
          document.querySelector('.FDag2E0P').hidden=false;
          document.querySelector('#reviewtab').textContent='商品评价(8.9万)';
          for(let i=10;i<=29;i++)addReview(i);
          const underlying=document.createElement('div');
          underlying.innerHTML='<span>商品评价 (8.9w)</span><span>共 1 种规格可选</span>';
          underlying.style='height:0;overflow:hidden';document.body.prepend(underlying);
          const noise=document.createElement('section');noise.hidden=true;
          noise.innerHTML=Array.from({length:500},(_,i)=>'<div><span>合成背景'+i+'</span><p>非商品文本</p></div>').join('');
          document.body.prepend(noise);
        }''')
        self.errors = []
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        self.files = json.loads((EXT/'manifest.json').read_text(encoding='utf-8'))['content_scripts'][0]['js']
        for filename in self.files:
            self.page.add_script_tag(content=(EXT/filename).read_text(encoding='utf-8'))

    def tearDown(self):
        self.context.close()

    def message(self, kind):
        return self.page.evaluate("kind=>dispatchContent({type:kind,roomUrl:location.href})",kind)

    def test_production_preview_and_reviews_share_identity_without_download(self):
        self.assertTrue(self.message('brandbai-content-script-ping')['ok'])
        first=self.message('brandbai-product-preview')
        self.assertEqual(first.get('status'),'recognized',first)
        reviews=self.message('brandbai-review-preview')
        self.assertTrue(reviews.get('ready'),reviews)
        self.assertEqual(first['snapshot']['product_identity'],reviews['product_identity'])
        self.assertEqual(self.page.evaluate('caught'),[])
        self.assertFalse(any(m['type']=='brandbai-review-bridge' for m in self.page.evaluate('sent')))
        self.assertEqual(self.page.evaluate('scrollEvents'),0)

    def test_injected_bundle_can_reconnect_without_duplicate_listeners(self):
        before=self.message('brandbai-product-preview')
        for filename in self.files:
            self.page.add_script_tag(content=(EXT/filename).read_text(encoding='utf-8'))
        self.assertEqual(self.errors,[])
        self.assertEqual(self.page.evaluate('contentListeners.length'),1)
        after=self.message('brandbai-product-preview')
        self.assertEqual(before.get('panel_key'),after.get('panel_key'))

    def test_product_reader_error_is_not_reported_as_missing_connection(self):
        self.page.evaluate("() => {globalThis.BrandbaiLiveProducts={...BrandbaiLiveProducts,createCollector:()=>{throw new Error('synthetic parser failure')}}}")
        self.assertEqual(self.message('brandbai-product-preview'),{'status':'read_failed'})
        self.assertTrue(self.message('brandbai-content-script-ping')['ok'])
        self.assertEqual(self.page.evaluate('caught'),[])

    def test_review_initialization_error_always_answers_message(self):
        self.page.evaluate("() => {globalThis.BrandbaiLiveReviews={...BrandbaiLiveReviews,create:()=>{throw new Error('synthetic reader failure')}}}")
        self.assertEqual(self.message('brandbai-review-preview'),{'error':'synthetic reader failure'})
        self.assertTrue(self.message('brandbai-content-script-ping')['ok'])
        self.assertEqual(self.page.evaluate('caught'),[])

    def test_unrelated_background_nodes_do_not_trigger_layout_scans(self):
        result=self.page.evaluate('''() => {
          const noise=document.createElement('section');
          noise.innerHTML=Array.from({length:1000},(_,i)=>'<div><span>合成普通背景'+i+'</span></div>').join('');
          document.body.prepend(noise);
          let backgroundReads=0;
          const rendered=n=>{if(noise.contains(n))backgroundReads++;return n.getBoundingClientRect().width>0;};
          const inspector=BrandbaiDouyinCommerceDom.createInspector({document,window,isVisible:rendered,isRendered:rendered});
          return {status:inspector.inspect().status,backgroundReads};
        }''')
        self.assertEqual(result['status'],'recognized',result)
        self.assertEqual(result['backgroundReads'],0,result)


if __name__ == '__main__':
    unittest.main()
