/* Synthetic clocks and rows only; no platform, accounts, or real browser. */
'use strict';
const assert=require('node:assert/strict');
const {createCollector}=require('../assets/chrome-extension/product-review-collector.js');
const lease=Object.fromEntries(['documentToken','contextKey','generation','sourceWorkId','sourceSurfaceInstance','productPanelInstanceId','reviewSurfaceInstanceId','filterKey'].map(k=>[k,'test-'+k]));
const row=i=>({reviewId:String(i),reviewerName:'buyer',dateText:'today',purchasedSku:'one',content:'synthetic '+i,images:[],helpfulCount:0,followups:[],followupStatus:'not_observed'});
async function scenario(mode){
  let clock=0,scrolls=0,hiddenReads=0,hiddenScrolls=0,hiddenWaits=0;
  const doc={visibilityState:'visible'},saved=new Set(),events=[];
  const state={surface:{mode:'product',ready:true,lease:{...lease},visibleReviewCount:60},rows:Array.from({length:60},(_,i)=>row(i)),unparsed:0};
  let collector;
  collector=createCollector({document:doc,window:{},isVisible:()=>true,
    limits:{maxRows:200,maxMs:600000,maxScrolls:600},now:()=>clock,
    inspectSurface(){if(doc.visibilityState==='hidden')hiddenReads++;return state;},
    async sleep(ms){clock+=ms;if(doc.visibilityState==='hidden'){
      hiddenWaits++;
      if(mode==='stop')collector.requestPause({taskId:'test',runId:'test'});
      if(mode==='resume'||mode==='changed'){
        doc.visibilityState='visible';
        if(mode==='changed')state.surface.lease.filterKey='different';
        else state.rows=Array.from({length:200},(_,i)=>row(i));
      }
    }},
    scrollSurface(){scrolls++;if(doc.visibilityState==='hidden')hiddenScrolls++;return {moved:true};},
    async sendMessage(m){events.push(m);if(m.type.startsWith('CAPTURE')){
      for(const r of m.rows)saved.add(r.reviewId);
      if(saved.size===60&&!hiddenWaits)doc.visibilityState='hidden';
    }
    return {ok:true,task:{id:'test',runId:'test',reviewCount:saved.size,
      ...(mode==='remote'&&m.progress?.phase==='waiting_page'?{state:'saved'}:{})}};
  }});
  collector.start({id:'test',runId:'test',lease});await collector.waitForIdle();
  assert.equal(hiddenReads,0);assert.equal(hiddenScrolls,0);
  assert.ok(events.some(m=>m.progress?.phase==='waiting_page'));
  return {saved,events,clock,collector,scrolls};
}
(async()=>{
  const resumed=await scenario('resume');assert.equal(resumed.saved.size,200);
  assert.equal(resumed.events.at(-1).doneReason,'target_reached');
  assert.equal(resumed.events.filter(m=>m.type.startsWith('FINISH')).length,1);
  const changed=await scenario('changed');assert.equal(changed.saved.size,60);assert.equal(changed.events.at(-1).doneReason,'surface_or_filter_changed');
  const stopped=await scenario('stop');assert.equal(stopped.saved.size,60);assert.equal(stopped.events.at(-1).doneReason,'user_paused');
  const timeout=await scenario('timeout');assert.equal(timeout.clock,300000);assert.equal(timeout.events.at(-1).doneReason,'page_hidden');
  const remote=await scenario('remote');assert.equal(remote.events.filter(m=>m.type.startsWith('FINISH')).length,0);
  console.log('review visibility: 60 to 200, hidden read/scroll guard, changed filter, stop, timeout, remote save passed');
})().catch(e=>{console.error(e);process.exitCode=1});
