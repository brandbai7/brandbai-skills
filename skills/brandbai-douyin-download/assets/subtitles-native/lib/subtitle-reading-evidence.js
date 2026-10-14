/* Same-frame reading provenance and crop completeness. Never rewrites OCR. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.BrandbaiSubtitleReadingEvidence=api;})(globalThis,function(){
  'use strict';
  const SCHEMA='subtitle-crop-assessment-v1';
  const finite=value=>typeof value==='number'&&Number.isFinite(value);
  const dense=value=>Array.isArray(value)&&Array.from({length:value.length},(_,i)=>i in value).every(Boolean);
  function alignment(reading,width,height){
    const a=reading?.tokenAlignment,chars=Array.from(reading?.text||'');
    if(!a||a.schema!=='ctc-temporal-bands-v1'||a.sourceWidth!==width||a.sourceHeight!==height
      ||!['sourceWidth','sourceHeight','modelWidth','contentWidth','steps'].every(k=>Number.isSafeInteger(a[k])&&a[k]>0)
      ||a.contentWidth>a.modelWidth||!chars.length||chars.length>1000||!dense(a.bands)||a.bands.length!==chars.length)return null;
    const scale=a.modelWidth/a.steps/a.contentWidth*a.sourceWidth;let last=-1;
    for(let i=0;i<a.bands.length;i++){
      const b=a.bands[i];
      if(!b||b.text!==chars[i]||!finite(b.confidence)||b.confidence<0||b.confidence>100
        ||!['firstStep','lastStep','peakStep'].every(k=>Number.isSafeInteger(b[k]))
        ||b.firstStep<=last||b.firstStep<0||b.firstStep>b.peakStep||b.peakStep>b.lastStep||b.lastStep>=a.steps
        ||(b.lastStep+1)*a.modelWidth>a.contentWidth*a.steps
        ||!['left','right','peak'].every(k=>finite(b[k]))
        ||Math.abs(b.left-b.firstStep*scale)>1e-5||Math.abs(b.right-(b.lastStep+1)*scale)>1e-5
        ||Math.abs(b.peak-(b.peakStep+.5)*scale)>1e-5)return null;
      last=b.lastStep;
    }
    return a;
  }
  function assessCrop(full,crop,evidence){
    const answer=(status,reason,extra={})=>({schema:SCHEMA,status,reason,usableForConsolidation:status==='complete',...extra});
    const c=crop?.cropEvidence,b=c?.box,v=evidence;
    if(!v||!c||c.schema!=='outlined-caption-spatial-crop-v1'||!b||c.inputWidth!==v.inputWidth||c.inputHeight!==v.inputHeight
      ||!['left','right','top','bottom'].every(k=>Number.isSafeInteger(b[k])&&b[k]===v.box?.[k])
      ||b.left<0||b.right>c.inputWidth||b.right<=b.left||b.top!==0||b.bottom!==c.inputHeight||v.spatialCropApplied)
      return answer('unverified','missing_or_mismatched_same_frame_geometry');
    const fa=alignment(full,c.inputWidth,c.inputHeight),ca=alignment(crop,b.right-b.left,c.inputHeight);
    if(!fa||!ca)return answer('unverified','missing_or_invalid_source_alignment');
    // An estimated CTC band is not a character box. It can veto clipping; it
    // cannot alone authorize deletion of an outside weak/protected character.
    const outside=fa.bands.filter(x=>/\S/u.test(x.text)&&(x.left<b.left||x.right>b.right));
    if(outside.length)return answer('incomplete','full_reading_extends_outside_crop',{outsideCharacters:outside.map(x=>x.text).join('')});
    const left=String(full.text).trim(),right=String(crop.text).trim();
    if(!left||!right)return answer('unverified','empty_reading');
    if(left!==right)return answer('unverified','readings_disagree');
    // Equal text alone is insufficient: bind corresponding estimated bands in
    // their actual source coordinates. This does not count as independent votes.
    const fg=fa.bands.filter(x=>/\S/u.test(x.text)),cg=ca.bands.filter(x=>/\S/u.test(x.text));
    if(fg.length!==cg.length||fg.some((x,i)=>x.text!==cg[i].text
      ||Math.abs(x.peak-(cg[i].peak+b.left))>Math.max(2,c.inputHeight*.25)))return answer('unverified','core_position_disagreement');
    return answer('complete','same_complete_reading_with_source_coordinates');
  }
  function copyAssessment(value){
    if(value?.schema!==SCHEMA||!['complete','incomplete','unverified'].includes(value.status)
      ||typeof value.reason!=='string'||!/^[a-z_]{1,80}$/.test(value.reason))return undefined;
    return {schema:SCHEMA,status:value.status,reason:value.reason,usableForConsolidation:value.status==='complete',
      ...(typeof value.outsideCharacters==='string'&&value.outsideCharacters.length<=1000?{outsideCharacters:value.outsideCharacters}: {})};
  }
  return {SCHEMA,alignment,assessCrop,copyAssessment};
});
