"""Local synthetic DOM acceptance; every request intercepted, no account/network.

Opt in with BRANDBAI_RUN_BROWSER_TESTS=1 and Python + Playwright Chromium.
Optionally set BRANDBAI_TEST_CHROMIUM to an installed Chromium executable.
The URL is localhost,
not a platform session. Nothing attaches to the user's running browser.
"""
import json
import os
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_collect_product_reviews import collect_product_reviews, ProductReviewError
from test_browser_collect_product_reviews import workspace_temp, WORK, PRODUCT

HTML = '''<!doctype html><meta charset="utf-8"><style>
body{margin:0;font:16px Arial} .eRfaxg7R{margin:20px;width:650px;height:500px;overflow-y:scroll}
.header{height:160px}.yVU8TMWn{display:flex;gap:30px;height:44px}.yVU8TMWn div{cursor:pointer}
.Ez3MC6d7{padding:20px;border-bottom:1px solid #ccc;min-height:100px}
.ji7a60UU{display:flex;gap:20px}.AdYl5cnz img{width:40px;height:40px}
</style><div class="lqrK15Gt"><div class="eRfaxg7R" data-product-id="123456789012345">
<div class="header"><div class="AjnzIIcY">合成旗舰店</div><span class="vs9hmvGz">合成测试商品标题</span><p>保障 物流</p></div>
<div class="NGeinxLS"><div class="yVU8TMWn"><div>商品详情</div><div id="reviewtab">商品评价(9000)</div></div>
<div class="FDag2E0P" hidden><span class="YLWPPuPR SrtfuQFU">全部</span><span class="NtPaXoT7 mFEHKTxv">综合</span>
<div class="PEzhiR4O"></div></div></div></div></div><script>
const list = document.querySelector('.PEzhiR4O'), panel = document.querySelector('.eRfaxg7R');
window.tabClicks=0; window.scrollEvents=0; window.appended=false;
function addReview(i) {
 const card=document.createElement('div'); card.className='Ez3MC6d7'; card.setAttribute('data-review-id','synthetic-'+i);
 card.innerHTML='<div class="ji7a60UU"><div class="sVIJnLfX"><span>合成用户'+i+'</span></div><div class="Xug6qnCc">'+(i%2?'12天前':'8月前')+'</div></div>'
 +'<div class="bFXVK94u">已购:50g</div><div class="mgNuPdjB">'+(i===2?'':'合成正文'+i)+'</div>'
 +'<div class="AdYl5cnz">'+(i===2?'<img src="https://p3-sign.douyinpic.com/synthetic.jpg?signature=NEVER_EXPORT">':'')+'</div>'
 +'<div class="swfDpKGt">浏览136837 <span class="X2TC7MK5">18</span></div>';
 list.append(card);
}
for(let i=1;i<=6;i++)addReview(i);
const footer=document.createElement('div');footer.className='Ao_Mqy8Y';footer.textContent='加载中';list.append(footer);
document.querySelector('#reviewtab').onclick=()=>{window.tabClicks++;document.querySelector('.FDag2E0P').hidden=false};
panel.addEventListener('scroll',()=>{window.scrollEvents++;
 if (!window.appended && panel.scrollTop+panel.clientHeight>=panel.scrollHeight-10) {
   window.appended=true; footer.remove(); for(let i=7;i<=9;i++)addReview(i);
   footer.textContent='没有更多评价';list.append(footer);
 }
});
</script>'''


@unittest.skipUnless(os.getenv('BRANDBAI_RUN_BROWSER_TESTS') == '1', 'Opt-in isolated Chromium synthetic test')
class ChromiumProductReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        kwargs = {"headless": True}
        if os.getenv("BRANDBAI_TEST_CHROMIUM"):
            kwargs["executable_path"] = os.environ["BRANDBAI_TEST_CHROMIUM"]
        cls.browser = cls.playwright.chromium.launch(**kwargs)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1000, "height": 800})
        self.requests=[]
        def route(request):
            self.requests.append(request.request.url)
            if request.request.url.startswith('http://localhost:9876/'):
                request.fulfill(status=200, content_type='text/html', body=HTML)
            else:
                request.abort()
        self.context.route('**/*', route)
        self.page = self.context.new_page()
        self.page.goto('http://localhost:9876/video/' + WORK)

    def tearDown(self):
        self.context.close()

    def test_actual_dom_open_scroll_media_only_and_durable_complete(self):
        with workspace_temp() as out:
            result=collect_product_reviews(self.page,WORK,PRODUCT,out,max_seconds=30)
            manifest=json.loads((out/'product_review_manifest.json').read_text(encoding='utf-8'))
            rows=[json.loads(line) for line in (out/'product_reviews.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(result,0,manifest)
            self.assertEqual(len(rows),9); self.assertEqual(manifest['review_count'],9)
            self.assertEqual(manifest['declared_review_count'],9000)
            self.assertEqual(self.page.evaluate('window.tabClicks'),1)
            self.assertGreater(self.page.evaluate('window.scrollEvents'),1)
            self.assertTrue(all(row['helpful_count']==18 for row in rows))
            media=next(row for row in rows if row['content_status']=='media_only')
            self.assertEqual(media['image_count'],1);self.assertEqual(media['images'],[])
            self.assertNotIn('NEVER_EXPORT', (out/'product_reviews.jsonl').read_text())
            self.assertTrue((out/'商品评价.xlsx').exists())
            self.assertTrue(all('localhost' in url or 'synthetic.jpg' in url for url in self.requests))

    def test_same_document_resume_updates_budget_without_replacing_lease(self):
        with workspace_temp() as out:
            self.assertEqual(collect_product_reviews(self.page,WORK,PRODUCT,out,max_reviews=2,max_seconds=30),3)
            first=json.loads((out/'product_review_manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(first['done_reason'],'run_budget')
            self.assertEqual(collect_product_reviews(self.page,WORK,PRODUCT,out,max_reviews=20,max_seconds=30,resume=True),0)
            second=json.loads((out/'product_review_manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(first['lease'],second['lease']);self.assertEqual(second['review_count'],9)

    def test_live_panel_change_interrupts_without_mixing_new_rows(self):
        with workspace_temp() as out:
            self.page.evaluate("""() => {document.querySelector('.eRfaxg7R').addEventListener('scroll',()=>{
              if(window.scrollEvents>0)document.querySelector('.vs9hmvGz').textContent='已切换成另一合成商品';
            },{once:true});}""")
            result=collect_product_reviews(self.page,WORK,PRODUCT,out,max_seconds=30)
            manifest=json.loads((out/'product_review_manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(result,3);self.assertEqual(manifest['status'],'partial')
            self.assertNotEqual(manifest['done_reason'],'source_exhausted')
            self.assertEqual(manifest['review_count'],6)

    def test_platform_alert_and_wrong_work_stop_before_review_tab_click(self):
        for mode in ('warning','wrong_work'):
            with self.subTest(mode=mode),workspace_temp() as out:
                if mode=='warning':self.page.evaluate("() => {let e=document.createElement('div');e.setAttribute('role','alert');e.textContent='访问过于频繁';document.body.append(e);}")
                with self.assertRaises(ProductReviewError):
                    collect_product_reviews(self.page,WORK if mode=='warning' else '7000000000000000002',PRODUCT,out)
                self.assertEqual(self.page.evaluate('window.tabClicks'),0)

    def test_inflight_ack_media_reply_and_helpful_updates_are_upserted(self):
        for explicit_id in (True,False):
            with self.subTest(explicit_id=explicit_id),workspace_temp() as out:
                self.page.goto('http://localhost:9876/video/' + WORK)
                if not explicit_id:
                    self.page.evaluate("() => document.querySelector('.Ez3MC6d7').removeAttribute('data-review-id')")
                class AckUpdatePage:
                    def __init__(shim,page):
                        shim.page=page;shim.kinds={};shim.updated=False
                    def evaluate(shim,script,arg=None):
                        if '.ack(value)' in script and not shim.updated and shim.kinds.get(arg['id'])=='CAPTURE_DOUYIN_COMMERCE_REVIEWS':
                            shim.updated=True
                            shim.page.evaluate("""() => {
                                const card=document.querySelector('.Ez3MC6d7');
                                card.querySelector('.AdYl5cnz').innerHTML='<img src="https://p3.ecombdimg.com/synthetic.jpg">';
                                card.querySelector('.X2TC7MK5').textContent='19';
                                const reply=document.createElement('div');reply.textContent='商家回复：合成商家已收到';card.append(reply);
                            }""")
                        result=shim.page.evaluate(script,arg)
                        if '.poll(value)' in script:
                            shim.kinds.update({item['id']:item['message']['type'] for item in result.get('items',[])})
                        return result
                    def wait_for_timeout(shim,value):shim.page.wait_for_timeout(value)
                self.assertEqual(collect_product_reviews(AckUpdatePage(self.page),WORK,PRODUCT,out,max_seconds=30),0)
                rows=[json.loads(line) for line in (out/'product_reviews.jsonl').read_text(encoding='utf-8').splitlines()]
                self.assertEqual(len(rows),9)
                first=next(row for row in rows if row['content']=='合成正文1')
                self.assertEqual(first['merchant_reply']['content'],'合成商家已收到')
                self.assertEqual(first['helpful_count'],19);self.assertEqual(first['image_count'],1)


if __name__ == '__main__':
    unittest.main()
