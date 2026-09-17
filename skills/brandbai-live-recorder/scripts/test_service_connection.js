"use strict";
// Exercise actual discovery/API/health/session/pairing and start/launch guards.
// Only I/O and unrelated task rendering are synthetic; no browser or live data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../assets/chrome-extension/popup.js'),'utf8')
  .split('elements.recordingPreset.addEventListener(')[0];

function fixture() {
  let now=1000, status=403, offline=false, supported=true, release=null;
  const calls=[], created=[], nodes=new Map(), memory={}, timers=new Map();
  let nextTimer=0;
  const document={querySelector(id){
    if(!nodes.has(id))nodes.set(id,{textContent:'',style:{},classList:{toggle(){},remove(){}},hidden:true});
    return nodes.get(id);
  }};
  const context=vm.createContext({document,URL,Map,Set,Promise,Number,String,AbortController,
    Date:{now:()=>now}, setTimeout(fn,ms){const id=++nextTimer;timers.set(id,{fn,at:now+ms});return id},
    clearTimeout(id){timers.delete(id)},
    fetch:async(url,opts)=>{
      const route=new URL(url).pathname; calls.push({url,route,opts});
      if(offline)throw new Error('synthetic offline');
      if(route==='/v1/health')return {ok:true,status:200,json:async()=>({service:'brandbai-live-recorder',status:'ready',automatic_pairing:supported})};
      if(route==='/v1/pair') {
        if(release===true)await new Promise(resolve=>release=resolve);
        return {ok:status===201,status,json:async()=>status===201?
          {session_token:'s'.repeat(40),persisted:false,origin_bound:true,expires_in_seconds:900}:
          {message:'the service is already paired with another extension; restart it to change origin'}};
      }
      throw new Error('unexpected synthetic route');
    },
    chrome:{runtime:{id:'a'.repeat(32)},storage:{session:{
      async get(key){return {[key]:memory[key]}},async set(data){Object.assign(memory,data)},async remove(key){delete memory[key]}
    }},tabs:{async create(value){created.push(value);return {id:50}},async get(){return {id:12,windowId:1,url:'https://live.douyin.com/123456'}},async update(){},async remove(){}},windows:{async update(){}}}
  });
  vm.runInContext(source,context);
  vm.runInContext('globalThis.actualRefreshTasks=refreshTasks;',context);
  vm.runInContext(`
    currentRoomUrl='https://live.douyin.com/123456';currentRoomTabId=12;currentRoomWindowId=1;
    updateStartAvailability=()=>{};readCurrentTab=async()=>{};
    refreshTasks=async()=>true;refreshStorageSettings=async()=>{storageSettings={configured:true};return true};
    activeTask=()=>null;recordingRequestFromForm=()=>({roomUrl:currentRoomUrl});
    submitRecordingRequest=async()=>{globalThis.submissions=(globalThis.submissions||0)+1;return true};
  `,context);
  const run=s=>vm.runInContext(s,context);
  const flush=async()=>{for(let i=0;i<60;i++)await Promise.resolve()};
  const advance=async(ms)=>{const end=now+ms;await flush();while(true){
    const entry=[...timers.entries()].sort((a,b)=>a[1].at-b[1].at)[0];
    if(!entry || entry[1].at>end)break;timers.delete(entry[0]);now=entry[1].at;entry[1].fn();await flush();
  }now=end;await flush()};
  return {run,flush,advance,calls,created,nodes,paired:()=>calls.filter(c=>c.route==='/v1/pair').length,
    status:v=>status=v,offline:v=>offline=v,supported:v=>supported=v,
    hold:()=>release=true,release:()=>{release();release=null}};
}

(async()=>{
  let f=fixture();
  await assert.rejects(f.run("api('/v1/pair',{method:'POST',auth:false})"),e=>e.status===403);
  f=fixture();await f.run('startTask()');
  assert.equal(f.paired(),1);assert.equal(f.created.length,0,'refused pairing must not launch protocol');
  assert.equal(f.run('pendingRecordingRequest'),null,'do not submit this failed recording later');
  assert.match(f.run('getConnectionIssue()'),/助手已运行/);
  assert.equal(f.nodes.get('#service-badge').textContent,'连接待恢复');
  assert.equal(f.nodes.get('#connection-panel').hidden,false);
  assert.equal(f.nodes.get('#launch-assistant').hidden,true);
  assert.equal(await f.run('beginAssistantLaunch()'),false);assert.equal(f.created.length,0);
  for(let i=0;i<9;i++){await f.advance(3000);assert.equal(await f.run('connectService()'),false)}
  assert.equal(f.paired(),1,'polling must back off after a refusal');
  f.status(201);assert.equal(await f.run('connectService({retry:true})'),true);
  assert.equal(f.run('getConnectionIssue()'),'');assert.equal(f.run('globalThis.submissions||0'),0);
  assert.equal(f.nodes.get('#service-badge').textContent,'助手已连接');
  assert.equal(f.nodes.get('#connection-panel').hidden,true);

  f=fixture();f.status(201);f.hold();
  const first=f.run('connectService()'), second=f.run('connectService({retry:true})');
  assert.equal(first,second,'concurrent callers share one connection result');await f.flush();
  assert.equal(f.paired(),1);f.release();assert.equal(await first,true);assert.equal(await second,true);

  f=fixture();await f.run('connectService()');f.status(201);await f.advance(30000);
  assert.equal(await f.run('connectService()'),true,'bounded auto-retry can recover after helper restart');
  f=fixture();await f.run('connectService()');f.offline(true);
  assert.equal(await f.run('connectService()'),false);assert.equal(f.run('getConnectionIssue()'),'');
  assert.equal(f.nodes.get('#service-badge').textContent,'使用时启动');
  assert.ok(f.calls.every(c=>['8765','18765','28765'].includes(new URL(c.url).port)));

  f=fixture();const launching=f.run('beginAssistantLaunch()');await f.advance(500);
  assert.equal(await launching,false,'online refusal ends launch wait without the 60s timeout');
  assert.equal(f.paired(),1);assert.match(f.run('getConnectionIssue()'),/助手已运行/);
  assert.doesNotMatch(f.nodes.get('#message').textContent,/浏览器确认/);
  f=fixture();f.supported(false);const unsupported=f.run('beginAssistantLaunch()');await f.advance(500);
  assert.equal(await unsupported,false);assert.equal(f.paired(),0);assert.match(f.run('getConnectionIssue()'),/更新助手/);
  f=fixture();f.status(201);
  f.run(`refreshTasks=globalThis.actualRefreshTasks;renderTasks=()=>{};
    sessionToken='s'.repeat(40);let originalApi=api;globalThis.taskReads=0;
    api=(route,options)=>route==='/v1/tasks'?(globalThis.taskReads++,new Promise(resolve=>globalThis.releaseTasks=()=>resolve({tasks:[]}))):originalApi(route,options);`);
  const refreshA=f.run('refreshTasks({silent:true})'), refreshB=f.run('refreshTasks({silent:true})');
  assert.equal(refreshA,refreshB);assert.equal(f.run('globalThis.taskReads'),1);
  const connecting=f.run('connectService({retry:true})');await f.flush();
  f.run('globalThis.releaseTasks()');
  assert.equal(await refreshA,true);assert.equal(await connecting,true);
  assert.equal(f.run('getConnectionIssue()'),'','shared pending task read must not clear a valid pairing');
  assert.equal(f.run('globalThis.taskReads'),1);
  console.log('service connection: refusal, no spurious launch, cooldown, explicit retry, single-flight, recovery and no late recording passed');
})().catch(error=>{console.error(error);process.exitCode=1});
