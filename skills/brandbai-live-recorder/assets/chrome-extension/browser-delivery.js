/* Background-only ZIP transport. No cookies, arbitrary URLs, paths, or page actions. */
(()=>{
  'use strict';
  const WATCH='brandbai.browserDeliveryWatch',ALARM='brandbai-browser-deliveries';
  const valid=id=>typeof id==='string'&&/^[a-f0-9]{32}$/.test(id);
  const active=new Set(['starting','downloading','paused']);
  let flight=null,queue=Promise.resolve(),watchQueue=Promise.resolve();
  function serial(fn){const result=queue.then(fn);queue=result.catch(()=>{});return result;}
  function changeWatches(fn){const result=watchQueue.then(async()=>{
    await chrome.storage.session.set({[WATCH]:fn(await watches())});
  });watchQueue=result.catch(()=>{});return result;}
  async function watches(){return (await chrome.storage.session.get(WATCH))[WATCH]||[];}
  async function watch(id){
    if(!valid(id))return;
    await changeWatches(ids=>ids.includes(id)?ids:[...ids,id].slice(-200));
    await chrome.alarms.create(ALARM,{periodInMinutes:1});
  }
  async function forget(id){await changeWatches(ids=>ids.filter(x=>x!==id));}
  async function observe(payload,method,path){
    const item=payload?.task?.delivery||payload?.product_download?.delivery;
    if(item&&method==='POST'&&!path.startsWith('/v1/deliveries/')){
      await watch(item.id);void sync().catch(()=>{});
    }
  }
  function fileUrl(item){return `${activeServiceBase}/v1/deliveries/${item.id}/file/${item.attempt_id}`;}
  async function browserItem(item){
    if(!item.attempt_id)return null;
    // Search only this attempt; never enumerate unrelated browser downloads.
    for(const base of SERVICE_BASES){
      const url=base+`/v1/deliveries/${item.id}/file/${item.attempt_id}`;
      const results=await chrome.downloads.search({urlRegex:'^'+url.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'$',limit:10});
      const found=results.find(x=>x.byExtensionId===chrome.runtime.id&&x.url===url);
      if(found)return found;
    }
    return null;
  }
  async function report(item,download){
    const state=download.state==='complete'?'completed':download.state==='interrupted'
      ?download.error==='USER_CANCELED'?'canceled':'interrupted':download.paused?'paused':'downloading';
    const result=await api(`/v1/deliveries/${item.id}/report`,{method:'POST',body:{attempt_id:item.attempt_id,
      download_id:download.id,state,bytes_received:Math.max(0,Math.floor(download.bytesReceived||0)),reason:download.error||null}});
    if(['completed','interrupted','canceled'].includes(state))await forget(item.id);
    return result.delivery;
  }
  async function start(item,retry=false){
    if(item.state==='interrupted'&&item.attempt_id){
      const prior=await browserItem(item);
      if(prior&&prior.state!=='interrupted')return report(item,prior);
    }
    if(active.has(item.state)){
      const existing=await browserItem(item);
      if(existing)return report(item,existing);
      if(!retry||Date.now()/1000-(item.attempt_created_at||0)<15)return item;
      item=(await api(`/v1/deliveries/${item.id}/missing`,{method:'POST',body:{}})).delivery;
    }
    const prepared=(await api(`/v1/deliveries/${item.id}/prepare`,{method:'POST',body:{}})).delivery;
    if(prepared.state==='packing'){await watch(item.id);return prepared;}
    if(prepared.recoverable===false)throw new Error('临时副本已清理，请在浏览器下载记录中查找已保存文件。');
    const claimed=(await api(`/v1/deliveries/${item.id}/claim`,{method:'POST',body:{retry}})).delivery;
    if(!claimed.ticket)return claimed;
    const route=`/v1/deliveries/${item.id}/file/${claimed.attempt_id}`;
    if(claimed.file_route!==route||!SERVICE_BASES.includes(activeServiceBase))throw new Error('下载地址未确认');
    let dispatchReturned=false;
    try{
      const downloadId=await chrome.downloads.download({url:activeServiceBase+route,filename:claimed.filename,
        saveAs:false,conflictAction:'uniquify',headers:[{name:'X-BrandBAI-FileTicket',value:claimed.ticket},
          {name:'X-BrandBAI-Client',value:chrome.runtime.id}]});
      dispatchReturned=true;
      const [download]=await chrome.downloads.search({id:downloadId});
      if(download)return report(claimed,download);
      return claimed;
    }catch(_){
      // Preserve the package; no automatic redispatch of an uncertain download.
      if(dispatchReturned)return claimed; // A report failure is not a failed download.
      await forget(item.id);
      return (await api(`/v1/deliveries/${item.id}/missing`,{method:'POST',body:{}})).delivery;
    }
  }
  function sync(){
    if(flight)return flight;
    flight=serial(async()=>{
      const ids=await watches();if(!ids.length)return;
      const {deliveries=[]}=await api('/v1/deliveries');
      for(const item of deliveries.filter(x=>ids.includes(x.id))){
        if(item.state==='ready')await start(item);
        else if(active.has(item.state)){
          const download=await browserItem(item);if(download)await report(item,download);
        }else if(['interrupted','canceled','completed'].includes(item.state))await forget(item.id);
      }
    }).finally(()=>{flight=null;});return flight;
  }
  self.BrandbaiDelivery={observe,watch,sync};
  chrome.alarms.onAlarm.addListener(alarm=>{if(alarm.name===ALARM)void sync().catch(()=>{});});
  chrome.downloads.onChanged.addListener(change=>{
    if(!change.state&&!change.paused&&!change.error)return;
    void serial(async()=>{
      const [download]=await chrome.downloads.search({id:change.id});
      if(download?.byExtensionId!==chrome.runtime.id)return;
      const url=new URL(download.url);
      if(!SERVICE_BASES.includes(url.origin))return;
      const match=url.pathname.match(/^\/v1\/deliveries\/([a-f0-9]{32})\/file\/([a-f0-9]{32})$/);
      if(!match)return;
      const {deliveries=[]}=await api('/v1/deliveries');
      const item=deliveries.find(x=>x.id===match[1]&&x.attempt_id===match[2]);
      if(item)await report(item,download);
    }).catch(()=>{});
  });
  chrome.runtime.onMessage.addListener((message,sender,reply)=>{
    if(message?.type!=='brandbai-delivery')return false;
    if(sender.id!==chrome.runtime.id||sender.url!==chrome.runtime.getURL('popup.html')){
      reply({error:'仅支持插件侧栏操作'});return false;
    }
    (async()=>{
      if(message.action==='watch'&&valid(message.id)){await watch(message.id);void sync().catch(()=>{});return {ok:true};}
      if(message.action==='sync'){await sync();return {ok:true};}
      if(!valid(message.id))throw new Error('资料包未确认');
      return serial(async()=>{
      const {deliveries=[]}=await api('/v1/deliveries'),item=deliveries.find(x=>x.id===message.id);
      if(!item)throw new Error('资料包未找到');
      if(message.action==='download'){
        await watch(item.id);return {delivery:await start(item,true)};
      }
      const download=await browserItem(item);
      if(!download)throw new Error('浏览器下载记录未找到，可重新下载已有资料包。');
      if(message.action==='show'){
        if(download.state!=='complete')throw new Error('资料包尚未下载完成');
        await chrome.downloads.show(download.id);return {ok:true};
      }
      if(message.action==='pause')await chrome.downloads.pause(download.id);
      else if(message.action==='resume'){await chrome.downloads.resume(download.id);await watch(item.id);}
      else if(message.action==='cancel'){await chrome.downloads.cancel(download.id);await forget(item.id);}
      else throw new Error('操作不支持');
      return {ok:true};
      });
    })().then(reply).catch(error=>reply({error:error.message||'下载状态暂未确认，请重试。'}));
    return true;
  });
})();
