'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../assets/chrome-extension/help-panel.js'), 'utf8');
function harness(writeText) {
  const nodes = new Map(['contact-status','copy-official-account','copy-support-email'].map(id=>[id,{hidden:true,textContent:'',addEventListener(type,fn){this[type]=fn;}}]));
  vm.runInNewContext(source,{document:{getElementById:id=>nodes.get(id)},navigator:{clipboard:{writeText}}});
  return nodes;
}
(async()=>{
  const calls=[];
  const nodes=harness(async text=>calls.push(text));
  assert.equal(calls.length,0);
  await nodes.get('copy-official-account').click();
  assert.deepEqual(calls,['布兰德老白BrandBai']);
  assert.equal(nodes.get('contact-status').textContent,'公众号已复制');
  await nodes.get('copy-support-email').click();
  assert.equal(calls.at(-1),'brandlaobai@163.com');
  assert.equal(nodes.get('contact-status').hidden,false);
  const denied=harness(async()=>{throw Error('denied')});
  await denied.get('copy-support-email').click();
  assert.equal(denied.get('contact-status').textContent,'未能自动复制，请手动复制：brandlaobai@163.com');
  let finish;
  const raced=harness(text=>text==='布兰德老白BrandBai'?new Promise(resolve=>finish=resolve):Promise.resolve());
  const pending=raced.get('copy-official-account').click();
  await raced.get('copy-support-email').click();finish();await pending;
  assert.equal(raced.get('contact-status').textContent,'邮箱已复制');
  console.log('Help contacts: explicit click, exact text, denial fallback and late result isolation passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
