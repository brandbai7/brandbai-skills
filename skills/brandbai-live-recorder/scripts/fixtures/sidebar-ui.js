/* Synthetic Chrome/helper boundary. No live platform, account, recording or download. */
(() => {
  const room='https://live.douyin.com/123456';
  const identity={platform:'douyin',product_id:'123456789012345',product_ref:'douyin:product:123456789012345',identity_status:'verified'};
  const product={status:'recognized',room_url:room,panel_key:'synthetic-product-A',tab_id:1,snapshot:{product_title:'合成记忆枕礼盒｜可调高度亲肤枕套双只装',shop_name:'合成旗舰店',price_texts:['¥399'],images:[{url:'https://example.invalid/main.png'}],sku_groups:[{name:'规格',options:[{value:'双只装 · 蓝色',selected:true}]}],parameter_texts:['品牌：合成'],product_identity:identity}};
  const task={task_id:'synthetic-recording',room_url:room,room_name:'合成旗舰店',state:'recording',max_runtime_seconds:1800,segment_duration_seconds:1800,quality:'SD',started_at:new Date(Date.now()-100000).toISOString(),collect_comments:true,collect_product_cards:true,collect_room_metrics:true,visible_event_count:136,visible_event_counts:{comment_visible:126,product_state:5,room_snapshot:5},recording_health:{state:'receiving'}};
  const review={id:'synthetic-review',runId:'synthetic-review',room_url:room,tab_id:1,state:'collecting',product:{title:product.snapshot.product_title,shop_name:'合成旗舰店',product_id:identity.product_id},product_identity:identity,current_product:product,filter_label:'全部 · 综合',reviewCount:100,limit:200,elapsed_seconds:180};
  const delivery={id:'synthetic-delivery',kind:'reviews',state:'completed',created_at:Date.now()/1000,filename:'合成商品_评价资料.zip',bytes_total:66000,bytes_received:66000};
  const stored={};
  window.audit={room,product,task,review,delivery,stored,tasks:[],deliveries:[],mode:'detail',requests:[],unhandled:[],failedStatus:false,failedDelivery:false,commandDelay:0};
  const event={addListener(){},removeListener(){}};
  window.chrome={runtime:{id:'synthetic-extension',async sendMessage(m){audit.requests.push(m);if(audit.commandDelay)await new Promise(r=>setTimeout(r,audit.commandDelay));return {ok:true}}},permissions:{onAdded:event,onRemoved:event,async contains(){return true}},tabs:{onActivated:event,onUpdated:event,
    async query(){return [{id:1,windowId:1,active:true,url:room,title:'合成旗舰店的抖音直播间 - 抖音直播'}]},
    async get(){return {id:1,url:room}},
    async sendMessage(id,m){audit.requests.push(m);
      if(m.type==='brandbai-product-preview')return audit.mode==='empty'?{status:'none'}:audit.product;
      if(m.type==='brandbai-review-preview')return {ready:audit.mode==='review',product_identity:identity,product:review.product,lease:{id:'synthetic-lease'},filter_label:'全部 · 综合',loaded_count:20,declared_count_text:'8.9万',resumable_job_id:review.can_continue?review.id:null};
      if(m.type==='brandbai-review-start'){Object.assign(review,{id:m.request_id,runId:m.request_id,state:'collecting',limit:m.limit,reviewCount:100});return {job:review};}
      if(m.type==='brandbai-review-stop'){Object.assign(review,{state:'saved',doneReason:'user_paused',can_continue:true,output_dir:'synthetic',delivery});audit.deliveries=[delivery];return {job:review};}
      return {ok:true,room_url:room,roomUrl:room,playbackPaused:false};}},
    scripting:{async executeScript(){return []}},storage:{session:{async get(keys){return !keys?{...stored}:Object.fromEntries((Array.isArray(keys)?keys:[keys]).filter(k=>k in stored).map(k=>[k,stored[k]]))},async set(v){Object.assign(stored,structuredClone(v))},async remove(k){delete stored[k]}}}};
  const health={service:'brandbai-live-recorder',status:'ready',version:'0.22.7',automatic_pairing:true,one_click_pairing:true,product_downloads:true,product_catalog:true,product_snapshots:true,independent_product_reviews:true,shared_product_identity:true,review_stop_save:true,browser_zip_delivery:true,review_target_continuation:true,review_visibility_wait:true};
  window.fetch=async(url,opts={})=>{
    const path=new URL(url).pathname;audit.requests.push({path,method:opts.method||'GET'});
    let data;
    if(path==='/v1/health')data=health;
    else if(path==='/v1/pair')data={session_token:'synthetic-not-a-credential',persisted:false,origin_bound:true,expires_in_seconds:900};
    else if(path==='/v1/tasks')data={tasks:audit.tasks};
    else if(path==='/v1/settings')data={storage:{configured:true,mode:'browser-zip'}};
    else if(path==='/v1/deliveries'){if(audit.failedDelivery)throw Error('synthetic receipt offline');data={deliveries:audit.deliveries};}
    else if(path.startsWith('/v1/product-reviews/')){if(audit.failedStatus)throw Error('synthetic disconnected');data={task:review};}
    else if(path.endsWith('/collector-options'))data={task};
    else if(path==='/v1/tasks/synthetic-recording/stop'){
      await new Promise(r=>setTimeout(r,400));task.state='stopping';data={task};
    }
    else {audit.unhandled.push(path);throw Error('Blocked unexpected synthetic endpoint: '+path);}
    return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
  };
})();
