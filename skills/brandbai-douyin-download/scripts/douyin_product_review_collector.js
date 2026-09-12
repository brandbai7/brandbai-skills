// Adapted from BrandBAI Chrome extension v0.11.156; DOM/parser unchanged.
// Source module: lib/douyin-commerce-review-collector.js. BrandBAI source license applies.
// Skill-only adaptation: configureLimits updates inactive-run budgets without
// discarding the document/panel lease needed for honest unknown-ID resume.
// Row-version keys include every observed field, so late gallery/reply/stat
// updates are acknowledged again and upserted under their stable export ID.
(function installDouyinCommerceReviewCollector(root) {
  "use strict";

  const LEASE_FIELDS = ["documentToken", "contextKey", "generation", "sourceWorkId", "sourceSurfaceInstance", "productPanelInstanceId", "reviewSurfaceInstanceId", "filterKey"];
  const clean = (value) => String(value || "").replace(/[\t\r ]+/g, " ").trim();
  const text = (node) => clean(node?.innerText || node?.textContent);
  const all = (node, selector) => Array.from(node?.querySelectorAll?.(selector) || []);
  const first = (node, selector) => node?.querySelector?.(selector) || null;
  const hash = (value) => {
    let result = 2166136261;
    for (const char of String(value)) result = Math.imul(result ^ char.charCodeAt(0), 16777619);
    return (result >>> 0).toString(36);
  };
  const leaseEquals = (left, right) => Boolean(left && right
    && LEASE_FIELDS.every((field) => typeof left[field] === "string" && left[field].length > 0 && left[field] === right[field]));
  const cloneLease = (lease) => Object.fromEntries(LEASE_FIELDS.map((field) => [field, String(lease?.[field] || "")]));
  const directContaining = (card, node) => {
    for (let current = node; current && current !== card; current = current.parentElement) {
      if (current.parentElement === card) return current;
    }
    return null;
  };

  function mediaUrl(value) {
    try {
      const url = new URL(String(value || ""));
      if (url.protocol !== "https:" || url.username || url.password) return "";
      if (!["ecombdimg.com", "byteimg.com", "douyinpic.com", "douyinstatic.com"].some((host) => url.hostname === host || url.hostname.endsWith(`.${host}`))) return "";
      return url.href;
    } catch (_error) { return ""; }
  }

  function galleryImages(gallery) {
    return Array.from(new Set(all(gallery, "img").map((image) => mediaUrl(image.currentSrc || image.src || image.getAttribute("src"))).filter(Boolean)));
  }

  function readReviewCard(card) {
    const children = Array.from(card?.children || []);
    if (children.length < 2) return null;
    const datePattern = /(?:20\d{2}[年/.-]\d{1,2}(?:[月/.-]\d{1,2}日?)?|\d{1,2}[-/.月]\d{1,2}日?|\d+\s*(?:个\s*)?(?:分钟|小时|天|日|周|星期|月|年)前|今天|昨天|前天)/;
    const knownHeader = first(card, ".ji7a60UU");
    const header = knownHeader && directContaining(card, knownHeader) === knownHeader ? knownHeader
      : children.find((node) => Boolean(first(node, "img")) && datePattern.test(text(node)));
    if (!header) return null;
    const dateNode = first(header, ".Xug6qnCc,time,[data-e2e='review-date'],[data-role='review-date']")
      || all(header, "span,div,time").find((node) => !node.children.length && datePattern.test(text(node)));
    const dateText = text(dateNode);
    const knownSku = first(card, ".bFXVK94u,[data-e2e='review-sku'],[data-role='purchased-sku']");
    const sku = knownSku && directContaining(card, knownSku) === knownSku ? knownSku
      : children.find((node) => /^(?:已购|购买规格|所购规格|已选规格)\s*[:：]/.test(text(node)));
    const knownBody = first(card, ".mgNuPdjB,[data-e2e='review-content'],[data-role='review-content']");
    const body = knownBody && directContaining(card, knownBody) === knownBody ? knownBody : sku?.nextElementSibling;
    // Consumer prose is data, including words such as “加载中/登录/追评”.
    // Structural ownership, not its wording, separates it from list status.
    const explicitStructure = header === knownHeader && body === knownBody;
    // Header/body roles establish the card. Date and purchased SKU are
    // optional metadata, not admission gates for otherwise valid reviews.
    // Unknown layouts still need the semantic date + SKU relationship.
    if (!explicitStructure && (!sku || !dateText || !datePattern.test(dateText))) return null;
    if (!body || body === header || body === sku) return null;
    if (body.matches?.(".AdYl5cnz,.swfDpKGt") || first(body, ".ji7a60UU,.sVIJnLfX")) return null;
    const authorBlock = first(header, ".sVIJnLfX,[data-e2e='reviewer-name'],[data-role='reviewer-name']") || header;
    const authorLeaf = all(authorBlock, "span,div,a").find((node) => !node.children.length && text(node)
      && !datePattern.test(text(node)) && !/^(?:已购|徽章|会员等级|评价达人)$/.test(text(node)));
    const reviewerName = text(authorLeaf) || (authorBlock !== header ? text(authorBlock).split("\n")[0] : "");
    const knownGallery = first(card, ".AdYl5cnz,[data-e2e='review-images'],[data-role='review-images']");
    let gallery = knownGallery && directContaining(card, knownGallery) === knownGallery ? knownGallery : null;
    if (!gallery) {
      const next = body.nextElementSibling;
      if (next && next !== header && next !== sku && all(next, "img").length
        && !text(next) && !first(next, ".sVIJnLfX,[data-role='reviewer-name']")) gallery = next;
    }
    const content = text(body);
    const images = galleryImages(gallery);
    // A review's payload can be text OR a media gallery. An explicitly empty
    // body is valid only with the confirmed card/header/body/gallery roles
    // and a public gallery image; avatars, badges, embedded play icons and
    // unrelated next siblings cannot establish a media-only review.
    if (!content && !(explicitStructure && reviewerName && gallery === knownGallery && images.length)) return null;
    const stats = first(card, ".swfDpKGt,[data-e2e='review-stats'],[data-role='review-stats']")
      || children.find((node) => node !== header && node !== body && /(?:浏览|有用)/.test(text(node)));
    const helpfulMatch = text(stats).match(/(?:有用\s*([\d,]+)|([\d,]+)\s*(?:人觉得)?有用)/);
    const helpfulNode = first(stats, ".X2TC7MK5,[data-role='review-helpful-count']");
    const helpfulNodeText = text(helpfulNode);
    const helpfulCount = /^\d[\d,]*$/.test(helpfulNodeText) ? Number(helpfulNodeText.replace(/,/g, ""))
      : !helpfulNode && helpfulMatch ? Number((helpfulMatch[1] || helpfulMatch[2]).replace(/,/g, "")) : null;
    const extraRows = children.filter((node) => ![header, sku, body, gallery, stats].includes(node));
    const followups = [];
    let hasUnparsedFollowup = false;
    let merchantReply = "";
    for (const node of extraRows) {
      const value = text(node);
      if (/^(?:\d+\s*天后)?追评/.test(value)) {
        const followupBody = first(node, "[data-e2e='review-content'],[data-role='review-content'],.mgNuPdjB");
        if (followupBody && text(followupBody)) {
          followups.push({ content: text(followupBody), dateText: value.match(/^(?:\d+\s*天后)?追评/)?.[0] || "追评", images: galleryImages(first(node, "[data-role='review-images'],.AdYl5cnz")) });
        } else hasUnparsedFollowup = true;
      } else if (/^商家回复\s*[:：]/.test(value)) {
        merchantReply = value.replace(/^商家回复\s*[:：]\s*/, "");
      }
    }
    return {
      reviewId: clean(card.getAttribute?.("data-review-id") || card.getAttribute?.("data-comment-id")),
      reviewerName,
      dateText,
      purchasedSku: text(sku),
      content,
      contentStatus: content ? "text_observed" : "media_only",
      images,
      helpfulCount,
      followups,
      followupStatus: followups.length ? "observed" : hasUnparsedFollowup ? "unparsed" : "not_observed",
      hasUnparsedFollowup,
      merchantReply
    };
  }

  function createCollector(adapters) {
    const document = adapters.document;
    const window = adapters.window;
    const visible = adapters.isVisible;
    const rendered = adapters.isRendered || visible;
    const now = adapters.now || Date.now;
    const wait = adapters.sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
    const bounds = {
      maxRows: Math.max(1, Math.min(2000, Number(adapters.limits?.maxRows) || 2000)),
      maxScrolls: Math.max(1, Math.min(200, Number(adapters.limits?.maxScrolls) || 200)),
      maxMs: Math.max(1000, Math.min(600000, Number(adapters.limits?.maxMs) || 600000)),
      delayMs: Math.max(1000, Number(adapters.limits?.delayMs) || 1100),
      maxNoGrowth: Math.max(3, Number(adapters.limits?.maxNoGrowth) || 8)
    };
    let panelSession = null;
    let serial = 0;
    let activeRun = null;
    let observer = null;
    const owned = (node) => Boolean(node?.closest?.('[id^="brandbai-"]'));
    const live = (node) => Boolean(node && node.isConnected !== false && visible(node)
      && !node.closest?.('[hidden],[inert],[aria-hidden="true"]') && !owned(node));
    const instanceId = (kind) => `${adapters.documentToken}:${kind}:${++serial}`;

    function clearPanelSession() { panelSession = null; }

    function installObserver() {
      if (observer || !window?.MutationObserver || !document?.documentElement) return;
      observer = new window.MutationObserver((mutations) => {
        const panel = panelSession?.panel;
        if (!panel) return;
        for (const mutation of mutations) {
          if (Array.from(mutation.removedNodes || []).some((node) => node === panel || node.contains?.(panel))) {
            clearPanelSession();
            break;
          }
          if (mutation.type === "attributes" && (mutation.target === panel || mutation.target.contains?.(panel))
            && (mutation.attributeName === "hidden" || mutation.attributeName === "aria-hidden"
              || /(?:display\s*:\s*none|visibility\s*:\s*hidden|content-transition-(?:exit|leave))|(?:^|\s)(?:hidden|closed)(?:\s|$)/i.test(mutation.oldValue || ""))) {
            clearPanelSession();
            break;
          }
        }
        if (panelSession && !live(panelSession.panel)) clearPanelSession();
      });
      observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeOldValue: true, attributeFilter: ["hidden", "aria-hidden", "style", "class"] });
    }

    function tabRoot(panel) {
      const known = first(panel, ".NGeinxLS");
      const knownTabs = first(known, ".yVU8TMWn") || known;
      if (known && /商品详情/.test(text(knownTabs)) && /商品评价/.test(text(knownTabs))) return known;
      return all(panel, "section,div").filter((node) => /商品详情/.test(text(node)) && /商品评价/.test(text(node)))
        .sort((a, b) => all(a, "*").length - all(b, "*").length)[0] || null;
    }

    function findPanel(allowFallback = true) {
      const knownCandidates = Array.from(new Set([
        ...all(document, ".eRfaxg7R"), panelSession?.panel,
        ...all(document, ".lqrK15Gt,[role='dialog'],[aria-modal='true']")
      ].filter(Boolean)));
      const valid = (node) => {
        if (!live(node) || !tabRoot(node)) return false;
        const headers = all(node, ".vs9hmvGz,.AjnzIIcY");
        return headers.length ? headers.some((header) => rendered(header) && !header.closest?.('[hidden],[inert],[aria-hidden="true"]'))
          : /立即购买|加入购物车|保障|物流/.test(text(node));
      };
      const candidates = knownCandidates.filter(valid);
      if (!candidates.length && allowFallback) {
        const supplied = adapters.findProductPanel?.();
        if (supplied && valid(supplied)) candidates.push(supplied);
      }
      const smallest = candidates.filter((node) => !candidates.some((other) => other !== node && node.contains(other)));
      return { panel: smallest.length === 1 ? smallest[0] : null, ambiguous: smallest.length > 1, detected: candidates.length > 0 };
    }

    function readProductHeader(panel, tabs, work) {
      const outsideReviews = (node) => !tabs?.contains(node) && !node.closest?.(".FDag2E0P,.PEzhiR4O");
      const currentHeaderNode = (node) => Boolean(node && node.isConnected !== false && rendered(node) && outsideReviews(node)
        && !node.closest?.('[hidden],[inert],[aria-hidden="true"]') && !owned(node));
      const distinctText = (nodes) => Array.from(new Set(nodes.map(text).filter(Boolean)));
      const renderedHeaderImage = (node) => Boolean(currentHeaderNode(node)
        && !node.closest?.(".sVIJnLfX,.ji7a60UU,[class*='avatar' i]")
        && !/aweme[-_]?qrcode|qr[-_]?code/i.test(node.currentSrc || node.src || node.getAttribute("src") || ""));
      // A thumbnail is an explicitly identified main-gallery role, not the
      // first large bitmap anywhere in the product panel (QR/avatar/banner).
      const mainGalleries = all(panel, ".swiper-container,[data-e2e='product-main-gallery'],[data-role='product-main-gallery']")
        .filter((node) => outsideReviews(node) && rendered(node) && node.isConnected !== false
          && !node.closest?.('[hidden],[inert],[aria-hidden="true"]')
          && (node.matches?.("[data-e2e='product-main-gallery'],[data-role='product-main-gallery']")
            || (node.parentElement?.matches?.(".cTtrxUrv") && node.closest?.(".qVqbID8l"))));
      const firstSlides = mainGalleries.length === 1
        ? all(mainGalleries[0], '[data-swiper-slide-index="0"]').filter((node) => !node.matches?.(".swiper-slide-duplicate")
          && !node.closest?.('[hidden],[inert],[aria-hidden="true"]') && node.isConnected !== false && rendered(node)) : [];
      const mainImages = firstSlides.length === 1 ? all(firstSlides[0], "img").filter((node) => renderedHeaderImage(node)
        && mediaUrl(node.currentSrc || node.src || node.getAttribute("src"))
        && Math.min(Number(node.naturalWidth || 0), Number(node.naturalHeight || 0)) >= 300) : [];
      const mainThumbnailUrl = mainImages.length === 1 ? mediaUrl(mainImages[0].currentSrc || mainImages[0].src || mainImages[0].getAttribute("src")) : "";
      const titleNodes = all(panel, ".vs9hmvGz,[data-e2e='product-title'],[data-role='product-title']").filter(currentHeaderNode);
      const shopNodes = all(panel, ".AjnzIIcY,[data-e2e='shop-name'],[data-role='shop-name']").filter(currentHeaderNode);
      const headerLeaves = all(panel, "h1,h2,h3,h4,p,div,span").filter((node) => currentHeaderNode(node)
        && !Array.from(node.children || []).some((child) => text(child).length > 3));
      const shopCandidates = headerLeaves.filter((node) => /(?:旗舰店|专卖店|专营店|官方店)$/.test(text(node)) && text(node).length <= 80);
      const titleCandidates = headerLeaves.filter((node) => !shopNodes.includes(node) && !shopCandidates.includes(node)
        && text(node).length >= 8 && text(node).length <= 220
        && !/^(?:立即购买|客服|进店|推荐|保障|物流|选择|商品评价|商品详情|价格说明|￥|¥|已售|销量|\d)/.test(text(node)));
      const explicitTitles = distinctText(titleNodes);
      const explicitShops = distinctText(shopNodes);
      const titleValues = explicitTitles.length ? explicitTitles : distinctText(titleCandidates);
      const shopValues = explicitShops.length ? explicitShops : distinctText(shopCandidates);
      // Recycled panels can retain both products' headers. Identical copies
      // are harmless; conflicting visible titles/shops are not a ranking
      // problem and must not be resolved by DOM order or font-size scoring.
      const title = titleValues.length === 1 ? titleValues[0] : "";
      const shopName = shopValues.length === 1 ? shopValues[0] : "";
      const identityConflict = titleValues.length > 1 || shopValues.length > 1;
      const reliableHeader = Boolean(title && !identityConflict);
      const thumbnailUrl = reliableHeader ? mainThumbnailUrl : "";
      const thumbnailSource = thumbnailUrl ? first(firstSlides[0], "video,.CcoHiZjd") ? "main_video_poster" : "product_main" : "";
      const images = all(panel, "img").filter((node) => renderedHeaderImage(node)
        && Math.min(Number(node.naturalWidth || 0), Number(node.naturalHeight || 0)) >= 300)
        .map((node) => mediaUrl(node.currentSrc || node.src || node.getAttribute("src"))).filter(Boolean);
      const imageRows = Array.from(new Set([...(thumbnailUrl ? [thumbnailUrl] : []), ...images])).slice(0, 30)
        .map((url) => ({ url, kind: url === thumbnailUrl ? thumbnailSource : "product_image" }));
      const titleNode = reliableHeader ? titleNodes.find((node) => text(node) === title) : null;
      const explicitId = clean(panel.getAttribute?.("data-product-id") || titleNode?.getAttribute?.("data-product-id"));
      const productId = /^\d{6,24}$/.test(explicitId) ? explicitId : "";
      const headerText = headerLeaves.map(text).join(" ");
      const evidence = identityConflict ? `conflict:${hash(JSON.stringify([titleValues.sort(), shopValues.sort()]))}`
        : `${productId ? `id:${productId}|` : ""}${title}|${shopName}`;
      return {
        productId,
        productKey: reliableHeader ? productId ? `product:${productId}` : `visible:${hash(evidence)}` : "",
        title, shopName, images: imageRows, thumbnailUrl, thumbnailSource,
        priceText: headerText.match(/(?:￥|¥)\s*\d+(?:\.\d+)?(?:\s*起)?/)?.[0] || "",
        detailUrl: "",
        sourceWorkId: work.sourceWorkId,
        sourceSurfaceInstance: work.sourceSurfaceInstance,
        identityStatus: reliableHeader ? productId ? "verified" : "panel_bound" : "unconfirmed",
        identityConflict,
        evidence
      };
    }

    function findList(panel, tabs) {
      const listIsLive = (node) => node?.isConnected !== false && rendered(node)
        && !node.closest?.('[hidden],[inert],[aria-hidden="true"]') && !owned(node);
      const known = all(tabs || panel, ".PEzhiR4O,[data-e2e='product-review-list'],[data-role='product-review-list']").filter(listIsLive);
      if (known.length === 1) return known[0];
      if (known.length > 1) return null;
      const area = first(tabs || panel, ".FDag2E0P") || tabs;
      if (!area) return null;
      const candidates = all(area, "div,section,ul").filter((node) => listIsLive(node)
        && Array.from(node.children || []).filter((child) => readReviewCard(child)).length >= 2);
      return candidates.length === 1 ? candidates[0] : null;
    }

    function reviewRows(list) {
      const children = Array.from(list?.children || []).filter((node) => rendered(node) && !owned(node));
      const rows = [];
      let unparsed = 0;
      const footerTexts = [];
      for (const child of children) {
        const row = readReviewCard(child);
        if (row) rows.push(row);
        else if (/^(?:加载中[.。…]*|正在加载[.。…]*|暂无更多(?:商品)?评价|没有更多(?:商品)?评价|已展示全部评价|全部评价已加载|暂无评价|还没有评价|暂无相关评价|暂无评论|没有更多了|暂无更多了)$/.test(text(child))) {
          // A pre-rendered terminal node below the viewport is not yet a
          // witnessed bottom. Scroll the bound panel until it is visible.
          let statusVisible = visible(child);
          const rect = child.getBoundingClientRect?.();
          for (let ancestor = child.parentElement; statusVisible && rect && ancestor; ancestor = ancestor.parentElement) {
            if (!/auto|scroll|hidden|clip/.test(window.getComputedStyle(ancestor).overflowY)) continue;
            const bounds = ancestor.getBoundingClientRect?.();
            if (bounds && (rect.bottom <= bounds.top || rect.top >= bounds.bottom)) statusVisible = false;
          }
          if (statusVisible) footerTexts.push(text(child));
        }
        else if (text(child) || all(child, "img").length) unparsed += 1;
      }
      const explicitEnd = footerTexts.some((value) => /^(?:暂无更多(?:商品)?评价|没有更多(?:商品)?评价|已展示全部评价|全部评价已加载|没有更多了|暂无更多了)$/.test(value));
      const emptyConfirmed = !rows.length && footerTexts.some((value) => /^(?:暂无评价|还没有评价|暂无相关评价|暂无评论)$/.test(value));
      return { rows, unparsed, explicitEnd, emptyConfirmed, loading: footerTexts.some((value) => /加载中|正在加载/.test(value)) };
    }

    function filtersFor(list, tabs) {
      const area = list?.closest?.(".FDag2E0P") || list?.parentElement || tabs;
      if (!area) return { key: "filter:not_open", label: "当前筛选" };
      let nodes = all(area, ".YLWPPuPR,.NtPaXoT7,.yCVc5DaW,[aria-selected],[aria-pressed],[data-state]")
        .filter((node) => !list?.contains(node) && !owned(node) && rendered(node) && text(node).length <= 80);
      if (!nodes.length) nodes = all(area, "button,span,[role='tab']").filter((node) => !list?.contains(node)
        && !owned(node) && rendered(node) && /^(?:全部|有图|视频|追评|好评|中评|差评|综合|最新)(?:\s*[（(][\d,]+[）)])?$/.test(text(node)));
      const observations = nodes.map((node) => {
        const style = window.getComputedStyle(node);
        const className = clean(node.getAttribute?.("class"));
        const color = clean(style.color);
        const rgb = color.match(/rgba?\(\s*(\d+),\s*(\d+),\s*(\d+)/);
        const selected = node.getAttribute?.("aria-selected") === "true" || node.getAttribute?.("aria-pressed") === "true"
          || node.getAttribute?.("data-state") === "active" || /(?:^|\s)(?:SrtfuQFU|mFEHKTxv)(?:\s|$)/.test(className)
          || Boolean(rgb && Number(rgb[1]) > 180 && Number(rgb[1]) > Number(rgb[2]) * 1.5);
        return { label: text(node), className, color, weight: clean(style.fontWeight), selected, ariaSelected: node.getAttribute?.("aria-selected") || "", ariaPressed: node.getAttribute?.("aria-pressed") || "" };
      });
      return { key: `filter:${hash(JSON.stringify(observations))}`, label: observations.filter((row) => row.selected).map((row) => row.label).join(" · ") || "当前筛选" };
    }

    function getSafetyState(panel) {
      if (document.visibilityState === "hidden") return { reason: "页面已转入后台，已停止自动加载", code: "page_hidden" };
      const verification = all(document, "[id*='captcha' i],[class*='captcha' i],[data-e2e*='verify' i]").some(live);
      if (verification) return { reason: "页面出现安全验证，请先手动处理", code: "verification_required" };
      const warnings = all(document, "[role='dialog'],[aria-modal='true'],[role='alert']").filter((node) => node !== panel
        && !panel?.contains(node) && !node.contains?.(panel) && live(node) && text(node).length < 1500);
      if (warnings.some((node) => /访问过于频繁|操作频繁|安全验证|异常行为|账号.*限制|登录后(?:查看|继续)|请先登录/.test(text(node)))) {
        return { reason: "页面提示登录、验证或访问限制，请先手动处理", code: "platform_warning" };
      }
      return null;
    }

    function inspect() {
      if (adapters.inspectSurface) return adapters.inspectSurface();
      installObserver();
      const found = findPanel();
      if (!found.panel) {
        clearPanelSession();
        return { surface: { mode: found.detected ? "product" : "work", ready: false, lease: null, product: null, visibleReviewCount: null, declaredReviewCount: null, filterLabel: "", reasonCode: found.ambiguous ? "ambiguous_product_panel" : "product_not_open", reason: found.ambiguous ? "页面存在多个商品面板，请保留目标商品面板" : "请先打开当前作品的商品面板" }, rows: [], unparsed: 0 };
      }
      const panel = found.panel;
      const work = adapters.getWorkContext();
      const tabs = tabRoot(panel);
      const product = readProductHeader(panel, tabs, work);
      const workIdentity = JSON.stringify([work.contextKey, work.generation, work.sourceWorkId, work.sourceSurfaceInstance]);
      if (!panelSession || panelSession.panel !== panel || panelSession.workIdentity !== workIdentity || panelSession.evidence !== product.evidence) {
        panelSession = { panel, workIdentity, evidence: product.evidence, instanceId: instanceId("product"), list: null, reviewId: "" };
      }
      const list = findList(panel, tabs);
      if (panelSession.list !== list) {
        panelSession.list = list;
        panelSession.reviewId = list ? instanceId("reviews") : "";
      }
      const parsed = list ? reviewRows(list) : { rows: [], unparsed: 0, explicitEnd: false, emptyConfirmed: false, loading: false };
      const filters = filtersFor(list, tabs);
      const totalMatch = text(first(tabs, ".yVU8TMWn") || tabs).match(/商品评价\s*[（(]\s*([\d,]+)\s*[）)]/);
      const declaredReviewCount = totalMatch ? Number(totalMatch[1].replace(/,/g, "")) : null;
      const safety = getSafetyState(panel);
      const identityReady = Boolean(product.title && product.identityStatus !== "unconfirmed" && work.documentToken && work.contextKey && work.generation && work.sourceWorkId && work.sourceSurfaceInstance);
      const lease = list && identityReady ? cloneLease({ ...work, documentToken: adapters.documentToken,
        productPanelInstanceId: panelSession.instanceId, reviewSurfaceInstanceId: panelSession.reviewId, filterKey: filters.key }) : null;
      const ready = Boolean(lease && (parsed.rows.length || parsed.emptyConfirmed) && !safety);
      const reason = (safety?.reason || !identityReady) ? safety?.reason || (product.identityConflict ? "当前商品标题或店铺存在冲突，请等待面板切换完成后重新识别" : "当前商品或作品身份尚未确认，请重新读取商品")
        : !list ? "请在商品面板打开“商品评价”"
          : parsed.unparsed ? "部分评价结构尚未识别，将保留可读取内容并报告缺失"
            : !ready ? parsed.loading ? "评价正在加载，请稍后重试" : "尚未识别到有效商品评价，不能视为空评价" : "";
      const reasonCode = safety?.code || (!identityReady ? product.identityConflict ? "product_header_conflict" : "source_identity_unconfirmed" : !list ? "reviews_not_open"
        : parsed.unparsed ? "selector_drift" : !ready ? parsed.loading ? "reviews_loading" : "reviews_unverified" : "");
      const { evidence: _evidence, ...displayProduct } = product;
      return { surface: { mode: "product", ready, lease, product: displayProduct,
        documentToken: adapters.documentToken, contextKey: work.contextKey, generation: work.generation,
        productPanelInstanceId: panelSession.instanceId,
        visibleReviewCount: list ? parsed.rows.length + parsed.unparsed : null,
        parsedReviewCount: list ? parsed.rows.length : null, unparsedReviewCount: list ? parsed.unparsed : null,
        declaredReviewCount, filterLabel: filters.label, reason, reasonCode },
        panel, list, ...parsed, safety };
    }

    function getSurfaceState() { return inspect().surface; }

    function getInlineReviewAnchor() {
      const state = inspect();
      const { surface } = state;
      if (!state.list || !surface.lease || state.safety || surface.product?.identityStatus === "unconfirmed") return { anchor: null, surface };
      const bars = all(state.panel, ".yVU8TMWn").filter((node) => node.isConnected !== false && rendered(node) && !owned(node)
        && !node.closest?.('[hidden],[inert],[aria-hidden="true"]') && /商品详情/.test(text(node)) && /商品评价/.test(text(node)));
      return { anchor: bars.length === 1 ? bars[0] : null, surface };
    }

    function getMode() {
      installObserver();
      const found = findPanel(false);
      if (!found.detected || (panelSession && found.panel !== panelSession.panel)) clearPanelSession();
      return found.detected ? "product" : "work";
    }

    function locateReviewTab(panelIdentity) {
      const fail = (reasonCode, reason) => ({ ok: false, found: false, reasonCode, reason, error: reason });
      if (activeRun || adapters.hasActiveTransaction?.()) return fail("operation_running", "请先暂停或等待当前读取任务完成，再定位商品评价");
      const state = inspect();
      if (state.safety) return fail(state.safety.code, state.safety.reason);
      const fields = ["documentToken", "contextKey", "generation", "productPanelInstanceId"];
      const samePanel = (surface) => surface?.mode === "product" && surface.product?.identityStatus !== "unconfirmed" && fields.every((field) => typeof panelIdentity?.[field] === "string"
        && panelIdentity[field].length > 0 && panelIdentity[field] === surface[field]);
      if (!samePanel(state.surface)) return fail("panel_changed", "当前商品面板已变化，请重新识别后再定位");
      const candidates = all(state.panel, ".yVU8TMWn").flatMap((bar) => all(bar, "div,span,button,[role='tab']"))
        .filter((node) => node.isConnected !== false && rendered(node) && !owned(node) && !node.closest?.('[hidden],[inert],[aria-hidden="true"]')
          && /^商品评价(?:[（(][\d,]+[）)])?$/.test(text(node).replace(/\s+/g, "")));
      const exactTabs = candidates.filter((node) => !candidates.some((other) => other !== node && node.contains(other)));
      if (exactTabs.length !== 1) return { ok: true, found: false, reasonCode: "review_tab_unavailable", reason: "暂未找到唯一的商品评价入口，请在当前商品面板手动打开“商品评价”" };
      const current = inspect();
      if (current.safety || activeRun || adapters.hasActiveTransaction?.()) return fail("operation_unavailable", current.safety?.reason || "当前已有读取任务，请先暂停");
      const target = exactTabs[0];
      if (!samePanel(current.surface) || current.panel !== state.panel || !current.panel.contains(target)
        || target.isConnected === false || !rendered(target)) return fail("panel_changed", "当前商品面板已变化，请重新识别后再定位");
      // This is navigation guidance only: no click, no tab change, no review
      // capture, no product selection, and no window-level scroll fallback.
      if (typeof target.scrollIntoView !== "function") return { ok: true, found: false, reasonCode: "review_tab_unavailable", reason: "请在当前商品面板手动打开“商品评价”" };
      target.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" });
      target.animate?.([{ outline: "3px solid #ff8a24", outlineOffset: "5px" }, { outline: "3px solid transparent", outlineOffset: "8px" }], { duration: 2200, easing: "ease-out" });
      return { ok: true, found: true };
    }

    function validation(run) {
      if (activeRun !== run) return { code: "superseded", reason: "评价任务已切换" };
      const current = inspect();
      if (current.safety) return { ...current.safety, state: current };
      if (document.visibilityState === "hidden") return { code: "page_hidden", reason: "页面已转入后台", state: current };
      if (!leaseEquals(run.lease, current.surface.lease)) {
        const code = current.surface.mode !== "product" ? "product_panel_closed"
          : run.lease.filterKey !== current.surface.lease?.filterKey ? "surface_or_filter_changed" : "product_or_work_changed";
        return { code, reason: "当前商品、评价面板、筛选或作品已经变化", state: current };
      }
      try { adapters.assertTransaction?.(run.transaction); }
      catch (error) { return { code: "product_or_work_changed", reason: error?.message || String(error), state: current }; }
      return { state: current };
    }

    function rowKey(row) {
      const version = hash(JSON.stringify([row.reviewerName, row.dateText, row.purchasedSku,
        row.content, row.contentStatus, row.images, row.helpfulCount, row.followups,
        row.followupStatus, row.hasUnparsedFollowup, row.merchantReply]));
      return row.reviewId ? `platform:${row.reviewId}:${version}` : `derived:${version}`;
    }

    function progressSnapshot(run, state, phase) {
      return {
        sequence: ++run.progressSequence, phase,
        elapsedMs: Math.max(0, Math.floor(now() - run.startedAt)), scrollActions: run.scrollActions,
        visibleReviewCount: state?.surface?.visibleReviewCount ?? null,
        parsedReviewCount: state?.surface?.parsedReviewCount ?? state?.rows?.length ?? null,
        unparsedReviewCount: state?.surface?.unparsedReviewCount ?? state?.unparsed ?? null
      };
    }

    async function reportProgress(run, state, phase) {
      if (validation(run).code) return false;
      // Local task telemetry only: no extra platform requests or independent
      // polling loop. Saving acknowledgements remain the sole count authority.
      const response = await adapters.sendMessage({ type: "PROGRESS_DOUYIN_COMMERCE_REVIEWS", taskId: run.taskId,
        runId: run.runId, lease: run.lease, progress: progressSnapshot(run, state, phase) });
      if (activeRun !== run) return false;
      if (response?.ok === false || response?.ignored || response?.task?.id !== run.taskId || response?.task?.runId !== run.runId) {
        throw new Error(response?.error || "商品评价进度未被当前任务确认");
      }
      return !validation(run).code;
    }

    async function capture(run, state) {
      if (validation(run).code) return;
      const remaining = bounds.maxRows - run.visited.size;
      const rows = state.rows.filter((row) => !run.visited.has(rowKey(row))).slice(0, Math.max(0, remaining));
      for (let offset = 0; offset < rows.length; offset += 100) {
        const checked = validation(run);
        if (checked.code) return;
        const batch = rows.slice(offset, offset + 100);
        if (!await reportProgress(run, checked.state, "saving")) return;
        const response = await adapters.sendMessage({ type: "CAPTURE_DOUYIN_COMMERCE_REVIEWS", taskId: run.taskId, runId: run.runId, lease: run.lease,
          rows: batch, progress: progressSnapshot(run, checked.state, "reading"),
          scrollActions: run.scrollActions, visibleReviewCount: state.surface.visibleReviewCount, declaredReviewCount: state.surface.declaredReviewCount });
        if (activeRun !== run) return;
        if (response?.ignored || response?.ok === false || !response?.task) throw new Error(response?.error || "商品评价批次未被当前任务接受");
        if (response.task.id !== run.taskId || response.task.runId !== run.runId) throw new Error("商品评价保存返回了其他任务");
        if (!Number.isInteger(response.task.reviewCount) || response.task.reviewCount < 0) throw new Error("商品评价保存结果缺少有效数量");
        batch.forEach((row) => run.visited.add(rowKey(row)));
        run.savedCount = response.task.reviewCount;
        run.hadUnparsedFollowup ||= batch.some((row) => row.hasUnparsedFollowup);
        if (validation(run).code) return;
      }
    }

    function scroll(state, run) {
      let owner = null;
      for (let node = state.list; node && state.panel?.contains(node); node = node.parentElement) {
        const style = window.getComputedStyle(node);
        if (live(node) && /auto|scroll/.test(style.overflowY) && node.scrollHeight > node.clientHeight + 2) {
          owner = node;
          break;
        }
        if (node === state.panel) break;
      }
      // No owner is not evidence of an exhausted list. Never fall back to
      // body/window (or the adjacent purchase/SKU panel).
      if (!owner || typeof owner.scrollTo !== "function") return { moved: false, atBottom: false, reasonCode: "scroll_container_unavailable" };
      if (run.scrollOwner && run.scrollOwner !== owner) return { moved: false, atBottom: false, reasonCode: "scroll_container_changed" };
      run.scrollOwner = owner;
      const before = Number(owner.scrollTop || 0);
      const maxTop = Math.max(0, owner.scrollHeight - owner.clientHeight);
      const top = Math.min(maxTop, before + Math.max(500, owner.clientHeight * .8));
      owner.scrollTo({ top, left: owner.scrollLeft || 0, behavior: "instant" });
      return { moved: Math.abs(owner.scrollTop - before) > 2, atBottom: owner.scrollTop >= maxTop - 3 };
    }

    async function finish(run, detail, state) {
      if (activeRun !== run || run.finishing) return;
      run.finishing = true;
      // A changed surface explains interruption, but its counts belong to
      // another product/filter and must not overwrite the old run's scope.
      const sameSourceState = leaseEquals(run.lease, state?.surface?.lease) ? state : null;
      const response = await adapters.sendMessage({ type: "FINISH_DOUYIN_COMMERCE_REVIEWS", taskId: run.taskId, runId: run.runId, lease: run.lease,
        ...detail, progress: progressSnapshot(run, sameSourceState, "reading"), scrollActions: run.scrollActions, visibleReviewCount: sameSourceState?.surface?.visibleReviewCount ?? null,
        declaredReviewCount: sameSourceState?.surface?.declaredReviewCount ?? null });
      if (response?.ignored || response?.ok === false || !response?.task
        || response.task.id !== run.taskId || response.task.runId !== run.runId) throw new Error(response?.error || "商品评价结束状态保存失败");
      run.result = { ok: true, task: response?.task };
    }

    async function runLoop(run) {
      let noGrowth = 0;
      let stalledScroll = 0;
      let lastSaved = -1;
      let lastVisible = -1;
      let lastScroll = { moved: true, atBottom: false };
      try {
        while (activeRun === run) {
          const checked = validation(run);
          if (checked.code) return await finish(run, { status: "interrupted", doneReason: checked.code, completeness: `partial_${checked.code}`, exhausted: false }, checked.state);
          await capture(run, checked.state);
          const afterCapture = validation(run);
          if (afterCapture.code) return await finish(run, { status: "interrupted", doneReason: afterCapture.code, completeness: `partial_${afterCapture.code}`, exhausted: false }, afterCapture.state);
          const state = afterCapture.state;
          // The list may append while the storage acknowledgement is in
          // flight. Flush that same-lease data before pause/end, not only the
          // earlier DOM snapshot that happened to contain the footer.
          if (run.visited.size < bounds.maxRows && state.rows.some((row) => !run.visited.has(rowKey(row)))) continue;
          if (run.pauseRequested) return await finish(run, { status: "paused", doneReason: "user_paused", completeness: "partial_user_paused", exhausted: false }, afterCapture.state);
          if (state.unparsed || run.hadUnparsedFollowup) return await finish(run, { status: "interrupted", doneReason: "selector_drift", completeness: "partial_selector_drift", exhausted: false }, state);
          if (run.visited.size >= bounds.maxRows && state.rows.some((row) => !run.visited.has(rowKey(row)))) {
            return await finish(run, { status: "interrupted", doneReason: "run_budget", completeness: "partial_limit_sample", exhausted: false }, state);
          }
          if ((state.explicitEnd || state.emptyConfirmed) && (run.savedCount > 0 || state.emptyConfirmed)) {
            return await finish(run, { status: "finished", doneReason: "source_exhausted", completeness: "complete_visible_panel_exhausted", exhausted: true, emptyConfirmed: Boolean(state.emptyConfirmed) }, state);
          }
          if (run.visited.size >= bounds.maxRows || run.scrollActions >= bounds.maxScrolls || now() - run.startedAt >= bounds.maxMs) {
            return await finish(run, { status: "interrupted", doneReason: "run_budget", completeness: "partial_limit_sample", exhausted: false }, state);
          }
          const count = Number(state.surface.visibleReviewCount || 0);
          noGrowth = !lastScroll.moved && lastScroll.atBottom && run.savedCount === lastSaved && count <= lastVisible ? noGrowth + 1 : 0;
          stalledScroll = !lastScroll.moved && !lastScroll.atBottom && run.savedCount === lastSaved && count <= lastVisible ? stalledScroll + 1 : 0;
          lastSaved = run.savedCount;
          lastVisible = count;
          if (noGrowth >= bounds.maxNoGrowth) return await finish(run, { status: "interrupted", doneReason: state.loading ? "loading_stalled" : "no_growth", completeness: "partial_current_loaded", exhausted: false }, state);
          if (stalledScroll >= bounds.maxNoGrowth) return await finish(run, { status: "interrupted", doneReason: "scroll_stalled", completeness: "partial_scroll_stalled", exhausted: false }, state);
          if (validation(run).code) continue;
          lastScroll = adapters.scrollSurface ? adapters.scrollSurface(state) : scroll(state, run);
          lastScroll ||= { moved: false, atBottom: false };
          if (lastScroll.reasonCode) return await finish(run, { status: "interrupted", doneReason: lastScroll.reasonCode, completeness: `partial_${lastScroll.reasonCode}`, exhausted: false }, state);
          run.scrollActions += 1;
          if (!await reportProgress(run, state, lastScroll.moved ? "scrolling" : "waiting")) continue;
          await wait(bounds.delayMs);
        }
      } catch (error) {
        run.error = error?.message || String(error);
        if (activeRun === run && !run.finishing) {
          try {
            await finish(run, { status: "interrupted", doneReason: "collector_error", completeness: "partial_collector_error", exhausted: false, error: run.error }, null);
          } catch (finishError) { run.error += `；${finishError?.message || String(finishError)}`; }
        }
      } finally {
        adapters.finishTransaction?.(run.transaction);
        if (activeRun === run) activeRun = null;
      }
    }

    function start(task) {
      if (activeRun) throw new Error("当前商品评价任务正在运行，请先暂停");
      if (!task?.id || !task.runId) throw new Error("商品评价任务缺少运行标识");
      const state = inspect();
      if (!state.surface.ready || !leaseEquals(task.lease, state.surface.lease)) throw new Error(state.surface.reason || "商品或评价面板已经变化，请重新识别");
      const run = { taskId: String(task.id), runId: String(task.runId), lease: cloneLease(task.lease), startedAt: now(), scrollActions: 0,
        savedCount: Number(task.reviewCount || 0), visited: new Set(), pauseRequested: false, finishing: false, hadUnparsedFollowup: false, result: null, error: "", progressSequence: 0 };
      run.transaction = adapters.beginTransaction?.();
      activeRun = run;
      run.completion = runLoop(run);
      run.completion.catch(() => {});
      return { ok: true, taskId: run.taskId, runId: run.runId };
    }

    async function pause(request) {
      const run = activeRun;
      if (!run || String(request?.taskId) !== run.taskId || String(request?.runId) !== run.runId) return { ok: false, error: "当前商品评价运行已结束或已切换，请刷新状态" };
      run.pauseRequested = true;
      await run.completion;
      return run.error ? { ok: false, error: run.error } : run.result || { ok: true };
    }

    async function waitForIdle() { if (activeRun) await activeRun.completion; }
    function configureLimits(limits) {
      if (activeRun) throw new Error("Cannot change an active review run's limits");
      bounds.maxRows = Math.max(1, Math.min(2000, Number(limits?.maxRows) || 2000));
      bounds.maxScrolls = Math.max(1, Math.min(200, Number(limits?.maxScrolls) || 200));
      bounds.maxMs = Math.max(1000, Math.min(600000, Number(limits?.maxMs) || 600000));
    }
    return { getSurfaceState, getMode, getInlineReviewAnchor, locateReviewTab, start, pause, waitForIdle, configureLimits };
  }

  const api = { createCollector, readReviewCard, leaseEquals, mediaUrl };
  if (typeof module === "object" && module.exports) module.exports = api;
  root.BrandbaiDouyinCommerceReviewCollector = api;
})(typeof globalThis === "object" ? globalThis : this);
