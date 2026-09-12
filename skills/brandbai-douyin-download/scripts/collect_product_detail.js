async ({expectedAwemeId, timeoutMs}) => {
  // Explicit commerce collection only; no private API or account data lookup.
  const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
  const all = (node, selector) => Array.from(node.querySelectorAll(selector));
  const hidden = '[hidden],[inert],[aria-hidden="true"],[id^="brandbai-"]';
  const privateScope = '[data-role="shipping-address"],[data-e2e*="address" i],[class*="address" i],[class*="receiver" i]';
  const reviewScope = '.PEzhiR4O,.FDag2E0P,[data-role="product-review-list"],[data-e2e="product-review-list"]';
  const excluded = `${hidden},${privateScope},${reviewScope}`;
  const rendered = node => {
    if (!(node instanceof Element) || node.closest(hidden)) return false;
    const rect = node.getBoundingClientRect(), style = getComputedStyle(node);
    return rect.width > 2 && rect.height > 2 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const visible = node => {
    if (!rendered(node)) return false;
    const rect = node.getBoundingClientRect();
    return rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth;
  };
  const currentId = () => {
    const url = new URL(location.href);
    return url.searchParams.get('modal_id') || url.pathname.match(/\/(?:video|note)\/(\d+)/)?.[1] || '';
  };
  const assertCurrent = () => {
    if (currentId() !== String(expectedAwemeId || '')) throw new Error('work_changed_during_product_collection');
    if (document.visibilityState === 'hidden') throw new Error('product_page_hidden');
    if (all(document, '[id*="captcha" i],[class*="captcha" i],[data-e2e*="verify" i]').some(visible)) {
      throw new Error('product_verification_required');
    }
    if (all(document, '[role="alert"]').some(node => visible(node)
        && /访问过于频繁|操作频繁|安全验证|账号.*限制|请先登录/.test(clean(node.innerText)))) {
      throw new Error('product_platform_warning');
    }
  };
  const panelCandidate = () => {
    const candidates = all(document, '.eRfaxg7R,.lqrK15Gt,[role="dialog"],[aria-modal="true"],[data-role="product-panel"]')
      .filter(node => visible(node) && /商品详情/.test(node.innerText || '') && /商品评价/.test(node.innerText || ''));
    const smallest = candidates.filter(node => !candidates.some(other => other !== node && node.contains(other)));
    if (smallest.length > 1) throw new Error('ambiguous_product_panels');
    return smallest[0] || null;
  };
  assertCurrent();
  for (const video of all(document, 'video')) video.pause();
  // Never relabel an already-open, potentially stale product with the current URL's work ID.
  if (panelCandidate()) throw new Error('product_panel_already_open_close_and_retry');
  const triggers = all(document, '.xgplayer-shop-anchor,[data-e2e="video-product-anchor"],[data-role="work-product-anchor"]')
    .filter(node => visible(node) && !node.closest('[data-role="product-panel"]'))
    .filter(node => {
      const owner = node.closest('[data-aweme-id],[data-work-id]');
      const id = owner?.getAttribute('data-aweme-id') || owner?.getAttribute('data-work-id');
      if (id && id !== String(expectedAwemeId)) return false;
      const rect = node.getBoundingClientRect();
      const hit = document.elementFromPoint(Math.max(0, rect.left + rect.width / 2), Math.max(0, rect.top + rect.height / 2));
      return !hit || hit === node || node.contains(hit);
    });
  const uniqueTriggers = triggers.filter(node => !triggers.some(other => other !== node && other.contains(node)));
  if (uniqueTriggers.length !== 1) throw new Error('current_work_product_trigger_not_unique');
  const trigger = uniqueTriggers[0];
  const shortTitle = clean(trigger.innerText || trigger.textContent).replace(/^(?:购物|商品|小黄车)\s*[|｜:：·•-]?\s*/, '').slice(0, 180);
  trigger.click();
  const deadline = Date.now() + Math.max(1000, Number(timeoutMs || 8000));
  let panel = null, signature = '', stable = 0;
  while (Date.now() < deadline) {
    assertCurrent();
    const candidate = panelCandidate();
    const next = candidate ? clean(candidate.innerText).slice(0, 1500) : '';
    stable = next && candidate === panel && next === signature ? stable + 1 : next ? 1 : 0;
    panel = candidate; signature = next;
    if (panel && stable >= 3) break;
    await new Promise(resolve => setTimeout(resolve, 160));
  }
  if (!panel || stable < 3) throw new Error('stable_product_panel_not_observed');
  assertCurrent();
  const text = node => clean(node?.innerText || node?.textContent);
  const publicNode = node => rendered(node) && !node.closest(excluded);
  const distinct = values => Array.from(new Set(values.filter(Boolean)));
  const explicitText = selector => distinct(all(panel, selector).filter(publicNode).map(text));
  const titles = explicitText('.vs9hmvGz,[data-e2e="product-title"],[data-role="product-title"]');
  const shops = explicitText('.AjnzIIcY,[data-e2e="shop-name"],[data-role="shop-name"]');
  if (titles.length !== 1 || shops.length > 1) throw new Error('product_header_unconfirmed');
  const title = titles[0], shopName = shops[0] || '';
  const leaves = all(panel, 'h1,h2,h3,h4,p,div,span,li').filter(publicNode)
    .filter(node => !Array.from(node.children || []).some(child => text(child)));
  const personalText = value => /(?:收货人|收件人|收货地址|联系电话|\b1[3-9]\d{9}\b|\d{3}\*{4}\d{4}|\S{1,4}(?:先生|女士)\s*\d|省.{0,10}市.{0,15}(?:区|县|路|街))/.test(value);
  const safeText = node => personalText(text(node)) ? '' : text(node);
  const leafTexts = distinct(leaves.map(safeText));
  const priceTexts = distinct(leafTexts.flatMap(value => value.match(/(?:￥|¥)\s*\d+(?:\.\d+)?(?:\s*起)?/g) || [])).slice(0, 20);
  const salesTexts = leafTexts.filter(value => /^(?:已售|销量)/.test(value) && value.length < 100).slice(0, 20);
  // Deliberately retain public delivery promises, not address-dependent estimates or destinations.
  const deliveryTexts = distinct(leafTexts.flatMap(value => value.match(/\d+\s*小时内发货|\d+\s*天内发货|包邮|免运费/g) || []));
  const serviceTexts = leafTexts.filter(value => /^(?:运费险|\d+天无理由退货|商家资质|保障说明)/.test(value) && value.length < 240).slice(0, 40);
  const reviewCountText = leafTexts.find(value => /^商品评价\s*[（(]?\d+/.test(value)) || '';
  const parameterHead = leaves.find(node => text(node) === '产品参数');
  const parameterScope = panel.querySelector('[data-role="product-parameters"],[data-e2e="product-parameters"]')
    || parameterHead?.nextElementSibling;
  const parameters = [];
  if (parameterScope && panel.contains(parameterScope) && !parameterScope.closest(excluded)) {
    const values = all(parameterScope, 'div,span,li,dt,dd').filter(publicNode)
      .filter(node => !Array.from(node.children || []).some(child => text(child))).map(safeText).filter(Boolean);
    for (let index = 0; index + 1 < Math.min(values.length, 80); index += 2) {
      if (/^(?:购买数量|支付|价格说明|收货地址|商品评价|商品详情)$/.test(values[index])) break;
      parameters.push({name: values[index], value: values[index + 1], scope: 'page_visible'});
    }
  }
  const skuGroups = [];
  const headings = leaves.filter(node => /^(?:口味分类|规格分类|选择规格|规格|净含量|颜色分类|尺码)$/.test(text(node)));
  for (const heading of headings) {
    // Stop at the heading's own option list. Never consume the next 80 page lines.
    const group = heading.closest('[data-role="sku-group"],[data-e2e="sku-group"]');
    const container = group || heading.nextElementSibling;
    if (!container || !panel.contains(container) || container.closest(excluded)) continue;
    if (/购买数量|收货地址|立即购买|支付/.test(text(container))) continue;
    let optionNodes = all(container, '[data-role="sku-option"],[data-e2e="sku-option"],[role="option"],button');
    if (!optionNodes.length) optionNodes = Array.from(container.children || []);
    if (!optionNodes.length && text(container)) optionNodes = [container];
    const options = [];
    for (const node of optionNodes.filter(publicNode)) {
      const value = safeText(node);
      if (!value || value.length > 280 || /^(?:规格|口味分类|购买数量|数量|请选择|已选择|预计|库存)/.test(value)) continue;
      if (options.some(option => option.value === value)) continue;
      const selected = node.getAttribute('aria-selected') === 'true' || node.getAttribute('data-state') === 'selected'
        || node.getAttribute('aria-checked') === 'true';
      options.push({value, selected, disabled: node.getAttribute('aria-disabled') === 'true' || Boolean(node.disabled)});
    }
    if (!options.length) continue;
    const selected = options.filter(option => option.selected);
    skuGroups.push({name: text(heading), selected_value: selected.length === 1 ? selected[0].value : '', options});
  }
  const images = [], seen = new Set();
  for (const image of all(panel, 'img').filter(publicNode)) {
    if (image.closest('[class*="avatar" i],[class*="qrcode" i]')) continue;
    let url; try { url = new URL(image.currentSrc || image.src || ''); } catch (_error) { continue; }
    const allowed = ['ecombdimg.com','detailpage.byteimg.com'];
    if (url.protocol !== 'https:' || url.username || url.password || (url.port && url.port !== '443')
        || !allowed.some(host => url.hostname === host || url.hostname.endsWith(`.${host}`))) continue;
    if (Array.from(url.searchParams.keys()).some(key => /token|sign|auth|credential|secret|cookie|session|expire|policy|key/i.test(key))) continue;
    if (Math.min(Number(image.naturalWidth || 0), Number(image.naturalHeight || 0)) < 300) continue;
    if (/\/(?:girdle|second_page|priority|common|shop_)|qrcode|qr_code/i.test(url.pathname)) continue;
    url.hash = '';
    const key = `${url.hostname}${url.pathname.split('~tplv-')[0]}`;
    if (seen.has(key)) continue; seen.add(key);
    images.push({url: url.href, width: image.naturalWidth, height: image.naturalHeight, order: images.length + 1});
  }
  assertCurrent();
  if (!panel.isConnected || panelCandidate() !== panel) throw new Error('product_panel_changed');
  const observedAt = new Date().toISOString();
  const productId = panel.getAttribute('data-product-id') || panel.querySelector('[data-role="product-title"],.vs9hmvGz')?.getAttribute('data-product-id') || '';
  return {status: 'detail_observed', source_work_id: String(expectedAwemeId), observed_at: observedAt, playback_paused: true, products: [{
    title, short_title: shortTitle, shop_name: shopName, detail_url: '', product_id: /^\d{6,30}$/.test(productId) ? productId : '',
    price_texts: priceTexts, sales_texts: salesTexts, delivery_texts: deliveryTexts, service_texts: serviceTexts,
    review_count_text: reviewCountText, sku_groups: skuGroups, parameters, images: images.slice(0, 200), observed_at: observedAt
  }]};
}
