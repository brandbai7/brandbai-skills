/* Synthetic source and clock only; no browser or platform requests. */
'use strict';
const assert=require('node:assert/strict');
const {createCollector}=require('../assets/chrome-extension/product-review-collector.js');
const lease=Object.fromEntries(['documentToken','contextKey','generation','sourceWorkId','sourceSurfaceInstance','productPanelInstanceId','reviewSurfaceInstanceId','filterKey'].map(k=>[k,'synthetic-'+k]));
const row=i=>({reviewId:String(i),reviewerName:'synthetic',dateText:'today',purchasedSku:'one',content:'review '+i,images:[],helpfulCount:0,followups:[],followupStatus:'not_observed'});
async function scenario(mode) {
  let clock=0,waits=0,scrolls=0;const saved=new Map(),finishes=[];
  const state={surface:{ready:true,mode:'product',lease,visibleReviewCount:20},rows:Array.from({length:20},(_,i)=>row(i)),unparsed:1,explicitEnd:false};
  const collector=createCollector({document:{visibilityState:'visible'},window:{},isVisible:()=>true,inspectSurface:()=>state,
    limits:{maxRows:200,maxMs:600000,maxScrolls:600},now:()=>clock,
    sleep:async ms=>{clock+=ms;waits++;if(waits===1){
      if(mode==='filter')state.surface={...state.surface,lease:{...lease,filterKey:'changed'}};
      if(mode==='time')clock=600001;
    }},
    scrollSurface:()=>{scrolls++;state.rows.push(...Array.from({length:20},(_,i)=>row(state.rows.length+i)));state.surface.visibleReviewCount=state.rows.length;return {moved:true,atBottom:false}},
    async sendMessage(m){
      if(m.type==='CAPTURE_DOUYIN_COMMERCE_REVIEWS')for(const r of m.rows)saved.set(r.reviewId,r);
      if(m.type==='FINISH_DOUYIN_COMMERCE_REVIEWS')finishes.push(m);
      return {ok:true,task:{id:'task',runId:'run',reviewCount:saved.size}};
    }});
  collector.start({id:'task',runId:'run',lease});await collector.waitForIdle();
  return {saved,finish:finishes.at(-1),scrolls,waits};
}
(async()=>{
  const target=await scenario('target');assert.equal(target.saved.size,200);assert.equal(target.finish.doneReason,'target_reached');
  assert.equal(target.finish.progress.unparsedReviewCount,1);assert.equal(target.finish.exhausted,false);assert.equal(target.scrolls,9);
  const filter=await scenario('filter');assert.equal(filter.finish.doneReason,'surface_or_filter_changed');assert.equal(filter.scrolls,0);assert.equal(filter.saved.size,20);
  const time=await scenario('time');assert.equal(time.finish.doneReason,'time_limit');assert.equal(time.scrolls,0);
  process.stdout.write('review retries preserve 200-row target, gaps, filter identity and original deadline\n');
})().catch(e=>{process.stderr.write(e.stack+'\n');process.exitCode=1});
