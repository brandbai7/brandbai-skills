'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const room='https://live.douyin.com/123456',id='11111111-1111-4111-8111-111111111111',storage={},calls=[];
const event={addListener(){}},chrome={runtime:{id:'abcdefghijklmnopabcdefghijklmnop',onInstalled:event,onStartup:event,onMessage:event},
  sidePanel:{async setPanelBehavior(){}},tabs:{onRemoved:event},storage:{session:{async get(key){return {[key]:storage[key]}},async set(v){Object.assign(storage,v)},async remove(key){delete storage[key]}}}};
const context=vm.createContext({chrome,URL,console,AbortController,setTimeout,clearTimeout,fetch(){throw Error('network forbidden')},calls});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../assets/chrome-extension/background.js'),'utf8')+
  '\napi=async (url,options)=>{calls.push({url,options});return {task:{id:"'+id+'",runId:"'+id+'",reviewCount:0,state:"collecting"}}};globalThis.invoke=handleMessage;',context);
(async()=>{
  const sender={id:chrome.runtime.id,tab:{id:12,url:room},url:room,documentId:'document-a'};
  const lease=Object.fromEntries(['documentToken','contextKey','generation','sourceWorkId','sourceSurfaceInstance','productPanelInstanceId','reviewSurfaceInstanceId','filterKey'].map(k=>[k,k==='filterKey'?'all':k]));
  const start={type:'brandbai-review-bridge',roomUrl:room,action:'start',body:{request_id:id,room_url:room,lease}};
  await context.invoke(start,sender);assert.equal(calls.length,1);assert.equal(calls[0].url,'/v1/product-reviews');
  // Storage objects have no field-order contract. Mimic a reordered round trip.
  storage['brandbai.reviewBindings'][id].lease=Object.fromEntries(Object.entries(lease).sort(([a],[b])=>a.localeCompare(b)));
  const batch={type:'brandbai-review-bridge',roomUrl:room,action:'event',request_id:id,body:{lease}};
  for(const modified of [{...sender,documentId:'document-b'},{...sender,id:'other-extension'},{...sender,tab:{id:13,url:room}},{...sender,url:'https://live.douyin.com/999'}]){
    await context.invoke(batch,modified);assert.equal(calls.length,1);
  }
  await context.invoke({...batch,body:{lease:{filterKey:'different'}}},sender);assert.equal(calls.length,1);
  for(const key of Object.keys(lease)){
    await context.invoke({...batch,body:{lease:{...lease,[key]:'changed'}}},sender);assert.equal(calls.length,1);
  }
  await context.invoke({...batch,body:{lease:{...lease,extra:'not allowed'}}},sender);assert.equal(calls.length,1);
  await context.invoke({...batch,action:'arbitrary',path:'/v1/tasks'},sender);assert.equal(calls.length,1);
  await context.invoke(batch,sender);assert.equal(calls.length,2);assert.equal(calls[1].url,`/v1/product-reviews/${id}/events`);
  for(const action of ['resume','status']){
    const before=calls.length;
    await context.invoke({...batch,action},{...sender,documentId:'other'});assert.equal(calls.length,before);
    await context.invoke({...batch,action,body:{lease:{...lease,filterKey:'other'}}},sender);assert.equal(calls.length,before);
    await context.invoke({...batch,action},sender);assert.equal(calls.length,before+1);
    assert.equal(calls.at(-1).url,`/v1/product-reviews/${id}${action==='resume'?'/resume':''}`);
  }
  console.log('Review bridge: room, extension, document, tab, lease and fixed-route checks passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
