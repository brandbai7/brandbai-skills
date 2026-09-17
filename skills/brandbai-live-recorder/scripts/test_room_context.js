"use strict";
// Actual extension functions with synthetic URLs/tabs, never a user browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ext = path.join(__dirname,'../assets/chrome-extension');
function code(file, name) {
  const source=fs.readFileSync(path.join(ext,file),'utf8');
  const match=source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n}`));
  assert.ok(match,`${file}: ${name}`); return match[0];
}
const live='https://live.douyin.com/123456';
const search='https://www.douyin.com/jingxuan/search/synthetic?live_web_rid=123456&type=live';
const directSearch=search.replace('/jingxuan/search/','/search/');
const accepted=[live,live+'/?from=synthetic',search,search+'&tracking=DO_NOT_EXPORT',search.replace('synthetic','%E5%90%88%E6%88%90'),
  directSearch,directSearch+'&tracking=DO_NOT_EXPORT',directSearch.replace('synthetic','%E5%90%88%E6%88%90')];
accepted.push(...accepted.filter(url=>url.includes('www.douyin.com')).map(url=>url.replace('www.douyin.com','douyin.com')));
const rejected=['', 'https://live.douyin.com/',live+'/other','https://live.douyin.com/abc',live.replace('https:','http:'),
  'https://user:pass@live.douyin.com/123456','https://live.douyin.com:1234/123456',live.replace('douyin.com','douyin.com.evil.test'),
  search.replace('www.douyin.com','www.douyin.com.evil.test'),search.replace('www.douyin.com','user@www.douyin.com'),
  search.replace('jingxuan/search','video'),search.replace('type=live','type=video'),search.replace('&type=live',''),
  search+'&live_web_rid=999999',search+'&live_web_rid=123456',search+'&type=live',search.replace('123456','abc'),
  'https://www.douyin.com/jingxuan/search/synthetic?type=live',search.replace('/synthetic?','/?'),
  search.replace('www.douyin.com','www.douyin.com:1234'), search.replace('123456','1'.repeat(31)),
  'https://www.douyin.com/?live_web_rid=123456&type=live'];
rejected.push(...rejected.filter(url=>url.includes('/jingxuan/search/')).map(url=>url.replace('/jingxuan/search/','/search/')),
  directSearch.replace('/synthetic?', '/synthetic/other?'),directSearch.replace('/search/', '/research/'));
rejected.push(...rejected.filter(url=>url.includes('www.douyin.com')).map(url=>url.replace('www.douyin.com','douyin.com')));
for(const file of ['popup.js','content.js','background.js']) {
  const context=vm.createContext({URL});vm.runInContext(code(file,'canonicalRoomUrl'),context);
  for(const input of accepted) assert.equal(context.canonicalRoomUrl(input),live,`${file}: ${input}`);
  for(const input of rejected) assert.equal(context.canonicalRoomUrl(input),null,`${file}: reject ${input}`);
}
async function access({url=search,id=12,permission=true,already=false}={}) {
  let injected=false;const calls=[];
  const chrome={tabs:{query:async()=>[{id,url}],sendMessage:async()=>({ok:already||injected})},scripting:{executeScript:async options=>{
    calls.push(options);if(!permission)throw Error('permission denied');injected=true;
  }}};
  const context=vm.createContext({URL,chrome});
  vm.runInContext(code('popup.js','canonicalRoomUrl')+'\n'+code('popup.js','ensureCurrentTabContentScript'),context);
  return {ok:await context.ensureCurrentTabContentScript(live,12),calls};
}
(async()=>{
  let result=await access();assert.equal(result.ok,true);assert.equal(result.calls.length,1);
  assert.equal(result.calls[0].target.tabId,12);
  assert.deepEqual(Array.from(result.calls[0].files),['douyin-commerce-dom.js','product-identity.js','live-products.js','page-materials.js','product-review-collector.js','review-page.js','content.js']);
  result=await access({url:directSearch});assert.equal(result.ok,true);assert.equal(result.calls.length,1);
  assert.equal(result.calls[0].target.tabId,12);
  assert.equal((await access({url:directSearch,permission:false})).ok,false);
  assert.equal((await access({permission:false})).ok,false);
  assert.equal((await access({already:true})).calls.length,0);
  for(const options of [{url:'https://example.test'},{url:search.replace('123456','999999')},{id:99}]) {
    result=await access(options);assert.equal(result.ok,false);assert.equal(result.calls.length,0);
  }
  const manifest=JSON.parse(fs.readFileSync(path.join(ext,'manifest.json'),'utf8'));
  assert.equal(manifest.host_permissions.some(p=>p.includes('www.douyin.com')),false);
  assert.deepEqual(manifest.optional_host_permissions,['https://www.douyin.com/*','https://douyin.com/*']);
  assert.ok(manifest.permissions.includes('activeTab'));
  console.log('room context: three actual parsers, explicit search live id, URL rejection, scoped injection and denied access passed');
})().catch(error=>{console.error(error);process.exitCode=1});
