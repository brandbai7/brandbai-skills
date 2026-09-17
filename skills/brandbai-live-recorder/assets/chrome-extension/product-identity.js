/* Public DOM identity only. No page state objects, cookies, requests or guessed IDs. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.BrandbaiProductIdentity=api;})(globalThis,()=>{
  'use strict';
  const id=value=>typeof value==='string'&&/^\d{5,30}$/.test(value)?value:null;
  const skip='[hidden],[inert],[aria-hidden="true"],[data-role="product-reviews"],[data-role="checkout"],.FDag2E0P,.PEzhiR4O';
  function same(left,right){
    if(!left||!right||left.shop_id&&right.shop_id&&left.shop_id!==right.shop_id)return false;
    if(left.product_id||right.product_id)return Boolean(left.product_id&&left.product_id===right.product_id);
    return left.identity_status==='panel_bound'&&right.identity_status==='panel_bound'&&left.product_ref===right.product_ref&&left.source_room_url===right.source_room_url;
  }
  function create({document,roomUrl,publicUrl,now=Date.now,newId=()=>crypto.randomUUID()}){
    let current=null;const knownCatalog=new Map();
    const observer=new document.defaultView.MutationObserver(records=>{
      if(!current)return;
      const panel=current.scope;
      if(!panel.isConnected||records.some(r=>r.type==='childList'?[...r.removedNodes].some(n=>n===panel||n.contains?.(panel)):
        (r.target===panel||r.target.contains(panel))&&(r.attributeName!=='style'||/display\s*:\s*none|visibility\s*:\s*hidden/.test(r.oldValue||'')||!rendered(panel))))current=null;
    });
    observer.observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeOldValue:true,attributeFilter:['hidden','inert','aria-hidden','style']});
    function rendered(n){
      if(!n?.isConnected||n.closest(skip))return false;
      for(let p=n;p&&p!==document;p=p.parentElement){const s=document.defaultView.getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden')return false;}
      return n.getBoundingClientRect().width>0;
    }
    function read(scope,{title,shop_name,product_url=null,headerNode=null,shopNode=null,position=null,catalog=false}={}){
      const room=roomUrl();if(!room||!scope||!title)return null;
      // Attribute evidence must belong to the identified product root/header,
      // not a recommendation, buyer review, image filename or checkout field.
      const nodes=[scope,headerNode,...scope.querySelectorAll('[data-role="product-title"],[data-e2e="product-title"],.vs9hmvGz')].filter(rendered);
      const ids=[...new Set(nodes.map(n=>id(n.getAttribute('data-product-id'))).filter(Boolean))];
      const urls=[...new Set([publicUrl(product_url),...[...scope.querySelectorAll('a[href]')].filter(rendered).map(n=>publicUrl(n.href))].filter(Boolean))];
      const linked=[...new Set(urls.map(u=>id(new URL(u).searchParams.get('id'))).filter(Boolean))];
      const candidates=[...new Set([...ids,...linked])];if(candidates.length>1)return null;
      const shops=[...new Set([scope,shopNode,...scope.querySelectorAll('[data-role="shop-name"],[data-e2e="shop-name"],.AjnzIIcY')].filter(rendered).map(n=>id(n.getAttribute('data-shop-id'))).filter(Boolean))];
      if(shops.length>1)return null;
      const productId=candidates[0]||null,shopId=shops[0]||null;
      const signature=JSON.stringify([room,title,shop_name,productId,shopId]);
      if(!catalog&&(!current||current.scope!==scope||current.signature!==signature)) current={scope,signature,ref:'douyin:observation:'+newId(),at:now()};
      const at=catalog?now():current.at,entry=productId?knownCatalog.get(room+'|'+productId):null;
      const record={platform:'douyin',product_id:productId,product_url:urls[0]||null,shop_id:shopId,shop_name:shop_name||null,
        product_ref:productId?'douyin:product:'+productId:catalog?'douyin:observation:'+newId():current.ref,
        identity_status:productId?'verified':catalog?'unconfirmed':'panel_bound',
        product_id_source:productId?(linked.length?'public_product_link':'visible_dom_attribute'):'not_observed',shop_id_source:shopId?'visible_dom_attribute':'not_observed',
        source_room_id:room.split('/').pop(),source_room_url:room,
        catalog_position:catalog?position:entry?.position||null,catalog_observed_at_epoch_ms:catalog&&position?at:entry?.at||null,observed_at_epoch_ms:at};
      if(catalog&&productId&&position){knownCatalog.set(room+'|'+productId,{position,at});if(knownCatalog.size>1000)knownCatalog.delete(knownCatalog.keys().next().value);}
      return record;
    }
    function clear(){current=null;}
    function selectedSkuId(panel,groups){
      const direct=id(panel.getAttribute('data-selected-sku-id'));
      const options=groups.flatMap(g=>g.options.filter(o=>o.selected).map(o=>o.node));
      const selected=groups.length===1&&options.length===1?id(options[0].getAttribute('data-sku-id')):null;
      return direct&&selected&&direct!==selected?null:direct||selected;
    }
    return {read,clear,selectedSkuId};
  }
  return {create,same,id};
});
