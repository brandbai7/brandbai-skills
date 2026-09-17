/* Synthetic clock/surface only. No platform or browser access. */
'use strict';
const assert=require('node:assert/strict');
const {createCollector}=require('../assets/chrome-extension/product-review-collector.js');
const lease=Object.fromEntries(['documentToken','contextKey','generation','sourceWorkId','sourceSurfaceInstance','productPanelInstanceId','reviewSurfaceInstanceId','filterKey'].map(k=>[k,'synthetic-'+k]));
const row=i=>({reviewId:String(i),reviewerName:'synthetic',dateText:'today',purchasedSku:'one',content:'review '+i,images:[],helpfulCount:0,followups:[],followupStatus:'not_observed'});
function harness(limits){
  let clock=0,current,collector;const saved=new Map(),outcomes=[],batches=[];
  const state={surface:{ready:true,lease,visibleReviewCount:1},rows:[row(1)],unparsed:0,explicitEnd:false};
  collector=createCollector({document:{visibilityState:'visible'},window:{},isVisible:()=>true,inspectSurface:()=>state,
    limits,now:()=>clock,sleep:async ms=>{clock+=ms},scrollSurface:()=>({moved:true,atBottom:false}),
    async sendMessage(m){
      if(m.type==='CAPTURE_DOUYIN_COMMERCE_REVIEWS'){batches.push(m.rows);for(const r of m.rows)saved.set(r.reviewId,r);}
      if(m.type==='FINISH_DOUYIN_COMMERCE_REVIEWS')outcomes.push(m.doneReason);
      return {ok:true,task:{id:current.id,runId:current.runId,reviewCount:saved.size}};
    }});
  return {collector,state,saved,outcomes,batches,
    async run(id,resumeFrom=null){current={id,runId:id,lease,reviewCount:resumeFrom?saved.size:0};collector.start(current,{resumeFrom});await collector.waitForIdle();},
    clock:()=>clock};
}
(async()=>{
  const time=harness({maxRows:200,maxMs:1000,maxScrolls:600});await time.run('first');
  assert.equal(time.outcomes.at(-1),'time_limit');assert.equal(time.saved.size,1);
  assert.equal(time.collector.canResume('first',lease),true);
  time.state.rows.push(row(2));time.state.explicitEnd=true;
  await time.run('continued','first');assert.equal(time.saved.size,2);assert.equal(time.outcomes.at(-1),'source_exhausted');
  assert.deepEqual(time.batches.flat().map(r=>r.reviewId),['1','2']);
  assert.equal(time.collector.canResume('continued',{...lease,filterKey:'changed'}),false);
  const scroll=harness({maxRows:200,maxMs:600000,maxScrolls:1});await scroll.run('scroll');assert.equal(scroll.outcomes.at(-1),'scroll_limit');
  const target=harness({maxRows:1,maxMs:600000});await target.run('target');assert.equal(target.outcomes.at(-1),'target_reached');assert.equal(target.clock(),0);
  // Versions of one platform review are updates, not extra completed target rows.
  const versions=harness({maxRows:2,maxMs:1000});await versions.run('versions');
  versions.state.rows[0]={...row(1),helpfulCount:1};versions.state.rows.push(row(2));
  versions.collector.configureLimits({maxRows:2,maxMs:600000,maxScrolls:600});
  await versions.run('versions-next','versions');assert.equal(versions.saved.size,2);assert.equal(versions.outcomes.at(-1),'target_reached');
  process.stdout.write('review target, time, scroll, continuation and version dedup passed\n');
})().catch(e=>{process.stderr.write(e.stack+'\n');process.exitCode=1});
