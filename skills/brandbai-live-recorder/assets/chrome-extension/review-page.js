/* Explicit review adapter. Never changes playback, filters, SKU or checkout. */
(function(root) {
  'use strict';
  root.BrandbaiLiveReviews={create({document,window,roomUrl,isVisible,isRendered,inspector,send,materialBusy,getProductContext}) {
    const documentToken=crypto.randomUUID(); let job=null,sequence=0,starting=false;
    async function exchange(message) {
      let timer;
      try { return await Promise.race([send(message), new Promise((_,reject)=>{
        timer=setTimeout(()=>reject(new Error('评价保存连接超时；已确认批次仍在本机，可停止并保存。')),10000);
      })]); } finally { clearTimeout(timer); }
    }
    const hash=async value=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)))).map(v=>v.toString(16).padStart(2,'0')).join('');
    const safe=value=>String(value||'').replace(/(?<!\d)1[3-9]\d{9}(?!\d)/g,'[手机号已脱敏]');
    const sanitize=async row=>({
      review_id:await hash((job.anonymization_id||job.id)+'|'+(row.reviewId || JSON.stringify([row.reviewerName,row.dateText,row.purchasedSku,row.content]))),
      reviewer:'买家_'+(await hash((job.anonymization_id||job.id)+'|'+row.reviewerName)).slice(0,12),date_text:safe(row.dateText),
      purchased_sku:safe(row.purchasedSku),content:safe(row.content),content_status:row.contentStatus,
      image_count:row.images.length,helpful_count:row.helpfulCount,
      followups:row.followups.map(f=>({content:safe(f.content),date_text:safe(f.dateText),image_count:f.images.length})),
      followup_status:row.followupStatus,merchant_reply:safe(row.merchantReply)
    });
    const collector=root.BrandbaiDouyinCommerceReviewCollector.createCollector({document,window,documentToken,isVisible,isRendered,
      ...(getProductContext?{getProductContext}:{}),
      getWorkContext:()=>({documentToken,contextKey:roomUrl()||'',generation:documentToken,sourceWorkId:roomUrl()||'',sourceSurfaceInstance:documentToken}),
      findProductPanel:()=>inspector.inspect().panel,hasActiveTransaction:()=>materialBusy(),
      limits:{maxRows:200,maxMs:600000,maxScrolls:600,maxNoGrowth:5,delayMs:1200},
      sendMessage:async message=>{
        if(!job || message.taskId!==job.id || message.runId!==job.runId) throw new Error('评价任务已经变化');
        const action=message.type.startsWith('CAPTURE')?'batch':message.type.startsWith('FINISH')?'finish':'progress';
        const body={lease:message.lease,sequence:++sequence,action,rows:await Promise.all((message.rows||[]).map(sanitize)),
          ...(job.collection_mode==='automatic'?{run_id:job.runId}:{}),
          done_reason:message.doneReason||'',exhausted:message.exhausted===true,empty_confirmed:message.emptyConfirmed===true,
          unparsed_count:message.progress?.unparsedReviewCount||0};
        if(action==='progress')body.phase=message.progress?.phase==='waiting_page'?'waiting_page':'reading';
        const response=await exchange({type:'brandbai-review-bridge',roomUrl:job.room_url,action:'event',request_id:job.id,body});
        if(!response?.task) throw new Error('评价保存连接中断，已确认的批次保留在本机。');
        job={...job,...response.task};return {ok:true,task:job};
      }
    });
    function busy(){return starting || job?.state==='collecting';}
    function preview() {
      const s=collector.getSurfaceState();
      return {ready:s.ready,lease:s.lease,room_url:roomUrl(),product_identity:s.product?.productIdentity||null,product:s.product?{title:s.product.title,shop_name:s.product.shopName,product_id:s.product.productId}:null,
        filter_label:s.filterLabel||'当前筛选',declared_count_text:s.declaredReviewCountText||'',loaded_count:s.parsedReviewCount||0,reason:s.reason||'',busy:busy(),
        resumable_job_id:(job?.can_continue || job?.collection_mode==='automatic') && collector.canResume(job.id,s.lease,job?.collection_mode==='automatic')?job.id:null};
    }
    async function start({expected,limit,request_id,resume_from=null,collection_mode='target'}) {
      if(busy() || materialBusy()) throw new Error('请先完成或停止当前商品读取，再下载评价。');
      const current=preview();
      if(!current.ready || !root.BrandbaiDouyinCommerceReviewCollector.leaseEquals(expected?.lease,current.lease)) throw new Error('评价页面已变化，请重新识别。');
      if(getProductContext && (!current.product_identity||!root.BrandbaiProductIdentity.same(expected?.product_identity,current.product_identity)))throw new Error('商品已变化，未读取其他商品的评价。');
      if(resume_from && (current.resumable_job_id!==resume_from || limit!==job?.limit)) throw new Error('原页面或继续读取检查点已失效，请重新下载。');
      starting=true;
      try {
        const automatic=collection_mode==='automatic';
        collector.configureLimits({maxRows:automatic?10000:limit,maxMs:automatic?600000:Math.min(600000,Math.max(180000,limit*3000)),maxScrolls:600});
        const body={request_id,room_url:current.room_url,observed_at_epoch_ms:Date.now(),lease:current.lease,product:current.product,
          ...(current.product_identity?{product_identity:current.product_identity}:{}),
          filter_label:current.filter_label,declared_count_text:current.declared_count_text,limit:automatic?null:limit,
          ...(automatic?{collection_mode}:{}),
          ...(resume_from?{resume_from}:{})};
        const response=await exchange({type:'brandbai-review-bridge',roomUrl:current.room_url,action:'start',body});
        if(!response?.task) throw new Error('无法开始保存评价，请检查本机助手。');
        job={...response.task,lease:current.lease};sequence=0;
        collector.start(job,{resumeFrom:resume_from});
        const runningId=job.id;
        collector.waitForIdle().finally(()=>{if(job?.id===runningId&&job.state==='collecting')job.state='disconnected';});
        return {job};
      } finally {starting=false;}
    }
    function signal({request_id,run_id}={},finish=false) {
      if(request_id && request_id!==job?.id)throw new Error('评价任务已变化，未停止其他任务。');
      if(run_id && run_id!==job?.runId)throw new Error('评价读取已继续，未停止新的读取。');
      const accepted=job&&busy()?collector.requestPause({taskId:job.id,runId:job.runId,finish:finish&&job.collection_mode==='automatic'}):null;
      return {job,stopping:accepted?.stopping===true};
    }
    async function resume({request_id,expected}) {
      if(starting || materialBusy() || request_id!==job?.id || job.collection_mode!=='automatic')throw new Error('请先完成当前操作。');
      starting=true;
      try {
        const response=await exchange({type:'brandbai-review-bridge',roomUrl:job.room_url,action:'status',request_id:job.id,body:{lease:job.lease}});
        if(!response?.task)throw new Error('进度连接暂未恢复，请稍后继续。');
        job={...job,...response.task};
        // A remotely paused run must drain its last acknowledgement before a
        // new run token is issued. No overlapping readers or stale batches.
        await collector.waitForIdle();
        const current=preview();
        if(job.state!=='paused' || !job.can_continue || !current.ready || current.resumable_job_id!==job.id
          || !root.BrandbaiDouyinCommerceReviewCollector.leaseEquals(expected?.lease,current.lease)
          || !root.BrandbaiDouyinCommerceReviewCollector.leaseEquals(job.lease,current.lease))throw new Error('原商品或筛选已变化，请先结束并下载已读取的评价。');
        if(getProductContext && !root.BrandbaiProductIdentity.same(job.product_identity,current.product_identity))throw new Error('商品已变化，未混入其他评价。');
        const resumed=await exchange({type:'brandbai-review-bridge',roomUrl:job.room_url,action:'resume',request_id:job.id,
          body:{room_url:job.room_url,lease:job.lease,run_id:job.runId,next_run_id:crypto.randomUUID()}});
        if(!resumed?.task)throw new Error('继续读取尚未确认，请稍后检查进度。');
        job={...job,...resumed.task};sequence=0;
        collector.configureLimits({maxRows:10000,maxMs:600000,maxScrolls:600});
        collector.start(job,{resumeFrom:job.id});
        const run=job.runId;
        collector.waitForIdle().finally(()=>{if(job?.runId===run&&job.state==='collecting')job.state='disconnected';});
        return {job};
      } finally {starting=false;}
    }
    return {preview,start,resume,stop:request=>signal(request,true),pause:request=>signal(request,false),busy,status:()=>({job})};
  }};
})(globalThis);
