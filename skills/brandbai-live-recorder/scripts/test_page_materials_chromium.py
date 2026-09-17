"""Synthetic page mechanics, no login/profile/live website/network access."""
import os
import unittest
import test_live_products_chromium as fixtures
EXT, HTML, CATALOG = fixtures.EXT, fixtures.HTML, fixtures.CATALOG

@unittest.skipUnless(os.getenv('BRANDBAI_RUN_BROWSER_TESTS')=='1','Opt-in isolated synthetic Chromium')
class MaterialChromiumTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.LiveProductChromiumTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.LiveProductChromiumTests.tearDownClass.__func__)

    def setUp(self):
        self.context=self.browser.new_context(viewport={'width':1000,'height':900})
        self.context.route('**/*',lambda r:r.abort())
        self.page=self.context.new_page()
        self.page.set_content(HTML)
        for name in ('douyin-commerce-dom.js','product-identity.js','live-products.js','page-materials.js'):
            self.page.add_script_tag(content=(EXT/name).read_text(encoding='utf-8'))
        self.page.evaluate('''() => {
          window.room='https://live.douyin.com/123456';window.records=[];window.clicks=[];
          let serial=0;crypto.randomUUID=()=>`11111111-1111-4111-8111-${String(++serial).padStart(12,'0')}`;
          Object.defineProperties(HTMLImageElement.prototype,{complete:{get(){return !this.dataset.broken}},naturalWidth:{get(){return 500}},naturalHeight:{get(){return 500}}});
          window.rendered=n=>!n.closest('[hidden],[aria-hidden="true"]')&&n.getBoundingClientRect().width>0&&getComputedStyle(n).display!=='none';
          window.visible=n=>{
            return rendered(n)&&BrandbaiDouyinCommerceDom.visibleWithinViewport(n,window);
          };
          window.inspect=BrandbaiDouyinCommerceDom.createInspector({document,window,isVisible:visible,isRendered:rendered});
          window.reader=BrandbaiLiveProducts.createCollector({document,inspector:inspect,isVisible:visible,roomUrl:()=>room,emit:(...r)=>records.push(r),newId:()=>crypto.randomUUID()});
          window.materials=BrandbaiPageMaterials.create({document,window,inspector:inspect,reader,roomUrl:()=>room,publicUrl:BrandbaiLiveProducts.publicUrl,sleep:async ms=>{window.onWait?.();await new Promise(r=>setTimeout(r,10))}});
          window.start=(kind='product',resume=false)=>materials.start({kind,resume,request_id:crypto.randomUUID(),expected:kind==='product'?reader.previewCurrent():null});
          document.addEventListener('click',e=>clicks.push(e.target.textContent),true);
        }''')

    def tearDown(self): self.context.close()

    def product(self, lazy=False):
        self.page.evaluate('''lazy=>{
          const p=document.querySelector('#panel');p.hidden=false;p.style.overflowY='auto';
          p.innerHTML=`<div><h1 data-role="product-title">合成商品完整测试标题</h1><p>合成旗舰店</p><span>¥49</span></div>
            <div data-role="product-main-gallery" data-total="5"><span>1/5</span>${Array.from({length:lazy?1:5},(_,i)=>`<img src="https://p3.ecombdimg.com/main-${i}.webp">`).join('')}<button data-role="gallery-next">下一张</button></div>
            <div class="tabs"><span>商品详情</span><span>商品评价(9)</span></div>
            <section data-role="product-detail-content">${[1,2,3].map(i=>`<img style="display:block;width:400px;height:400px" src="https://p3.ecombdimg.com/detail-${i}.webp">`).join('')}<p data-role="product-detail-end">商品详情结束</p></section>`;
          let i=0; p.querySelector('[data-role="gallery-next"]').onclick=()=>{i++;p.querySelector('[data-role="product-main-gallery"] img').src=`https://p3.ecombdimg.com/main-${i%5}.webp`};
          window.originalPanel=p;
        }''',lazy)

    def finish(self):
        self.page.wait_for_function("materials.status().state!=='collecting'",timeout=15000)
        return self.page.evaluate('materials.status()')

    def test_loaded_all_images_and_restore_scroll_without_live_events(self):
        self.product(); self.page.evaluate('start()'); result=self.finish()
        self.assertEqual(result['state'],'ready',result)
        self.assertTrue(result['result']['complete'],result)
        self.assertEqual(result['result']['snapshot']['image_coverage']['main_observed'],5)
        self.assertEqual(result['result']['snapshot']['image_coverage']['detail_observed'],3)
        self.assertEqual(self.page.evaluate('originalPanel.scrollTop'),0)
        self.assertEqual(self.page.evaluate('records'),[])

    def test_lazy_gallery_flips_only_next_and_deduplicates(self):
        self.product(True);self.page.evaluate('start()'); result=self.finish()
        self.assertTrue(result['result']['complete'],result)
        self.assertEqual(len(result['result']['snapshot']['images']),8)
        self.assertEqual(self.page.evaluate('clicks'),['下一张']*4)

    def test_gallery_counter_and_controls_outside_rehashed_gallery(self):
        self.product(True)
        self.page.evaluate('''()=>{
          const gallery=originalPanel.querySelector('[data-role="product-main-gallery"]');
          gallery.removeAttribute('data-total');
          const shell=document.createElement('div');shell.className='changed-gallery-shell';
          gallery.before(shell);shell.append(gallery);shell.append(gallery.querySelector('span'),gallery.querySelector('button'));
          start();
        }''')
        result=self.finish();self.assertTrue(result['result']['complete'],result)
        self.assertEqual(result['result']['snapshot']['image_coverage']['main_expected'],5)
        self.assertEqual(self.page.evaluate('clicks'),['下一张']*4)

    def test_preopened_list_with_tall_individual_row_wrappers(self):
        self.catalog(4)
        self.page.evaluate('''()=>{list.hidden=false;document.querySelector('#entry').remove();
          for(const row of list.querySelectorAll('.item')){const wrapper=document.createElement('section');
            wrapper.style.minHeight='180px';row.before(wrapper);wrapper.append(row)}start('catalog');}''')
        result=self.finish();self.assertEqual(result['state'],'ready',result)
        self.assertEqual(len(result['result']['catalog']['rows']),4)
        self.assertEqual(self.page.evaluate('clicks'),[])

    def test_fixed_catalog_portal_escapes_collapsed_page_root_but_not_scrollbox(self):
        self.catalog(8)
        self.page.evaluate('''()=>{list.hidden=false;document.querySelector('#entry').remove();
          const collapsed=document.createElement('main');collapsed.style='height:0;overflow:hidden';
          const portal=document.createElement('div');portal.style='position:fixed;inset:0';
          document.body.append(collapsed);collapsed.append(portal);portal.append(list);
          window.collapsedRoot=collapsed;window.portalRoot=portal;
          start('catalog');}''')
        result=self.finish();self.assertEqual(result['state'],'ready',result)
        self.assertEqual(len(result['result']['catalog']['rows']),8)
        # A true containing block DOES clip the portal. Do not weaken all clipping.
        self.page.evaluate("collapsedRoot.style.transform='translateZ(0)'")
        self.assertIsNone(self.page.evaluate('reader.catalogSurface()'))

    def test_large_review_count_with_qr_purchase_panel_collects_only_product_materials(self):
        self.product(True)
        self.page.evaluate('''() => {
          originalPanel.querySelector('.tabs span:last-child').textContent='商品评价(22.9万)';
          originalPanel.insertAdjacentHTML('afterbegin','<img style="width:100px;height:30px" src="https://p3.ecombdimg.com/img/eden-cn/synthetic/product_opt/4x/aweme_flagship.png">');
          const qr=document.createElement('aside');qr.style='position:absolute;left:800px;top:30px;width:180px;height:500px';
          qr.innerHTML='<img src="https://p3.ecombdimg.com/qrcode.png"><p>请打开抖音APP扫描二维码购买此商品</p><button>支付</button>';
          document.body.append(qr);start();
        }''')
        result=self.finish()
        self.assertEqual(result['state'],'ready',result)
        self.assertTrue(result['result']['complete'],result)
        value=result['result']['snapshot']
        self.assertEqual(value['image_coverage']['main_observed'],5)
        self.assertEqual(value['image_coverage']['detail_observed'],3)
        self.assertNotIn('flagship',str(value));self.assertNotIn('qrcode',str(value))
        self.assertEqual(self.page.evaluate('clicks'),['下一张']*4)

    def test_catalog_unreadable_badge_row_prevents_complete_claim(self):
        self.page.evaluate(CATALOG);self.page.evaluate(fixtures.PROMOTED_ROW)
        self.page.evaluate("document.querySelector('.thumbnail').remove();document.querySelector('#catalog').style.height='640px';start('catalog')")
        result=self.finish()['result']
        self.assertFalse(result['complete'],result)
        self.assertNotIn('满1000',str(result['catalog']['rows']))

    def missing_number_catalog(self):
        self.page.evaluate(CATALOG)
        self.page.evaluate('''() => {
          const list=document.querySelector('#catalog');list.hidden=false;list.style.height='640px';
          window.missingRow=list.querySelector('.item');window.numberNode=missingRow.querySelector('span');numberNode.textContent='';
          window.rechecks=0;
        }''')

    def test_hidden_number_has_bounded_recheck_and_inference_only(self):
        self.missing_number_catalog()
        self.page.evaluate("onWait=()=>{if(materials.status().phase==='verifying_numbers')rechecks++};start('catalog')")
        value=self.finish()['result']
        self.assertEqual(len(value['catalog']['rows']),3)
        self.assertIsNone(value['catalog']['rows'][0]['list_position'])
        self.assertEqual(value['number_hints']['0']['candidate'],1)
        self.assertEqual(self.page.evaluate('rechecks'),12)
        self.assertEqual(self.page.evaluate('clicks'),[]);self.assertEqual(self.page.evaluate('records'),[])

    def test_same_row_number_observed_twice_can_be_confirmed(self):
        self.missing_number_catalog()
        self.page.evaluate("onWait=()=>{if(materials.status().phase==='verifying_numbers'){rechecks++;numberNode.textContent='1'}};start('catalog')")
        value=self.finish()['result'];row=value['catalog']['rows'][0]
        self.assertEqual(len(value['catalog']['rows']),3);self.assertEqual(row['list_position'],1)
        self.assertEqual(row['number_verification']['method'],'same_row_reobserved')
        self.assertIsNone(row['number_verification']['initial_position'])
        self.assertGreater(row['number_verification']['confirmed_at_epoch_ms'],row['observed_at_epoch_ms'])
        self.assertEqual(row['product_identity']['catalog_observed_at_epoch_ms'],row['number_verification']['confirmed_at_epoch_ms'])
        self.assertEqual(value['number_hints'],{});self.assertEqual(self.page.evaluate('rechecks'),2)
        # The actual browser result must pass the helper contract, including identity times.
        from material_contract import validate_catalog
        self.assertEqual(validate_catalog(value['catalog'])['rows'][0]['list_position'],1)

    def test_recycled_row_and_colliding_number_cannot_confirm(self):
        for mutation in ["missingRow.querySelector('h3').textContent='另一个合成商品标题';numberNode.textContent='1'",
                         "numberNode.textContent='2'", "missingRow.dataset.productId='123456789012345';numberNode.textContent='1'"]:
            with self.subTest(mutation=mutation):
                # Reuse this DOM only after removing the previous list and entry.
                self.page.evaluate("document.querySelector('#catalog')?.remove();document.querySelector('#entry')?.remove()")
                self.missing_number_catalog()
                self.page.evaluate("onWait=()=>{if(materials.status().phase==='verifying_numbers'){"+mutation+"}};start('catalog')")
                row=self.finish()['result']['catalog']['rows'][0]
                self.assertIsNone(row['list_position']);self.assertNotIn('number_verification',row)

    def test_stop_during_number_recheck_keeps_rows_and_valid_partial_contract(self):
        self.missing_number_catalog()
        self.page.evaluate("onWait=()=>{if(materials.status().phase==='verifying_numbers')materials.stop()};start('catalog')")
        value=self.finish()['result']
        from material_contract import validate_catalog
        c=validate_catalog(value['catalog'])
        self.assertEqual(c['stop_reason'],'user_stopped');self.assertFalse(c['complete']);self.assertEqual(len(c['rows']),3)
        self.assertEqual(value['number_hints'],{})

    def test_missing_main_and_broken_detail_are_partial(self):
        self.product();self.page.evaluate("originalPanel.querySelector('[data-role=gallery-next]').remove();originalPanel.querySelector('img').remove();originalPanel.querySelector('[data-role=product-detail-content] img').dataset.broken='1';start()")
        result=self.finish()['result'];self.assertFalse(result['complete'])
        self.assertFalse(result['snapshot']['image_coverage']['main_complete'])
        self.assertFalse(result['snapshot']['image_coverage']['detail_complete'])

    def test_product_change_never_exports_mixed_materials(self):
        self.product(True);self.page.evaluate("onWait=()=>{originalPanel.querySelector('h1').textContent='另一个完全不同的商品标题'};start()")
        result=self.finish();self.assertEqual(result['state'],'failed');self.assertNotIn('result',result)

    def test_recycled_same_title_with_different_id_stops(self):
        self.product(True)
        self.page.evaluate("originalPanel.dataset.productId='123456789012345';onWait=()=>{originalPanel.dataset.productId='999999999999999'};start()")
        result=self.finish();self.assertEqual(result['state'],'failed');self.assertNotIn('result',result)

    def test_identity_stays_on_sku_change_but_not_reopened_unknown_panel(self):
        self.product()
        first=self.page.evaluate('reader.previewCurrent().snapshot.product_identity')
        self.assertIsNone(first['product_id'])
        self.page.evaluate("originalPanel.dataset.selectedSkuId='123456789';originalPanel.querySelector('span').textContent='¥99'")
        second=self.page.evaluate('reader.previewCurrent().snapshot.product_identity')
        self.assertEqual(first['product_ref'],second['product_ref'])
        self.page.evaluate('originalPanel.hidden=true;originalPanel.hidden=false')
        third=self.page.evaluate('reader.previewCurrent().snapshot.product_identity')
        self.assertNotEqual(first['product_ref'],third['product_ref'])

    def test_catalog_to_product_mapping_uses_id_only(self):
        self.product()
        self.page.evaluate("originalPanel.dataset.productId='123456789012345'")
        value=self.page.evaluate('reader.previewCurrent().snapshot.product_identity')
        self.assertEqual(value['product_id'],'123456789012345');self.assertIsNone(value['catalog_position'])
        self.assertEqual(value['product_ref'],'douyin:product:123456789012345')

    def test_detail_growth_before_end_is_collected(self):
        self.product()
        self.page.evaluate('''() => {
          let added=false;onWait=()=>{if(!added && originalPanel.scrollTop>100){added=true;const img=document.createElement('img');img.src='https://p3.ecombdimg.com/lazy-detail.webp';img.style.cssText='display:block;width:400px;height:500px';originalPanel.querySelector('[data-role=product-detail-end]').before(img)}};start();
        }''')
        result=self.finish()['result'];self.assertTrue(result['complete']);self.assertEqual(result['snapshot']['image_coverage']['detail_observed'],4)

    def test_unknown_main_count_is_not_claimed_complete(self):
        self.product();self.page.evaluate("originalPanel.querySelector('[data-total]').removeAttribute('data-total');originalPanel.querySelector('[data-role=product-main-gallery] span').remove();originalPanel.querySelector('[data-role=gallery-next]').remove();start()")
        result=self.finish()['result'];self.assertFalse(result['complete']);self.assertIsNone(result['snapshot']['image_coverage']['main_expected'])

    def test_specification_change_aborts_without_export(self):
        self.product(True);self.page.evaluate('''() => {
          originalPanel.insertAdjacentHTML('beforeend','<div><span>容量</span><button aria-checked="true">50g</button><button>100g</button></div>');
          onWait=()=>originalPanel.querySelector('[aria-checked]').setAttribute('aria-checked','false');start();
        }''')
        result=self.finish();self.assertEqual(result['state'],'failed');self.assertEqual(result['reason'],'specification_changed')

    def test_stop_keeps_observed_images_partial(self):
        self.product(True);self.page.evaluate('onWait=()=>materials.stop();start()');result=self.finish()['result']
        self.assertFalse(result['complete']);self.assertGreater(len(result['snapshot']['images']),0)
        self.assertEqual(result['snapshot']['image_coverage']['stop_reason'],'user_stopped')

    def catalog(self, count):
        self.page.evaluate(CATALOG)
        self.page.evaluate('''count=>{
          const list=document.querySelector('#catalog'),sample=list.querySelector('.item').cloneNode(true);list.replaceChildren();
          for(let i=0;i<count;i++){const row=sample.cloneNode(true);row.querySelector('span').textContent=String(i+1);row.querySelector('h3').textContent=`合成目录第${i+1}号测试商品`;row.querySelector('img').src=`https://p3.ecombdimg.com/list-${i+1}.webp`;list.append(row)}
          window.list=list;
        }''',count)

    def test_catalog_caps_one_hundred_then_continues_with_actual_numbers(self):
        self.catalog(106);self.page.evaluate("list.querySelector('.item span').textContent='35';start('catalog')")
        first=self.finish()['result'];self.assertEqual(len(first['catalog']['rows']),100)
        self.assertFalse(first['complete']);self.assertEqual(first['catalog']['rows'][0]['list_position'],35)
        self.page.evaluate("start('catalog',true)");second=self.finish()['result']
        self.assertEqual(len(second['catalog']['rows']),106);self.assertTrue(second['complete'],second)
        self.assertNotIn('sku',str(second));self.assertEqual(self.page.evaluate('clicks'),['全部商品'])
        self.assertEqual(self.page.evaluate('records'),[])

    def test_single_row_catalog_and_no_guessed_number(self):
        self.catalog(1);self.page.evaluate("list.querySelector('.item span').remove();start('catalog')")
        result=self.finish()['result'];self.assertTrue(result['complete']);self.assertEqual(result['catalog']['rows'][0]['list_position'],None)

    def test_catalog_refuses_open_detail(self):
        self.product();self.page.evaluate("start('catalog')");result=self.finish()
        self.assertEqual(result['reason'],'close_product_detail');self.assertEqual(self.page.evaluate('clicks'),[])

    def test_preopened_catalog_reads_without_toggling_entry(self):
        self.catalog(3);self.page.evaluate("list.hidden=false;start('catalog')")
        result=self.finish()['result'];self.assertTrue(result['complete'])
        self.assertEqual(len(result['catalog']['rows']),3)
        self.assertEqual(self.page.evaluate('clicks'),[])

    def test_delayed_catalog_waits_and_clicks_nested_entry_only_once(self):
        self.catalog(3)
        self.page.evaluate('''() => {
          const entry=document.querySelector('#entry');entry.innerHTML='<span>全部商品</span>';entry.onclick=()=>{};
          window.waits=0;window.phases=[];onWait=()=>{phases.push(materials.status().phase);if(++waits===8)list.hidden=false};start('catalog');
        }''')
        result=self.finish()['result'];self.assertTrue(result['complete'])
        self.assertEqual(self.page.evaluate('clicks'),['全部商品'])
        self.assertIn('opening_catalog',self.page.evaluate('phases'))

    def test_missing_entry_requests_manual_open_without_buy_click(self):
        self.catalog(3);self.page.evaluate("document.querySelector('#entry').remove();start('catalog')")
        result=self.finish();self.assertEqual(result['reason'],'catalog_entry_unavailable')
        self.assertEqual(self.page.evaluate('clicks'),[])

    def test_multiple_visible_entries_are_not_guessed(self):
        self.catalog(3)
        self.page.evaluate("document.body.append(document.querySelector('#entry').cloneNode(true));start('catalog')")
        result=self.finish();self.assertEqual(result['reason'],'catalog_entry_ambiguous')
        self.assertEqual(self.page.evaluate('clicks'),[])

    def test_open_without_response_times_out_after_one_click(self):
        self.catalog(3);self.page.evaluate("document.querySelector('#entry').onclick=()=>{};start('catalog')")
        result=self.finish();self.assertEqual(result['reason'],'catalog_open_failed')
        self.assertEqual(self.page.evaluate('clicks'),['全部商品'])

    def test_hidden_entry_is_not_clicked(self):
        self.catalog(3);self.page.evaluate("document.querySelector('#entry').hidden=true;start('catalog')")
        result=self.finish();self.assertEqual(result['reason'],'catalog_entry_unavailable')
        self.assertEqual(self.page.evaluate('clicks'),[])

    def test_changed_room_while_opening_does_not_export_catalog(self):
        self.catalog(3)
        self.page.evaluate("document.querySelector('#entry').onclick=()=>{};onWait=()=>room='https://live.douyin.com/999999';start('catalog')")
        result=self.finish();self.assertEqual(result['reason'],'page_changed')
        self.assertNotIn('result',result)

    def test_catalog_keeps_numbered_lottery_without_price_or_click(self):
        self.catalog(16)
        self.page.evaluate('''() => {
          const row=list.lastElementChild;row.querySelector('button').textContent='点击抽奖';row.querySelector('button').disabled=true;
          [...row.querySelectorAll('p,span')].filter(n=>/¥|￥/.test(n.textContent)).forEach(n=>n.remove());
          start('catalog');
        }''')
        result=self.finish()['result']
        self.assertTrue(result['complete'],result);self.assertEqual(len(result['catalog']['rows']),16)
        last=result['catalog']['rows'][-1];self.assertEqual(last['entry_type'],'lottery');self.assertEqual(last['list_position'],16)
        self.assertIsNone(last['display_price']);self.assertEqual(self.page.evaluate('clicks'),['全部商品'])

    def test_long_image_tiles_preserved_and_cdn_replicas_deduplicated(self):
        self.product()
        self.page.evaluate('''() => {
          const d=originalPanel.querySelector('[data-role=product-detail-content]');
          d.innerHTML=[0,1000,2000].map(y=>`<img style="display:block;width:400px;height:300px" src="https://p3-item.ecombdimg.com/img/long~tplv-5mmsx3fupr-xy:0:${y}:1562:${y+1000}.jpeg">`).join('')
            +'<img style="width:400px;height:300px" src="https://p26-item.ecombdimg.com/img/long~tplv-5mmsx3fupr-xy:0:0:1562:1000.jpeg"><p data-role="product-detail-end">商品详情结束</p>';start();
        }''')
        result=self.finish()['result'];self.assertTrue(result['complete'],result)
        self.assertEqual(result['snapshot']['image_coverage']['detail_observed'],3)

    def test_price_explanation_marks_end_and_ui_icons_do_not_block(self):
        self.product()
        self.page.evaluate('''() => {
          originalPanel.querySelector('[data-role=product-detail-content]').removeAttribute('data-role');
          originalPanel.querySelector('[data-role=product-detail-end]').outerHTML='<div><span>价格说明</span><img src="https://p3.ecombdimg.com/common/arrow.png"></div><p>销量说明</p><p>协议</p>';
          start();
        }''')
        result=self.finish()['result'];self.assertTrue(result['complete'],result)
        self.assertEqual(result['snapshot']['image_coverage']['detail_end_evidence'],'explicit_end')
        self.assertEqual(result['snapshot']['image_coverage']['detail_observed'],3)

    def sku_product(self):
        self.product()
        self.page.evaluate('''() => {
          const modal=document.createElement('div');modal.setAttribute('role','dialog');document.body.append(modal);modal.append(originalPanel);
          const sku=document.createElement('aside');sku.style='position:fixed;top:10px;left:780px;width:200px;height:700px';
          sku.innerHTML='<div data-role="sku-public-header"><span class="sku-price">¥49.00</span><span>已选择</span></div><div><span>尺寸规格</span><div class="options">'
            +[0,1,2,3].map(i=>`<div class="ufz0AqTE ${i===0?'vZSOutR4':'wlXQKgvo'}" style="border:1px solid gray;height:65px"><img style="width:40px;height:40px" src="https://p3.ecombdimg.com/sku-${i}.png"><span>合成规格 ${i+1}</span></div>`).join('')+'</div></div><button id="never-buy">支付</button>';
          modal.append(sku);window.sku=sku;
          const gallery=originalPanel.querySelector('[data-role=product-main-gallery]');gallery.removeAttribute('data-total');gallery.className='swiper-container';
          gallery.innerHTML=[...Array.from({length:5},(_,i)=>`https://p3.ecombdimg.com/main-${i}.webp`),...Array.from({length:4},(_,i)=>`https://p3.ecombdimg.com/sku-${i}.png`)].map((u,i)=>`<div class="swiper-slide" data-swiper-slide-index="${i}" style="display:inline-block"><img src="${u}"></div>`).join('');
          const shell=document.createElement('div');shell.dataset.role='product-gallery-shell';gallery.before(shell);shell.append(gallery);shell.insertAdjacentHTML('beforeend','<span>1/4</span>');
          sku.querySelectorAll('.ufz0AqTE').forEach((o,i)=>o.onclick=()=>{sku.querySelectorAll('.ufz0AqTE').forEach(n=>n.className='ufz0AqTE wlXQKgvo');o.className='ufz0AqTE vZSOutR4';sku.querySelector('.sku-price').textContent=`¥${49+i*20}.00`;});
          window.startAll=()=>materials.start({kind:'product',sku_mode:'all_visible',request_id:crypto.randomUUID(),expected:reader.previewCurrent()});
        }''')

    def test_all_skus_have_price_image_mapping_and_restore_selection(self):
        self.sku_product(); self.page.evaluate('startAll()');result=self.finish()['result']
        self.assertTrue(result['complete'],result)
        snapshot=result['snapshot'];skus=snapshot['sku_materials']
        self.assertEqual(snapshot['image_coverage']['main_observed'],5)
        self.assertEqual(skus['status'],'complete_all_visible_skus');self.assertTrue(skus['selection_restored'])
        self.assertTrue(snapshot['sku_groups'][0]['options'][0]['selected'])
        self.assertEqual([v['price_texts'] for v in skus['variants']],[[f'¥{49+i*20}.00'] for i in range(4)])
        for i,v in enumerate(skus['variants']):
            self.assertEqual(len(v['image_urls']),6)
            self.assertIn(f'https://p3.ecombdimg.com/sku-{i}.png',v['image_urls'])
        self.assertEqual(self.page.evaluate("sku.querySelector('.vZSOutR4 span').textContent"),'合成规格 1')
        self.assertNotIn('支付',self.page.evaluate('clicks'));self.assertEqual(self.page.evaluate('records'),[])

    def test_sku_failed_selection_is_partial_and_other_options_continue(self):
        self.sku_product();self.page.evaluate("sku.querySelectorAll('.ufz0AqTE')[1].onclick=()=>{};startAll()")
        result=self.finish()['result'];self.assertFalse(result['complete'])
        skus=result['snapshot']['sku_materials'];self.assertEqual(skus['variants'][1]['state'],'failed')
        self.assertEqual(skus['variants'][2]['state'],'observed');self.assertTrue(skus['selection_restored'])

    def test_sku_disabled_option_not_clicked(self):
        self.sku_product();self.page.evaluate("sku.querySelectorAll('.ufz0AqTE')[1].setAttribute('aria-disabled','true');startAll()")
        result=self.finish()['result'];self.assertTrue(result['complete'],result)
        self.assertEqual(result['snapshot']['sku_materials']['variants'][1]['state'],'unavailable')
        self.assertNotIn('合成规格 2',self.page.evaluate('clicks'))

    def test_unconfirmed_initial_sku_never_switches(self):
        self.sku_product();self.page.evaluate("sku.querySelector('.vZSOutR4').className='ufz0AqTE wlXQKgvo';startAll()")
        result=self.finish()['result'];self.assertFalse(result['complete'])
        self.assertEqual(result['snapshot']['sku_materials']['stop_reason'],'selection_unconfirmed')
        self.assertEqual(self.page.evaluate('clicks'),[])

    def test_each_sku_lazy_gallery_is_completed_not_just_first(self):
        self.sku_product()
        self.page.evaluate('''() => {
          sku.querySelectorAll('img').forEach(i=>i.remove());
          const gallery=originalPanel.querySelector('[data-role=product-main-gallery]');gallery.setAttribute('data-total','2');
          gallery.innerHTML='<span>1/2</span><img src="https://p3.ecombdimg.com/variant-0-0.webp"><button data-role="gallery-next">下一张</button>';
          gallery.parentElement.querySelector(':scope>span').remove();
          let variant=0,position=0;
          gallery.querySelector('button').onclick=()=>{position=(position+1)%2;gallery.querySelector('img').src=`https://p3.ecombdimg.com/variant-${variant}-${position}.webp`;};
          sku.querySelectorAll('.ufz0AqTE').forEach((o,i)=>{const select=o.onclick;o.onclick=()=>{select();variant=i;position=0;gallery.querySelector('img').src=`https://p3.ecombdimg.com/variant-${i}-0.webp`;};});
          startAll();
        }''')
        result=self.finish()['result'];self.assertTrue(result['complete'],result)
        variants=result['snapshot']['sku_materials']['variants']
        for i,row in enumerate(variants):
            self.assertEqual(set(row['image_urls']),{f'https://p3.ecombdimg.com/variant-{i}-{j}.webp' for j in range(2)})
        self.assertEqual(result['snapshot']['image_coverage']['main_observed'],8)

    def test_failed_restore_does_not_claim_all_skus_complete(self):
        self.sku_product();self.page.evaluate("sku.querySelector('.ufz0AqTE').onclick=()=>{};startAll()")
        result=self.finish()['result'];self.assertFalse(result['complete'])
        self.assertFalse(result['snapshot']['sku_materials']['selection_restored'])
        self.assertEqual(result['snapshot']['sku_materials']['stop_reason'],'restore_unconfirmed')

    def test_manual_sku_click_aborts_without_overwriting_user_selection(self):
        self.sku_product();self.page.evaluate('startAll()')
        self.page.wait_for_function("materials.status().phase==='sku_images'")
        self.page.locator('.ufz0AqTE').nth(3).click()
        result=self.finish();self.assertEqual(result['state'],'failed');self.assertEqual(result['reason'],'specification_changed')
        self.assertEqual(self.page.evaluate("sku.querySelector('.vZSOutR4 span').textContent"),'合成规格 4')

if __name__=='__main__': unittest.main()
