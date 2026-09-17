/* One delivery center for all material types; collection completeness stays separate. */
(()=>{
  'use strict';
  const list=document.getElementById('browser-delivery-list'),note=document.getElementById('browser-delivery-message');
  let polling=false,signature='',selected=null,all=[],visibleCount=5,historyOpen=false;
  const expanded=new Set();
  const receipts=new WeakMap();
  let statusUnavailable=false;
  const labels={collecting:'正在读取或录制',packing:'正在打包',ready:'可以下载',starting:'准备下载',
    downloading:'正在下载',paused:'下载已暂停',interrupted:'下载未完成',
    canceled:'已取消下载',completed:'下载完成'};
  const kinds={recording:'直播录制',catalog:'商品目录',product:'商品资料',reviews:'商品评价',recorded_products:'本场商品资料'};
  function size(bytes){return `${((bytes||0)/1024/1024).toFixed(1)} MB`;}
  async function command(action,id){
    const reply=await chrome.runtime.sendMessage({type:'brandbai-delivery',action,id});
    if(!reply||reply.error)throw new Error(reply?.error||'下载状态暂未响应，请稍后重试。');
    return reply;
  }
  function inlineAction(item) {
    if(item?.state==='completed')return ['show','在文件夹中显示'];
    if(item?.state==='paused')return ['resume','继续下载'];
    if(['ready','interrupted','canceled'].includes(item?.state))return ['download',item.state==='ready'?'下载资料包':'重试下载已有文件'];
    return [null,'查看下载'];
  }
  function renderInline() {
    for(const host of document.querySelectorAll('.inline-delivery')) {
      const id=host.dataset.deliveryId;
      host.hidden=!id;if(!id)continue;
      let view=receipts.get(host);
      if(!view||view.id!==id) {
        const title=document.createElement('strong'),detail=document.createElement('p'),progress=document.createElement('progress');
        const action=document.createElement('button'),feedback=document.createElement('p');
        action.type='button';action.className='product-secondary';
        progress.setAttribute('aria-label','资料包文件下载进度');
        feedback.setAttribute('role','status');feedback.hidden=true;
        host.replaceChildren(title,detail,progress,action,feedback);
        view={id,title,detail,progress,action,feedback,busy:false};receipts.set(host,view);
        action.onclick=async()=>{
          if(view.busy||host.dataset.deliveryId!==id)return;
          const [operation]=inlineAction(all.find(item=>item.id===id));
          if(!operation||statusUnavailable){window.BrandbaiDownloads.reveal(id);return;}
          view.busy=true;action.disabled=true;feedback.hidden=true;
          try{await command(operation,id);await refresh();}
          catch(error){if(host.dataset.deliveryId===id){feedback.textContent=error.message;feedback.hidden=false;}}
          finally{view.busy=false;if(host.dataset.deliveryId===id)renderInline();}
        };
      }
      const item=all.find(value=>value.id===id),state=item?.state;
      view.title.textContent=statusUnavailable?'文件状态暂未更新':state==='completed'?'文件已下载':labels[state]||'正在确认文件下载';
      view.detail.textContent=statusUnavailable?'正在恢复连接，暂时显示上次确认的文件状态。'
        :state==='completed'?(item.late_data_available?'有新收到的直播信息，可在下载记录中取得更新包。':'已保存到浏览器下载文件夹。')
        :['interrupted','canceled'].includes(state)?'资料已保留，重试只下载已有文件，不会重新采集。'
        :state==='paused'?'文件下载已暂停，取得的资料仍保留。'
        :item?.bytes_total?`${size(state==='packing'?item.bytes_packed:item.bytes_received)} / ${size(item.bytes_total)}`
        :state==='packing'?'正在生成压缩包。':'文件是否下载好，以这里的状态为准。';
      view.progress.hidden=statusUnavailable||!['packing','downloading','paused'].includes(state);
      view.progress.max=Math.max(1,item?.bytes_total||0);
      if(item?.bytes_total)view.progress.value=state==='packing'?item.bytes_packed||0:item.bytes_received||0;
      else view.progress.removeAttribute('value');
      view.action.textContent=statusUnavailable?'查看下载':inlineAction(item)[1];
      view.action.disabled=view.busy;
    }
  }
  function button(card,text,action,item){
    const b=document.createElement('button');b.type='button';b.textContent=text;b.className='product-secondary';
    b.onclick=async()=>{b.disabled=true;try{await command(action,item.id);note.textContent='';signature='';await refresh();}
      catch(e){note.textContent=e.message;}finally{b.disabled=false;}};
    card.append(b);
  }
  function render(){
    const next=JSON.stringify([all,selected,visibleCount]);if(next===signature)return;signature=next;
    list.replaceChildren();
    const active=all.filter(x=>['collecting','packing','starting','downloading','paused'].includes(x.state));
    const featured=selected?all.filter(x=>x.id===selected):active;
    const history=all.filter(x=>!featured.some(y=>y.id===x.id));
    const renderItem=(item,parent)=>{
      const card=document.createElement('details');card.className='browser-delivery-item';
      card.open=item.id===selected||expanded.has(item.id);
      card.addEventListener('toggle',()=>{if(card.open)expanded.add(item.id);else expanded.delete(item.id);});
      const summary=document.createElement('summary');
      const title=document.createElement('strong');title.textContent=`${kinds[item.kind]||'资料包'} · ${labels[item.state]||'请稍后查看'}`;
      const name=document.createElement('p');name.className='muted';name.textContent=item.filename||new Date(item.created_at*1000).toLocaleString();
      summary.append(title,name);card.append(summary);
      if(['packing','downloading','paused'].includes(item.state)){
        const progress=document.createElement('progress');progress.max=Math.max(1,item.bytes_total||0);
        if(item.bytes_total)progress.value=item.state==='packing'?item.bytes_packed||0:item.bytes_received||0;
        const detail=document.createElement('p');detail.textContent=item.bytes_total
          ?`${size(progress.value)} / ${size(item.bytes_total)}`:'正在核对资料大小……';card.append(progress,detail);
      }
      if(item.reason){const p=document.createElement('p');p.className='muted';p.textContent=item.reason==='delivery_storage_low'
        ?'临时磁盘空间不足。已取得资料保留，请释放空间后重试。':'当前步骤未完成，可以重试；不会重新采集商品或重新录制。';card.append(p);}
      if(item.late_data_available){const p=document.createElement('p');p.textContent='有新收到的直播互动，可下载更新后的文件。';card.append(p);}
      if(item.state==='completed')button(card,'在文件夹中显示','show',item);
      if(item.state==='downloading')button(card,'暂停下载','pause',item);
      if(item.state==='paused')button(card,'继续下载','resume',item);
      if(['downloading','paused'].includes(item.state))button(card,'取消本次下载','cancel',item);
      if(['ready','interrupted','canceled','starting'].includes(item.state)||(item.state==='completed'&&item.late_data_available))
        button(card,item.late_data_available?'下载更新后的资料包':item.state==='ready'?'下载资料包':'重试下载已有资料','download',item);
      parent.append(card);
    };
    if(!all.length){list.textContent='还没有下载记录。';return;}
    for(const item of featured)renderItem(item,list);
    if(history.length){
      const box=document.createElement('details');box.className='download-history';box.open=historyOpen;
      const summary=document.createElement('summary');summary.textContent=`历史下载（${history.length}）`;box.append(summary);
      box.addEventListener('toggle',()=>{historyOpen=box.open;});
      const rows=document.createElement('div');rows.className='download-history-rows';box.append(rows);
      for(const item of history.slice(0,visibleCount))renderItem(item,rows);
      if(history.length>visibleCount){const b=document.createElement('button');b.type='button';b.className='product-secondary';
        b.textContent='再显示 5 条';b.onclick=()=>{visibleCount+=5;render();};box.append(b);}
      list.append(box);
    }
  }
  async function refresh(){
    if(polling||!sessionToken)return;polling=true;
    try{const response=await api('/v1/deliveries');all=response.deliveries||[];statusUnavailable=false;render();void command('sync').catch(()=>{});}
    catch(_){statusUnavailable=true;/* Retain last confirmed receipts, without claiming live progress. */}
    finally{polling=false;renderInline();}
  }
  window.BrandbaiDownloads={reveal(id){selected=id;historyOpen=false;const box=document.getElementById('storage-settings');box.open=true;
    box.scrollIntoView({behavior:'smooth',block:'start'});signature='';render();void refresh();},refresh,renderInline};
  renderInline();
  setInterval(refresh,2000);void refresh();
})();
