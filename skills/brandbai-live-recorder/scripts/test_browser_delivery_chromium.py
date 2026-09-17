"""Opt-in real extension/local ZIP test in a fresh profile, never a user's browser."""
import hashlib
import json
import os
import secrets
import threading
import time
import unittest
import uuid
import zipfile
from pathlib import Path
from local_service import TaskManager, TaskStore, create_http_server

EXT=Path(__file__).resolve().parent.parent/'assets/chrome-extension'

@unittest.skipUnless(os.getenv('BRANDBAI_RUN_DELIVERY_BROWSER_TESTS')=='1','Opt-in fresh extension browser')
class BrowserDeliveryChromiumTests(unittest.TestCase):
    def test_real_default_zip_download_retry_and_narrow_layout(self):
        from playwright.sync_api import sync_playwright
        qa=Path(os.environ['BRANDBAI_DELIVERY_QA']).resolve()/('run-'+uuid.uuid4().hex)
        qa.mkdir(parents=True)
        profile=qa/'profile';(profile/'Default').mkdir(parents=True)
        downloads=qa/'browser-default-downloads';downloads.mkdir()
        (profile/'Default'/'Preferences').write_text(json.dumps({'download':{
            'default_directory':str(downloads),'prompt_for_download':False},'extensions':{'ui':{'developer_mode':True}}}),encoding='utf-8')
        manager=TaskManager(store=TaskStore(qa/'helper'/'state.sqlite3'),output_root=qa/'legacy')
        server=None
        for port in (28765,18765,8765):
            try:
                server=create_http_server(host='127.0.0.1',port=port,manager=manager,token=secrets.token_hex(32));break
            except OSError:pass  # Never stop or communicate with an occupied service.
        if server is None:self.fail('No unoccupied allowed test port')
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        # Fixture copy remaps only allowed loopback ports: never probe the user's helper.
        test_ext=qa/'extension';test_ext.mkdir()
        for source in EXT.rglob('*'):
            if not source.is_file():continue
            target=test_ext/source.relative_to(EXT);target.parent.mkdir(parents=True,exist_ok=True)
            data=source.read_bytes()
            if source.suffix in {'.js','.json'}:
                for candidate in (b'http://127.0.0.1:8765',b'http://127.0.0.1:18765',b'http://127.0.0.1:28765'):
                    data=data.replace(candidate,b'http://127.0.0.1:TESTPORT')
                data=data.replace(b'http://127.0.0.1:TESTPORT',base.encode())
            target.write_bytes(data)
        jobs=manager.deliveries;entry=jobs.create('product','synthetic-browser-test');ident=entry['id']
        material=jobs.work_root(ident)/'合成商品资料';material.mkdir()
        (material/'商品资料.md').write_text('合成测试资料\n商品 ID：未取得。',encoding='utf-8')
        (material/'合成文件.bin').write_bytes(b'synthetic-data'*16384)
        jobs.source(ident,material);jobs.pack(ident,material_status='partial_current_loaded')
        while jobs.workers:time.sleep(.02)
        archive=jobs._file(ident,jobs.jobs[ident]['archive']);expected=hashlib.sha256(archive.read_bytes()).hexdigest()
        page_errors=[]
        try:
            with sync_playwright() as pw:
                context=pw.chromium.launch_persistent_context(str(profile),headless=True,
                    executable_path=os.environ['BRANDBAI_TEST_CHROMIUM'],
                    args=[f'--disable-extensions-except={test_ext}',f'--load-extension={test_ext}'],
                    viewport={'width':380,'height':900})
                try:
                    # Restore normal browser download behavior: use its own default_directory preference.
                    context.new_cdp_session(context.pages[0]).send('Browser.setDownloadBehavior',{'behavior':'default','eventsEnabled':True})
                    worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker',timeout=15000)
                    extension_id=worker.url.split('/')[2]
                    # Pair ONLY with the isolated server, before popup discovery can probe other helpers.
                    worker.evaluate('''async base=>{
                      const response=await fetch(base+'/v1/pair',{method:'POST',headers:{
                        'X-BrandBAI-Pair':'extension-popup','X-BrandBAI-Client':chrome.runtime.id}});
                      const payload=await response.json();if(!response.ok)throw Error('test pairing failed');
                      await chrome.storage.session.set({brandbaiLiveRecorderSession:{token:payload.session_token,
                        clientId:chrome.runtime.id,serviceBase:base,expiresAt:Date.now()+800000}});
                    }''',base)
                    page=context.new_page();page.on('pageerror',lambda err:page_errors.append(str(err)))
                    page.goto(f'chrome-extension://{extension_id}/popup.html')
                    def wait(predicate,arg=None):
                        deadline=time.monotonic()+20
                        while time.monotonic()<deadline:
                            if page.evaluate(predicate,arg):return
                            page.wait_for_timeout(100)
                        self.fail('Timed out in isolated browser check; page errors: '+str(page_errors))
                    wait("()=>typeof BrandbaiDownloads!=='undefined' && Boolean(sessionToken)")
                    self.assertTrue(page.locator('#choose-location').is_hidden())
                    self.assertEqual(jobs.public(ident)['state'],'ready','opening a browser does not replay old ready packages')
                    worker.evaluate('''async id=>{await BrandbaiDelivery.watch(id);await BrandbaiDelivery.sync();}''',ident)
                    wait('''async id=>(await api('/v1/deliveries')).deliveries.find(x=>x.id===id)?.state==='completed' ''',ident)
                    item=worker.evaluate('''async id=>(await chrome.downloads.search({id}))[0]''',jobs.public(ident)['download_id'])
                    self.assertEqual(Path(item['filename']).parent,downloads)
                    saved=Path(item['filename']);self.assertEqual(hashlib.sha256(saved.read_bytes()).hexdigest(),expected)
                    self.assertEqual(saved.name,'合成商品资料.zip')
                    with zipfile.ZipFile(saved) as z:self.assertIsNone(z.testzip())
                    self.assertNotIn('?',item['url']);self.assertEqual(item['bytesReceived'],archive.stat().st_size)
                    page.evaluate('id=>window.firstDownload=id',item['id'])
                    result=page.evaluate('''async id=>await chrome.runtime.sendMessage({type:'brandbai-delivery',action:'download',id})''',ident)
                    self.assertNotIn('error',result)
                    wait('''async id=>{const x=(await api('/v1/deliveries')).deliveries.find(x=>x.id===id);return x.state==='completed'&&x.download_id!==Number(window.firstDownload);}''',ident)
                    files=list(downloads.glob('*.zip'));self.assertEqual(len(files),2,'manual re-download preserves original')
                    self.assertTrue(all(hashlib.sha256(f.read_bytes()).hexdigest()==expected for f in files))
                    page.evaluate('id=>BrandbaiDownloads.reveal(id)',ident)
                    for width in (320,380,480):
                        page.set_viewport_size({'width':width,'height':900});page.wait_for_timeout(150)
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                        page.screenshot(path=str(qa/f'download-center-{width}.png'),full_page=True)
                    self.assertEqual(page_errors,[])
                    (qa/'result.json').write_text(json.dumps({'default_directory_verified':True,'real_chrome_download_complete':True,
                        'zip_hash_verified':True,'same_name_no_overwrite':True,'sidebars':[320,380,480],
                        'source_extension_except_isolated_port':True,'user_browser_accessed':False},indent=2),encoding='utf-8')
                    print('Isolated ZIP browser verification:',qa)
                finally:context.close()
        finally:
            manager.shutdown();server.shutdown();server.server_close();thread.join(3)

if __name__=='__main__':unittest.main()
