/* Transport adapter only. Review parsing and scrolling belong to the vendored collector. */
(() => {
  const key = '__brandbaiSkillProductReviewsV060';
  if (globalThis[key]) return;
  const documentToken = crypto.randomUUID();
  const messages = [];
  const acknowledgements = new Map();
  let collector = null, active = null, transaction = null, options = null, serial = 0;
  const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
  const workId = () => {
    const url = new URL(location.href);
    return url.searchParams.get('modal_id') || url.pathname.match(/\/(?:video|note)\/(\d+)/)?.[1] || '';
  };
  const rendered = node => {
    if (!(node instanceof Element) || !node.isConnected || node.closest('[hidden],[inert],[aria-hidden="true"]')) return false;
    for (let parent = node; parent; parent = parent.parentElement) {
      const style = getComputedStyle(parent);
      if (style.display === 'none' || style.visibility === 'hidden') return false;
    }
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const visible = node => {
    if (!rendered(node)) return false;
    const rect = node.getBoundingClientRect();
    return rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth;
  };
  const identity = surface => ['documentToken','contextKey','generation','productPanelInstanceId'].map(k => surface?.[k]).join('|');
  function verify(surface) {
    if (document.visibilityState === 'hidden') throw new Error('page_hidden');
    if (workId() !== options.expectedWorkId) throw new Error('work_changed');
    if (surface?.mode !== 'product' || !surface.product || surface.product.identityStatus === 'unconfirmed') throw new Error('product_identity_unconfirmed');
    const expected = options.product;
    if (clean(surface.product.title) !== clean(expected.title)) throw new Error('product_changed');
    if (expected.shopName && clean(surface.product.shopName) !== clean(expected.shopName)) throw new Error('product_changed');
    if (expected.productId && surface.product.productId !== expected.productId) throw new Error('product_changed');
    if (surface.reasonCode && !['reviews_not_open','reviews_loading','reviews_unverified','selector_drift'].includes(surface.reasonCode)) throw new Error(surface.reasonCode);
    return surface;
  }
  const api = {
    configure(value) {
      if (active) throw new Error('product_review_run_active');
      options = value;
      if (workId() !== options.expectedWorkId) throw new Error('work_changed');
      // Keep this instance across calls: unknown product IDs may resume only
      // in the same live document, panel and filter lease.
      if (!collector) collector = BrandbaiDouyinCommerceReviewCollector.createCollector({
        document, window, documentToken, isVisible: visible, isRendered: rendered,
        getWorkContext: () => ({ documentToken, contextKey: `work:${workId()}`, generation: `${documentToken}:${workId()}`,
          sourceWorkId: workId(), sourceSurfaceInstance: `${documentToken}:work:${workId()}` }),
        limits: value.limits,
        sendMessage: message => new Promise(resolve => {
          const id = ++serial; acknowledgements.set(id, resolve); messages.push({id,message});
        }),
        beginTransaction: () => {
          if (transaction) throw new Error('product_transaction_active');
          const surface = verify(collector.getSurfaceState());
          transaction = { identity: identity(surface) };
          document.querySelectorAll('video').forEach(video => video.pause());
          return transaction;
        },
        assertTransaction: lease => {
          if (transaction !== lease || identity(verify(collector.getSurfaceState())) !== lease.identity) throw new Error('product_changed');
        },
        finishTransaction: () => { transaction = null; }
      });
      collector.configureLimits(value.limits);
      return verify(collector.getSurfaceState());
    },
    async open() {
      const before = verify(collector.getSurfaceState());
      document.querySelectorAll('video').forEach(video => video.pause());
      if (before.lease) return before;
      if (before.reasonCode !== 'reviews_not_open') return before;
      const located = collector.locateReviewTab(before);
      if (!located.ok || !located.found) throw new Error(located.reasonCode || 'review_tab_unavailable');
      const panel = Array.from(document.querySelectorAll('.eRfaxg7R,.lqrK15Gt,[role="dialog"],[aria-modal="true"]'))
        .filter(node => visible(node) && node.querySelector('.yVU8TMWn'))
        .filter((node, _, nodes) => !nodes.some(other => node !== other && node.contains(other)));
      if (panel.length !== 1) throw new Error('ambiguous_product_panel');
      const candidates = Array.from(panel[0].querySelectorAll('.yVU8TMWn div,.yVU8TMWn span,.yVU8TMWn button,.yVU8TMWn [role="tab"]'))
        .filter(node => rendered(node) && /^商品评价(?:[（(][\d,]+[）)])?$/.test(clean(node.innerText).replace(/\s/g,'')));
      const tabs = candidates.filter(node => !candidates.some(other => node !== other && node.contains(other)));
      if (tabs.length !== 1 || identity(verify(collector.getSurfaceState())) !== identity(before)) throw new Error('review_tab_unavailable');
      tabs[0].click();
      let previous = '', stable = 0;
      for (let attempt = 0; attempt < 16; attempt++) {
        await new Promise(resolve => setTimeout(resolve, 250));
        const surface = verify(collector.getSurfaceState());
        if (identity(surface) !== identity(before)) throw new Error('product_changed');
        const signature = JSON.stringify(surface.lease);
        stable = signature === previous ? stable + 1 : 1; previous = signature;
        if (surface.ready && stable >= 3) return surface;
      }
      return verify(collector.getSurfaceState());
    },
    surface() { return verify(collector.getSurfaceState()); },
    start(task) {
      if (active || messages.length || acknowledgements.size) throw new Error('product_review_run_active');
      verify(collector.getSurfaceState());
      const result = collector.start(task); active = task;
      collector.waitForIdle().finally(() => { active = null; });
      return result;
    },
    poll() { return { active: Boolean(active), items: messages.splice(0) }; },
    ack({id,response}) { const resolve = acknowledgements.get(id); if (resolve) { acknowledgements.delete(id); resolve(response); } },
    pause() { if (active) collector.pause({taskId:active.id,runId:active.runId}).catch(() => {}); return {ok:true}; }
  };
  globalThis[key] = api;
})();
