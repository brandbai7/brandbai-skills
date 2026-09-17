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
        main_complete:false, detail_complete:false, detail_end_evidence:'not_reached', stop_reason:null,
        fields_observed_at_epoch_ms:selected.observed_at_epoch_ms};
      const title = base.product_title, shop = base.shop_name;
      const readGroups = () => inspector.liveSkuGroups?.(panel) || inspector.localSkuGroups(panel) || [];
      const selectedGroups = () => readGroups().map(g=>[g.name,g.options.filter(o=>inspector.optionSelected(o.node)).map(o=>o.value)]);
      let groups = JSON.stringify(selectedGroups());
      const initialGroups=selectedGroups();
      const skuScopes = readGroups().map(g=>g.scope).filter(Boolean);
      let manualSkuChanged=false;
      const onUserSku=event=>{
        if(event.isTrusted && readGroups().some(g=>g.options.some(o=>o.node.contains(event.target)))) manualSkuChanged=true;
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
      const counter = () => {
        if (!gallery) return null;
        const slides=all(gallery,'.swiper-slide:not(.swiper-slide-duplicate)');
        const indexes=slides.map(n=>n.getAttribute('data-swiper-slide-index'));
        // A mixed live carousel contains common gallery + SKU thumbnails.
        // DOM slide indices establish the full set, unlike the SKU-only 1/4 badge.
        if (skuImageKeys.size && slides.length && indexes.every((v,i)=>v===String(i))
          && slides.every(n=>all(n,'img').length===1) && !all(gallery,'video').length) {
          const main=slides.filter(n=>{const u=publicUrl(n.querySelector('img').currentSrc||n.querySelector('img').src,'image');return u&&!skuImageKeys.has(imageKey(u));});
          if (main.length) return main.length;
        }
        const values=counterLeaves(galleryControls).map(n=>Number(text(n).split('/')[1]));
        const explicit=Number(gallery.getAttribute('data-total'));
        if (explicit>0) values.push(explicit);
        const unique=[...new Set(values.filter(n=>n>0 && n<=200))];
        return unique.length===1 ? unique[0] : null;
      };
      function gather() {
        sameProduct();
        detailEnd=endHeading();
        for (const img of safeImages(panel)) {
          const url=publicUrl(img.currentSrc || img.src,'image');
          if (!url) continue;
          const kind=gallery?.contains(img) ? skuImageKeys.has(imageKey(url)) ? 'product_sku' : 'product_main' : isDetail(img) ? 'product_detail' : null;
          if (!kind) continue;
          const key=kind+':'+imageKey(url), area=img.naturalWidth*img.naturalHeight;
          const previous=images.get(key);
          if (!previous || area>previous.area) images.set(key,{url,kind,area});
          if (images.size>200) { images.delete(key); throw new Error('image_limit'); }
        }
        coverage.main_expected=counter();
        coverage.main_observed=[...images.values()].filter(i=>i.kind==='product_main').length;
        coverage.detail_observed=[...images.values()].filter(i=>i.kind==='product_detail').length;
        coverage.main_complete=coverage.main_expected !== null && coverage.main_observed===coverage.main_expected
          && !all(gallery,'video').length;
        emit({main_observed:coverage.main_observed, main_expected:coverage.main_expected, detail_observed:coverage.detail_observed});
      }
      const box=scrollBox(detailScope, n=>!skuScopes.some(s=>s===n || s.contains(n))
        && (n.contains(detailScope) || detailScope.contains(n) && all(n,'img').some(isDetail))), originalTop=box?.scrollTop;
      const skuMaterials={mode:'all_visible',status:'not_observed',initial_selection:initialGroups.filter(([,values])=>values.length===1).flatMap(([name,values])=>values.map(value=>({name,value}))),
        selection_restored:true,variants:[],stop_reason:null};
      let switchedSku=false, skuMainComplete=true;
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
              urls=safeImages(gallery).map(i=>publicUrl(i.currentSrc||i.src,'image')).filter(Boolean)
                .filter(u=>!skuImageKeys.has(imageKey(u))||optionKeys.has(imageKey(u)));
              urls=[...new Map(urls.map(u=>[imageKey(u),u])).values()];
              priceTexts=inspector.skuPrices(panel);
              const current=JSON.stringify([choice(),urls,priceTexts]);
              stable=current===previous?stable+1:0; previous=current;
              if(stable>=2 && urls.length) break;
              await sleep(300);
            }
            if(stable<2 || !urls.length) record.reason='sku_media_unconfirmed';
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
                for(const i of safeImages(gallery)) {
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
      }
      try {
        emit({phase:'main_images'}); gather();
        for(let turn=0; gallery && !coverage.main_complete && turn<200; turn++) {
          sameProduct();
          const next=all(galleryControls,'.swiper-button-next,[aria-label="Next slide"],[aria-label="下一张"],[data-role="gallery-next"],.ceXWdiFN')
            .filter(n=>rendered(n) && !n.matches(':disabled,[aria-disabled="true"],.swiper-button-disabled'));
          if(next.length!==1) break;
          const before=coverage.main_observed;
          next[0].click(); await sleep(600); gather();
          if (before===coverage.main_observed) { await sleep(800); gather(); if(before===coverage.main_observed) break; }
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
          await collectSkus();
        }
      } catch(error) {
        coverage.stop_reason=error.message;
        if (['product_changed','specification_changed','page_changed','access_confirmation'].includes(error.message)) {
          // Never export a mixed snapshot after identity/access changes.
          throw error;
        }
      } finally {
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
      if(job.sku_mode==='all_visible') {
        if(skuMaterials.variants.length && skuMaterials.variants.every(v=>v.state==='unavailable'||v.state==='observed'&&!v.reason)
          && skuMaterials.variants.some(v=>v.state==='observed') && skuMaterials.selection_restored && !coverage.stop_reason && !skuMaterials.stop_reason) skuMaterials.status='complete_all_visible_skus';
        else if(skuMaterials.variants.length) {skuMaterials.status='partial_all_visible_skus';skuMaterials.stop_reason ||= !skuMaterials.selection_restored?'restore_unconfirmed':coverage.stop_reason||'sku_coverage_unconfirmed';}
        if(skuMainComplete && skuMaterials.variants.some(v=>v.state==='observed')) {
          coverage.main_expected=coverage.main_observed=[...images.values()].filter(i=>i.kind==='product_main').length;
          coverage.main_complete=coverage.main_expected>0;
        }
      }
      if(!coverage.main_complete || !coverage.detail_complete) coverage.stop_reason ||= 'coverage_unconfirmed';
      const snapshot={...base, images:[...images.values()].map(({url,kind})=>({url,kind})), image_coverage:coverage,
        ...(job.sku_mode==='all_visible'?{sku_materials:skuMaterials}:{})};
      return {snapshot, observed_at_epoch_ms:now(), complete:coverage.main_complete && coverage.detail_complete && !coverage.stop_reason
        && (job.sku_mode!=='all_visible'||skuMaterials.status==='complete_all_visible_skus')};
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
