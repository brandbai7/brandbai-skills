'use strict';
// Synthetic broker tests: actual extension delivery code, no browser/account/files.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const code=fs.readFileSync(path.join(__dirname,'../assets/chrome-extension/browser-delivery.js'),'utf8');
const ID='a'.repeat(32),CLIENT='abcdefghijklmnopabcdefghijklmnop',BASE='http://127.0.0.1:8765';
function fixture(){
  const rows=new Map(),files=[],storage={},calls=[],requests=[],messages=[],changes=[],alarms=[];
  let now=100000,serial=0,reportFailure=false;
  const event=arr=>({addListener:fn=>arr.push(fn)});
  const publicRow=r=>{const c={...r};delete c.ticket;return c;};
  const chrome={runtime:{id:CLIENT,getURL:p=>'chrome-extension://'+CLIENT+'/'+p,onMessage:event(messages)},
    storage:{session:{get:async k=>({[k]:storage[k]}),set:async v=>Object.assign(storage,v)}},
    alarms:{create:async()=>{},onAlarm:event(alarms)},downloads:{onChanged:event(changes),
      search:async q=>files.filter(x=>q.id!=null?x.id===q.id:new RegExp(q.urlRegex).test(x.url)),
      download:async options=>{calls.push(options);const id=files.length+1;files.push({id,url:options.url,byExtensionId:CLIENT,state:'in_progress',bytesReceived:0});return id;},
      show:async id=>{requests.push('show:'+id);},pause:async id=>{files.find(x=>x.id===id).paused=true;},
      resume:async id=>{files.find(x=>x.id===id).paused=false;},cancel:async id=>{Object.assign(files.find(x=>x.id===id),{state:'interrupted',error:'USER_CANCELED'});}}};
  const api=async(route,options={})=>{
    requests.push(route);
    if(route==='/v1/deliveries')return {deliveries:[...rows.values()].map(publicRow)};
    const [,id,action]=route.match(/^\/v1\/deliveries\/([a-f0-9]{32})\/(\w+)$/)||[];
    const r=rows.get(id);if(!r)throw Error('not found');
    if(action==='prepare')return {delivery:publicRow(r)};
    if(action==='claim'){
      if(['starting','downloading','paused'].includes(r.state))return {delivery:publicRow(r)};
      Object.assign(r,{state:'starting',attempt_id:(++serial).toString(16).padStart(32,'0'),attempt_created_at:now/1000,ticket:'synthetic-scoped-ticket'});
      return {delivery:{...r,file_route:`/v1/deliveries/${id}/file/${r.attempt_id}`}};
    }
    if(action==='report'){
      if(reportFailure){reportFailure=false;throw Error('synthetic report failure');}
      assert.equal(r.attempt_id,options.body.attempt_id);Object.assign(r,options.body);return {delivery:publicRow(r)};
    }
    if(action==='missing'){r.state='interrupted';return {delivery:publicRow(r)};}
    throw Error('unexpected route');
  };
  const context={chrome,api,URL,Set,Promise,Date:{now:()=>now},activeServiceBase:BASE,SERVICE_BASES:[BASE,'http://127.0.0.1:18765','http://127.0.0.1:28765']};
  context.self=context;vm.runInNewContext(code,context);
  const add=(id=ID)=>{rows.set(id,{id,kind:'product',state:'ready',filename:'合成商品资料.zip',bytes_total:1234,recoverable:true});return rows.get(id);};
  const flush=async()=>{for(let i=0;i<120;i++)await Promise.resolve();};
  const send=(action,id=ID,sender={id:CLIENT,url:'chrome-extension://'+CLIENT+'/popup.html'})=>new Promise(resolve=>messages[0]({type:'brandbai-delivery',action,id},sender,resolve));
  return {add,rows,files,storage,calls,requests,flush,send,context,changes,advance:ms=>now+=ms,failReport:()=>reportFailure=true};
}
(async()=>{
  let f=fixture();f.add();await f.context.BrandbaiDelivery.sync();assert.equal(f.calls.length,0,'restart must not download historical ready packages');
  await f.context.BrandbaiDelivery.watch(ID);await Promise.all([f.context.BrandbaiDelivery.sync(),f.context.BrandbaiDelivery.sync(),f.send('download'),f.send('download')]);
  assert.equal(f.calls.length,1,'automatic and simultaneous manual retries dispatch only once');
  assert.equal(f.calls[0].saveAs,false);assert.equal(f.calls[0].conflictAction,'uniquify');assert.equal(f.calls[0].filename,'合成商品资料.zip');
  assert.equal(new URL(f.calls[0].url).search,'');assert.deepEqual(f.calls[0].headers.map(x=>x.name).join(','),'X-BrandBAI-FileTicket,X-BrandBAI-Client');
  assert.equal(f.rows.get(ID).state,'downloading','download ID is not success');
  f.files[0].bytesReceived=400;await f.context.BrandbaiDelivery.sync();assert.equal(f.rows.get(ID).bytes_received,400);
  await f.send('pause');await f.context.BrandbaiDelivery.sync();assert.equal(f.rows.get(ID).state,'paused');
  await f.send('resume');await f.context.BrandbaiDelivery.sync();assert.equal(f.rows.get(ID).state,'downloading');
  Object.assign(f.files[0],{state:'complete',bytesReceived:1234});f.changes[0]({id:1,state:{current:'complete'}});await f.flush();
  assert.equal(f.rows.get(ID).state,'completed');await f.send('show');assert.ok(f.requests.includes('show:1'));
  assert.equal(JSON.stringify(f.storage).includes('ticket'),false);

  f=fixture();f.add();await f.send('download');await f.send('cancel');f.changes[0]({id:1,state:{current:'interrupted'}});await f.flush();
  assert.equal(f.rows.get(ID).state,'canceled');await f.context.BrandbaiDelivery.sync();assert.equal(f.calls.length,1);
  await f.send('download');assert.equal(f.calls.length,2,'explicit cancel retry uses existing package');

  f=fixture();f.add();f.failReport();await f.send('download');assert.equal(f.calls.length,1);assert.equal(f.rows.get(ID).state,'starting');
  await f.context.BrandbaiDelivery.sync();assert.equal(f.calls.length,1);assert.equal(f.rows.get(ID).state,'downloading');

  f=fixture();const r=f.add();Object.assign(r,{state:'starting',attempt_id:'b'.repeat(32),attempt_created_at:100});
  await f.send('download');assert.equal(f.calls.length,0,'uncertain fresh dispatch cannot be replaced');f.advance(16000);
  await f.send('download');assert.equal(f.calls.length,1,'explicit aged missing record retry is allowed');

  f=fixture();f.add();const denied=await f.send('download',ID,{id:CLIENT,url:'https://live.douyin.com/123',tab:{id:1}});
  assert.ok(denied.error);assert.equal(f.calls.length,0);
  f.files.push({id:1,url:'https://example.test/other.zip',byExtensionId:CLIENT,state:'complete'});
  f.changes[0]({id:1,state:{current:'complete'}});await f.flush();assert.equal(f.requests.length,0);
  await Promise.all([f.context.BrandbaiDelivery.watch(ID),f.context.BrandbaiDelivery.watch('b'.repeat(32))]);
  assert.equal(f.storage['brandbai.browserDeliveryWatch'].length,2,'concurrent watch updates are not lost');
  console.log('Browser delivery: 11 broker scenarios passed (serialized dispatch, default ZIP, progress, pause/resume/cancel, recovery, source guards).');
})().catch(e=>{console.error(e);process.exitCode=1;});
