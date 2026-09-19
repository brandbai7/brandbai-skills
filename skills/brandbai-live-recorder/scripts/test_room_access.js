"use strict";
// Exercise real sidebar functions using synthetic Chrome responses only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../assets/chrome-extension/popup.js'),'utf8');
const functions = ['canonicalRoomUrl','roomNameFromTab','loadCollectorOptions','roomTabWithTimeout',
  'classifyRoomTab','showRoomAccessState','clearCurrentRoomContext','requestRoomAccess','readCurrentTab','scheduleCurrentTabRead'];
const code = functions.map(name => {
  const match = source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n}`));
  assert.ok(match,name); return match[0];
}).join('\n');
const origins=['https://www.douyin.com/*','https://douyin.com/*'];
const roomA='https://live.douyin.com/123456';
const roomB='https://live.douyin.com/654321';
const tabA={id:1,windowId:11,url:'https://douyin.com/search/synthetic?live_web_rid=123456&type=live',title:'合成直播 A'};
const tabB={id:2,windowId:11,url:roomB,title:'合成直播 B'};
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
function setup() {
  const elements=Object.fromEntries(['roomAccessNotice','roomAccessTitle','roomAccessMessage','roomAccessScope',
    'allowRoomAccess','retryRoomAccess','roomName','pageStatus','roomState','roomStateLabel','start'].map(key=>[key,{hidden:false,disabled:false,textContent:''}]));
  const log={queries:[],requests:[],options:[],refresh:0};
  const context=vm.createContext({URL,Promise,setTimeout,clearTimeout,Number,Date,Error,console,elements,log,
    ROOM_TAB_TIMEOUT_MS:40,DOUYIN_OPTIONAL_ORIGINS:origins,COLLECTOR_OPTIONS_KEY:'collector',
    roomReadGeneration:0,roomAccessRequestInFlight:false,currentRoomUrl:null,currentRoomTabId:null,currentRoomWindowId:null,
    pagePlaybackPaused:false,tabRefreshTimer:null,sessionToken:null,
    applyCollectorOptionsToForm:value=>log.options.push(value),updatePlaybackPauseNotice:()=>{},
    refreshPagePlaybackState:()=>{},refreshTasks:()=>{log.refresh++},setMessage:()=>{},
    chrome:{tabs:{query:async options=>{log.queries.push(options);return [tabA]}},
      storage:{session:{get:async()=>({collector:{}})}},
      permissions:{request:async options=>{log.requests.push(options);return true}}}});
  vm.runInContext('function updateStartAvailability(){elements.start.disabled=!currentRoomUrl;}\n'+code,context);
  return {c:context,e:elements,log};
}
async function run() {
  let {c,e,log}=setup();
  assert.equal(c.classifyRoomTab({id:1}),'access_required');
  assert.equal(c.classifyRoomTab(null),'no_tab');
  assert.equal(c.classifyRoomTab({url:'https://example.test'}),'not_live');
  assert.equal(c.classifyRoomTab({url:'https://www.douyin.com/search/synthetic?type=video'}),'not_live');
  assert.equal(c.classifyRoomTab({url:tabA.url+'&live_web_rid=99'}),'entry_unconfirmed');
  assert.equal(c.classifyRoomTab({url:tabA.url.replace('type=live','type=general')}),'recognized');
  assert.equal(c.classifyRoomTab({url:'https://www.douyin.com/search/synthetic?type=general'}),'not_live');
  assert.equal(c.classifyRoomTab({url:tabA.url.replace('type=live','type=general')+'&live_web_rid=99'}),'entry_unconfirmed');
  await c.readCurrentTab();
  assert.equal(c.currentRoomUrl,roomA);assert.equal(e.roomName.textContent,'合成直播 A');
  assert.equal(e.roomAccessNotice.hidden,true);assert.equal(e.start.disabled,false);
  assert.equal(log.requests.length,0,'recognition never prompts automatically');
  c.chrome.tabs.query=async()=>[{id:1}]; await c.readCurrentTab();
  assert.equal(c.currentRoomUrl,null);assert.equal(e.allowRoomAccess.hidden,false);assert.equal(e.start.disabled,true);
  c.chrome.permissions.request=options=>{log.requests.push(options);return Promise.resolve(false)};
  await c.requestRoomAccess();
  assert.match(e.roomAccessMessage.textContent,/尚未授权/);assert.equal(e.allowRoomAccess.disabled,false);
  assert.deepEqual(Array.from(log.requests[0].origins),origins);
  c.chrome.permissions.request=()=>Promise.reject(new Error('synthetic denial'));
  await c.requestRoomAccess();assert.match(e.roomAccessMessage.textContent,/未能打开站点授权/);
  // The request is synchronous in the gesture, with no preceding tab query/await.
  const grant=deferred();let invoked=false;
  c.chrome.permissions.request=()=>{invoked=true;return grant.promise};
  const pending=c.requestRoomAccess();assert.equal(invoked,true);assert.equal(e.allowRoomAccess.disabled,true);
  await c.requestRoomAccess(); // duplicate click must not prompt twice
  c.chrome.tabs.query=async()=>[tabB];grant.resolve(true);await pending;
  assert.equal(c.currentRoomUrl,roomB);assert.equal(e.roomAccessNotice.hidden,true);
  assert.equal(log.refresh,0,'grant does not create/restart any task');
  // Slow previous query cannot replace the newly selected tab.
  ({c,e,log}=setup());const old=deferred();c.chrome.tabs.query=()=>old.promise;
  const oldRead=c.readCurrentTab();c.chrome.tabs.query=async()=>[tabB];await c.readCurrentTab();
  old.resolve([tabA]);await oldRead;assert.equal(c.currentRoomUrl,roomB);assert.equal(e.roomName.textContent,'合成直播 B');
  // Scope options from a late old-room response cannot modify the new room.
  ({c,e,log}=setup());const storage=deferred();c.chrome.storage.session.get=()=>storage.promise;
  const first=c.readCurrentTab();await Promise.resolve();await Promise.resolve();await Promise.resolve();
  c.chrome.tabs.query=async()=>[tabB];c.chrome.storage.session.get=async()=>({collector:{[roomB]:{enabled:false}}});
  await c.readCurrentTab();storage.resolve({collector:{[roomA]:{enabled:true}}});await first;
  assert.equal(c.currentRoomUrl,roomB);assert.ok(log.options.every(value=>value.enabled===false));
  // Scheduling invalidates old results immediately during the debounce window.
  const stale=deferred();c.chrome.tabs.query=()=>stale.promise;const staleRead=c.readCurrentTab();
  c.scheduleCurrentTabRead();assert.equal(c.currentRoomUrl,null);assert.equal(e.start.disabled,true);
  clearTimeout(c.tabRefreshTimer);c.tabRefreshTimer=null;stale.resolve([tabA]);await staleRead;
  assert.equal(c.currentRoomUrl,null);
  c.chrome.tabs.query=()=>new Promise(()=>{});await c.readCurrentTab();
  assert.match(e.roomName.textContent,/暂时无法读取/);assert.equal(e.allowRoomAccess.hidden,true);
  c.chrome.tabs.query=async()=>[tabA];await c.readCurrentTab();assert.equal(c.currentRoomUrl,roomA);
  // Listener wiring: revoke/grant, focus, visibility and navigation all recheck.
  const listeners={};const record=key=>({addListener:fn=>{listeners[key]=fn}});
  c.chrome.permissions={onAdded:record('grant'),onRemoved:record('revoke')};
  c.chrome.tabs.onActivated=record('activate');c.chrome.tabs.onUpdated=record('updated');
  c.window={addEventListener:(key,fn)=>{listeners[key]=fn}};
  c.document={visibilityState:'visible',addEventListener:(key,fn)=>{listeners[key]=fn}};
  vm.runInContext(source.slice(source.indexOf('chrome.permissions?.onAdded'),source.indexOf('\nsetInterval(() => {')),c);
  for(const key of ['grant','revoke','focus','visibilitychange','activate']) {
    c.currentRoomUrl=roomA;listeners[key]();assert.equal(c.currentRoomUrl,null,key);
    clearTimeout(c.tabRefreshTimer);c.tabRefreshTimer=null;
  }
  c.currentRoomUrl=roomA;listeners.updated(1,{status:'loading'},{active:true});assert.equal(c.currentRoomUrl,null);
  clearTimeout(c.tabRefreshTimer);
  console.log('room access: missing/denied/granted/revoked permissions, scoped request, current-tab binding, stale queries/options, timeout recovery, event wiring passed');
}
run().catch(error=>{console.error(error);process.exitCode=1});
