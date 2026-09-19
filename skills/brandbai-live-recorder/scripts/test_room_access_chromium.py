"""Opt-in isolated sidebar rendering. Permission-dialog outcomes are synthetic."""
import json
import os
from pathlib import Path
import unittest
import uuid

EXT = Path(__file__).resolve().parent.parent / 'assets/chrome-extension'

@unittest.skipUnless(os.getenv('BRANDBAI_RUN_ROOM_ACCESS_BROWSER_TESTS') == '1', 'Opt-in isolated room UI')
class RoomAccessChromiumTests(unittest.TestCase):
    def test_optional_permission_ui_and_current_tab_states(self):
        from playwright.sync_api import sync_playwright
        qa = Path(os.environ['BRANDBAI_ROOM_ACCESS_QA']).resolve() / ('run-' + uuid.uuid4().hex)
        test_ext = qa / 'extension'
        test_ext.mkdir(parents=True)
        for source in EXT.rglob('*'):
            if not source.is_file(): continue
            data = source.read_bytes()
            # The isolated test must never probe the user's local helper.
            if source.suffix in {'.js', '.json'}:
                for port in (8765, 18765, 28765):
                    data = data.replace(f'http://127.0.0.1:{port}'.encode(), b'http://127.0.0.1:1')
            target = test_ext / source.relative_to(EXT)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        errors = []
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(str(qa / 'profile'), headless=True,
                executable_path=os.environ['BRANDBAI_TEST_CHROMIUM'], viewport={'width':380,'height':900},
                args=[f'--disable-extensions-except={test_ext}',f'--load-extension={test_ext}'])
            try:
                worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
                extension_id = worker.url.split('/')[2]
                declared = worker.evaluate('chrome.runtime.getManifest().optional_host_permissions')
                self.assertEqual(declared, ['https://www.douyin.com/*','https://douyin.com/*'])
                self.assertFalse(worker.evaluate('chrome.permissions.contains({origins:chrome.runtime.getManifest().optional_host_permissions})'))
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.add_init_script('''
                    window.testTab = {id:777,windowId:7};
                    window.permissionRequests = 0;
                    chrome.tabs.query = async () => [window.testTab];
                    chrome.permissions.request = async options => {
                      window.permissionRequests++;
                      window.requestedOrigins = options.origins;
                      return false;
                    };
                ''')
                page.goto(f'chrome-extension://{extension_id}/popup.html')
                page.locator('#allow-room-access').wait_for(state='visible')
                self.assertEqual(page.evaluate('window.permissionRequests'),0)
                self.assertTrue(page.locator('#start').is_disabled())
                page.locator('#allow-room-access').click()
                page.wait_for_function('document.querySelector("#room-access-message").textContent.includes("尚未授权")')
                self.assertEqual(page.evaluate('window.permissionRequests'),1)
                self.assertEqual(page.evaluate('window.requestedOrigins'),declared)
                for width in (320,380,480):
                    page.set_viewport_size({'width':width,'height':900})
                    for mode in ('recording','product'):
                        page.locator('#'+mode+'-view').click()
                        self.assertTrue(page.locator('#room-access-notice').is_visible())
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                        page.screenshot(path=str(qa/f'permission-{mode}-{width}.png'))
                # Simulate Chrome accepting the dialog and exposing the new current tab.
                page.evaluate('''() => {chrome.permissions.request=async()=>{
                  window.permissionRequests++;
                  window.testTab={id:778,windowId:7,url:'https://douyin.com/search/synthetic?live_web_rid=123456&type=live',title:'合成直播间'};
                  return true;
                }}''')
                page.locator('#allow-room-access').click()
                page.wait_for_function('currentRoomUrl === "https://live.douyin.com/123456"')
                self.assertTrue(page.locator('#room-access-notice').is_hidden())
                self.assertEqual(page.evaluate('currentRoomTabId'),778)
                self.assertFalse(page.evaluate('Boolean(pendingRecordingRequest)'))
                page.locator('#recording-view').click()
                page.screenshot(path=str(qa/'recognized.png'))
                self.assertEqual(worker.evaluate('chrome.runtime.getManifest().name'), 'BrandBAI 直播采集助手')
                for size in (16,32,48,128):
                    loaded = page.evaluate('''async size=>{const image=new Image();
                      image.src=chrome.runtime.getURL(chrome.runtime.getManifest().icons[size]);
                      await image.decode();return image.naturalWidth}''',str(size))
                    self.assertEqual(loaded,size)
                for width in (320,380,480):
                    page.set_viewport_size({'width':width,'height':900})
                    page.evaluate('''() => {const card=taskElement({task_id:'synthetic-task',state:'recording',
                      room_url:currentRoomUrl,started_at:new Date(Date.now()-50000).toISOString(),
                      max_runtime_seconds:1800,segment_duration_seconds:600,split_enabled:true,quality:'SD',
                      recording_health:{state:'reconnecting',retry_index:1,retry_limit:2},
                      interaction_health:{status:'interaction_interrupted',reason:'account_entered_another_live_room'},
                      collect_comments:true,visible_event_counts:{comment_visible:3}});
                      document.body.replaceChildren(card); }''')
                    self.assertIn('重新连接',page.locator('body').inner_text())
                    self.assertIn('已运行',page.locator('body').inner_text())
                    self.assertIn('评论采集已受阻',page.locator('body').inner_text())
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                    page.screenshot(path=str(qa/f'recovery-{width}.png'))
                # The synthetic card replaces the document only after permission-path verification.
                self.assertEqual(errors,[])
                page.reload()
                page.wait_for_function('typeof readCurrentTab === "function"')
                page.evaluate('''async()=>{window.testTab={id:779,windowId:7,url:'https://example.test/'};await readCurrentTab()}''')
                self.assertIn('当前不是',page.locator('#room-name').inner_text())
                self.assertTrue(page.locator('#start').is_disabled())
                self.assertEqual(errors,[])
                (qa/'result.json').write_text(json.dumps({'extension_loaded':True,'optional_not_granted_on_install':True,
                    'synthetic_permission_dialog_outcomes':True,'both_modes_widths':[320,380,480],
                    'no_auto_recording':True,'user_browser_accessed':False,'live_page_verified':False},indent=2),encoding='utf8')
                print('Room UI verification:',qa)
            finally: context.close()

if __name__ == '__main__': unittest.main()
