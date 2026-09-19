/* Independent review UI. Counts are acknowledged local checkpoints, not page totals. */
(()=>{
  'use strict';
  const $=id=>document.getElementById(id),key='brandbai.reviewJob';
  let job=null,busy=false,polling=null,refreshing=null,stopping=false,pausing=false,resumableJobId=null;
  let lastPreviewIdentity=null,syncWarning=false,previewReady=false;
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  async function bounded(promise,ms=8000){
    let timer;
    try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('页面或保存连接暂未响应，请停止并保存已取得资料。')),ms);})]);}
    finally{clearTimeout(timer);}
  }
  window.BrandbaiReviewsBusy=()=>busy || stopping || pausing || ['collecting','unconfirmed'].includes(job?.state);
  window.BrandbaiReviewPreviewBusy=()=>Boolean(refreshing);
  function message(text,error=false){syncWarning=false;$('review-message').textContent=text;$('review-message').classList.toggle('error',error);$('review-message').classList.remove('reconnecting');$('review-message').setAttribute('role',error?'alert':'status');}
  function render(){
    const running=job?.state==='collecting';
    const paused=job?.state==='paused',automatic=job?.collection_mode==='automatic';
    const shared=window.BrandbaiCurrentProduct?.get()?.snapshot?.product_identity;
    const historical=['saved','paused'].includes(job?.state) && !window.BrandbaiProductIdentity.same(shared,job.product_identity);
    $('review-preview').hidden=Boolean(job)&&!historical||busy;
    $('review-start').hidden=window.BrandbaiReviewsBusy()||paused;
    $('review-message').hidden=Boolean(job)&&!$('review-message').classList.contains('error');
    const ready=previewReady&&window.BrandbaiProductIdentity.same(shared,lastPreviewIdentity);
    $('review-start').disabled=window.BrandbaiReviewsBusy()||window.BrandbaiMaterialsBusy?.()||!ready;
    $('review-start').textContent=busy?'正在确认评价页面……':!shared?'请先打开商品':!ready?'请先打开商品评价':'开始读取评价';
    $('review-start').setAttribute('aria-busy',String(window.BrandbaiReviewsBusy()));
    $('review-result').hidden=!job||historical&&job.state==='saved'&&Boolean(job.delivery);
    const destination=historical?$('review-history-result'):$('review-card');
    if($('review-result').parentElement!==destination)destination.append($('review-result'));
    $('product-history').hidden=$('product-recent-result').hidden&&(!historical||job?.state==='saved'&&Boolean(job?.delivery));
    if(!job)return;
    const receipt=$('review-delivery');
    receipt.dataset.deliveryId=job.state==='saved'?job.delivery?.id||'':'';receipt.hidden=job.state!=='saved'||!job.delivery;
    $('review-result').classList.toggle('product-recent',historical);
    const stoppingNow=job.state!=='saved'&&(stopping||job.stop_requested);
    const waiting=running&&job.phase==='waiting_page';
    $('review-result-title').textContent=stoppingNow?'正在结束并整理下载':pausing?'正在暂停':paused?'已暂停 · 进度已保留':running?'正在读取评价':job.state==='saved'?(job.reviewCount?'评价资料已保存':'本次未取得评价'):'正在确认保存状态';
    $('review-result-product').textContent=job.product?.title||'';
    $('review-count').textContent=automatic?`已读取 ${job.reviewCount||0} 条`:`已读取 ${job.reviewCount||0} / ${job.limit} 条`;
    const reasons={target_reached:'已达到目标条数',time_limit:'已达到本轮时间上限，未达目标条数',scroll_limit:'已达到本轮滚动上限',run_budget:'旧版数量或时间上限',user_paused:'已按你的操作停止',page_hidden:'直播页转入后台',
      page_disconnected:'页面连接已中断',surface_or_filter_changed:'评价筛选或面板发生变化',product_or_work_changed:'商品或直播间发生变化',
      no_growth:'页面未继续加载',loading_stalled:'页面加载停滞',selector_drift:'部分评价结构尚未识别',collector_error:'读取连接中断',
      scroll_container_unavailable:'未找到当前评价的滚动区域',scroll_container_changed:'评价滚动区域已变化',scroll_stalled:'评价列表未能继续滚动',
      user_finished:'已按你的操作结束读取',resource_limit:'本次资料较多，请先结束并下载'};
    $('review-result-note').textContent=stoppingNow?'正在保存已读到的评价，请稍等。':waiting?'评价页暂时不可见，进度已保留。请回到刚才的商品评价页，会接着读取；不会切换你的页面。最多等待 5 分钟，且不超过本次时间上限。':running?`${job.filter_label||'当前筛选'} · 正在向下读取，请保持评价页打开。`
      :job.doneReason==='source_folded'?'已读到当前列表末尾；平台折叠的评价未采集，不代表全部历史评价。'
      :job.completeness==='complete_visible_panel_exhausted'?'已读到当前列表末尾；不代表平台全部历史评价。'
      :job.doneReason==='page_hidden'?'等待返回评价页的时间已到，已保存读到的评价。回到原商品评价页后，可继续读取。'
      :`${reasons[job.doneReason]||'本次读取已结束'}。已保存读到的评价，不代表全部历史评价。`;
    if(paused&&!stoppingNow)$('review-result-note').textContent=job.doneReason==='user_paused'?'已停止自动滚动。可继续读取，或结束并下载已读取的评价。'
      :['time_limit','scroll_limit'].includes(job.doneReason)?'已连续读取一段时间，进度已保留。可以继续读取，也可结束并下载。'
      :`${reasons[job.doneReason]||'读取暂时中断'}。进度已保留；回到原商品和筛选后可继续，或结束并下载。`;
    if(job.resume_from) $('review-result-note').textContent+=` 本包累计包含原有 ${job.baseline_count||0} 条及本轮新增 ${Math.max(0,(job.reviewCount||0)-(job.baseline_count||0))} 条，不要与旧包相加。`;
    if(job.state==='saved' && job.unparsed_count) $('review-result-note').textContent+=` 有 ${job.unparsed_count} 个条目未能确认，其他评价已保存，缺口见资料包。`;
    $('review-continue').hidden=historical || !(['saved','paused'].includes(job.state)&&job.can_continue);
    $('review-continue').disabled=window.BrandbaiReviewsBusy()||window.BrandbaiMaterialsBusy?.()||resumableJobId!==job.id;
    $('review-continue').textContent=busy?'正在继续……':resumableJobId===job.id?'继续读取':'请回到原商品评价页';
    $('review-pause').hidden=!automatic||!running;
    $('review-pause').disabled=pausing||stopping||busy||syncWarning;
    $('review-pause').textContent=pausing?'正在暂停……':'暂停读取';
    $('review-stop').hidden=job.state==='saved';
    $('review-stop').disabled=stopping||pausing||busy;
    $('review-stop').textContent=stopping?'正在结束并保存……':job.stop_requested?'重试结束并下载':'结束并下载';
    $('review-stop').setAttribute('aria-busy',String(stopping));
    $('review-copy').hidden=job.state!=='saved'||Boolean(job.delivery);
    $('review-copy').textContent=job.delivery?'查看下载':'复制保存位置';
    if(job.delivery&&job.state==='saved'){
      $('review-result-title').textContent=job.reviewCount?'评价读取结束':'本次未读到评价';
      if(job.doneReason==='target_reached') $('review-result-title').textContent='已读满目标条数';
      else if(job.reviewCount&&job.completeness!=='complete_visible_panel_exhausted') $('review-result-title').textContent='已保存本次读取的评价';
      else if(job.completeness==='complete_visible_panel_exhausted')$('review-result-title').textContent='当前可读取的评价已读完';
    }
    if(waiting&&!stoppingNow)$('review-result-title').textContent='等待返回评价页';
    if(syncWarning&&!stoppingNow){
      $('review-result-title').textContent='正在恢复进度连接';
      $('review-count').textContent=`上次确认 ${job.reviewCount||0} 条`;
      $('review-result-note').textContent='暂时无法确认是否仍在读取。已确认的评价保留，请勿重复开始。';
    }
    if(historical){
      $('review-result-title').textContent=paused?'已暂停 · 其他商品评价':'历史下载 · 其他商品评价';
      $('review-result-note').textContent=paused?'这是上一个商品的进度。请回到原商品继续，或结束并下载后再读取新商品。':'这份结果属于本记录标题所示商品，不是当前研究商品。可查看原下载记录。';
    }
    $('review-progress').hidden=!running||syncWarning||waiting;
    if(automatic)$('review-progress').removeAttribute('value');
    else{$('review-progress').max=job.limit||200;$('review-progress').value=job.reviewCount||0;}
    window.BrandbaiDownloads?.renderInline?.();
  }
  async function context(){
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true}),room=canonicalRoomUrl(tab?.url||'');
    if(!tab?.id||!room)throw new Error('请回到正在观看的抖音直播间，再读取评价。');
    if(!await ensureCurrentTabContentScript(room,tab.id))throw new Error('请重新加载扩展并刷新直播页，再打开商品评价。');
    return {tab_id:tab.id,room_url:room};
  }
  async function page(ctx,type,extra={}){
    const response=await bounded(chrome.tabs.sendMessage(ctx.tab_id,{type,roomUrl:ctx.room_url,...extra}),['brandbai-review-start','brandbai-review-resume'].includes(type)?15000:['brandbai-review-stop','brandbai-review-pause'].includes(type)?1500:8000);
    if(!response||response.error)throw new Error(response?.error||'当前页面未响应，请重新识别。');
    return response;
  }
  function showPreview(p){
    if(lastPreviewIdentity&&p.product_identity&&!window.BrandbaiProductIdentity.same(lastPreviewIdentity,p.product_identity))message('');
    lastPreviewIdentity=p.product_identity||null;
    resumableJobId=p.resumable_job_id||null;
    const shared=window.BrandbaiCurrentProduct?.get()?.snapshot?.product_identity;
    const match=shared&&window.BrandbaiProductIdentity.same(shared,p.product_identity);
    previewReady=Boolean(p.ready&&match);
    $('review-preview').textContent=p.ready&&match?`评价已识别 · ${p.filter_label}`
      :p.ready&&!match?'评价尚未对应上方商品，请重新识别；不会混入其他商品。':'请打开此商品的“商品评价”；无需重新选择商品。';
    $('review-preview').style.whiteSpace='pre-line';
  }
  async function refresh(quiet=false){
    if(refreshing||busy||job?.state==='collecting'||window.BrandbaiMaterialsBusy?.()||window.BrandbaiCurrentProduct?.isReading?.()||$('product-workspace').hidden)return;
    refreshing=(async()=>{
      try{showPreview(await page(await context(),'brandbai-review-preview'));if(!quiet)message('已按当前评价页面重新识别。');}
      catch(e){resumableJobId=null;previewReady=false;if(!quiet)message(e.message,true);}
    })();
    try{await refreshing;}finally{refreshing=null;render();}
  }
  function poll(){
    if(polling||!job||job.state==='saved')return polling;
    const id=job.id;
    polling=(async()=>{
    try{
      const response=await bounded(api(`/v1/product-reviews/${id}`));
      if(job?.id!==id)return;
      if(response?.task?.id!==id)throw new Error('保存状态未确认');
      if(job.state==='saved'&&response.task.state!=='saved')return;
      const previous=job.state;
      job={...job,...response.task};await chrome.storage.session.set({[key]:job});
      // Clear only the warning owned by a failed status query. A later stop
      // or action error must not be erased by an unrelated successful poll.
      if(syncWarning){
        if(!$('review-message').classList.contains('error'))message('');
        syncWarning=false;
      }
      render();
      if(previous!=='saved'&&job.state==='saved')message(job.reviewCount?`已保存 ${job.reviewCount} 条评价。`: '本次未取得评价。请确认评价页仍打开，再重新下载。',!job.reviewCount);
    }catch(e){
      if(e.status===404){job=null;await chrome.storage.session.remove(key);render();message('本次评价任务未找到。若助手刚刚重启，请先检查保存文件夹；已有资料不会删除。',true);}
      else {
        if(!$('review-message').classList.contains('error')){
          message('正在恢复进度连接。');
          $('review-message').classList.add('reconnecting');
        }
        syncWarning=true;render();
      }
    }
    finally{polling=null;}
    })();return polling;
  }
  $('refresh-product').addEventListener('click',()=>refresh(true));
  window.addEventListener('brandbai-current-product-changed',()=>refresh(true));
  async function startReview(resume=false){
    if(window.BrandbaiReviewsBusy()||window.BrandbaiMaterialsBusy?.())return;
    if(job?.state==='paused'){if(resume)await resumeReview();return;}
    const previous=resume?job:null;
    if(resume&&(!previous?.can_continue||resumableJobId!==previous.id))return;
    busy=true;render();message('正在确认评价页面……');
    try{
      // Finish the already queued read-only preview before starting the
      // fresh product-lock check. No second poll can enter while busy.
      if(refreshing)await refreshing;
      const frozen=window.BrandbaiCurrentProduct.get();
      const currentProduct=await window.BrandbaiCurrentProduct.inspect();
      if(!currentProduct?.snapshot?.product_identity)throw new Error('请先识别上方商品，再下载其评价。');
      if(frozen && (frozen.panel_key!==currentProduct.panel_key || !window.BrandbaiProductIdentity.same(frozen.snapshot.product_identity,currentProduct.snapshot.product_identity)))throw new Error('当前页面已换成其他商品，请点上方“重新识别”。');
      window.BrandbaiCurrentProduct.hold(currentProduct);
      const ctx=await context(),selected=await page(ctx,'brandbai-review-preview');showPreview(selected);
      if(!selected.ready)throw new Error(selected.reason||'请先打开当前商品的“商品评价”。');
      if(!window.BrandbaiProductIdentity.same(currentProduct.snapshot.product_identity,selected.product_identity))throw new Error('评价没有对应上方商品，已阻止下载。请重新识别。');
      if(!await connectService({retry:true})){
        if(getConnectionIssue())throw new Error(getConnectionIssue());
        message('请在浏览器确认框中允许打开助手；准备后继续保存评价，不会录屏。');
        await readCurrentTab();if(!await beginAssistantLaunch())throw new Error('本次启动未完成，未读取评价。');
      }
      const health=await api('/v1/health',{auth:false});
      if(!health.review_automatic_pause_resume)throw new Error('请在任务空闲后更新本机助手，再使用自动读取和暂停继续。');
      if(!health.review_target_continuation)throw new Error('请空闲后更新本机助手，才能保留进度并继续读取。');
      if(!health.review_visibility_wait)throw new Error('请空闲后更新本机助手，才能在切回评价页后继续读取。');
      if(!health.browser_zip_delivery)throw new Error('请空闲后更新本机助手，才能使用浏览器 ZIP 下载。');
      if(!health.independent_product_reviews)throw new Error('请在当前录制和下载结束后更新本机助手，再使用评价下载。');
      if(!health.review_structure_recovery)throw new Error('请空闲后更新本机助手，再使用新版评价下载。');
      if(!health.shared_product_identity)throw new Error('请更新本机助手，才能保存与商品资料关联的评价。');
      if(!health.review_stop_save)throw new Error('请先更新本机助手，才能使用新版评价下载与停止保存。');
      await refreshStorageSettings({silent:true});
      if(storageSettings?.mode!=='browser-zip')throw new Error('浏览器 ZIP 下载尚未准备好，请更新本机助手。');
      const current=await context();
      if(current.tab_id!==ctx.tab_id||current.room_url!==ctx.room_url)throw new Error('直播页面已变化，请重新识别。');
      const request_id=crypto.randomUUID(),limit=previous?.limit||null,collection_mode=previous?'target':'automatic';
      if(previous&&selected.resumable_job_id!==previous.id)throw new Error('原评价页或筛选已变化，不能继续；请重新下载。');
      job={...ctx,id:request_id,runId:request_id,state:'collecting',product:selected.product,product_identity:selected.product_identity,current_product:currentProduct,limit,collection_mode,
        reviewCount:previous?.reviewCount||0,baseline_count:previous?.reviewCount||0,resume_from:previous?.id||null,time_limit_seconds:600};
      await chrome.storage.session.set({[key]:job});render();
      const response=await page(ctx,'brandbai-review-start',{expected:selected,request_id,limit,collection_mode,...(previous?{resume_from:previous.id}:{})});
      job={...job,...response.job};await chrome.storage.session.set({[key]:job});
      message('已开始读取评价；视频录制继续，商品弹窗观察暂时暂停。');
    }catch(e){
      message(e.message,true);
      if(job?.state==='collecting'){
        try{const r=await api(`/v1/product-reviews/${job.id}`);job={...job,...r.task};}
        catch(statusError){
          if(statusError.status===404){job=previous;if(job)await chrome.storage.session.set({[key]:job});else await chrome.storage.session.remove(key);}
          else {job.state='unconfirmed';await chrome.storage.session.set({[key]:job});}
        }
      }
    }finally{busy=false;render();void poll();}
  }
  $('review-start').onclick=()=>startReview(false);
  $('review-continue').onclick=()=>startReview(true);
  async function resumeReview(){
    if(busy||stopping||pausing||job?.state!=='paused'||!job.can_continue)return;
    const target={...job};busy=true;render();message('正在核对原商品和筛选……');
    try{
      if(refreshing)await refreshing;
      const ctx=await context();
      if(ctx.tab_id!==target.tab_id||ctx.room_url!==target.room_url)throw new Error('请回到原商品评价页继续；也可以先结束并下载。');
      const selected=await page(ctx,'brandbai-review-preview');showPreview(selected);
      if(!selected.ready||selected.resumable_job_id!==target.id||!window.BrandbaiProductIdentity.same(target.product_identity,selected.product_identity))throw new Error('商品、筛选或页面已变化，请先结束并下载已读取的评价。');
      const result=await page(ctx,'brandbai-review-resume',{request_id:target.id,expected:selected});
      if(result.job?.id!==target.id||result.job.state!=='collecting')throw new Error('继续读取暂未确认，请稍后检查进度。');
      job={...job,...result.job,stop_requested:false};await chrome.storage.session.set({[key]:job});message('已继续读取。');
    }catch(e){message(e.message,true);}finally{busy=false;render();void poll();}
  }
  $('review-pause').onclick=async()=>{
    if(pausing||stopping||busy||job?.state!=='collecting')return;
    const target={...job};pausing=true;render();message('正在暂停，保留已读取的评价……');
    try{
      try{await page(target,'brandbai-review-pause',{request_id:target.id,run_id:target.runId});}catch(_){}
      await sleep(600);if(polling)await polling;await poll();
      if(job?.id!==target.id||job.state!=='collecting')return;
      const response=await bounded(api(`/v1/product-reviews/${target.id}/pause`,{method:'POST',body:{room_url:target.room_url,run_id:target.runId}}));
      if(response.task?.id!==target.id||!['paused','saved'].includes(response.task.state))throw new Error('暂停尚未确认');
      job={...job,...response.task};await chrome.storage.session.set({[key]:job});
    }catch(_){message('暂停尚未确认，请重试；已确认的评价仍保留。',true);}
    finally{pausing=false;render();void refresh(true);}
  };
  $('review-stop').onclick=async()=>{
    if(stopping||pausing||busy||!job||job.state==='saved')return;
    const target={...job};stopping=true;job.stop_requested=true;render();
    message('已收到停止操作，正在保存已取得的评价……');
    try{
      await chrome.storage.session.set({[key]:job});
      // Signal the exact page job immediately; don't await its entire read loop.
      try{await page(target,'brandbai-review-stop',{request_id:target.id,run_id:target.runId});}catch(_){}
      // Give an in-flight batch a short chance to checkpoint before fallback.
      await sleep(600);if(polling)await polling;await poll();
      if(job?.id!==target.id||job.state==='saved')return;
      const response=await bounded(api(`/v1/product-reviews/${target.id}/stop`,{method:'POST',body:{room_url:target.room_url,...(target.collection_mode==='automatic'?{run_id:target.runId}:{})}}));
      if(response?.task?.id!==target.id||response.task.state!=='saved')throw new Error('停止保存尚未确认');
      if(job?.id===target.id){job={...job,...response.task};await chrome.storage.session.set({[key]:job});
        message(job.reviewCount?`已停止，保存了 ${job.reviewCount} 条评价。`:'已停止，本次未取得评价。',!job.reviewCount);}
    }catch(_){message('结束保存尚未确认。已保存批次保留，请点“重试结束并下载”。',true);}
    finally{stopping=false;render();}
  };
  $('review-copy').onclick=async()=>{if(job.delivery){window.BrandbaiDownloads?.reveal(job.delivery.id);return;}try{await navigator.clipboard.writeText(job.output_dir);message('已复制旧版评价资料保存位置。');}catch(_){message('复制失败，请重试。',true);}};
  chrome.storage.session.get(key).then(data=>{job=data[key]||null;if(window.BrandbaiReviewsBusy()&&job?.current_product)window.BrandbaiCurrentProduct.hold(job.current_product);render();void poll();}).catch(()=>{});
  $('product-view').addEventListener('click',()=>refresh(true));
  setInterval(()=>{render();void poll();void refresh(true);},2000);
})();
