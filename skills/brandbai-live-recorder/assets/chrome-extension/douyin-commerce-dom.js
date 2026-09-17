(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.BrandbaiDouyinCommerceDom = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const GROUP = /^(?:口味分类|规格分类|选择规格|尺寸规格|颜色分类|颜色|尺码|尺寸|款式|型号|规格|套餐|套餐类型|净含量|容量|数量|选择)$/;
  const STOP = /^(?:购买数量|订单留言|优惠明细|订单运费|收货地址|配送至|支付|立即购买|领券购买|加入购物车|物流|保障|商品详情|商品评价|产品参数|价格说明|温馨提示|订单发票)/;
  const HIDDEN = '[hidden],[inert],[aria-hidden="true"],[id^="brandbai-"]';
  const clean = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const text = (node) => clean(node?.innerText || node?.textContent);
  function isReviewTab(value) {
    // Counts are display labels, not necessarily bare integers (22.9万).
    // Keep exact tab matching and balanced parentheses: review chatter must
    // not establish a product pane. Never convert this label into sales.
    const label = clean(value).replace(/\s+/g, '').replace(/（/g, '(').replace(/）/g, ')');
    if (label === '商品评价') return true;
    if (!label.startsWith('商品评价') || label.length > 36) return false;
    let count = label.slice(4);
    if (count.startsWith('(') && count.endsWith(')')) count = count.slice(1, -1);
    return /^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?[万亿wW]?\+?$/.test(count);
  }
  function visibleWithinViewport(node, window) {
    if(!node || node.closest?.(HIDDEN))return false;
    const r=node.getBoundingClientRect();
    let left=Math.max(0,r.left),right=Math.min(window.innerWidth,r.right);
    let top=Math.max(0,r.top),bottom=Math.min(window.innerHeight,r.bottom);
    const fixedContainingBlock=n=>{const s=window.getComputedStyle(n);return (s.transform&&s.transform!=='none')||(s.perspective&&s.perspective!=='none')
      ||(s.filter&&s.filter!=='none')||/(?:layout|paint|strict|content)/.test(s.contain||'')
      ||/(?:transform|perspective|filter)/.test(s.willChange||'');};
    for(let child=node,parent=node.parentElement;parent;child=parent,parent=parent.parentElement){
      // A viewport-fixed portal escapes overflow on its old page ancestors.
      // Transformed/contained ancestors still establish a real clipping scope.
      if(window.getComputedStyle(child).position==='fixed'){
        while(parent&&!fixedContainingBlock(parent))parent=parent.parentElement;
        if(!parent)break;
      }
      const style=window.getComputedStyle(parent),p=parent.getBoundingClientRect();
      if(style.display==='none'||style.visibility==='hidden')return false;
      if(/hidden|clip|scroll|auto/.test(style.overflowY)){top=Math.max(top,p.top);bottom=Math.min(bottom,p.bottom);}
      if(/hidden|clip|scroll|auto/.test(style.overflowX)){left=Math.max(left,p.left);right=Math.min(right,p.right);}
    }
    return right>left&&bottom>top;
  }
  function mediaKey(value) {
    try {
      const url = new URL(value);
      if (!/(^|\.)(?:ecombdimg\.com|detailpage\.byteimg\.com)$/.test(url.hostname)) return "";
      if (/(?:qrcode|qr[-_]?code|avatar|girdle|second_page|priority|\/common\/|shop_|\/eden-cn\/|aweme_flagship)/i.test(url.pathname)) return "";
      // CDN transforms may differ between the main gallery and SKU thumbnail.
      return url.pathname.split("~tplv-")[0];
    } catch (_) { return ""; }
  }
  function createInspector({ document, window, isVisible, isRendered }) {
    const rendered = (node) => Boolean(node && node.isConnected !== false && !node.closest?.(HIDDEN) && isRendered(node));
    const live = (node) => rendered(node) && isVisible(node);
    const all = (node, selector) => Array.from(node?.querySelectorAll(selector) || []);
    const leaves = (node, before = null) => all(node, "h1,h2,h3,h4,p,div,span,button,label,dt,dd")
      .filter((child) => (!before || Boolean(child.compareDocumentPosition(before) & 4) && !child.contains(before))
        && rendered(child) && text(child) && !Array.from(child.children).some((part) => text(part).length > 3));
    const minimal = (nodes) => nodes.filter((node) => !nodes.some((other) => node !== other && node.contains(other)));
    const images = (node) => all(node, "img").filter((image) => rendered(image) && mediaKey(image.currentSrc || image.src)
      && !image.closest('.FDag2E0P,.PEzhiR4O,[data-role="product-reviews"],[class*="avatar" i]')
      && (Math.min(image.naturalWidth || 0, image.naturalHeight || 0) >= 300 || image.getBoundingClientRect().width >= 100));
    function tabLeaves(node) {
      // Cheap textContent is only a candidate filter. Still confirm rendered
      // innerText before accepting a label. Do not measure every review or
      // collapsed background card merely to find two product tabs.
      const labels = all(node, 'div,span,button,a,h1,h2,h3,h4,p,label,dt,dd')
        .filter(leaf => /商品详情|商品评价/.test(leaf.textContent || '') && rendered(leaf))
        .filter(leaf => text(leaf) === '商品详情' || isReviewTab(text(leaf)));
      return minimal(labels);
    }
    function hasTabs(node) {
      const labels = tabLeaves(node).map(text);
      return labels.includes("商品详情") && labels.some((label) => /^商品评价/.test(label));
    }
    function headerFields(panel, firstTab = tabLeaves(panel)[0]) {
      // DOM leaves are presentation fragments, not product fields. Preserve
      // the enclosing title/price component while staying before the tabs.
      return all(panel, "h1,h2,h3,h4,p,div,span,button,label,dt,dd,b,strong,em,small,a")
        .filter((node) => (!firstTab || Boolean(node.compareDocumentPosition(firstTab) & 4))
          && !node.contains(firstTab) && rendered(node) && text(node).length <= 260
          && !node.closest('.FDag2E0P,.PEzhiR4O,[data-role="product-reviews"],[role="radio"],[role="option"],[data-sku-id]'));
    }
    function pricesFromFields(fields) {
      const values = new Set();
      for (const node of fields) {
        let value = text(node).replace(/\s+/g, "");
        if (!value || value.length > 80) continue;
        // Currency may be a narrow child or a CSS pseudo element. Read it
        // only inside this small, visible monetary component, never from an
        // unrelated sibling or a guessed currency for a naked number.
        const before = clean(window.getComputedStyle(node, "::before").content).replace(/^["']|["']$/g, "");
        if (/^[￥¥]$/.test(before) && /^\d/.test(value)) value = before + value;
        const money = /(?:优惠前|券后|到手价?|原价|现价|预售价|售价|价格|活动价|平台补贴后)?[￥¥]\d+(?:\.\d+)?(?:元|起)?/g;
        const matches = value.match(money) || [];
        const remainder = value.replace(money, "");
        if (!matches.length || !/^(?:(?:优惠前|券后|到手价?|原价|现价|预售价|售价|价格|活动价|平台补贴后|起|元|[:：·|｜]))*$/.test(remainder)) continue;
        matches.forEach((price) => values.add(price));
      }
      const monetaryValue = (price) => price.match(/[￥¥]\d+(?:\.\d+)?/)?.[0];
      return Array.from(values).filter((price) => {
        if (!/[元起]$/.test(price) && (values.has(price + '起') || values.has(price + '元'))) return false;
        return !/^[￥¥]/.test(price) || !Array.from(values).some((other) => !/^[￥¥]/.test(other) && monetaryValue(other) === monetaryValue(price));
      });
    }
    function inspect(searchRoot = document) {
      // Start from actual tab labels, not every div's aggregate innerText.
      // Walk their ancestors so an underlying feed cannot outvote an open
      // detail pane merely because it also contains a purchase button.
      const tabs = tabLeaves(searchRoot).filter(node => isReviewTab(text(node)));
      const candidates = new Set();
      let incomplete = false;
      for (const tab of tabs) {
        for (let node = tab.parentElement; node && node !== document.body && node !== document.documentElement; node = node.parentElement) {
          if (!live(node)) continue;
          const rect = node.getBoundingClientRect();
          if (rect.width < 280 || rect.width > window.innerWidth + 32 || rect.height < 240) continue;
          if (!hasTabs(node) || !images(node).length) continue;
          incomplete = true;
          const identity = header(node);
          // Missing price is a field gap, not proof the product does not
          // exist. Title + shop + owned media may establish the surface;
          // ambiguous/missing title must still fail closed.
          if (!identity.title || (!identity.shopName && !identity.priceTexts.length)) continue;
          candidates.add(node);
          break;
        }
      }
      const panels = minimal(Array.from(candidates));
      return { status: panels.length === 1 ? "recognized" : panels.length ? "ambiguous" : incomplete ? "incomplete" : "none", panel: panels.length === 1 ? panels[0] : null };
    }
    function header(panel) {
      const firstTab = tabLeaves(panel)[0];
      const rows = leaves(panel, firstTab);
      const fields = headerFields(panel, firstTab);
      const priceTexts = pricesFromFields(fields);
      const shops = Array.from(new Set(rows.map(text).filter((value) => /(?:旗舰店|专卖店|专营店|官方店)$/.test(value) && value.length <= 80)));
      const explicit = fields.filter((row) => row.matches("h1,[data-e2e='product-title'],[data-role='product-title'],.vs9hmvGz"));
      if (new Set(explicit.map(text)).size > 1 || shops.length > 1) return { title: "", shopName: "", titleNode: null, priceTexts };
      const ranked = (explicit.length ? explicit : fields).filter((row) => {
        const value = text(row);
        return value.length >= 8 && value.length <= 220 && !shops.includes(value)
          && !STOP.test(value) && !/^(?:已选择|推荐|客服|进店|已售|销量|[￥¥\d])/.test(value)
          && !/[￥¥]\s*\d/.test(value) && !/推荐$/.test(value)
          && !all(row, "img,input,button").length
          && !GROUP.test(value) && !row.closest('[role="radio"],[role="option"],[data-sku-id]');
      }).map((node) => {
        const style = window.getComputedStyle(node);
        let priceContext = 0;
        for (let ancestor = node.parentElement, depth = 0; ancestor && ancestor !== panel && depth < 3; ancestor = ancestor.parentElement, depth += 1) {
          if (/[￥¥]\s*\d/.test(text(ancestor))) { priceContext = 80; break; }
        }
        return { node, value: text(node), score: (parseFloat(style.fontSize) || 0) * 10 + ((parseInt(style.fontWeight, 10) || 0) >= 600 ? 80 : 0) + priceContext };
      }).sort((a, b) => b.score - a.score);
      const titles = ranked.filter((row) => !ranked.some((other) => other.node !== row.node && other.node.contains(row.node) && other.score === row.score));
      const top = titles[0];
      const conflict = titles.some((row) => row.value !== top?.value && row.score >= (top?.score || 0));
      return { title: top && !conflict ? top.value : "", shopName: shops.length === 1 ? shops[0] : "", titleNode: top && !conflict ? top.node : null, priceTexts };
    }
    function diagnose() {
      const result = inspect();
      const tabs = all(document, "div,span,button,a").filter((node) => rendered(node) && isReviewTab(text(node)));
      const seen = new Set();
      const candidates = [];
      for (const tab of tabs) {
        for (let node = tab.parentElement; node && node !== document.body && node !== document.documentElement; node = node.parentElement) {
          if (seen.has(node) || !live(node) || !hasTabs(node)) continue;
          seen.add(node);
          const bounds = node.getBoundingClientRect();
          if (bounds.width < 280 || bounds.height < 240) continue;
          const info = header(node);
          candidates.push({ width: Math.round(bounds.width), height: Math.round(bounds.height),
            productImageCount: images(node).length, headerFieldCount: headerFields(node).length,
            titleConfirmed: Boolean(info.title), shopConfirmed: Boolean(info.shopName), priceCount: info.priceTexts.length,
            missing: [!images(node).length && "product_media", !info.title && "product_title", !info.shopName && !info.priceTexts.length && "shop_or_price"].filter(Boolean) });
          if (candidates.length >= 12) break;
        }
        if (candidates.length >= 12) break;
      }
      // Strict allowlist: no page text, URLs, IDs, DOM HTML, cookies, buyer
      // names, address, phone or comment content leave this function.
      return { schema: "brandbai.douyin.commerce-diagnostic.v1", status: result.status,
        viewport: { width: window.innerWidth, height: window.innerHeight }, reviewTabCount: tabs.length, candidates };
    }
    function purchaseScope(panel) {
      const keys = new Set(images(panel).map((image) => mediaKey(image.currentSrc || image.src)));
      const modal = panel.closest('[role="dialog"],[aria-modal="true"],.lqrK15Gt');
      const candidates = all(document, "aside,section,div").filter((node) => {
        if (!live(node) || node === panel || panel.contains(node) || node.contains(panel)) return false;
        const value = text(node);
        if (!/已选择/.test(value) || !/(?:购买数量|支付\s*[￥¥])/.test(value)) return false;
        // Never bind by generic labels such as 单只装/双支装 or 数量 alone.
        const sameModal = modal && modal !== document.body && modal.contains(node)
          && node.closest('[role="dialog"],[aria-modal="true"],.lqrK15Gt') === modal;
        return sameModal || images(node).some((image) => keys.has(mediaKey(image.currentSrc || image.src)));
      });
      const panes = minimal(candidates);
      return panes.length === 1 ? panes[0] : null;
    }
    function groupBlocks(scope) {
      const rows = leaves(scope);
      const headers = rows.filter((node) => GROUP.test(text(node)));
      const groups = [];
      for (const heading of headers) {
        // Find the smallest enclosing block with values but without another
        // group or checkout heading. This preserves wrapped option labels.
        let block = null;
        for (let node = heading.parentElement; node && scope.contains(node); node = node.parentElement) {
          const children = leaves(node).filter((row) => row !== heading && !row.contains(heading));
          if (children.some((row) => GROUP.test(text(row)) || STOP.test(text(row)))) break;
          if (children.length) { block = node; break; }
          if (node === scope) break;
        }
        if (!block) continue;
        const controls = all(block, 'button,[role="radio"],[role="option"],[data-sku-id]').filter((node) => rendered(node) && !node.contains(heading));
        let optionNodes = minimal(controls);
        if (!optionNodes.length) {
          // A common layout is heading + list + cards. Walk the sibling
          // branches, unwrapping a single list without splitting each card's
          // title, dimensions and thumbnail into fake options.
          let branch = heading;
          while (branch.parentElement && branch.parentElement !== block) branch = branch.parentElement;
          optionNodes = Array.from(block.children).filter((node) => node !== branch && rendered(node) && text(node));
          while (optionNodes.length === 1 && optionNodes[0].children.length > 1) {
            if (optionNodes[0].matches('button,[role="radio"],[role="option"],[data-sku-id]')
              || Array.from(optionNodes[0].children).some((node) => node.tagName === "IMG")
              || parseFloat(window.getComputedStyle(optionNodes[0]).borderTopWidth) > 0) break;
            const children = Array.from(optionNodes[0].children).filter((node) => rendered(node) && text(node));
            if (children.length < 2 || children.some((node) => node.tagName === "IMG")) break;
            optionNodes = children;
          }
        }
        const options = optionNodes.map((node) => ({ node, value: text(node) })).filter(({ value }) => value.length >= 1 && value.length <= 280
          && !GROUP.test(value) && !STOP.test(value) && !/^(?:[+−-]|已选择.*)$/.test(value));
        const unique = Array.from(new Map(options.map((option) => [option.value, option])).values());
        if (!unique.length) continue;
        if (text(heading) === "数量" && unique.every(({ value }) => /^\d+$/.test(value))) continue;
        groups.push({ name: text(heading) === "选择" ? "页面可见规格" : text(heading), scope: block, options: unique });
      }
      // Duplicate group headings with different values are ambiguous, not
      // an invitation to merge multiple products or fabricate combinations.
      return groups.filter((group) => groups.filter((other) => other.name === group.name).length === 1);
    }
    function skuGroups(panel) {
      const local = groupBlocks(panel);
      const purchase = purchaseScope(panel);
      const remote = purchase ? groupBlocks(purchase) : [];
      return remote.length ? remote : local;
    }
    function liveSkuGroups(panel) {
      // Live detail layouts split gallery and SKU cards into sibling columns.
      // Require one explicit, shared modal. Never search unrelated checkout
      // panes by generic SKU text or serialize the purchase column.
      const modal = panel.closest('[role="dialog"],[aria-modal="true"],.lqrK15Gt');
      const local = groupBlocks(panel);
      if (!modal || modal === panel || modal === document.body) return local;
      const groups = [];
      const headings = leaves(modal).filter((node) => live(node) && !panel.contains(node)
        && GROUP.test(text(node)) && node.closest('[role="dialog"],[aria-modal="true"],.lqrK15Gt') === modal);
      for (const heading of headings) {
        for (let scope = heading.parentElement, depth = 0; scope && scope !== modal && depth < 4; scope = scope.parentElement, depth++) {
          if (scope.contains(panel)) break;
          const found = groupBlocks(scope).filter((g) => g.scope.contains(heading));
          if (found.length) { groups.push(...found); break; }
        }
      }
      const combined = [...local, ...groups];
      return combined.filter((g) => combined.filter((other) => other.name === g.name).length === 1);
    }
    function optionSelected(node) {
      // Confirmed live SKU card states, scoped by groupBlocks; never infer
      // selection from colour alone or treat every visible option as selected.
      return node?.matches('[aria-checked="true"],[aria-selected="true"],[data-state="checked"],.ufz0AqTE.vZSOutR4') || false;
    }
    function optionDisabled(node) {
      return node?.matches(':disabled,[aria-disabled="true"],[data-disabled="true"],.disabled,.sold-out') || false;
    }
    function skuPrices(panel) {
      const groups=liveSkuGroups(panel);
      // Only the public header BEFORE the SKU group, not the order/payment
      // section below it. The observed desktop layout uses HYshOAHl here.
      const modal=panel.closest('[role="dialog"],[aria-modal="true"],.lqrK15Gt');
      if (!modal) return [];
      const headers=all(modal,'[data-role="sku-public-header"],.HYshOAHl').filter(n=>rendered(n)
        && !panel.contains(n) && groups.some(g=>Boolean(n.compareDocumentPosition(g.scope)&4))
        && !/收货|订单|配送至|支付|手机|地址/.test(text(n)));
      return headers.length===1 ? pricesFromFields(headerFields(headers[0])) : [];
    }
    function parameterLines(panel) {
      const heading = leaves(panel).find((node) => text(node) === "产品参数");
      if (!heading) return [];
      for (let node = heading.parentElement; node && panel.contains(node); node = node.parentElement) {
        const rows = leaves(node).map(text);
        if (rows.length > 1) {
          if (rows.some((value) => /^(?:已选择|购买数量|订单留言|收货地址|支付|优惠明细)/.test(value))) return [];
          // From collection plugin 0.11.158: bind label/value in the same row,
          // avoiding duplicated short words from nested div/span wrappers.
          const pairs = all(node, 'div,li,tr').map((row) => {
            const parts = Array.from(row.children).filter((part) => rendered(part) && text(part));
            if (parts.length !== 2 || row.contains(heading) || all(row, 'img,input,button').length) return null;
            const name = text(parts[0]), value = text(parts[1]);
            if (!name || name.length > 40 || !value || value.length > 300 || !/[\p{L}]/u.test(name) || STOP.test(name)) return null;
            return {node:row,name,value};
          }).filter(Boolean);
          const local = pairs.filter((pair) => !pairs.some((other) => other !== pair && pair.node.contains(other.node)));
          const unique = local.filter((pair) => !local.some((other) => other.name === pair.name && other.value !== pair.value));
          if (local.length) return ['产品参数', ...Array.from(new Map(unique.map((pair) => [pair.name,pair])).values()).flatMap((pair) => [pair.name,pair.value])];
          // Legacy flat rows remain original text, not manufactured pairs.
          return ['产品参数', ...leaves(node).filter((leaf) => !Array.from(leaf.children).some((child) => text(child))).map(text).filter((value) => value !== '产品参数')];
        }
        if (node === panel) break;
      }
      return [];
    }
    return Object.freeze({ inspect, header, purchaseScope, skuGroups, localSkuGroups: groupBlocks, liveSkuGroups, optionSelected, optionDisabled, skuPrices, parameterLines, diagnose });
  }
  return Object.freeze({ createInspector, mediaKey, visibleWithinViewport });
});
