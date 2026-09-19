/* Independent product workspace. Shares only connection/storage helpers with recording. */
"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const key = 'brandbaiIndependentProductDownload';
  const overviewKey = 'brandbaiProductWorkspaceOverview';
  let visible = false, preview = null, busy = false, reading = false, polling = false;
  let job = null, generation = 0, misses = 0, preparation = null;
  let actionKind = 'product', launchCanceled = false;
  let overview = null, currentOverviewRoom = null, recent = {};
  let syncWarning = '', restoring = true;
  let capturePending = null;
  window.BrandbaiMaterialsBusy=()=>busy||['running','collecting','submitting','unconfirmed'].includes(job?.state);
  window.BrandbaiCurrentProduct={get:()=>preview,inspect:currentCapture,isReading:()=>Boolean(capturePending),
    hold:value=>{if(value){preview=value;renderPreview(value);controls();}},refresh:refreshPreview};
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const signature = (p) => JSON.stringify([p?.room_url, p?.panel_key, p?.snapshot]);
  const terminal = value => ['complete_observed','partial','failed'].includes(value?.state);
  const belongsToCurrent = value => Boolean(preview && value?.current_product
    && preview.room_url === value.current_product.room_url
    && window.BrandbaiProductIdentity.same(preview.snapshot?.product_identity, value.current_product.snapshot?.product_identity));
  const previousProductResult = () => job && (job.kind || 'product') === 'product' && terminal(job) && !belongsToCurrent(job);
  const recognitionHints = Object.freeze({
    unsupported_page:'当前标签页未确认是抖音直播间。请在已打开直播间的标签页点击采集助手图标后重试。',
    unavailable:'无法连接当前商品页。请点击浏览器工具栏中的采集助手图标后重试；重新加载过插件时，请刷新直播页。',
    read_timeout:'商品页读取暂未完成，本次尚未开始下载。请保持页面打开，稍后重试。',
    read_failed:'页面已连接，但商品信息读取失败，本次尚未开始下载。请重新识别；仍失败时请反馈当前页面。',
    incomplete:'已检测到商品面板，但标题、店铺或图片尚未确认。请保持商品页打开，稍后重新识别。',
    ambiguous:'检测到多个商品面板，尚未确认当前商品。请关闭多余面板，再重新识别。',
    identity_conflict:'商品身份信息有冲突，暂不下载。请关闭后重新打开目标商品，再重新识别。',
    changed:'商品或页面已变化，请保持目标商品打开后重新识别。'
  });
  function recognitionError(reason) {
    const error=new Error(recognitionHints[reason]||recognitionHints.unavailable);
    error.recognitionReason=reason;return error;
  }
  function message(value, error = false) {
    $(`${actionKind}-feedback`).append($('product-message'));
    $('product-message').textContent = value;
    $('product-message').classList.toggle('error', error);
    $('product-message').setAttribute('role', error ? 'alert' : 'status');
    $('product-message').setAttribute('aria-live', error ? 'assertive' : 'polite');
    if(error) $('product-message').scrollIntoView({block:'nearest'});
  }
  function controls() {
    // Silent recognition must not toggle an already actionable button every 3 seconds.
    const inFlight = busy || ['running','collecting','submitting'].includes(job?.state);
    const uncertain = job?.state === 'unconfirmed' || window.BrandbaiReviewsBusy?.();
    const kind = busy ? actionKind : job?.kind || 'product';
    $('download-current-product').disabled = restoring || inFlight || uncertain || !preview;
    $('download-current-product').setAttribute('aria-busy', String(inFlight && kind === 'product'));
    $('download-current-product').textContent = kind === 'product' && busy ? '正在准备商品资料……' : kind === 'product' && inFlight ? '正在处理 · 进度见下方' : '下载图片与规格';
    $('download-current-product').classList.toggle('product-primary',Boolean(preview));
    $('download-current-product').classList.toggle('product-secondary',!preview);
    $('download-product-catalog').disabled = restoring || inFlight || uncertain;
    $('download-product-catalog').setAttribute('aria-busy', String(inFlight && kind === 'catalog'));
    $('download-product-catalog').textContent = kind === 'catalog' && busy ? '正在准备商品目录……' : kind === 'catalog' && inFlight ? '正在读取与保存 · 进度见下方' : overview?.room_url===currentOverviewRoom ? '更新商品目录' : '下载商品目录';
    $('download-product-catalog').classList.toggle('product-primary',!preview);
    $('download-product-catalog').classList.toggle('product-secondary',Boolean(preview));
    $('refresh-product').disabled = inFlight || uncertain;
    const task = activeTask();
    $('product-recording-status').hidden = !task;
    $('product-recording-status').textContent = task ? '视频录制继续；商品面板打开期间，弹窗记录可能无法观察。评论、人数取决于直播页是否仍更新。' : '';
  }
  function renderPreview(data) {
    const box = $('product-preview'); box.replaceChildren();
    if (!data) {
      const hint = document.createElement('p');
      hint.textContent = '在直播间的商品列表或讲解卡中，点开想深入查看的商品。这里会显示对应详情。';
      box.append(hint); return;
    }
    const p = data.snapshot;
    const title = document.createElement('h3'); title.textContent = p.product_title;
    const shop = document.createElement('p'); shop.className = 'muted'; shop.textContent = p.shop_name || '店铺名称暂未取得';
    const price = document.createElement('p'); price.className = 'product-price'; price.textContent = p.price_texts.join(' · ') || '展示价格暂未取得';
    const stats = document.createElement('p'); stats.className = 'product-counts';
    const groups=p.sku_groups.filter(g=>g.options.length);
    const optionCount=groups.reduce((n,g)=>n+g.options.length,0);
    stats.textContent = `当前预览 ${new Set(p.images.map((i) => i.url)).size} 张图片` + (optionCount ? ` · ${optionCount} 个页面规格选项` : '') + ` · ${p.parameter_texts.length ? '有参数资料' : '参数暂缺'}`;
    const selection=document.createElement('p');selection.className='muted';
    const selected=p.sku_groups.flatMap(g=>g.options.filter(o=>o.selected).map(o=>o.value));
    const onlyVisibleCombination=groups.length>0&&groups.every(g=>g.options.length===1);
    selection.textContent=!optionCount ? '本页未展示可切换的规格。'
      : onlyVisibleCombination ? (selected.length===groups.length?'当前规格：':'页面显示规格：')+groups.map(g=>g.options[0].value).join(' / ')
      : selected.length ? '当前选中：'+selected.join(' / ') : '页面展示了多个规格，尚未显示当前选择。';
    const extra=document.createElement('details');extra.className='product-help product-preview-details';
    const summary=document.createElement('summary');summary.textContent='查看识别到的图片与规格';
    extra.append(summary,stats,selection);
    box.append(title, shop, price, extra);
    const identity=document.createElement('p');identity.className='product-counts';
    identity.textContent=p.product_identity?.product_id?'商品 ID：'+p.product_identity.product_id:'商品 ID 未取得 · 仅绑定当前页面';
    extra.append(identity);
  }
  async function captureCurrent() {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    const room = canonicalRoomUrl(tab?.url || '');
    if (!room || !tab?.id) throw recognitionError('unsupported_page');
    if (!(await ensureCurrentTabContentScript(room,tab.id))) throw recognitionError('unavailable');
    const first = await chrome.tabs.sendMessage(tab.id, {type:'brandbai-product-preview', roomUrl:room});
    if (['none','not_found'].includes(first?.status)) return null;
    if (first?.status !== 'recognized') throw recognitionError(first?.status);
    if (first.room_url !== room) throw recognitionError('changed');
    await sleep(250);
    const second = await chrome.tabs.sendMessage(tab.id, {type:'brandbai-product-preview', roomUrl:room});
    const [active] = await chrome.tabs.query({active: true, currentWindow: true});
    if (active?.id !== tab.id || canonicalRoomUrl(active.url || '') !== room || second?.status !== 'recognized' || signature(first) !== signature(second)) throw recognitionError('changed');
    return {...second, tab_id:tab.id};
  }
  async function boundedCapture() {
    let timer;
    try {
      return await Promise.race([captureCurrent(), new Promise((_, reject) => {
        timer = setTimeout(() => reject(recognitionError('read_timeout')), 8000);
      })]);
    } finally { clearTimeout(timer); }
  }
  function currentCapture() {
    // Reuse only an in-flight two-sample read, never a cached product result.
    // Starting a review still verifies active tab, room and panel identity.
    if (!capturePending) capturePending = boundedCapture().finally(()=>{capturePending=null;});
    return capturePending;
  }
  async function pageAccessible(room, tabId) {
    let timer;
    try {
      return await Promise.race([ensureCurrentTabContentScript(room, tabId),
        new Promise(resolve=>{timer=setTimeout(()=>resolve(false),8000);})]);
    } finally { clearTimeout(timer); }
  }
  async function refreshPreview({quiet = false} = {}) {
    if (!visible || reading || busy || window.BrandbaiReviewsBusy?.() || window.BrandbaiReviewPreviewBusy?.() || ['collecting','submitting'].includes(job?.state)) return;
    reading = true; const stamp = generation; controls();
    try {
      const value = await currentCapture();
      if (stamp !== generation || !visible || busy || window.BrandbaiReviewsBusy?.()) return;
      // One unstable scan while the product page updates is not a confirmed removal.
      // Download still performs its own fresh, two-sample identity check.
      if (!value && quiet && preview && ++misses < 2) return;
      if (value) misses = 0;
      if(preview && (!value || !window.BrandbaiProductIdentity.same(preview.snapshot?.product_identity,value.snapshot?.product_identity)))message('');
      if (signature(preview) !== signature(value)) renderPreview(value);
      preview = value;
      window.dispatchEvent(new Event('brandbai-current-product-changed'));
      if (!quiet) { actionKind='product'; message(value ? '商品已识别，可以独立下载。' : '尚未检测到商品详情。若已经打开，请保持页面并重新识别。'); }
    } catch (error) {
      if (stamp !== generation || !visible || busy || window.BrandbaiReviewsBusy?.()) return;
      if (quiet && preview && ++misses < 2) return;
      preview = null; renderPreview(null);
      if (!quiet) { actionKind='product'; message(recognitionHints[error.recognitionReason]||recognitionHints.unavailable, true); }
    } finally { reading = false; renderJob(); controls(); }
  }
  async function saveJob() {
    if (job && ['complete_observed','partial','failed'].includes(job.state)) {
      recent[job.kind || 'product']={title:job.title,state:job.state,output_dir:job.output_dir,delivery:job.delivery,
        current_product:job.current_product,
        item_count:job.item_count || job.observation_count || 0,image_saved:job.image_saved || 0};
    }
    await chrome.storage.session.set({[key]:job,[overviewKey]:{overview,recent}});
  }
  function renderOverview() {
    const box=$('catalog-overview'); box.hidden=!overview;
    if (!overview) return;
    const same=overview.room_url===currentOverviewRoom;
    $('catalog-overview-title').textContent=`${same?'本次':'上次直播间'}已读取 ${overview.rows.length} 条商品记录`;
    const missingNumbers=overview.rows.filter(r=>r.list_position==null).length;
    if(missingNumbers) $('catalog-overview-title').textContent+=` · ${overview.rows.length-missingNumbers} 件编号已确认，${missingNumbers} 件待核验`;
    $('catalog-observed-note').textContent=`${new Date(overview.observed_at_epoch_ms).toLocaleString('zh-CN')} 的页面快照。` + (same?'商品编号和价格可能变化。':'不是当前直播间；请重新读取。');
    if(missingNumbers) $('catalog-observed-note').textContent+='已短暂复查；讲解商品可能置顶，推测编号不能当作已确认。可稍后重新读取验证。';
    const rows=$('catalog-rows'); rows.replaceChildren();
    for (const row of overview.rows) {
      const card=document.createElement('div'); card.className='catalog-row'; card.setAttribute('role','listitem');
      const number=document.createElement('strong'); number.textContent=row.list_position==null
        ? row.number_inference ? `推测 ${row.number_inference.candidate} 号 · 待核验` : '编号未显示 · 待核验'
        : `${row.list_position} 号链接${row.number_verification?' · 复核确认':''}`;
      card.append(number);
      if(row.explaining===true) { const badge=document.createElement('span'); badge.className='catalog-explaining'; badge.textContent='读取时讲解中'; card.append(badge); }
      const title=document.createElement('p'); title.textContent=row.product_title;
      if(row.entry_type==='lottery') title.textContent='【福袋／抽奖】'+row.product_title;
      else if(row.entry_type==='unavailable') title.textContent='【售罄／下架】'+row.product_title;
      const price=document.createElement('p'); price.className='muted'; price.textContent=row.display_price || '展示价格未取得';
      card.append(title,price); rows.append(card);
    }
  }
  function renderRecent(kind) {
    const box=$(`${kind}-recent-result`), value=recent[kind] || (kind==='product'&&previousProductResult()?job:null);
    const activeKind=preparation ? actionKind : job?.kind || 'product';
    const hidden=!value || Boolean(value.delivery) || activeKind===kind && !(kind==='product' && previousProductResult());
    const signature=JSON.stringify([hidden,value]);
    if(box.dataset.signature===signature)return;
    box.dataset.signature=signature; box.hidden=hidden; box.replaceChildren();
    if(kind==='product') $('product-history').hidden=hidden&&(!$('review-history-result').children.length||$('review-result').hidden);
    if(hidden)return;
    box.className='product-recent';
    const label=document.createElement('p');
    label.textContent=`历史下载 · ${kind==='catalog'?'目录':'其他商品资料'}${value.state==='complete_observed'?'已保存':value.state==='partial'?'部分已保存':'未完成'} · ${kind==='catalog'?`${value.item_count} 条记录`:`${value.image_saved} 张图片`}`;
    if(value.delivery)label.textContent=label.textContent.replaceAll('已保存','已整理')+' · ZIP 下载见下方';
    const title=document.createElement('p'); title.textContent=value.title; box.append(label,title);
    if(value.output_dir) {
      const button=document.createElement('button'); button.type='button'; button.textContent='复制保存位置';
      button.onclick=async()=>{ try { await navigator.clipboard.writeText(value.output_dir); button.textContent='位置已复制'; } catch(_) { button.textContent='复制失败，请重试'; } };
      if(value.delivery){button.textContent='查看 ZIP 下载进度';button.onclick=()=>window.BrandbaiDownloads?.reveal(value.delivery.id);}
      box.append(button);
    }
  }
  const result = $('product-download-result');
  // Keep the same nodes while polling: no layout/focus resets or disappearing actions.
  const heading = document.createElement('h3');
  const resultTitle = document.createElement('p'); resultTitle.className = 'product-result-title';
  const progress = document.createElement('progress'); progress.className = 'product-download-progress';
  progress.setAttribute('aria-label', '图片处理进度');
  const counts = document.createElement('p'); counts.className = 'product-progress-counts';
  const detail = document.createElement('p'); detail.className = 'muted';
  const resultDetails = document.createElement('details'); resultDetails.className='product-help';
  const resultSummary = document.createElement('summary'); resultSummary.textContent='查看本次读取情况';
  resultDetails.append(resultSummary,detail);
  const warning = document.createElement('p'); warning.className = 'product-sync-warning';
  const check = document.createElement('button'); check.type = 'button'; check.className = 'product-status-check'; check.textContent = '重新查询下载状态';
  const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'product-status-check'; retry.textContent = '检查后重新下载';
  const copy = document.createElement('button'); copy.type = 'button'; copy.className = 'product-copy'; copy.textContent = '复制商品资料位置';
  const stop = document.createElement('button'); stop.type='button'; stop.className='product-status-check'; stop.textContent='停止读取并保存已取得资料';
  const more = document.createElement('button'); more.type='button'; more.className='product-status-check'; more.textContent='继续读取商品目录';
  const cancelLaunch = document.createElement('button'); cancelLaunch.type='button'; cancelLaunch.className='product-status-check'; cancelLaunch.textContent='取消本次启动';
  result.append(heading, resultTitle, progress, counts, resultDetails, warning, check, retry, stop, more, copy, cancelLaunch);
  const receipt=document.createElement('div');receipt.className='inline-delivery';receipt.hidden=true;result.append(receipt);
  cancelLaunch.onclick=async()=>{ launchCanceled=true; cancelLaunch.disabled=true; await cancelAssistantLaunch(); };
  stop.onclick=async()=>{ stop.disabled=true; try { await pageMessage('brandbai-material-stop'); } catch (_) { message('页面未响应，请保持原页面打开后重试。',true); } finally { stop.disabled=false; } };
  more.onclick=()=>download('catalog',true);
  copy.onclick = async () => {
    if(job.delivery){window.BrandbaiDownloads?.reveal(job.delivery.id);return;}
    try { await navigator.clipboard.writeText(job.output_dir); copy.textContent = '位置已复制'; }
    catch (_) { message('复制失败，请在“文件保存”所示目录的“商品资料”中查看。', true); }
  };
  check.onclick = () => pollJob({reconnect:true});
  retry.onclick = async () => {
    if (busy || polling || job?.state !== 'unconfirmed' || !preview) return;
    if (!window.confirm('请先检查保存目录，上次下载可能已保存文件。确认重新下载当前商品吗？会新建资料包，不覆盖旧文件。')) return;
    job = null; syncWarning = ''; await saveJob(); renderJob(); controls(); void download();
  };
  function preparing(title, text) {
    preparation = {title, text}; renderJob();
  }
  function renderJob() {
    const kind=preparation ? actionKind : job?.kind || 'product';
    if(result.parentElement!==$(`${kind}-feedback`)) $(`${kind}-feedback`).append(result);
    renderRecent('catalog'); renderRecent('product');
    result.hidden = !preparation && (!job || previousProductResult());
    if (result.hidden) return;
    cancelLaunch.hidden=!preparation?.launching;
    cancelLaunch.disabled=launchCanceled;
    receipt.dataset.deliveryId=!preparation&&job?.delivery?.id||'';
    receipt.hidden=!receipt.dataset.deliveryId;
    window.BrandbaiDownloads?.renderInline?.();
    copy.hidden = Boolean(preparation) || !job?.output_dir || Boolean(job?.delivery);
    if(job?.delivery)copy.textContent='查看下载';
    resultDetails.open=Boolean(preparation)||['collecting','running','submitting','unconfirmed'].includes(job?.state);
    warning.hidden = Boolean(preparation) || !syncWarning;
    warning.textContent = syncWarning;
    check.hidden = Boolean(preparation) || (!syncWarning && job?.state !== 'unconfirmed');
    check.disabled = polling;
    retry.hidden = Boolean(preparation) || job?.state !== 'unconfirmed';
    retry.disabled = polling || busy || !preview || job?.kind==='catalog';
    progress.hidden = false; counts.hidden = false;
    stop.hidden=Boolean(preparation) || job?.state!=='collecting';
    more.hidden=Boolean(preparation) || job?.kind!=='catalog' || !job?.can_continue || !['partial','complete_observed'].includes(job?.state);
    result.classList.toggle('needs-attention', !preparation && (job?.state === 'partial' || job?.state === 'failed' || job?.state === 'unconfirmed'));
    if (preparation) {
      heading.textContent = '正在准备下载'; resultTitle.textContent = preparation.title;
      progress.removeAttribute('value'); counts.hidden = true; detail.textContent = preparation.text; return;
    }
    if(job.state==='collecting') {
      heading.textContent=job.kind==='catalog' ? job.phase==='opening_catalog' ? '正在展开全部商品' : job.phase==='verifying_numbers' ? '正在核验未显示的编号' : '正在读取商品编号目录' : job.phase==='parameter_options' ? '正在读取套餐内容' : job.phase==='sku_images' ? '正在逐个确认规格与图片' : job.phase==='detail_images' ? '正在补齐详情图' : '正在补齐主图';
      resultTitle.textContent=job.title;
      counts.textContent=job.kind==='catalog' ? `已读取 ${job.item_count||0} 条商品记录` : `主图 ${job.main_observed||0} / ${job.main_expected||'总数待确认'} · 详情图 ${job.detail_observed||0} 张`;
      detail.textContent='正在当前页面读取，请勿切换商品。关闭侧栏后仍会读取，重新打开可继续保存；视频继续，商品弹窗观察暂时暂停。';
      if(job.phase==='sku_images') counts.textContent=`已处理 ${job.sku_done||0} / ${job.sku_total||0} 个规格 · `+counts.textContent;
      if(job.phase==='parameter_options') counts.textContent=`已读取 ${job.parameter_done||0} / ${job.parameter_total||0} 个套餐 · `+counts.textContent;
      detail.textContent+=` 已用时 ${Math.max(0,Math.floor((Date.now()-(job.started_at_epoch_ms||job.submitted_at))/1000))} 秒。`;
      if(job.no_change_steps>2 && job.phase==='detail_images') detail.textContent+='正在核对详情末端；没有新增内容时将结束读取并说明缺失。';
      if(job.kind==='catalog') detail.textContent=job.phase==='opening_catalog'
        ? '已尝试打开“全部商品”，正在等待列表显示；请勿重复点击。'
        : job.phase==='verifying_numbers' ? '商品已读取，正在短暂复查被讲解标识遮挡的编号（最多约 12 秒）。确认不了也会保存已有资料，并标注待核验。'
        : '正在读取商品编号与名称。请保持直播间和列表打开；不会逐个进入商品详情。';
      progress.removeAttribute('value'); return;
    }
    const saved = job.image_saved || 0, failed = job.image_failed || 0, skipped = job.image_skipped || 0;
    const running = ['running','submitting'].includes(job.state), total = job.image_total || (running ? job.expected_images || 0 : 0);
    const processed = saved + failed + skipped;
    resultTitle.textContent = job.title;
    counts.textContent = total ? `已保存 ${saved} / ${total} 张图片` : `已保存 ${saved} 张图片`;
    if (failed) counts.textContent += ` · ${failed} 张失败`;
    if (skipped) counts.textContent += ` · ${skipped} 张未下载`;
    progress.max = Math.max(total, 1); progress.value = Math.min(processed, total);
    if (running) {
      const packaging = total === 0 || processed >= total;
      heading.textContent = packaging ? '正在整理资料与压缩包' : '正在下载图片';
      detail.textContent = packaging ? '图片处理结束，正在生成资料文件，请稍候。' : '下载完成后会自动整理资料与压缩包。';
      if (total === 0) detail.textContent = '当前未识别到图片，正在保存商品文字资料。';
      if (packaging) progress.removeAttribute('value');
      const idle = Date.now() - (job.last_progress_at || job.submitted_at || Date.now());
      if (idle > 15000) detail.textContent = '暂未收到新进度，正在等待助手处理；请勿重复下载。';
      if (job.submitted_at) detail.textContent += ` 已用时 ${Math.max(0, Math.floor((Date.now()-job.submitted_at)/1000))} 秒。`;
    } else {
      heading.textContent = job.state === 'complete_observed' ? '当前识别资料已保存'
        : job.state === 'partial' ? '部分资料已保存'
        : job.state === 'unconfirmed' ? '下载状态待确认' : '本次下载未完成';
      detail.textContent = job.state === 'complete_observed' ? '图片、商品资料和压缩包已保存到本机。仅覆盖本次识别内容。'
        : job.state === 'partial' ? '已保留取得的资料，缺失项目请查看下载清单。'
        : job.state === 'unconfirmed' ? '暂时无法确认结果。请先查询状态或检查保存位置，不会自动重复下载。'
        : '请检查保存位置；已经取得的文件不会主动删除。';
      progress.hidden = true;
      if(job.kind==='catalog') {
        heading.textContent=job.state==='complete_observed' ? '商品编号目录已保存' : job.state==='partial' ? '商品目录已部分保存' : heading.textContent;
        counts.textContent=`${job.item_count||job.observation_count||0} 条商品记录 · 已保存 ${saved} 张缩略图`;
        detail.textContent=job.state==='complete_observed' ? '已读取至列表末端；目录、缩略图与压缩包已保存。未打开商品详情。' : job.state==='partial' ? '当前版本已保存。目录未读完时可继续读取，图片失败项见下载清单。' : detail.textContent;
        if(job.number_coverage?.missing) {
          heading.textContent='商品目录已保存 · 部分编号待核验';
          counts.textContent+=` · ${job.number_coverage.observed} 件编号已确认，${job.number_coverage.missing} 件待核验`;
          detail.textContent+='商品记录与编号完整性分开核对。推测编号不等于已确认，可等讲解标识消失后重新读取。';
        }
      } else if(job.image_coverage) {
        const c=job.image_coverage;
        const full=job.state==='complete_observed' && c.main_complete && c.detail_complete && !c.stop_reason;
        const imagesComplete=c.main_complete&&c.detail_complete&&!c.stop_reason&&total>0&&saved===total&&!failed&&!skipped;
        const missingImages=failed>0 || skipped>0 || saved<total || c.main_expected>c.main_observed
          || ['detail_stalled','image_limit'].includes(c.stop_reason);
        // No visible switching controls is a page limitation, not a failed SKU
        // download or proof of one SKU. Keep the original task/export status.
        const noSkuOptions=job.sku_materials?.status==='not_observed'
          && job.sku_materials.stop_reason==='sku_not_observed'
          && job.sku_materials.selection_restored===true && !job.sku_materials.variants.length;
        const interruptions={page_hidden:['页面转入后台','页面转入后台，已提前结束读取；需要补齐时，请保持商品页在前台重新读取。'],
          user_stopped:['已结束读取','已按你的操作结束读取，保留本次已取得的图片。'],
          time_limit:['读取时间已到','本轮读取时间已到，保留本次已取得的图片。'],
          image_limit:['图片数量已达上限','本轮图片数量已达上限，保留本次已取得的图片。'],
          bytes_limit:['资料大小已达上限','本轮资料大小已达上限，保留本次已取得的图片。']};
        const interruption=job.state==='partial'&&interruptions[c.stop_reason];
        heading.textContent=full ? '主图与详情图已收齐并保存' : imagesComplete ? (noSkuOptions?'图片已保存':'图片已保存 · 规格未读完')
          : missingImages ? '部分图片资料待补齐' : '已取得图片已保存 · 完整性待核验';
        if(interruption) heading.textContent=interruption[0]+(saved?' · 图片已保存':' · 读取已结束');
        if(imagesComplete&&noSkuOptions&&job.state==='partial'&&!job.observation_limited&&!job.fields_limited&&!job.parameter_materials) result.classList.remove('needs-attention');
        detail.textContent=`主图 ${c.main_observed} / ${c.main_expected||'总数未知'} · 详情图 ${c.detail_observed} 张。` + (full ? '图片和资料包已保存。' : '已保留取得的文件。');
        if(interruption) detail.textContent+=' '+interruption[1];
        if(c.stop_reason==='detail_stalled') detail.textContent+='详情已无新增内容，但尚未确认收齐，已停止等待。';
        else if(!c.main_complete) detail.textContent+='主图数量尚未核对完整。';
        else if(!c.detail_complete) detail.textContent+='详情末端或图片加载尚未确认。';
        if(c.main_video_observed) detail.textContent+=` 另有 ${c.main_video_observed} 个商品视频，未下载视频文件，不计入图片缺失。`;
        if(job.sku_materials) {
          const s=job.sku_materials;
          // An interrupted image phase may never have reached SKU inspection.
          // A default empty record is not an attempted/failed SKU traversal.
          const skuNotStarted=interruption&&s.status==='not_observed'&&!s.stop_reason&&!s.variants.length;
          if(skuNotStarted) { /* Preserve the unknown export state; no SKU failure claim. */ }
          else if(!s.variants.length && !job.parameter_materials) detail.textContent+=noSkuOptions
            ? ' 本页未展示可切换的规格，资料包包含本次读到的图片与商品信息。'
            : ' 规格尚未读完，已保存的图片可正常使用。';
          else if(!s.variants.length) detail.textContent+=' 已读取套餐内容；未取得各套餐的独立价格和规格图片。';
          else {
            if(s.status==='complete_all_visible_skus'&&s.variants.length===1&&s.variants[0].state==='observed') detail.textContent+=' 已确认 1 个页面可选规格，价格和对应图片已核对，无需切换多个规格。';
            else
            detail.textContent+=` 规格已读取 ${s.variants.filter(v=>v.state==='observed'&&!v.reason).length} / ${s.variants.length} 项；`+(s.selection_restored?'原选择已核对。':'原选择未确认恢复，请检查页面。');
            if(s.status!=='complete_all_visible_skus') detail.textContent+='部分规格未确认，详见资料包中的逐项记录。';
          }
          if(!s.variants.length&&s.selection_restored===false) detail.textContent+=' 原选择未确认恢复，请检查页面。';
        }
        if(job.parameter_materials){
          const p=job.parameter_materials, done=p.variants.filter(v=>v.state==='observed').length;
          counts.textContent+=` · 套餐 ${done} / ${p.option_count} 项`;
          if(imagesComplete&&!job.sku_materials?.variants.length){
            heading.textContent=p.status==='complete_visible_options'?'图片与套餐内容已保存':'图片已保存 · 部分套餐未读完';
            result.classList.toggle('needs-attention',p.status!=='complete_visible_options');
          }
          detail.textContent+=` 已读取 ${done} 个套餐的组成与参数。`+(p.selection_restored?'':'原选择未确认恢复，请检查页面。');
        }
      }
    }
    if(job?.delivery&&!preparation&&['partial','complete_observed','failed'].includes(job.state)){
      heading.textContent=heading.textContent.replaceAll('已保存','已整理').replace('并保存','并整理');
      detail.textContent=detail.textContent.replaceAll('已保存','已保留')+' 文件下载情况可在“下载记录”查看。';
    }
  }
  function acceptStatus(value) {
    const before = JSON.stringify([job.state, job.image_saved, job.image_failed, job.image_skipped]);
    job = {...job, ...value};
    const after = JSON.stringify([job.state, job.image_saved, job.image_failed, job.image_skipped]);
    if (before !== after) job.last_progress_at = Date.now();
    syncWarning = '';
    if (job.state !== 'running') message('');
  }
  async function pollJob({reconnect = false} = {}) {
    if (!job || busy || polling || !['running','unconfirmed','collecting','submitting'].includes(job.state)) return;
    const requestId = job.request_id;
    polling = true; renderJob();
    try {
      if(job.state==='collecting') { await pollCollection(); return; }
      if (!sessionToken || reconnect) {
        if (!(await connectService())) throw new Error('not connected');
      }
      const response = await api(`/v1/product-downloads/${requestId}`);
      if (job?.request_id !== requestId) return;
      acceptStatus(response.product_download); await saveJob();
    } catch (error) {
      if (job?.request_id !== requestId) return;
      syncWarning = '下载进度暂时连接不上，保留最后进度；正在重新查询，不会重复下载。';
      if (/not found/i.test(error.message)) {
        job.state='unconfirmed'; syncWarning = '助手未找到这次任务，请先检查“文件保存”目录中的“商品资料”。';
        await saveJob();
      }
    } finally { polling = false; renderJob(); controls(); }
  }
  async function pageMessage(type, extra={}) {
    let timer;
    try { return await Promise.race([chrome.tabs.sendMessage(job.tab_id,{type,roomUrl:job.room_url,...extra}),
      new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('page_timeout')),8000);})]); }
    finally { clearTimeout(timer); }
  }
  async function pollCollection() {
    let capture;
    try { capture=await pageMessage('brandbai-material-status'); }
    catch (_) { job.state='failed'; syncWarning='原商品页面已关闭、刷新或无法连接。本次读取未能保存，请重新打开后下载。'; await saveJob(); return; }
    if(capture.request_id!==job.request_id || capture.room_url!==job.room_url) { job.state='failed'; syncWarning='原页面读取任务已失效，请重新读取。'; await saveJob(); return; }
    if(capture.state==='failed') {
      job.state='failed';
      const reasons={close_product_detail:'请先关闭商品详情，再点击“读取商品编号目录”。无需离开直播间。',
        product_changed:'商品已变化，本次资料未保存，请重新选择。',specification_changed:'规格已变化，本次资料未保存，请重新选择。',
        catalog_unavailable:'未找到商品列表。请在直播画面右下方手动打开“全部商品”，再点击“读取商品编号目录”。',
        catalog_entry_unavailable:'尚未确认商品列表或展开入口。若列表已经打开，请保持页面并重新识别；否则请先手动打开“全部商品”。本次未取得目录，不代表直播间没有商品。',
        catalog_entry_ambiguous:'页面上有多个商品入口，暂未自动点击。请手动打开本场直播的“全部商品”，再点击“读取商品编号目录”。',
        catalog_open_failed:'已尝试打开“全部商品”，但列表尚未显示。请手动展开列表，再点击“读取商品编号目录”。',
        catalog_resume_changed:'原商品列表已变化，请重新读取目录。'};
      syncWarning=reasons[capture.reason]||'页面或商品已变化，本次未保存混合资料，请重新读取。';
      actionKind=job.kind; message(syncWarning,true); syncWarning='';
      await saveJob(); return;
    }
    if(capture.state!=='ready') { Object.assign(job,{phase:capture.phase,main_observed:capture.main_observed,main_expected:capture.main_expected,detail_observed:capture.detail_observed,item_count:capture.item_count,
      sku_done:capture.sku_done,sku_total:capture.sku_total,parameter_done:capture.parameter_done,parameter_total:capture.parameter_total,no_change_steps:capture.no_change_steps,started_at_epoch_ms:capture.started_at_epoch_ms}); await saveJob(); return; }
    const data=capture.result;
    if(Date.now()-data.observed_at_epoch_ms>120000 || data.catalog && !data.catalog.rows.length) {
      job.state='failed'; syncWarning='资料已过期或未取得商品，请重新读取。'; await saveJob(); return;
    }
    if(job.kind==='catalog') {
      // Only public, already validated list fields; no DOM, customer or checkout data.
      overview={room_url:job.room_url,observed_at_epoch_ms:data.observed_at_epoch_ms,
        rows:data.catalog.rows.slice(0,1000).map((r,i)=>({list_position:r.list_position,product_title:r.product_title,
          display_price:r.display_price,explaining:r.explaining,entry_type:r.entry_type,
          number_inference:data.number_hints?.[i]||null,number_verification:r.number_verification||null}))};
      renderOverview(); $('catalog-overview').open=true;
    }
    job={...job,state:'submitting',expected_images:data.snapshot?.images.length||data.catalog?.rows.filter(r=>r.thumbnail).length||0,
      image_coverage:data.snapshot?.image_coverage,sku_materials:data.snapshot?.sku_materials,parameter_materials:data.snapshot?.parameter_materials,fields_limited:data.snapshot?.fields_limited===true,can_continue:data.can_continue,item_count:data.catalog?.rows.length,submitted_at:Date.now()};
    await saveJob(); renderJob(); controls();
    try {
      if(!sessionToken && !(await connectService())) throw new Error('not_connected');
      const response=await api('/v1/product-downloads',{method:'POST',body:{request_id:job.request_id,room_url:job.room_url,
        observed_at_epoch_ms:data.observed_at_epoch_ms,...(job.kind==='catalog'?{catalog:data.catalog}:{snapshot:data.snapshot})}});
      acceptStatus(response.product_download); await saveJob();
      await pageMessage('brandbai-material-ack',{request_id:job.request_id}).catch(()=>{});
    } catch (_) {
      try { acceptStatus((await api(`/v1/product-downloads/${job.request_id}`)).product_download); }
      catch (_) { job.state='unconfirmed'; syncWarning='暂未确认保存结果，请先查询状态或检查保存位置，避免重复下载。'; }
      await saveJob();
    }
  }
  async function download(kind='product', resume=false) {
    if (restoring || busy || window.BrandbaiReviewsBusy?.() || kind==='product' && !preview || ['running','unconfirmed','collecting','submitting'].includes(job?.state)) return;
    const selected = preview; actionKind=kind; launchCanceled=false; busy = true; generation++; controls(); message('');
    const title=kind==='catalog'?'商品编号目录':selected.snapshot.product_title;
    preparing(title, '正在确认页面和保存位置……');
    result.scrollIntoView({block:'nearest'});
    try {
      const [origin]=await chrome.tabs.query({active:true,currentWindow:true});
      const originRoom=canonicalRoomUrl(origin?.url||'');
      if(!originRoom)throw new Error('尚未识别到当前直播间。请切回正在观看的抖音直播标签页，点一下浏览器工具栏中的采集助手图标，再读取目录。');
      if(!(await pageAccessible(originRoom,origin.id))) throw new Error('暂时无法读取当前直播页。请在这个直播标签页点一下浏览器工具栏中的采集助手图标，再重试；仍无响应时请刷新直播页。');
      if (!(await connectService({retry:true}))) {
        if(getConnectionIssue())throw new Error(getConnectionIssue());
        preparation={title,text:'请在浏览器确认框中选择打开助手。准备好后自动返回；不会开始录制。',launching:true}; renderJob();
        await readCurrentTab();
        if(launchCanceled)throw new Error('本次启动已取消，未开始读取或下载。');
        const connected=await beginAssistantLaunch();
        if(launchCanceled)throw new Error('本次启动已取消，未开始读取或下载。');
        if(!connected || !sessionToken)throw new Error(getConnectionIssue() || '启动等待已结束，尚未下载。请处理浏览器确认后返回直播间重试。');
        preparing(title, '正在确认页面和保存位置……');
      }
      const health = await api('/v1/health',{auth:false});
      if(health.browser_zip_delivery!==true)throw new Error('请空闲后更新本机助手，才能使用浏览器 ZIP 下载。');
      if (health.independent_product_downloads !== true) throw new Error('请更新并重新启动本机助手，再下载商品资料。');
      if(health.shared_product_identity!==true)throw new Error('请在任务结束后更新本机助手，才能保存统一商品身份。');
      if(kind==='product' && !health.product_media_classification)throw new Error('请空闲后更新本机助手，再下载图片与规格。');
      if(kind==='product' && !health.product_parameter_options)throw new Error('请空闲后更新本机助手，以便保存套餐内容。');
      if (health.full_product_materials !== true || health.independent_product_catalogs !== true) throw new Error('本机助手需要更新，才能补齐图片和保存商品目录。现有录制不受影响；请在任务结束后更新助手。');
      if (health.all_visible_product_skus !== true) throw new Error('本机助手需要更新到新版，才能保存全部规格和福袋目录。请在录制或下载结束后更新助手，再重试。');
      if(kind==='catalog' && health.catalog_number_verification!==true) throw new Error('商品编号核验需要新版助手。请在录制或下载结束后更新并重新启动助手，再读取目录。');
      await refreshStorageSettings({silent:true});
      if (storageSettings?.mode !== 'browser-zip') throw new Error('浏览器 ZIP 下载尚未准备好，请更新本机助手。');
      const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
      const room=canonicalRoomUrl(tab?.url||'');
      if(room!==originRoom || tab?.id!==origin.id) throw new Error('直播间或标签页已变化，本次未读取。请返回原直播间重试。');
      if(!(await pageAccessible(room,tab.id))) throw new Error('当前直播页暂时无法连接。请在原直播标签页点一下浏览器工具栏中的采集助手图标，再重试。');
      currentOverviewRoom=room;
      const fresh = kind==='product'?await currentCapture():{tab_id:tab.id,room_url:room};
      if (!fresh || kind==='product' && (fresh.tab_id !== selected.tab_id || signature(fresh) !== signature(selected))) {
        preview = fresh; renderPreview(fresh);
        throw new Error('商品或页面已变化，请核对新的预览后再点下载。');
      }
      const request_id = crypto.randomUUID();
      job = {request_id, state:'collecting', kind, title, tab_id:fresh.tab_id,room_url:fresh.room_url,phase:'preparing',
        current_product:kind==='product'?fresh:null,
        submitted_at:Date.now(), last_progress_at:Date.now()};
      preparation = null; syncWarning = ''; copy.textContent = kind==='catalog'?'复制商品目录位置':'复制商品资料位置';
      await saveJob(); renderJob();
      try {
        const capture=await pageMessage('brandbai-material-start',{kind,request_id,expected:kind==='product'?fresh:null,resume,sku_mode:'all_visible'});
        if(capture.state==='failed' && !capture.request_id) throw new Error('page_unavailable');
      } catch (error) {
        // Query the same page request on the next tick; never duplicate a start.
        syncWarning='正在确认页面读取状态，请勿重复点击。';
      }
      message('正在读取当前页面。无需手动翻图或滚动，也不会开始新的录制。');
    } catch (error) { message(error.message,true); }
    finally { busy = false; preparation = null; renderJob(); controls(); void pollJob(); }
  }
  function switchView(product) {
    visible = product; generation++; misses=0;
    if(!window.BrandbaiReviewsBusy?.()&&!window.BrandbaiMaterialsBusy()){preview=null;renderPreview(null);}
    controls();
    document.body.classList.toggle('product-mode',product);
    $('product-workspace').hidden = !product;
    $('product-view').setAttribute('aria-pressed',String(product));
    $('recording-view').setAttribute('aria-pressed',String(!product));
    document.querySelector('.app-subtitle').textContent=product?'先看整场商品，再深入重点资料 · 无需录屏':'录制当前公开直播间';
    if (product) { void refreshPreview({quiet:true}); void refreshOverviewRoom(); }
  }
  async function refreshOverviewRoom() {
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    currentOverviewRoom=canonicalRoomUrl(tab?.url||''); renderOverview();
  }
  function invalidate() {
    if(window.BrandbaiReviewsBusy?.()||window.BrandbaiMaterialsBusy()) {generation++;void refreshOverviewRoom();return;}
    generation++; misses=0; preview = null; renderPreview(null); controls();
    if (visible && !busy) void refreshPreview({quiet:true});
    void refreshOverviewRoom();
  }
  $('product-view').onclick = () => switchView(true);
  $('recording-view').onclick = () => switchView(false);
  $('refresh-product').onclick = () => refreshPreview();
  $('download-current-product').onclick = ()=>download();
  $('download-product-catalog').onclick = ()=>download('catalog');
  chrome.tabs.onActivated.addListener(invalidate);
  chrome.tabs.onUpdated.addListener((id, info, tab) => { if (tab.active && (info.url || info.status === 'loading')) invalidate(); });
  chrome.storage.session.get([key,overviewKey]).then((data) => {
    job=data[key] || null; overview=data[overviewKey]?.overview || null; recent=data[overviewKey]?.recent || {};
    if(window.BrandbaiMaterialsBusy()&&job?.current_product){preview=job.current_product;renderPreview(preview);}
    renderJob(); renderOverview();
  }).catch(()=>{}).finally(()=>{
    restoring=false; controls(); void pollJob();
  });
  setInterval(() => { controls(); renderJob(); void pollJob(); if(visible) void refreshPreview({quiet:true}); },3000);
})();
