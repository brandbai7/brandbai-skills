/* Comparison evidence only. Never returns rewritten OCR or moves/resizes pixels. */
(function(root,factory){const api=factory(()=>root.BrandbaiSubtitleVisualEvents || (typeof require==='function'?require('./subtitle-visual-events.js'):null));
  if(typeof module==='object'&&module.exports)module.exports=api;root.BrandbaiSubtitleCaptionLine=api;
})(globalThis,function(visualApi){
  'use strict';
  const HORIZONTAL=/^[\t \u00a0\u3000]$/u, EDGE=/^[·•・,，.．。:：]$/u, HAN=/^\p{Script=Han}$/u;
  function comparableReading(reading){
    const text=typeof reading==='string'?reading:reading?.text;
    if(typeof text!=='string'||!text||text.length>300||/[\r\n]/u.test(text))return null;
    const chars=Array.from(text);let left=0,right=chars.length;
    while(left<right&&HORIZONTAL.test(chars[left]))left++;
    while(right>left&&HORIZONTAL.test(chars[right-1]))right--;
    // Only punctuation adjoining a Han sentence edge. Never erase decimal,
    // sign, percentage, question/exclamation, quote, internal punctuation.
    let first=left,last=right;
    while(first<last&&EDGE.test(chars[first]))first++;
    while(last>first&&EDGE.test(chars[last-1]))last--;
    if(first<last&&HAN.test(chars[first]))left=first;
    if(last>left&&HAN.test(chars[last-1]))right=last;
    const positions=[];
    for(let i=left;i<right;i++){
      if(HORIZONTAL.test(chars[i])){
        let j=i;while(j<right&&HORIZONTAL.test(chars[j]))j++;
        if(i>left&&j<right&&HAN.test(chars[i-1])&&HAN.test(chars[j])){i=j-1;continue;}
      }
      positions.push(i);
    }
    const kept=positions.map(i=>chars[i]);
    return kept.length?{key:kept.join(''),chars:kept,positions,omitted:chars.map((_,i)=>i).filter(i=>!positions.includes(i))}:null;
  }
  const comparisonKey=text=>comparableReading(text)?.key || '';
  function bit(e,i){return e.maskEncoding==='hex4'?(parseInt(e.mask[Math.floor(i/4)],16)>>(3-i%4))&1:Number(e.mask[i]);}
  function common(a,b){
    const v=visualApi();
    return v?.valid(a)&&v.valid(b)&&!a.spatialCropApplied&&!b.spatialCropApplied
      &&['inputWidth','inputHeight','maskWidth','maskHeight'].every(k=>a[k]===b[k])
      &&['left','right','top','bottom'].every(k=>Math.abs(a.ink[k]-b.ink[k])<=2);
  }
  function difference(a,b,left,right){
    let union=0,diff=0;
    for(let y=Math.min(a.ink.top,b.ink.top);y<Math.max(a.ink.bottom,b.ink.bottom);y++)for(let x=left;x<right;x++){
      const aa=bit(a,y*a.maskWidth+x),bb=bit(b,y*b.maskWidth+x);if(aa||bb)union++;if(aa!==bb)diff++;
    }
    return {union,diff};
  }
  function sameLine(a,b){
    if(!common(a,b))return false;
    const d=difference(a,b,Math.min(a.ink.left,b.ink.left),Math.max(a.ink.right,b.ink.right));
    return d.union>=100&&d.diff/d.union<=.085;
  }
  function sameGlyph(a,b,position,length){
    if(!sameLine(a,b)||!Number.isInteger(position)||!Number.isInteger(length)||length<1||position<0||position>=length)return false;
    const left=Math.max(a.ink.left,b.ink.left),right=Math.min(a.ink.right,b.ink.right);
    const d=difference(a,b,Math.floor(left+(right-left)*position/length),Math.ceil(left+(right-left)*(position+1)/length));
    return d.union>=20&&d.diff/d.union<=.02;
  }
  function sameBand(a,b,bandA,bandB){
    if(!sameLine(a,b))return false;
    for(const band of [bandA,bandB])if(!band||!['left','right','peak'].every(k=>Number.isFinite(band[k]))
      ||band.left<0||band.right>a.inputWidth||band.left>=band.right||band.peak<band.left||band.peak>band.right)return false;
    // CTC spans are estimates, not character boxes. They supply an additional
    // veto: checking a different equal-width cell cannot authorize changed
    // pixels in the actual estimated band. No shifts, resizing or mask hashes.
    if(Math.max(bandA.left,bandB.left)>=Math.min(bandA.right,bandB.right))return false;
    const l=Math.floor(Math.min(bandA.left,bandB.left)/a.inputWidth*a.maskWidth);
    const r=Math.ceil(Math.max(bandA.right,bandB.right)/a.inputWidth*a.maskWidth);
    const d=difference(a,b,l,r);
    return d.union>=10&&d.diff/d.union<=.02;
  }
  return {comparisonKey,comparableReading,sameLine,sameGlyph,sameBand};
});
