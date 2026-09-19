/* Explicit page-material collection, never an on-air product event. */
(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.BrandbaiPageMaterials = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  'use strict';
  function cropTile(value) {
    try {
      const path=new URL(value).pathname,size=path.match(/_www(\d+)-(\d+)/),crop=path.match(/~tplv-[^/]*?-xy:(\d+):(\d+):(\d+):(\d+)/);
      if(!size||!crop)return null;
      const [width,height]=size.slice(1).map(Number),[left,top,right,bottom]=crop.slice(1).map(Number);
      if(width<100||height<1000||left!==0||right!==width||top<0||bottom<=top||bottom>height)return null;
      return {key:path.split('~tplv-')[0],width,height,top,bottom};
    }catch(_){return null;}
  }
  function completeCropTiles(urls) {
    const groups=new Map();
    for(const url of urls){const tile=cropTile(url);if(tile){if(!groups.has(tile.key))groups.set(tile.key,[]);groups.get(tile.key).push(tile);}}
    for(const tiles of groups.values()){
      let end=0;
      for(const tile of tiles.sort((a,b)=>a.top-b.top)){if(tile.top>end)return false;end=Math.max(end,tile.bottom);}
      if(end!==tiles[0].height)return false;
    }
    return true;
  }
  function numberHints(rows, complete) {
    // A speaking item can be promoted to the top. Order is a clue, never proof.
    const missing=rows.map((r,i)=>r.list_position==null?i:-1).filter(i=>i>=0);
    if(!complete || rows.length<3 || missing.length!==1 || rows.filter(r=>r.explaining===true).length!==1) return {};
    const index=missing[0];
    if(rows[index].explaining!==true || rows.some((r,i)=>i!==index && r.list_position!==i+1)) return {};
    return {[index]:{candidate:index+1,status:'inferred_unverified',
      evidence:['single_missing_number','other_numbers_contiguous','row_order_consistent','explaining_label'],
      warning:'explaining_item_may_be_promoted'}};
  }
  function create({document, window, inspector, reader, roomUrl, publicUrl,
    sleep = ms => new Promise(resolve => setTimeout(resolve, ms)), now = Date.now}) {
    let job = null, cancelled = false, savedCatalog = null;
    const all = (node, selector) => Array.from(node?.querySelectorAll(selector) || []);
    const text = node => String(node?.innerText || node?.textContent || '').replace(/\s+/g, ' ').trim();
    function rendered(node) {
      if (!node?.isConnected || node.closest('[hidden],[inert],[aria-hidden="true"]')) return false;
      for (let n=node; n && n !== document; n=n.parentElement) {
        const s=window.getComputedStyle(n);
        if (s.display === 'none' || s.visibility === 'hidden') return false;
      }
      return node.getBoundingClientRect().width > 0;
    }
    const imageKey = url => {
      const u=new URL(url), crop=u.pathname.match(/~tplv-[^/]*?-xy:([\d:]+)/)?.[1] || '';
      // Resize/CDN replicas are one image; different long-image crop tiles
      // are different content. Never synthesize an unobserved image URL.
      return u.hostname.replace(/^p\d+(?:-item)?\./,'')+u.pathname.split('~tplv-')[0]+(crop?'#xy:'+crop:'');
    };
    function safeImages(scope) {
      return all(scope, 'img').filter(img => rendered(img) && img.complete && img.naturalWidth > 0
        && (Math.min(img.naturalWidth, img.naturalHeight) >= 100
          || img.naturalHeight>0 && img.naturalWidth>=100 && cropTile(img.currentSrc||img.src))
        && !img.closest('[data-role="product-reviews"],[class*="avatar" i],[data-role="checkout"],.FDag2E0P,.PEzhiR4O'));
    }
    function guard() {
      if (cancelled) throw new Error('user_stopped');
      if (roomUrl() !== job.room_url) throw new Error('page_changed');
      if (document.visibilityState === 'hidden') throw new Error('page_hidden');
      if (now() - job.started_at_epoch_ms > (job.sku_mode==='all_visible'?180000:90000)) throw new Error('time_limit');
      // Only examine visible small challenge controls, never account/payment text.
      if (all(document, '[role="dialog"],button').some(n => rendered(n) && /^(?:请完成验证|请先登录|请完成安全验证|拖动滑块完成验证)$/.test(text(n)))) throw new Error('access_confirmation');
    }
    function emit(patch) { Object.assign(job, patch); }
    function scrollBox(node, accepts = () => true) {
      const candidates = [node, ...all(node, 'div,section,article')];
      for (let p=node.parentElement, depth=0; p && p!==document.body && depth<4; p=p.parentElement, depth++) candidates.push(p);
      return candidates.filter(n => accepts(n) && rendered(n) && n.clientHeight >= 100 && n.scrollHeight > n.clientHeight+4
        && /auto|scroll/.test(window.getComputedStyle(n).overflowY))
        .sort((a,b) => a.getBoundingClientRect().width - b.getBoundingClientRect().width)[0] || null;
    }
    const bottom = box => box.scrollTop + box.clientHeight >= box.scrollHeight - 3;
    function loading(scope) {
      return all(scope, '[aria-busy="true"],[role="progressbar"],[data-role="loading"]')
        .some(rendered) || all(scope,'span,p').some(n => rendered(n) && /^(?:加载中[.。…]*|正在加载[.。…]*|点击加载更多|加载更多)$/.test(text(n)));
    }
    function status() {
      if (!job) return {state:'idle'};
      return JSON.parse(JSON.stringify(job));
    }
    function stop() { cancelled = true; return status(); }
    async function product(expected) {
      const selected = reader.previewCurrent();
      if (!selected || selected.status!=='recognized' || selected.panel_key !== expected.panel_key || selected.snapshot.product_title !== expected.snapshot.product_title
        || expected.snapshot.product_identity && !globalThis.BrandbaiProductIdentity.same(expected.snapshot.product_identity,selected.snapshot.product_identity))
        throw new Error('product_changed');
      const found = inspector.inspect(), panel = found.panel;
      if (found.status !== 'recognized' || !panel) throw new Error('product_unavailable');
      const base = structuredClone(selected.snapshot), images = new Map();
      const coverage = {mode:'single_product_full', main_expected:null, main_observed:0, detail_observed:0,
        main_media_expected:null, main_video_observed:0, main_video_downloaded:false,
        main_complete:false, detail_complete:false, detail_end_evidence:'not_reached', stop_reason:null,
        fields_observed_at_epoch_ms:selected.observed_at_epoch_ms};
      const title = base.product_title, shop = base.shop_name;
      const readGroups = () => inspector.liveSkuGroups?.(panel) || inspector.localSkuGroups(panel) || [];
      const selectedGroups = () => readGroups().map(g=>[g.name,g.options.filter(o=>inspector.optionSelected(o.node)).map(o=>o.value)]);
      let groups = JSON.stringify(selectedGroups());
      const initialGroups=selectedGroups();
      const skuScopes = readGroups().map(g=>g.scope).filter(Boolean);
      const initialParameterGroup=inspector.parameterGroup?.(panel);
      const parameterInventory=initialParameterGroup?.options.map(o=>o.value)||[];
      const parameterSelection=g=>g?.options.filter(o=>inspector.parameterSelected(o.node)).map(o=>o.value)||[];
      let parameterChoice=parameterSelection(initialParameterGroup);
      const parameterMaterials=initialParameterGroup ? {source:'product_parameter_tabs',status:'partial_visible_options',
        option_count:parameterInventory.length,initial_selection:parameterChoice.length===1?parameterChoice[0]:null,
        selection_restored:true,variants:[],stop_reason:null}:null;
      let switchedParameter=false;
      let manualSkuChanged=false;
      const onUserSku=event=>{
        if(event.isTrusted && (readGroups().some(g=>g.options.some(o=>o.node.contains(event.target)))
          || initialParameterGroup?.scope.contains(event.target))) manualSkuChanged=true;
      };
      document.addEventListener('click',onUserSku,true);
      function sameIdentity() {
        if(manualSkuChanged) throw new Error('specification_changed');
        const current = inspector.inspect();
        if (!panel.isConnected || current.status !== 'recognized' || current.panel !== panel) throw new Error('product_changed');
        if(base.product_identity && !globalThis.BrandbaiProductIdentity.same(base.product_identity,reader.identityCurrent()?.product_identity))throw new Error('product_changed');
        const header=inspector.header(panel);
        if (header.title !== title || (shop && header.shopName && header.shopName !== shop)) throw new Error('product_changed');
      }
      function sameProduct() {
        guard(); sameIdentity();
        const currentGroups=selectedGroups();
        if (JSON.stringify(currentGroups) !== groups) throw new Error('specification_changed');
        if(initialParameterGroup && JSON.stringify(parameterSelection(inspector.parameterGroup(panel)))!==JSON.stringify(parameterChoice))
          throw new Error('specification_changed');
      }
      const tabs=all(panel,'span,div,button').filter(n=>rendered(n) && text(n)==='商品详情'
        && !Array.from(n.children).some(c=>text(c)==='商品详情'));
      const tab=tabs[0];
      const galleries=all(panel,'.swiper-container,.swiper,[data-role="product-main-gallery"],[data-e2e="product-main-gallery"]')
        .filter(n=>rendered(n) && (!tab || (n.compareDocumentPosition(tab)&4)) && !n.contains(tab));
      const uniqueGallery=galleries.filter(n=>!galleries.some(other=>other!==n && n.contains(other)));
      const gallery=uniqueGallery.length===1 ? uniqueGallery[0] : null;
      const optionMedia=()=>new Set(readGroups().flatMap(g=>g.options.flatMap(o=>all(o.node,'img')
        .map(i=>publicUrl(i.currentSrc||i.src,'image')).filter(Boolean).map(imageKey))));
      const skuImageKeys=optionMedia();
      const counterLeaves=node=>all(node,'span,div').filter(n=>rendered(n) && /^\d+\s*\/\s*\d+$/.test(text(n))
        && !all(n,'span,div').some(c=>/^\d+\s*\/\s*\d+$/.test(text(c))));
      function galleryShell() {
        if(!gallery)return null;
        const known=gallery.closest('.qVqbID8l,[data-role="product-gallery-shell"]');
        if(known&&panel.contains(known)&&!known.contains(tab))return known;
        const bounds=gallery.getBoundingClientRect();
        for(let n=gallery,depth=0;n&&n!==panel&&depth<5;n=n.parentElement,depth++){
          if(n.contains(tab)||skuScopes.some(s=>n.contains(s)))break;
          const others=all(n,'.swiper-container,.swiper,[data-role="product-main-gallery"]').filter(g=>g!==gallery&&!g.contains(gallery)&&!gallery.contains(g)&&rendered(g));
          if(others.length)break;
          if(counterLeaves(n).some(c=>{const r=c.getBoundingClientRect();return r.left>=bounds.left-24&&r.right<=bounds.right+24
            &&r.top>=bounds.top-24&&r.bottom<=bounds.bottom+48;}))return n;
        }
        return gallery;
      }
      const galleryControls=galleryShell();
      const detailRoots=all(panel,'[data-role="product-detail-content"],[data-e2e="product-detail-content"]')
        .filter(rendered);
      const detailScope=detailRoots.length===1 ? detailRoots[0] : panel;
      const endHeading=()=>all(detailScope,'div,span,p').find(n=>rendered(n) && text(n)==='价格说明'
        && !all(n,'div,span,p').some(c=>text(c)==='价格说明') && tab && Boolean(tab.compareDocumentPosition(n)&4));
      let detailEnd=endHeading();
      const isDetail=img => !gallery?.contains(img) && !skuScopes.some(s=>s.contains(img))
        && !img.closest('[data-role="product-reviews"],[data-role="checkout"],.FDag2E0P,.PEzhiR4O,[role="radio"],[data-sku-id]')
        && (detailRoots.length===1 ? detailScope.contains(img) : tab && Boolean(tab.compareDocumentPosition(img)&4))
        && (!detailEnd || Boolean(img.compareDocumentPosition(detailEnd)&4));
      const videoSlide = slide => Boolean(slide && all(slide,'video,.CcoHiZjd,[data-role="product-video"]').length);
      const rawCounter = () => {
        if (!gallery) return null;
        const slides=all(gallery,'.swiper-slide:not(.swiper-slide-duplicate)');
        const indexes=slides.map(n=>n.getAttribute('data-swiper-slide-index'));
        // A mixed live carousel contains common gallery + SKU thumbnails.
        // DOM slide indices establish the full set, unlike the SKU-only 1/4 badge.
        if (skuImageKeys.size && slides.length && indexes.every((v,i)=>v===String(i))
          && slides.every(n=>safeImages(n).filter(i=>publicUrl(i.currentSrc||i.src,'image')).length===1)) {
          if(slides.some(videoSlide))return slides.length;
          const main=slides.filter(n=>{const u=publicUrl(n.querySelector('img').currentSrc||n.querySelector('img').src,'image');return u&&!skuImageKeys.has(imageKey(u));});
          if (main.length) return main.length;
        }
        const values=counterLeaves(galleryControls).map(n=>Number(text(n).split('/')[1]));
        const explicit=Number(gallery.getAttribute('data-total'));
        if (explicit>0) values.push(explicit);
        const unique=[...new Set(values.filter(n=>n>0 && n<=200))];
        return unique.length===1 ? unique[0] : null;
      };
      function galleryLayout() {
        const total=rawCounter(), slides=all(gallery,'.swiper-slide:not(.swiper-slide-duplicate)');
        const indexes=slides.map(n=>n.getAttribute('data-swiper-slide-index'));
        const indexed=slides.length>0 && indexes.every((v,i)=>v===String(i));
        const videos=indexed ? slides.filter(videoSlide).length : all(gallery,'video').length;
        const keys=[], order=new Map();
        let loaded=indexed && total===slides.length;
        for(const slide of slides) {
          if(videoSlide(slide)) continue;
          const observed=safeImages(slide).map(i=>publicUrl(i.currentSrc||i.src,'image')).filter(Boolean).map(imageKey);
          const urls=observed.filter(k=>!skuImageKeys.has(k));
          if(!observed.length) loaded=false;
          for(const key of urls) {if(!order.has(key))order.set(key,order.size);keys.push(key);}
        }
        // Media slots, distinct still images and videos are separate units.
        // Subtract video slots only when the complete public slide set agrees
        // with its counter; an incomplete/lazy set cannot prove completeness.
        return {total,videos,order,expected:loaded ? new Set(keys).size || null : videos ? null : total,
          confirmed:loaded};
      }
      const cursor=()=>all(gallery,'.swiper-slide-active')[0]?.getAttribute('data-swiper-slide-index')
        ?? counterLeaves(galleryControls).map(text).join('|');
      const counter=()=>galleryLayout().expected;
      let mainOrder=new Map();
      function gather() {
        sameProduct();
        detailEnd=endHeading();
        for (const img of safeImages(panel)) {
          const url=publicUrl(img.currentSrc || img.src,'image');
          if (!url) continue;
          if(gallery?.contains(img) && videoSlide(img.closest('.swiper-slide'))) continue;
          const kind=gallery?.contains(img) ? skuImageKeys.has(imageKey(url)) ? 'product_sku' : 'product_main' : isDetail(img) ? 'product_detail' : null;
          if (!kind) continue;
          const key=kind+':'+imageKey(url), area=img.naturalWidth*img.naturalHeight;
          const previous=images.get(key);
          if (!previous || area>previous.area) images.set(key,{url,kind,area});
          if (images.size>200) { images.delete(key); throw new Error('image_limit'); }
        }
        const layout=galleryLayout();mainOrder=layout.order;
        coverage.main_expected=layout.expected;
        coverage.main_media_expected=layout.total;
        coverage.main_video_observed=layout.videos;
        coverage.main_observed=[...images.values()].filter(i=>i.kind==='product_main').length;
        coverage.detail_observed=[...images.values()].filter(i=>i.kind==='product_detail').length;
        coverage.main_complete=coverage.main_expected !== null && coverage.main_observed===coverage.main_expected
          && (!layout.videos || layout.confirmed);
        emit({main_observed:coverage.main_observed, main_expected:coverage.main_expected, detail_observed:coverage.detail_observed});
      }
      const box=scrollBox(detailScope, n=>!skuScopes.some(s=>s===n || s.contains(n))
        && (n.contains(detailScope) || detailScope.contains(n) && all(n,'img').some(isDetail))), originalTop=box?.scrollTop;
      const skuMaterials={mode:'all_visible',status:'not_observed',initial_selection:initialGroups.filter(([,values])=>values.length===1).flatMap(([name,values])=>values.map(value=>({name,value}))),
        selection_restored:true,variants:[],stop_reason:null};
      let switchedSku=false, skuMainComplete=true;
      const skuInventory=JSON.stringify(readGroups().map(g=>[g.name,g.options.map(o=>o.value)]));
      const choice=()=>selectedGroups().flatMap(([name,values])=>values.map(value=>({name,value})));
      const selectionKey=selection=>JSON.stringify(selection.map(x=>[x.name,x.value]));
      async function choose(selection, restoring=false) {
        for(const target of selection) {
          if(roomUrl()!==job.room_url || document.visibilityState==='hidden') return false;
          if(!restoring) guard(); sameIdentity();
          const g=readGroups().find(g=>g.name===target.name), option=g?.options.find(o=>o.value===target.value);
          if(!option || inspector.optionDisabled(option.node)) return false;
          if(!inspector.optionSelected(option.node)) { option.node.click(); switchedSku=true; }
          let confirmed=false;
          for(let i=0;i<10;i++) {
            await sleep(200); sameIdentity(); if(!restoring) guard();
            const current=readGroups().find(g=>g.name===target.name)?.options;
            if(current?.filter(o=>inspector.optionSelected(o.node)).length===1
              && current.some(o=>o.value===target.value && inspector.optionSelected(o.node))) {confirmed=true;break;}
          }
          if(!confirmed) return false;
        }
        groups=JSON.stringify(selectedGroups());
        return selectionKey(choice())===selectionKey(selection);
      }
      async function collectSkus() {
        const inventory=readGroups();
        if(!inventory.length) {skuMaterials.stop_reason='sku_not_observed';return;}
        skuMaterials.status='partial_all_visible_skus';
        if(initialGroups.some(([,v])=>v.length!==1)) {skuMaterials.stop_reason='selection_unconfirmed';return;}
        // Only combinations of public, rendered options. Recheck enabled
        // states after each preceding group; never visit a buy/order control.
        let combinations=[[]];
        for(const g of inventory) {
          if(combinations.length*g.options.length>40) {skuMaterials.stop_reason='sku_limit';return;}
          combinations=combinations.flatMap(c=>g.options.map(o=>[...c,{name:g.name,value:o.value}]));
        }
        emit({phase:'sku_images',sku_total:combinations.length,sku_done:0});
        for(const selection of combinations) {
          sameProduct();
          if(JSON.stringify(readGroups().map(g=>[g.name,g.options.map(o=>o.value)]))!==skuInventory){
            skuMaterials.stop_reason='sku_inventory_changed';break;
          }
          const record={selection,state:'failed',reason:null,price_texts:[],image_urls:[],main_expected:null,main_complete:false,observed_at_epoch_ms:now(),sku_id:null,sku_id_source:'not_observed'};
          skuMaterials.variants.push(record);
          const disabled=selection.some(t=>{const o=readGroups().find(g=>g.name===t.name)?.options.find(o=>o.value===t.value);return !o||inspector.optionDisabled(o.node);});
          if(disabled && inventory.length===1) {record.state='unavailable';record.reason='option_disabled';}
          else if(!await choose(selection)) {record.reason='selection_unconfirmed';groups=JSON.stringify(selectedGroups());}
          else {
            // Wait for selection, gallery URLs and public SKU price to agree
            // in two consecutive observations, bounded to four seconds.
            let previous='',stable=0, urls=[],priceTexts=[];
            for(let attempt=0;attempt<12;attempt++) {
              sameProduct();
              const optionKeys=new Set(readGroups().flatMap(g=>g.options.filter(o=>inspector.optionSelected(o.node))
                .flatMap(o=>all(o.node,'img').map(i=>publicUrl(i.currentSrc||i.src,'image')).filter(Boolean).map(imageKey))));
              urls=safeImages(gallery).filter(i=>!videoSlide(i.closest('.swiper-slide'))).map(i=>publicUrl(i.currentSrc||i.src,'image')).filter(Boolean)
                .filter(u=>!skuImageKeys.has(imageKey(u))||optionKeys.has(imageKey(u)));
              urls=[...new Map(urls.map(u=>[imageKey(u),u])).values()];
              priceTexts=inspector.skuPrices(panel);
              const current=JSON.stringify([choice(),urls,priceTexts]);
              stable=current===previous?stable+1:0; previous=current;
              if(stable>=2 && urls.length && !loading(gallery)) break;
              await sleep(300);
            }
            if(stable<2 || !urls.length || loading(gallery)) record.reason='sku_media_unconfirmed';
            else {
              gather();
              const observed=new Map(urls.map(u=>[imageKey(u),u]));
              const targetCount=counter();
              // A SKU can lazy-load a different gallery. Traverse its public
              // next control too, not just the initially selected SKU's gallery.
              for(let turn=0;targetCount && [...observed.keys()].filter(k=>!skuImageKeys.has(k)).length<targetCount && turn<200;turn++) {
                sameProduct();
                const next=all(galleryControls,'.swiper-button-next,[aria-label="Next slide"],[aria-label="下一张"],[data-role="gallery-next"],.ceXWdiFN')
                  .filter(n=>rendered(n)&&!n.matches(':disabled,[aria-disabled="true"],.swiper-button-disabled'));
                if(next.length!==1) break;
                const before=observed.size;next[0].click();await sleep(600);gather();
                const selectedKeys=new Set(readGroups().flatMap(g=>g.options.filter(o=>inspector.optionSelected(o.node)).flatMap(o=>all(o.node,'img')
                  .map(i=>publicUrl(i.currentSrc||i.src,'image')).filter(Boolean).map(imageKey))));
                for(const i of safeImages(gallery).filter(i=>!videoSlide(i.closest('.swiper-slide')))) {
                  const u=publicUrl(i.currentSrc||i.src,'image');
                  if(u&&(!skuImageKeys.has(imageKey(u))||selectedKeys.has(imageKey(u)))) observed.set(imageKey(u),u);
                }
                if(observed.size===before) break;
              }
              urls=[...observed.values()];
              record.image_urls=urls.map(u=>[...images.values()].find(i=>i.kind!=='product_detail'&&imageKey(i.url)===imageKey(u))?.url).filter(Boolean);
              record.price_texts=priceTexts;record.observed_at_epoch_ms=now();
              record.sku_id=reader.selectedSkuId?.(panel,readGroups().map(g=>({...g,options:g.options.map(o=>({...o,selected:inspector.optionSelected(o.node)}))})))||null;
              record.sku_id_source=record.sku_id?'visible_dom_attribute':'not_observed';
              const common=urls.filter(u=>!skuImageKeys.has(imageKey(u)));
              record.main_expected=targetCount;
              record.main_complete=Boolean(targetCount && common.length===targetCount);
              record.state='observed';
              if(!record.main_complete) record.reason='sku_media_unconfirmed';
              else if(!priceTexts.length) record.reason='sku_price_unconfirmed';
              skuMainComplete &&= record.main_complete;
            }
          }
          emit({phase:'sku_images',sku_done:skuMaterials.variants.length,sku_total:combinations.length});
        }
        if(JSON.stringify(readGroups().map(g=>[g.name,g.options.map(o=>o.value)]))!==skuInventory)
          skuMaterials.stop_reason='sku_inventory_changed';
      }
      function currentParameters() {
        const current=inspector.parameterGroup?.(panel);
        return current?.scope===initialParameterGroup?.scope ? current : null;
      }
      async function chooseParameter(label,restoring=false) {
        sameIdentity();if(!restoring)guard();
        if(document.visibilityState==='hidden'||roomUrl()!==job.room_url)return false;
        const group=currentParameters(), option=group?.options.find(o=>o.value===label);
        if(!option||inspector.optionDisabled(option.node))return false;
        if(!inspector.parameterSelected(option.node)){option.node.click();switchedParameter=true;}
        for(let attempt=0;attempt<10;attempt++){
          await sleep(200);sameIdentity();if(!restoring)guard();
          const chosen=parameterSelection(currentParameters());
          if(chosen.length===1&&chosen[0]===label){parameterChoice=chosen;return true;}
        }
        parameterChoice=parameterSelection(currentParameters());return false;
      }
      async function collectParameters() {
        if(!parameterMaterials)return;
        emit({phase:'parameter_options',parameter_done:0,parameter_total:parameterInventory.length});
        if(!parameterMaterials.initial_selection){parameterMaterials.stop_reason='selection_unconfirmed';return;}
        if(parameterInventory.length>40){parameterMaterials.stop_reason='option_limit';return;}
        const targets=[parameterMaterials.initial_selection,...parameterInventory.filter(v=>v!==parameterMaterials.initial_selection)];
        for(const label of targets){
          sameProduct();
          if(JSON.stringify(currentParameters()?.options.map(o=>o.value))!==JSON.stringify(parameterInventory)){
            parameterMaterials.stop_reason='options_changed';break;
          }
          const previousChoice=parameterSelection(currentParameters())[0];
          const before=JSON.stringify(inspector.parameterContent(currentParameters()));
          const record={label,state:'failed',reason:'selection_unconfirmed',components:[],observed_at_epoch_ms:now()};
          parameterMaterials.variants.push(record);
          const option=currentParameters().options.find(o=>o.value===label);
          if(inspector.optionDisabled(option.node)){record.state='unavailable';record.reason='option_disabled';}
          else if(await chooseParameter(label)){
            let previous='',stable=0,content=null;
            for(let attempt=0;attempt<16;attempt++){
              sameProduct();content=inspector.parameterContent(currentParameters());
              const signature=JSON.stringify(content);
              stable=signature===previous?stable+1:0;previous=signature;
              if(content&&stable>=2&&!loading(currentParameters()?.content)
                && (previousChoice===label||signature!==before))break;
              content=null;await sleep(250);
            }
            record.reason='content_unconfirmed';
            if(content){record.state='observed';record.reason=null;record.components=content;record.observed_at_epoch_ms=now();}
          }
          if(JSON.stringify(parameterMaterials).length>80000){
            record.state='failed';record.reason='content_limit';record.components=[];parameterMaterials.stop_reason='bytes_limit';break;
          }
          emit({phase:'parameter_options',parameter_done:parameterMaterials.variants.filter(v=>v.state==='observed').length,parameter_total:parameterInventory.length});
        }
        if(JSON.stringify(currentParameters()?.options.map(o=>o.value))!==JSON.stringify(parameterInventory))parameterMaterials.stop_reason='options_changed';
      }
      try {
        emit({phase:'main_images'}); gather();
        const stalledPositions=new Set();
        for(let turn=0; gallery && !coverage.main_complete && turn<200; turn++) {
          sameProduct();
          const next=all(galleryControls,'.swiper-button-next,[aria-label="Next slide"],[aria-label="下一张"],[data-role="gallery-next"],.ceXWdiFN')
            .filter(n=>rendered(n) && !n.matches(':disabled,[aria-disabled="true"],.swiper-button-disabled'));
          if(next.length!==1) break;
          const before=coverage.main_observed;
          const beforePosition=cursor();
          next[0].click(); await sleep(600); gather();
          if (before===coverage.main_observed) { await sleep(800); gather();
            if(before===coverage.main_observed) {
              const afterPosition=cursor();
              if(!beforePosition || afterPosition===beforePosition || stalledPositions.has(afterPosition)) break;
              stalledPositions.add(beforePosition);
            } else stalledPositions.clear();
          } else stalledPositions.clear();
        }
        emit({phase:'detail_images'});
        if (box) { sameProduct(); box.scrollTop=0; await sleep(450); }
        let confirmedHeight=null, stagnant=0, lastSignature='';
        for(let step=0; step<180; step++) {
          gather();
          const marker=all(detailScope,'[data-role="product-detail-end"],span,p').some(n=>rendered(n)
            && (n.matches('[data-role="product-detail-end"]') || /^(?:已经到底了|没有更多了|商品详情结束|到底啦)[！!。]?$/.test(text(n))));
          const bounds=detailScope.getBoundingClientRect();
          const tail=endHeading(), tailRect=tail?.getBoundingClientRect(), boxRect=box?.getBoundingClientRect();
          const semanticEnd=tailRect && tailRect.top < (boxRect?.bottom || window.innerHeight) && tailRect.bottom>0;
          const boundary=semanticEnd || (box ? bottom(box) : bounds.top>=0 && bounds.bottom<=window.innerHeight
            && detailScope.scrollHeight<=detailScope.clientHeight+3);
          if(boundary) {
            const height=box?.scrollHeight || detailScope.scrollHeight;
            await sleep(800); gather();
            const allLoaded=all(detailScope,'img').filter(n=>rendered(n) && isDetail(n)
              && publicUrl(n.currentSrc||n.src,'image') && (n.getBoundingClientRect().width>=100 || n.naturalWidth>=100))
              .every(n=>n.complete && n.naturalWidth>0);
            if ((semanticEnd || !box || bottom(box)) && height===(box?.scrollHeight||detailScope.scrollHeight)
              && !loading(detailScope) && allLoaded
              && completeCropTiles([...images.values()].filter(i=>i.kind==='product_detail').map(i=>i.url))
              && (coverage.detail_observed>0 || marker)) {
              if (marker || confirmedHeight===height) {
                coverage.detail_complete=true;
                coverage.detail_end_evidence=marker || semanticEnd ? 'explicit_end' : 'stable_scroll_boundary'; break;
              }
              confirmedHeight=height;
            } else confirmedHeight=null;
          }
          const sig=[coverage.detail_observed,box?.scrollTop,box?.scrollHeight].join(':');
          stagnant=sig===lastSignature ? stagnant+1 : 0; lastSignature=sig;
          emit({no_change_steps:stagnant,elapsed_seconds:Math.floor((now()-job.started_at_epoch_ms)/1000)});
          if(stagnant>=6) {coverage.stop_reason='detail_stalled';break;}
          if(!box && !boundary) break;
          if(box && !bottom(box)) { sameProduct(); box.scrollTop+=Math.max(100,Math.floor(box.clientHeight*0.7)); }
          await sleep(450);
          if(!box && !coverage.detail_observed && step>2) break;
        }
        if(job.sku_mode==='all_visible' && !['time_limit','user_stopped','page_hidden'].includes(coverage.stop_reason)) {
          if(box) {box.scrollTop=0;await sleep(150);}
          await collectParameters();
          await collectSkus();
        }
      } catch(error) {
        coverage.stop_reason=error.message;
        if (['product_changed','specification_changed','page_changed','access_confirmation'].includes(error.message)) {
          // Never export a mixed snapshot after identity/access changes.
          throw error;
        }
      } finally {
        if(switchedParameter){
          parameterMaterials.selection_restored=false;
          if(panel.isConnected&&roomUrl()===job.room_url&&!['product_changed','specification_changed','access_confirmation'].includes(coverage.stop_reason)){
            try{
              const selected=await chooseParameter(parameterMaterials.initial_selection,true);
              const original=parameterMaterials.variants.find(v=>v.label===parameterMaterials.initial_selection&&v.state==='observed');
              if(selected)for(let i=0;i<16;i++){
                sameIdentity();
                if(!loading(currentParameters()?.content)&&(!original||JSON.stringify(inspector.parameterContent(currentParameters()))===JSON.stringify(original.components))){parameterMaterials.selection_restored=true;break;}
                await sleep(250);
              }
            }catch(_){}
          }
        }
        if(job.sku_mode==='all_visible' && switchedSku) {
          skuMaterials.selection_restored=false;
          // Do not overwrite a manual product/room/specification change.
          if(panel.isConnected && roomUrl()===job.room_url && !['product_changed','specification_changed','access_confirmation'].includes(coverage.stop_reason)) {
            try {skuMaterials.selection_restored=await choose(skuMaterials.initial_selection,true);} catch(_) {}
          }
        }
        if(box && panel.isConnected && roomUrl()===job.room_url && !['product_changed','specification_changed'].includes(coverage.stop_reason)) box.scrollTop=originalTop;
        document.removeEventListener('click',onUserSku,true);
      }
      if(parameterMaterials){
        if(!parameterMaterials.selection_restored)parameterMaterials.stop_reason='restore_unconfirmed';
        const complete=parameterMaterials.variants.length===parameterMaterials.option_count
          &&parameterMaterials.variants.some(v=>v.state==='observed')&&parameterMaterials.variants.every(v=>v.state!=='failed');
        if(complete&&parameterMaterials.selection_restored&&!parameterMaterials.stop_reason&&!coverage.stop_reason)parameterMaterials.status='complete_visible_options';
        else parameterMaterials.stop_reason ||= coverage.stop_reason||'content_unconfirmed';
      }
      if(job.sku_mode==='all_visible') {
        if(skuMaterials.variants.length && skuMaterials.variants.every(v=>v.state==='unavailable'||v.state==='observed'&&!v.reason)
          && skuMaterials.variants.some(v=>v.state==='observed') && skuMaterials.selection_restored && !coverage.stop_reason && !skuMaterials.stop_reason) skuMaterials.status='complete_all_visible_skus';
        else if(skuMaterials.variants.length) {skuMaterials.status='partial_all_visible_skus';skuMaterials.stop_reason ||= !skuMaterials.selection_restored?'restore_unconfirmed':coverage.stop_reason||'sku_coverage_unconfirmed';}
        if(skuMainComplete && skuMaterials.variants.some(v=>v.state==='observed')) {
          coverage.main_expected=coverage.main_observed=[...images.values()].filter(i=>i.kind==='product_main').length;
          // Aggregate SKU image coverage is not one carousel's slot count.
          coverage.main_media_expected=null;
          coverage.main_complete=coverage.main_expected>0;
        }
      }
      if(!coverage.main_complete || !coverage.detail_complete) coverage.stop_reason ||= 'coverage_unconfirmed';
      const mainImages=[...images.values()].filter(i=>i.kind==='product_main').sort((a,b)=>
        (mainOrder.get(imageKey(a.url))??200)-(mainOrder.get(imageKey(b.url))??200));
      let mainIndex=0;
      const ordered=[...images.values()].map(i=>i.kind==='product_main'?mainImages[mainIndex++]:i);
      const snapshot={...base, images:ordered.map(({url,kind})=>({url,kind})), image_coverage:coverage,
        ...(job.sku_mode==='all_visible'?{sku_materials:skuMaterials,...(parameterMaterials?{parameter_materials:parameterMaterials}:{})}:{})};
      return {snapshot, observed_at_epoch_ms:now(), complete:coverage.main_complete && coverage.detail_complete && !coverage.stop_reason
        && (job.sku_mode!=='all_visible'||skuMaterials.status==='complete_all_visible_skus')
        && (!parameterMaterials||parameterMaterials.status==='complete_visible_options')};
    }
    async function catalog(resume) {
      if (inspector.inspect().status !== 'none') throw new Error('close_product_detail');
      let surface=reader.catalogSurface();
      if(!surface) {
        emit({phase:'opening_catalog'});
        const isEntry = n => /^(?:🛒\s*)?全部商品(?:\s*[›>❯])?$/.test(text(n));
        const entries=all(document,'button,[role="button"],div,a,span').filter(n=>{
          const rect=n.getBoundingClientRect();
          return rendered(n) && isEntry(n) && rect.bottom>0 && rect.top<window.innerHeight
            && rect.right>0 && rect.left<window.innerWidth
            && !all(n,'button,[role="button"],div,a,span').some(child=>rendered(child) && isEntry(child));
        });
        if(!entries.length) throw new Error('catalog_entry_unavailable');
        if(entries.length!==1) throw new Error('catalog_entry_ambiguous');
        guard(); entries[0].click();
        // Click once only. Wait for the actual list, not a fixed short delay.
        for(let attempt=0; attempt<20 && !surface; attempt++) {
          guard();
          if(inspector.inspect().status!=='none') throw new Error('close_product_detail');
          surface=reader.catalogSurface();
          if(!surface) await sleep(250);
        }
        guard(); surface ||= reader.catalogSurface();
      }
      if(!surface) throw new Error('catalog_open_failed');
      const scope=surface.scope, box=scrollBox(scope);
      const prior=resume && savedCatalog?.scope===scope && savedCatalog.room_url===job.room_url ? savedCatalog : null;
      if(resume && !prior) throw new Error('catalog_resume_changed');
      const rows=prior ? structuredClone(prior.rows) : [], seen=new Set(rows.map(r=>JSON.stringify([r.list_position,r.product_url,r.product_title,r.display_price,r.explaining,r.thumbnail])));
      const startCount=rows.length;
      const pending=[];
      let complete=false, reason=null, confirmedHeight=null, unreadable=false;
      if(box && !prior) box.scrollTop=0;
      try {
        for(let step=0; step<180; step++) {
          guard();
          if(!scope.isConnected || !rendered(scope) || inspector.inspect().status !== 'none') throw new Error('catalog_changed');
          let next=reader.catalogSurface(scope);
          if(!next || next.scope!==scope) throw new Error('catalog_changed');
          if(next.unreadable_count) {
            await sleep(800); guard(); next=reader.catalogSurface(scope);
            if(!next || next.scope!==scope) throw new Error('catalog_changed');
            unreadable ||= next.unreadable_count>0;
          }
          for(const {element,data} of next.rows) {
            const key=JSON.stringify([data.list_position,data.product_url,data.product_title,data.display_price,data.explaining,data.thumbnail]);
            if(seen.has(key)) continue;
            if(rows.length-startCount>=100 || rows.length>=1000) { reason='item_limit'; break; }
            if(new TextEncoder().encode(JSON.stringify([...rows,data])).length>800000) { reason='bytes_limit'; break; }
            seen.add(key); rows.push(data);
            if(data.list_position==null && data.explaining===true && pending.length<3)
              pending.push({row:data,element,scrollTop:box?.scrollTop||0,last:null});
          }
          emit({phase:'catalog', item_count:rows.length});
          if(reason) break;
          if(!box || bottom(box)) {
            const height=box?.scrollHeight || scope.scrollHeight;
            if(!loading(scope) && height===confirmedHeight) { complete=!unreadable; break; }
            confirmedHeight=height; await sleep(900); continue;
          }
          confirmedHeight=null; box.scrollTop+=Math.max(100,Math.floor(box.clientHeight*0.65)); await sleep(550);
        }
        // A small bounded recheck on this list only; never wait for the host
        // indefinitely, open another product, or invent a confirmed number.
        if(complete && !reason && pending.length) {
          const endPosition=box?.scrollTop||0;
          emit({phase:'verifying_numbers',item_count:rows.length});
          try {
            for(let attempt=0; attempt<12 && pending.some(p=>p.row.list_position==null); attempt++) {
              guard();
              if(!scope.isConnected || !rendered(scope) || inspector.inspect().status!=='none') throw new Error('catalog_changed');
              const target=pending.find(p=>p.row.list_position==null);
              if(box) box.scrollTop=target.scrollTop;
              await sleep(1000); guard();
              const next=reader.catalogSurface(scope);
              if(!next || next.scope!==scope) throw new Error('catalog_changed');
              const found=next.rows.find(r=>r.element===target.element)?.data;
              const old=target.row;
              const same=found && found.product_title===old.product_title && found.product_url===old.product_url
                && found.thumbnail===old.thumbnail && found.product_identity?.product_id===old.product_identity?.product_id;
              const n=same ? found.list_position : null;
              if(n!=null && n===target.last && !rows.some(r=>r!==old && r.list_position===n)) {
                old.list_position=n;
                old.number_verification={method:'same_row_reobserved',initial_position:null,
                  initial_observed_at_epoch_ms:old.observed_at_epoch_ms,confirmed_at_epoch_ms:found.observed_at_epoch_ms};
                if(old.product_identity) old.product_identity={...old.product_identity,catalog_position:n,
                  catalog_observed_at_epoch_ms:found.observed_at_epoch_ms};
              }
              target.last=n;
            }
          } finally {
            if(box && scope.isConnected && roomUrl()===job.room_url && inspector.inspect().status==='none') box.scrollTop=endPosition;
          }
        }
      } catch(error) {
        if(['page_changed','catalog_changed','access_confirmation'].includes(error.message)) throw error;
        reason=error.message; complete=false;
      }
      reason ||= complete ? null : 'end_unconfirmed';
      savedCatalog={scope, room_url:job.room_url, rows};
      return {catalog:{rows, complete, stop_reason:reason}, number_hints:numberHints(rows,complete&&!reason), observed_at_epoch_ms:now(), complete,
        can_continue:!complete && rows.length<1000 && reason!=='bytes_limit'};
    }
    function start({kind, request_id, expected=null, resume=false, sku_mode='current'}) {
      if(job?.state==='collecting' || job?.request_id===request_id) return status();
      if(!['product','catalog'].includes(kind) || !/^[a-f0-9-]{36}$/.test(request_id)) throw new Error('invalid_capture_request');
      cancelled=false;
      job={request_id, kind, sku_mode:kind==='product'&&sku_mode==='all_visible'?'all_visible':'current',room_url:roomUrl(), started_at_epoch_ms:now(), state:'collecting', phase:'preparing'};
      (async()=>{
        try { guard(); const result=await (kind==='product' ? product(expected) : catalog(resume)); emit({state:'ready',result}); }
        catch(error) { emit({state:'failed', reason:error.message}); }
      })();
      return status();
    }
    function acknowledge(request_id) { if(job?.request_id===request_id && job.state!=='collecting') job=null; }
    return {start,status,stop,acknowledge};
  }
  return Object.freeze({create,cropTile,completeCropTiles,numberHints});
});
