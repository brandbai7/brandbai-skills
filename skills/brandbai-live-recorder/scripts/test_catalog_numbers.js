const assert=require('node:assert/strict');
const {numberHints}=require('../assets/chrome-extension/page-materials.js');
const rows=Array.from({length:16},(_,i)=>({list_position:i?i+1:null,explaining:i?null:true}));
assert.equal(numberHints(rows,true)[0].candidate,1);
assert.equal(rows[0].list_position,null);
assert.deepEqual(numberHints(rows,false),{});
for(const change of [r=>r[1].list_position=1,r=>r[5].list_position=null,r=>r[1].explaining=true,r=>r[0].explaining=null,r=>r.reverse()]){
  const r=structuredClone(rows);change(r);assert.deepEqual(numberHints(r,true),{});
}
console.log('Catalog inference boundaries passed');
