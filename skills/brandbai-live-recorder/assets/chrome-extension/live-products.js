(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.BrandbaiLiveProducts = api;
})(globalThis, function () {
  "use strict";
  // Adapted from the download extension's visible commerce inspector. No
  // hidden IDs, requests, automatic clicks, SKU traversal or media downloads.
  const PRIVATE = /(?:收货|配送至|送至|收件|联系人|订单|手机|电话|地址|Cookie|Bearer|token|signature|[\w.+-]+@[\w.-]+\.[a-z]{2,}|1[3-9]\d{9})/i;
  const text = (value, max = 300) => {
    const result = String(value || "").replace(/\s+/g, " ").trim();
    return !result || result.length > max || PRIVATE.test(result) || /https?:\/\/|[\x00-\x1f]/i.test(result) ? null : result;
  };
  function publicUrl(value, kind = "product") {
    try {
      const u = new URL(value);
      if (u.protocol !== "https:" || u.username || u.password || u.port || u.href.length > 2048) return null;
      if (kind === "image") {
        if (!/(^|\.)(?:ecombdimg\.com|detailpage\.byteimg\.com|douyinpic\.com)$/.test(u.hostname)
          || /avatar|qrcode|qr[-_]?code|girdle|second_page|priority|\/common\/|shop_|\/eden-cn\/|aweme_flagship/i.test(u.pathname)) return null;
        return u.origin + u.pathname;
      }
      if (!["haohuo.jinritemai.com", "e.ghaohuo.com", "haohuo.snssdk.com"].includes(u.hostname)
        || !/^\/(?:views\/product\/(?:detail|item2)|ecommerce\/trade\/detail\/index\.html)\/?$/.test(u.pathname)) return null;
      const id = u.searchParams.get("id");
      return /^\d{5,30}$/.test(id || "") ? `${u.origin}${u.pathname}?id=${id}` : null;
    } catch (_) { return null; }
  }
  function createCollector({document, isVisible, inspector, roomUrl, emit, now = Date.now, newId, catalogEnabled = () => false}) {
    const identity = globalThis.BrandbaiProductIdentity?.create({document,roomUrl,publicUrl,now,newId});
    function bounded(data) {
      const size = () => new TextEncoder().encode(JSON.stringify(data)).length;
      for (const key of ["images", "parameter_texts", "sku_groups", "offer_texts", "price_texts"]) {
        while (size() > 40000 && data[key]?.length) { data[key].pop(); data.fields_limited = true; }
      }
      return data;
    }
    const all = (node, selector) => Array.from(node?.querySelectorAll(selector) || []);
    let materialRow = null;
    const visible = (node) => {
      if (materialRow?.contains(node)) {
        if(node.closest('[hidden],[inert],[aria-hidden="true"]')) return false;
        for(let n=node;n && n!==document;n=n.parentElement) {
          const style=document.defaultView.getComputedStyle(n);
          if(style.display==='none'||style.visibility==='hidden')return false;
        }
        return node.getBoundingClientRect().width>0;
      }
      if (!node || node.closest?.('[hidden],[inert],[aria-hidden="true"]') || !isVisible(node)) return false;
      if(globalThis.BrandbaiDouyinCommerceDom?.visibleWithinViewport)
        return globalThis.BrandbaiDouyinCommerceDom.visibleWithinViewport(node,document.defaultView);
      const win = document.defaultView, r = node.getBoundingClientRect();
      let left = Math.max(0, r.left), right = Math.min(win.innerWidth, r.right);
      let top = Math.max(0, r.top), bottom = Math.min(win.innerHeight, r.bottom);
      for (let parent = node.parentElement; parent; parent = parent.parentElement) {
        const style = win.getComputedStyle(parent), p = parent.getBoundingClientRect();
        if (/hidden|clip|scroll|auto/.test(style.overflowY)) { top = Math.max(top, p.top); bottom = Math.min(bottom, p.bottom); }
        if (/hidden|clip|scroll|auto/.test(style.overflowX)) { left = Math.max(left, p.left); right = Math.min(right, p.right); }
      }
      return right > left && bottom > top;
    };
    const rows = (node) => all(node, "h1,h2,h3,p,div,span,a,button,label,dt,dd")
      .filter((n) => visible(n) && !Array.from(n.children || []).some((c) => text(c.textContent)))
      .map((n) => text(n.innerText || n.textContent)).filter(Boolean);
    const unique = (values, limit) => [...new Set(values.filter(Boolean))].slice(0, limit);
    function prices(node) {
      // Preserve visible price qualifiers; never calculate a discount or use
      // the private checkout total. Only small monetary components qualify.
      const fields = [node, ...all(node, 'span,div,p,b,strong,em,del')].filter(visible);
      const candidates = fields.map((n) => {
        let value = text(n.innerText || n.textContent, 80)?.replace(/\s+/g, '');
        if (!value) return null;
        const before = document.defaultView.getComputedStyle(n, '::before').content.replace(/["']/g, '');
        if (/^[¥￥]$/.test(before) && /^\d/.test(value)) value = before + value;
        const rest = value.replace(/[¥￥]\d+(?:\.\d+)?(?:元|起)?/g, '');
        return /[¥￥]\d/.test(value) && /^(?:(?:优惠前|券后价?|到手价?|原价|现价|预售价|售价|价格|活动价|大促价|平台补贴后|起|元|[:：·|｜]))*$/.test(rest) ? value : null;
      }).filter(Boolean);
      return unique(candidates.filter((v) => !candidates.some((other) => other !== v && other.includes(v))), 12);
    }
    function images(node, kind) {
      return unique(all(node, "img").filter(visible).filter((img) =>
        !img.closest?.('[data-role="product-reviews"],[class*="avatar" i]'))
        .map((img) => publicUrl(img.currentSrc || img.src, "image")), 40)
        .map((url) => ({url, kind}));
    }
    function link(node) {
      const links = unique([node, ...all(node, "a[href]")].filter(visible)
        .map((n) => publicUrl(n.getAttribute?.("href"))), 2);
      return links.length === 1 ? links[0] : null;
    }
    function snapshot(element, fallbackTitle, fallbackPrice) {
      const lines = rows(element);
      const explicit = unique(all(element, '[data-e2e="product-title"],[data-role="product-title"],h1,h2,h3')
        .filter(visible).map((n) => text(n.innerText || n.textContent)), 2);
      const offers = lines.filter((v) => /^(?:运费险|\d+天无理由|包邮|赠|满\d|优惠|券|到手)/.test(v));
      const shops = unique(lines.filter((v) => /(?:旗舰店|专卖店|专营店|官方店)$/.test(v)), 2);
      const titles = unique(lines.filter((v) => v.length >= 8 && !/[¥￥]|^(?:讲解中|热卖|已售|销量|全部商品|立即抢|运费险|\d+天无理由|包邮|赠|满\d|优惠)/.test(v)
        && !shops.includes(v)), 2);
      const title = explicit.length === 1 ? explicit[0] : titles.length === 1 ? titles[0] : text(fallbackTitle);
      return bounded({product_title: title, display_price: text(fallbackPrice, 80),
        product_url: link(element), shop_name: shops.length === 1 ? shops[0] : null,
        offer_texts: unique(offers, 12), images: images(element, "card_image"),
        identity_status: link(element) ? "public_product_link" : "unconfirmed",
        source: "live_visible_product_card"});
    }
    let current = null;
    let pending = null;
    let lastSignature = null;
    let lastIdentity = null;
    let visibleBefore = false;
    let seen = false;
    let misses = 0;
    let catalog = null;
    let openingCatalog = null;
    let surfaceCovered = false;
    const BUY = /^(?:去抢购|领券抢购|立即抢购)$/;
    const CATALOG_ACTION = /^(?:去抢购|领券抢购|立即抢购|点击抽奖|参与抽奖|已售罄|暂时售罄|已抢光|已下架)$/;
    function listPicture(element) {
      // A price/benefit sub-box can contain a shop badge. Require an owned,
      // thumbnail-sized product image before accepting its ancestor as a row.
      // Ambiguous different thumbnails are not silently resolved by DOM order.
      const candidates = all(element, 'img').filter((img) => {
        if (!visible(img) || !publicUrl(img.currentSrc || img.src, 'image')
          || img.closest('[data-role="product-reviews"],[class*="avatar" i]')) return false;
        const r = img.getBoundingClientRect();
        return r.width >= 64 && r.height >= 64 && r.width / r.height >= 0.45 && r.width / r.height <= 2.2;
      });
      const keys = unique(candidates.map((img) => publicUrl(img.currentSrc || img.src, 'image').split('~tplv-')[0]), 2);
      return keys.length === 1 ? candidates[0] : null;
    }
    function listTitle(element, picture = listPicture(element)) {
      if (!picture) return null;
      const edge = picture.getBoundingClientRect().right;
      // The list's name is the first text component beside its thumbnail;
      // a later promotional subtitle is not a competing product name.
      const nodes = all(element, 'h1,h2,h3,p,div,span,a').filter((n) => {
        const value = text(n.innerText || n.textContent);
        if (!visible(n) || !value || value.length < 8 || /[¥￥]|^(?:热卖|讲解中|运费险|\d+天无理由|优惠|券|到手|满\s*\d|立减|每满|包邮|赠|已售|销量|抖音旗舰$)/.test(value)
          || Array.from(n.children).some((c) => (text(c.innerText || c.textContent)?.length || 0) >= 8)) return false;
        // A full-width block beside a floated thumbnail starts on the left,
        // but its actual text starts on the right. Use the rendered text box.
        const range = document.createRange(); range.selectNodeContents(n);
        const rect = Array.from(range.getClientRects()).find((r) => r.width > 0 && r.height > 0) || n.getBoundingClientRect();
        return rect.left >= edge - 8;
      }).sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
      if (!nodes.length) return null;
      const top = nodes[0].getBoundingClientRect().top;
      const titles = unique(nodes.filter((n) => Math.abs(n.getBoundingClientRect().top - top) < 2).map((n) => text(n.innerText || n.textContent)), 2);
      return titles.length === 1 ? titles[0] : null;
    }
    function listSnapshot(element) {
      const picture = listPicture(element), title = listTitle(element, picture);
      if (!picture || !title) return null;
      const base = snapshot(element, title, prices(element).join(' / '));
      return {...base, product_title: title,
        images: [{url: publicUrl(picture.currentSrc || picture.src, 'image'), kind: 'list_image'}]};
    }
    function listRows(scope, wholeRow = false) {
      const found = new Set();
      const buttons = all(scope, 'button,a,div,span').filter((n) => visible(n) && (wholeRow?CATALOG_ACTION:BUY).test((n.innerText || n.textContent || '').trim()));
      for (const button of buttons.slice(0, 100)) {
        for (let node = button.parentElement, depth = 0; node && node !== scope && depth < 6; node = node.parentElement, depth++) {
          const r = node.getBoundingClientRect();
          if (r.width < 180 || r.width > 720 || r.height < 65 || r.height > 330) continue;
          if (buttons.some((other) => other !== button && !other.contains(button) && !button.contains(other) && node.contains(other))) break;
          let qualifies=false;
          if(wholeRow) materialRow=node;
          try { qualifies=(wholeRow || prices(node).length) && listSnapshot(node); }
          finally { materialRow=null; }
          if(qualifies) { found.add(node); break; }
        }
      }
      return [...found].filter((node) => ![...found].some((other) => other !== node && node.contains(other)));
    }
    function findList(wholeRow = false) {
      const candidates = new Set(), items = listRows(document,wholeRow);
      for (const item of items) {
        for (let node = item.parentElement, depth = 0; node && node !== document.body && depth < 6; node = node.parentElement, depth++) {
          const r = node.getBoundingClientRect();
          if (r.width > 760 || r.height < 150 || !visible(node)) continue;
          // Per-row wrappers can be as tall as the former list threshold.
          // A list owns repeated rows, not merely the first row's wrapper.
          if (items.filter((row) => node.contains(row)).length >= Math.min(2,items.length)) { candidates.add(node); break; }
        }
      }
      const minimal = [...candidates].filter((n) => ![...candidates].some((other) => other !== n && n.contains(other)));
      return minimal.length === 1 ? minimal[0] : null;
    }
    function scanList() {
      if (!catalogEnabled()) { catalog = openingCatalog = null; return false; }
      if (openingCatalog && (openingCatalog.room !== roomUrl() || now() > openingCatalog.deadline)) openingCatalog = null;
      if (catalog && (catalog.room !== roomUrl() || !visible(catalog.scope))) catalog = null;
      if (!catalog && openingCatalog) {
        const scope = findList();
        if (scope) { catalog = {scope, room: roomUrl(), seen: new Map(), nodes: new WeakMap(), nextNode: 0, rows: []}; openingCatalog = null; }
      }
      if (!catalog) return false;
      catalog.rows = [];
      for (const element of listRows(catalog.scope).slice(0, 30)) {
        const base = listSnapshot(element);
        const lines = rows(element), numbers = unique(lines.filter((v) => /^\d{1,4}$/.test(v)), 2);
        const data = {...base, source: 'live_visible_product_list',
          images: base.images.map((img) => ({...img, kind: 'list_image'})),
          list_position: numbers.length === 1 && Number(numbers[0]) > 0 ? Number(numbers[0]) : null,
          explaining: lines.some((v) => v === '讲解中') ? true : null};
        if (!catalog.nodes.has(element)) catalog.nodes.set(element, ++catalog.nextNode);
        // Equal names/prices are not identity: two distinct rows without a
        // public item link must never share an observation binding.
        const key = `${catalog.nodes.get(element)}:${JSON.stringify(data)}`;
        let id = catalog.seen.get(key);
        if (!id) {
          id = `list-${newId()}`;
          catalog.seen.set(key, id);
          if (catalog.seen.size > 500) catalog.seen.delete(catalog.seen.keys().next().value);
          emit('product_list_item', {...data, list_observation_id: id});
        }
        catalog.rows.push({element, id, data, room: roomUrl(), kind: 'list'});
      }
      return true;
    }
    function reset() {
      current = pending = lastSignature = lastIdentity = null;
      visibleBefore = seen = false;
      misses = 0;
      catalog = openingCatalog = null;
      surfaceCovered = false;
    }
    function scan(card) {
      const panelOpen = inspector.inspect().status !== 'none';
      // A list/detail overlays the on-air card. Do not date that UI covering
      // as a controller hide event or mistake a list row for an on-air card.
      surfaceCovered = Boolean(panelOpen || scanList() || openingCatalog);
      if (surfaceCovered) { pollDetail(); return; }
      if (card) {
        const data = snapshot(card.element, card.product_title, card.display_price);
        const identity = data.product_url || data.product_title || "unknown";
        const signature = JSON.stringify(data);
        const changed = signature !== lastSignature;
        let kind = !visibleBefore ? (seen ? "restored_visible" : "baseline_visible") :
          identity !== lastIdentity ? "visible_product_changed" : changed ? "visible_info_changed" : null;
        if (kind) {
          const id = newId();
          current = {element: card.element, id, data, room: roomUrl(), kind: 'card'};
          emit("product_state", {visible: true, ...data, change_kind: kind, card_observation_id: id});
        } else if (current) current.element = card.element;
        if (pending && (pending.room !== roomUrl() || pending.identity !== identity)) pending = null;
        lastIdentity = identity;
        lastSignature = signature;
        visibleBefore = seen = true;
        misses = 0;
      } else if (++misses >= 2 && visibleBefore) {
        emit("product_state", {visible: false, product_title: null, display_price: null,
          change_kind: "temporarily_not_visible", card_observation_id: current?.id || null});
        visibleBefore = false;
        // Keep the clicked card binding when its own detail pane obscures it.
        current = null;
      }
      pollDetail();
    }
    function clicked(event) {
      if (!event.isTrusted) return;
      if (catalogEnabled()) {
        const entry = event.target.closest?.('[data-e2e="yellowCart-container"],button,[role="button"],a');
        if (entry && visible(entry) && /^(?:🛒\s*)?全部商品\s*[›>]?\s*$/.test(entry.innerText || entry.textContent || '')) {
          pending = catalog = null;
          openingCatalog = inspector.inspect().status === 'none' && !findList() ? {room: roomUrl(), deadline: now() + 10000} : null;
          return;
        }
        if (openingCatalog) scanList();
      }
      const selected = catalogEnabled() && catalog?.rows.find((row) => visible(row.element) && row.element.contains(event.target))
        || (current && visibleBefore && current.element.contains(event.target) ? current : null);
      if (!selected || selected.room !== roomUrl()) {
        pending = null;
        return;
      }
      const before = inspector.inspect();
      // A pre-opened / ambiguous / incomplete pane has no proven ownership.
      if (before.status !== "none") { pending = null; return; }
      // The DOM may reuse a list row between one-second scans. Reject its
      // old observation if the title changed before the trusted click.
      const selectedTitle = selected.kind === 'list' ? listSnapshot(selected.element)?.product_title : snapshot(selected.element).product_title;
      if (selectedTitle !== selected.data.product_title) { pending = null; return; }
      pending = {card: selected, room: roomUrl(), identity: selected.data.product_url || selected.data.product_title, clickedAt: now(),
        previousSignature: null, deadline: now() + 10000};
    }
    function titleMatches(short, full) {
      const prefix = String(short || "").replace(/(?:…+|\.{3})\s*$/, "").trim();
      return prefix.length >= 8 && (full === prefix || (/[….]/.test(short) && full.startsWith(prefix)));
    }
    function detailSnapshot(panel) {
      const header = inspector.header(panel);
      const title = text(header.title);
      const url = link(panel);
      if (!title) return null;
      // Include sibling SKU boxes only when owned by the same explicit modal;
      // never serialize the address/payment area or infer SKU combinations.
      const skuGroups = (inspector.liveSkuGroups?.(panel) || inspector.localSkuGroups(panel)).slice(0, 12)
        .map((g) => ({name: text(g.name, 80), options: g.options.filter((o) => visible(o.node)).slice(0, 40)
          .map((o) => ({value: text(o.value, 280), selected: !inspector.optionDisabled(o.node) && inspector.optionSelected(o.node)})).filter((o) => o.value)}))
        .map((g) => g.options.filter((o) => o.selected).length > 1 ?
          {...g, options: g.options.map((o) => ({...o, selected: false}))} : g)
        .filter((g) => g.name && g.options.length);
      return bounded({product_title: title,
        product_url: url, shop_name: text(header.shopName, 80),
        price_texts: unique((header.priceTexts?.length ? header.priceTexts : prices(header.titleNode?.parentElement)).map((v) => text(v, 80)), 12),
        offer_texts: unique(rows(panel).filter((v) => /^(?:运费险|\d+天无理由|包邮|赠|满\d|优惠|券)/.test(v)), 12),
        sku_groups: skuGroups,
        parameter_texts: unique(inspector.parameterLines(panel).map((v) => text(v, 280)), 40),
        images: images(panel, "unclassified_product_image"),
        identity_status: url ? "public_product_link" : "unconfirmed",
        source: "user_selected_current_product_panel", completeness: "visible_snapshot_only"});
    }
    // Standalone preview is explicitly requested by the side panel. It does
    // not emit live events, enable collection, or touch playback. DOM identity
    // prevents reusing a lookalike pane or a previous document after navigation.
    const previewPanels = new WeakMap();
    let previewDocument = null;
    let previewSerial = 0;
    function previewCurrent() {
      const result = inspector.inspect();
      if (result.status !== 'recognized') {identity?.clear(); return {status: result.status};}
      const data = detailSnapshot(result.panel);
      if (!data) return {status: 'incomplete'};
      if(identity){
        data.product_identity=identityCurrent(result)?.product_identity;
        if(!data.product_identity)return {status:'identity_conflict'};
      }
      if (!previewDocument) previewDocument = newId();
      if (!previewPanels.has(result.panel)) previewPanels.set(result.panel, ++previewSerial);
      return {status: 'recognized', room_url: roomUrl(),
        panel_key: `${previewDocument}:${previewPanels.get(result.panel)}`,
        observed_at_epoch_ms: now(), snapshot: data};
    }
    function identityCurrent(found=inspector.inspect()) {
      if(found.status!=='recognized'||!found.panel){identity?.clear();return null;}
      const header=inspector.header(found.panel);
      const value=identity?.read(found.panel,{title:text(header.title),shop_name:text(header.shopName,80),
        product_url:link(found.panel),headerNode:header.titleNode});
      return value?{panel:found.panel,product_identity:value,title:text(header.title),shop_name:text(header.shopName,80)}:null;
    }
    function pollDetail() {
      if (!pending) return;
      if (now() > pending.deadline || roomUrl() !== pending.room) { pending = null; return; }
      const result = inspector.inspect();
      if (result.status !== "recognized") { pending.previousSignature = null; return; }
      const panel = result.panel, base = detailSnapshot(panel);
      if (!base || (pending.card.data.product_url && base.product_url && base.product_url !== pending.card.data.product_url)
        || (pending.card.data.shop_name && base.shop_name && base.shop_name !== pending.card.data.shop_name)
        || !titleMatches(pending.card.data.product_title, base.product_title)) { pending = null; return; }
      const fromList = pending.card.kind === 'list';
      if (fromList && !catalogEnabled()) { pending = null; return; }
      const data = bounded({...base, [fromList ? 'list_observation_id' : 'card_observation_id']: pending.card.id,
        source: 'user_opened_live_product_panel', association: fromList ? 'fresh_panel_after_list_click' : 'fresh_panel_after_card_click',
        clicked_at_epoch_ms: pending.clickedAt});
      const signature = JSON.stringify(data);
      // Two consecutive observations of the same pane and data. Never date
      // detail fields back to the original on-air card observation.
      if (pending.panel === panel && pending.previousSignature === signature) {
        emit("product_detail", data);
        pending = null;
      } else { pending.panel = panel; pending.previousSignature = signature; }
    }
    function catalogSurface(knownScope = null) {
      const scope = knownScope?.isConnected && visible(knownScope) ? knownScope : findList(true);
      if (!scope) return null;
      const elements=listRows(scope,true);
      const unreadable=all(scope,'button,a,div,span').filter(n=>visible(n) && CATALOG_ACTION.test((n.innerText||n.textContent||'').trim())
        && !elements.some(row=>row.contains(n))).length;
      return {scope, unreadable_count:unreadable, rows: elements.map((element) => {
        // A partially clipped row must not become a fake catalog revision
        // merely because its number/price moved out of the scroll viewport.
        // Only this explicitly selected row's rendered public fields qualify.
        materialRow=element;
        try {
        const base = listSnapshot(element);
        const numbers = unique(rows(element).filter((v) => /^\d{1,4}$/.test(v)), 2);
        const action=rows(element).find(v=>CATALOG_ACTION.test(v)) || null;
        const position=numbers.length === 1 && +numbers[0] > 0 ? +numbers[0] : null;
        const productIdentity=identity?.read(element,{title:base.product_title,shop_name:base.shop_name,product_url:base.product_url,position,catalog:true});
        return {element, data: {list_position: position,
          ...(productIdentity?{product_identity:productIdentity}:{}),
          product_title: base.product_title, display_price: base.display_price,
          entry_type: /抽奖/.test(action||'') ? 'lottery' : /售罄|抢光|下架/.test(action||'') ? 'unavailable' : 'product', action_label:action,
          thumbnail: base.images[0]?.url || null, product_url: base.product_url,
          explaining: rows(element).includes('讲解中') ? true : null, observed_at_epoch_ms: now()}};
        } finally { materialRow=null; }
      })};
    }
    return {scan, clicked, reset, snapshot, previewCurrent, identityCurrent, catalogSurface,
      selectedSkuId:(panel,groups)=>identity?.selectedSkuId(panel,groups)||null, isSurfaceCovered: () => surfaceCovered};
  }
  return Object.freeze({createCollector, publicUrl, text});
});
