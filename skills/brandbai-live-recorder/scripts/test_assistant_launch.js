"use strict";
// Actual popup functions, a virtual clock and synthetic tabs. No live browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../assets/chrome-extension/popup.js'),'utf8')
  .split('elements.recordingPreset.addEventListener(')[0];
function fixture() {
  let now=0, ready=false, next=50;
  const timers=[], removed=[], updated=[], created=[];
  const tabs=new Map([[12,{id:12,windowId:1,url:'https://live.douyin.com/123456'}]]);
  const nodes=new Map();
  const document={querySelector(id){if(!nodes.has(id))nodes.set(id,{style:{},classList:{toggle(){},remove(){}},hidden:true});return nodes.get(id)}};
  const context=vm.createContext({document,Date:{now:()=>now},URL,Map,Set,Promise,
    setTimeout(fn,ms){timers.push({at:now+ms,fn});return timers.length;},clearTimeout(){},
    chrome:{runtime:{id:'synthetic-extension'},tabs:{
      async get(id){if(!tabs.has(id))throw Error('closed');return tabs.get(id)},
      async create(value){const tab={...value,id:next++};tabs.set(tab.id,tab);created.push(tab);return tab},
      async remove(id){removed.push(id);tabs.delete(id)},
      async update(id,value){updated.push(id);return Object.assign(tabs.get(id),value)}
    },windows:{async update(){}}}});
  vm.runInContext(source,context);
  context.health=()=>{if(!ready)throw new Error('synthetic offline');return {status:'ready',automatic_pairing:true}};
  vm.runInContext(`
    currentRoomUrl='https://live.douyin.com/123456';currentRoomTabId=12;currentRoomWindowId=1;
    api=async()=>health();updateStartAvailability=()=>{};readCurrentTab=async()=>{};
    connectService=async()=>{sessionToken='synthetic';return true;};
  `,context);
  const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve()};
  const advance=async(ms)=>{const end=now+ms;await flush();while(true){timers.sort((a,b)=>a.at-b.at);if(!timers.length||timers[0].at>end)break;const t=timers.shift();now=t.at;t.fn();await flush()}now=end;await flush()};
  return {run:s=>vm.runInContext(s,context),advance,flush,removed,updated,created,tabs,ready:()=>{ready=true}};
}
(async()=>{
  let f=fixture(); const pending=f.run('beginAssistantLaunch()');await f.advance(8000);
  assert.equal(f.created.length,1);assert.deepEqual(f.removed,[],'native prompt must survive the old 6-second deadline');
  f.ready();await f.advance(400);assert.equal(await pending,true);assert.deepEqual(f.removed,[50]);assert.ok(f.updated.includes(12));
  f=fixture();f.run('pendingRecordingRequest={roomUrl:currentRoomUrl}');const timed=f.run('beginAssistantLaunch()');await f.advance(61000);
  assert.equal(await timed,false);assert.deepEqual(f.removed,[],'timeout cannot dismiss permission');assert.equal(f.run('pendingRecordingRequest'),null);
  f=fixture();const first=f.run('beginAssistantLaunch()'),second=f.run('beginAssistantLaunch()');await f.flush();assert.equal(f.created.length,1);
  await f.run('cancelAssistantLaunch()');await f.advance(400);assert.equal(await first,false);assert.equal(await second,false);assert.deepEqual(f.removed,[50]);
  f=fixture();const navigated=f.run('beginAssistantLaunch()');await f.flush();f.tabs.get(50).url='https://example.test/user-page';f.ready();await f.advance(400);
  assert.equal(await navigated,true);assert.deepEqual(f.removed,[],'do not close a user-repurposed tab');
  console.log('assistant launch: delayed approval, timeout, explicit cancellation, single-flight, and tab ownership passed');
})().catch(error=>{console.error(error);process.exitCode=1});
