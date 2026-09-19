"""Real sidebar scripts with synthetic Chrome/helper boundaries, no external requests."""
import os
import unittest
from pathlib import Path
from urllib.parse import urlparse

EXT = Path(__file__).resolve().parent.parent / 'assets/chrome-extension'
FIXTURE = Path(__file__).resolve().parent / 'fixtures/sidebar-ui.js'


@unittest.skipUnless(os.getenv('BRANDBAI_RUN_BROWSER_TESTS') == '1', 'Opt-in isolated Chromium')
class SidebarUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        options = {'headless': True}
        if os.getenv('BRANDBAI_TEST_CHROMIUM'):
            options['executable_path'] = os.environ['BRANDBAI_TEST_CHROMIUM']
        cls.browser = cls.pw.chromium.launch(**options)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width':380, 'height':820})
        self.context.add_init_script(path=str(FIXTURE))
        def serve(route):
            url = urlparse(route.request.url)
            target = (EXT / url.path.lstrip('/')).resolve()
            if url.hostname != 'sidebar.test' or not target.is_relative_to(EXT.resolve()) or not target.is_file():
                route.abort()
                return
            mime = {'.html':'text/html', '.js':'application/javascript', '.css':'text/css', '.svg':'image/svg+xml', '.png':'image/png'}.get(target.suffix,'application/octet-stream')
            route.fulfill(path=str(target),content_type=mime)
        self.context.route('**/*',serve)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.page.goto('https://sidebar.test/popup.html')
        self.page.wait_for_function('typeof sessionToken!=="undefined" && sessionToken')

    def tearDown(self):
        self.assertEqual(self.errors,[])
        self.assertEqual(self.page.evaluate('audit.unhandled'),[])
        self.context.close()

    def record(self):
        self.page.evaluate('async()=>{audit.tasks=[audit.task];await refreshTasks()}')
        self.page.wait_for_selector('#stop-recording:visible')

    def reviews(self):
        self.page.evaluate("audit.mode='review'")
        self.page.click('#product-view')
        self.page.wait_for_function("!document.querySelector('#review-start').disabled")
        self.page.click('#review-start')
        self.page.wait_for_function("document.querySelector('#review-count').textContent.includes('已读取 100 条')")

    def saved_review(self):
        self.reviews()
        self.page.evaluate("Object.assign(audit.review,{state:'saved',doneReason:'source_exhausted',completeness:'complete_visible_panel_exhausted',reviewCount:200,delivery:audit.delivery})")
        self.page.wait_for_selector('#review-delivery:visible')

    def preview(self,name):
        root=os.getenv('BRANDBAI_SIDEBAR_PREVIEW_DIR')
        if root:
            target=Path(root);target.mkdir(parents=True,exist_ok=True)
            self.page.screenshot(path=str(target/f'{name}.png'),full_page=True)

    def test_recording_progress_precedes_settings_and_keyboard_focus_survives_polls(self):
        self.record()
        self.assertTrue(self.page.evaluate("document.querySelector('.results-card').nextElementSibling.classList.contains('record-card')"))
        self.assertTrue(self.page.is_hidden('#start'))
        box=self.page.locator('#stop-recording').bounding_box()
        self.assertLessEqual(box['y']+box['height'],820)
        self.page.locator('#task-list .task-stop').focus()
        self.page.evaluate("window.focusedStop=document.activeElement;audit.task.visible_event_count=160")
        self.page.wait_for_timeout(3500)
        self.assertTrue(self.page.evaluate('document.activeElement===focusedStop && focusedStop.isConnected'))
        self.preview('recording')

    def test_stop_dock_targets_existing_recording_once_and_never_starts_one(self):
        self.record()
        self.page.evaluate("document.querySelector('#stop-recording').click();document.querySelector('#stop-recording').click()")
        self.page.wait_for_function("audit.task.state==='stopping'")
        self.assertEqual(self.page.evaluate("audit.requests.filter(x=>x.path?.endsWith('/stop')&&x.method==='POST').length"),1)
        self.assertEqual(self.page.evaluate("audit.requests.filter(x=>x.path==='/v1/tasks'&&x.method==='POST').length"),0)
        self.assertTrue(self.page.is_disabled('#stop-recording'))

    def test_review_unavailable_is_disabled_and_reconnect_has_one_truthful_state(self):
        self.page.click('#product-view')
        self.page.wait_for_function("document.querySelector('#product-preview').textContent.includes('合成记忆枕')")
        self.assertTrue(self.page.is_disabled('#review-start'))
        self.reviews()
        original=self.page.evaluate('audit.review.id')
        self.page.evaluate('audit.failedStatus=true')
        self.page.wait_for_function("document.querySelector('#review-result-title').textContent==='正在恢复进度连接'")
        self.assertTrue(self.page.is_hidden('#review-message'))
        self.assertTrue(self.page.is_hidden('#review-progress'))
        self.assertNotIn('正在向下读取',self.page.text_content('#review-result'))
        self.assertIn('上次确认 100',self.page.text_content('#review-count'))
        self.preview('review-reconnecting')
        self.page.evaluate('audit.failedStatus=false;audit.review.reviewCount=140')
        self.page.wait_for_function("document.querySelector('#review-count').textContent.includes('已读取 140 条')")
        self.assertEqual(self.page.evaluate('audit.review.id'),original)
        self.assertEqual(self.page.evaluate("audit.requests.filter(x=>x.type==='brandbai-review-start').length"),1)

    def test_receipt_requires_delivery_confirmation_then_opens_only_that_file(self):
        self.saved_review()
        self.assertNotIn('文件已下载',self.page.text_content('#review-delivery'))
        self.assertTrue(self.page.is_hidden('#review-copy'))
        self.page.evaluate('async()=>{audit.deliveries=[audit.delivery];await BrandbaiDownloads.refresh()}')
        self.assertIn('文件已下载',self.page.text_content('#review-delivery'))
        self.page.click('#review-delivery button')
        self.assertEqual(self.page.evaluate("audit.requests.filter(x=>x.type==='brandbai-delivery'&&x.action==='show').map(x=>x.id)"),['synthetic-delivery'])
        self.preview('review-downloaded')
        self.page.evaluate('async()=>{audit.failedDelivery=true;await BrandbaiDownloads.refresh()}')
        self.page.wait_for_function("document.querySelector('#review-delivery').textContent.includes('文件状态暂未更新')")
        self.assertIn('文件状态暂未更新',self.page.text_content('#review-delivery'))
        self.assertNotIn('文件已下载',self.page.text_content('#review-delivery'))

    def test_download_updates_keep_focus_and_retry_does_not_recollect(self):
        self.saved_review()
        self.page.evaluate("async()=>{audit.delivery.state='downloading';audit.deliveries=[audit.delivery];await BrandbaiDownloads.refresh()}")
        self.page.locator('#review-delivery button').focus()
        self.page.evaluate('window.receiptFocus=document.activeElement')
        self.page.evaluate('async()=>{audit.delivery.bytes_received=12000;await BrandbaiDownloads.refresh()}')
        self.assertTrue(self.page.evaluate('document.activeElement===receiptFocus'))
        self.page.evaluate("async()=>{audit.delivery.state='interrupted';await BrandbaiDownloads.refresh()}")
        self.page.click('#review-delivery button')
        self.assertEqual(self.page.evaluate("audit.requests.filter(x=>x.type==='brandbai-delivery'&&x.action==='download').map(x=>x.id)"),['synthetic-delivery'])
        self.assertEqual(self.page.evaluate("audit.requests.filter(x=>x.type==='brandbai-review-start').length"),1)

    def test_completed_recording_has_inline_receipt_and_stable_controls(self):
        self.page.evaluate("async()=>{Object.assign(audit.task,{state:'completed',delivery:audit.delivery});audit.tasks=[audit.task];audit.deliveries=[audit.delivery];await refreshTasks();await BrandbaiDownloads.refresh()}")
        self.assertTrue(self.page.is_hidden('#stop-recording'))
        self.assertIn('文件已下载',self.page.text_content('#task-list .inline-delivery'))
        self.page.locator('#task-list .inline-delivery button').focus()
        self.page.evaluate('window.receiptFocus=document.activeElement')
        self.page.wait_for_timeout(3500)
        self.assertTrue(self.page.evaluate('document.activeElement===receiptFocus'))

    def test_compact_header_and_no_overflow_in_both_workspaces(self):
        for product in (False,True):
            self.page.click('#product-view' if product else '#recording-view')
            for width in (320,380,480):
                self.page.set_viewport_size({'width':width,'height':820})
                self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth>innerWidth'))
                self.assertLess(self.page.locator('.app-header').bounding_box()['height'],140)
                self.assertFalse(self.page.evaluate("document.querySelector('#help-contact').open"))
        self.page.set_viewport_size({'width':380,'height':820})
        self.page.wait_for_function("document.querySelector('#product-preview').textContent.includes('合成记忆枕')")
        self.assertIn('product-primary',self.page.locator('#download-current-product').get_attribute('class'))
        self.assertIn('product-secondary',self.page.locator('#download-product-catalog').get_attribute('class'))
        self.preview('product-ready')

    def test_restored_catalog_receipt_is_independent_and_closed_history_stays_closed(self):
        self.context.add_init_script("""audit.stored.brandbaiIndependentProductDownload={id:'synthetic-catalog',kind:'catalog',state:'complete_observed',title:'合成商品目录',room_url:audit.room,item_count:16,image_saved:16,image_total:16,delivery:{...audit.delivery,id:'catalog-file'}};audit.deliveries=[{...audit.delivery,id:'catalog-file',kind:'catalog'}];""")
        self.page.reload()
        self.page.wait_for_function('typeof sessionToken!=="undefined" && sessionToken')
        self.page.click('#product-view')
        self.page.wait_for_function("document.querySelector('#catalog-feedback .inline-delivery')?.textContent.includes('文件已下载')")
        self.assertEqual(self.page.locator('#product-feedback .inline-delivery').count(),0)
        self.page.click('#catalog-feedback .inline-delivery button')
        self.assertEqual(self.page.evaluate("audit.requests.filter(x=>x.action==='show').map(x=>x.id)"),['catalog-file'])
        self.assertFalse(self.page.evaluate("document.querySelector('#storage-settings').open"))

    def test_restored_product_receipt_disappears_when_a_different_product_is_opened(self):
        self.context.add_init_script("""audit.stored.brandbaiIndependentProductDownload={id:'synthetic-product',kind:'product',state:'partial',title:audit.product.snapshot.product_title,room_url:audit.room,current_product:audit.product,image_saved:4,image_total:5,image_failed:1,delivery:{...audit.delivery,id:'product-file'}};audit.deliveries=[{...audit.delivery,id:'product-file',kind:'product'}];""")
        self.page.reload()
        self.page.wait_for_function('typeof sessionToken!=="undefined" && sessionToken')
        self.page.click('#product-view')
        self.page.wait_for_function("!document.querySelector('#product-download-result').hidden")
        self.assertIn('1 张失败',self.page.text_content('#product-download-result'))
        self.page.wait_for_function("document.querySelector('#product-feedback .inline-delivery')?.textContent.includes('文件已下载')")
        self.page.evaluate("audit.product=structuredClone(audit.product);audit.product.panel_key='synthetic-B';audit.product.snapshot.product_title='其他合成商品';audit.product.snapshot.product_identity={platform:'douyin',product_id:'999999999999999',product_ref:'douyin:product:999999999999999',identity_status:'verified'}")
        self.page.click('#refresh-product')
        self.page.wait_for_function("document.querySelector('#product-preview').textContent.includes('其他合成商品')")
        self.assertTrue(self.page.is_hidden('#product-download-result'))
        self.assertFalse(self.page.evaluate("document.querySelector('#product-history').open"))


if __name__=='__main__':unittest.main()
