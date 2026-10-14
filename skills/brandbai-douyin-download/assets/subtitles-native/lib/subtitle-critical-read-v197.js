/* Pure, source-bound critical-reading arbitration. No OCR, dictionary hints,
 * confidence-as-accuracy, pixel templates, token splicing or cross-event merge. */
(function(root,factory){const value=factory(root);if(typeof module==='object'&&module.exports)module.exports=value;root.BrandbaiCriticalReadV197=value;})(globalThis,function(root){
  'use strict';
  const POLICY=Object.freeze({schema:'source-bound-critical-read-v197',maximumSupplementalReads:2,modelId:'PP-OCRv6_medium_rec',
    modelSha256:'9c09abf0957f7968c7586464b7397b84ad2387a0497a351af40e9acc71b673ba',semanticCorrectnessVerified:false});
  const TRANSFORMS=Object.freeze([Object.freeze({id:'rgb-linear-contrast-125-center-128-v1',algorithm:'round_clamp_rgb_linear',gain:1.25,center:128,alpha:'unchanged',resize:false}),
    Object.freeze({id:'rgb-linear-contrast-175-center-128-v1',algorithm:'round_clamp_rgb_linear',gain:1.75,center:128,alpha:'unchanged',resize:false})]);
  const ORIGINAL_MODELS=Object.freeze([Object.freeze({modelId:'PP-OCRv5_mobile_rec',modelSha256:'5825fc7ebf84ae7a412be049820b4d86d77620f204a041697b0494669b1742c5'}),
    Object.freeze({modelId:POLICY.modelId,modelSha256:POLICY.modelSha256})]);
  const HASH=/^[a-f0-9]{64}$/,NAME=/我叫|名叫|姓名|作者|嘉宾|达人|名为|叫做|先生|女士|老师|演员|明星|艺人|歌手|导演|医生/u,
    UNITS='[A-Za-z]+|千克|公斤|毫克|毫升|分钟|小时|厘米|毫米|摄氏度|百分之|克|斤|升|秒|杯|次|片|粒|瓶|袋|箱|罐|打|套|层|勺|天|周|月|年|度',
    clone=x=>JSON.parse(JSON.stringify(x)),same=(a,b)=>JSON.stringify(a)===JSON.stringify(b),finite=Number.isFinite;
  function validSource(s){let identity;try{identity=JSON.parse(s?.sourceIdentityKey);}catch{return false;}const b=s?.sourceRect;
    // This validates inert OCR evidence, never grants a live player capability.
    // A web task is bound by its complete work/intent/generation identity, its
    // exact task frame ID, parent pixels and native crop, just like a file.
    const local=identity?.kind==='local_file_sha256'&&HASH.test(identity.sha256)
      &&s.frameId==='file:'+identity.sha256+':frame:'+s.frameIndex;
    const locked=identity?.kind==='locked_visible_video'&&typeof identity.workId==='string'&&/^\d{5,30}$/.test(identity.workId)
      &&typeof identity.intentId==='string'&&identity.intentId.length>0&&identity.intentId.length<=200
      &&Number.isSafeInteger(identity.bindingGeneration)&&identity.bindingGeneration>=0
      &&(identity.sourceDocumentToken===undefined||typeof identity.sourceDocumentToken==='string'&&identity.sourceDocumentToken.length>0&&identity.sourceDocumentToken.length<=200)
      &&s.frameId==='task:'+identity.intentId+':frame:'+s.frameIndex;
    return s?.schema==='native-critical-crop-source-v197'&&(local||locked)
    &&Number.isSafeInteger(s.rowIndex)&&s.rowIndex>=0&&Number.isSafeInteger(s.frameIndex)&&s.frameIndex>=0&&typeof s.frameId==='string'&&s.frameId.length>0&&finite(s.time)&&s.time>=0&&s.time<=180
    &&HASH.test(s.parentPixelsSha256)&&HASH.test(s.nativeCropPixelsSha256)&&Number.isSafeInteger(s.sourceWidth)&&Number.isSafeInteger(s.sourceHeight)&&b&&['left','top','right','bottom'].every(k=>Number.isSafeInteger(b[k]))
    &&b.left>=0&&b.top>=0&&b.right<=s.sourceWidth&&b.bottom<=s.sourceHeight&&b.right>b.left&&b.bottom>b.top&&s.inputWidth===b.right-b.left&&s.inputHeight===b.bottom-b.top&&s.inputWidth<=2560&&s.inputHeight<=256;}
  function sourceKey(s){return JSON.stringify(['sourceIdentityKey','rowIndex','frameIndex','frameId','time','parentPixelsSha256','nativeCropPixelsSha256','sourceWidth','sourceHeight','sourceRect','inputWidth','inputHeight'].map(k=>s?.[k]));}
  function bindingReason(record,source,supplemental=false){const p=record?.receipt,r=record?.reading;if(!validSource(source)||!p||typeof record.id!=='string'||!record.id||p.readVariantId!==record.id)return 'source_or_variant_receipt_missing';
    if(sourceKey(p)!==sourceKey(source))return 'different_native_source_row_frame_or_crop';
    if(!r||typeof r.text!=='string'||!r.text.trim()||Array.from(r.text).length>300||!finite(r.confidence)||r.confidence<0||r.confidence>100||!same(p.originatingReading,r))return 'actual_originating_reading_mismatch';
    if(!HASH.test(p.recognitionInputCropPixelsSha256)||!HASH.test(p.modelSha256)||typeof p.modelId!=='string'||!p.modelId)return 'model_or_actual_input_hash_missing';
    if(supplemental){const t=TRANSFORMS.find(t=>t.id===p.transformId);if(p.modelId!==POLICY.modelId||p.modelSha256!==POLICY.modelSha256)return 'supplemental_model_not_the_same_pinned_v6';
      if(!t||!same(p.transform,t)||p.nativePixelsSha256!==source.nativeCropPixelsSha256||p.transformedPixelsSha256!==p.recognitionInputCropPixelsSha256)return 'fixed_transform_or_pixel_binding_invalid';}
    else{if(!ORIGINAL_MODELS.some(m=>m.modelId===p.modelId&&m.modelSha256===p.modelSha256))return 'original_model_not_one_of_the_two_existing_pinned_models';
      if(p.transformId!=='original_native_rgba'||p.recognitionInputCropPixelsSha256!==source.nativeCropPixelsSha256)return 'original_read_is_not_this_native_crop';}
    return null;}
  function criticalTokens(text,normalize=x=>x,stickyIdentity=false){const value=normalize(text),tokens=[];
    const add=(regex,kind)=>{for(const m of value.matchAll(regex))tokens.push({kind,text:m[0],start:Array.from(value.slice(0,m.index)).length,end:Array.from(value.slice(0,m.index+m[0].length)).length});};
    add(/[+\-−－]?\s*(?:\p{Nd}+(?:[.．]\p{Nd}*)?|[.．]\p{Nd}+)(?:\s*[%％])?/gu,'number');add(/[负正]?[零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟萬億点]+/gu,'chinese_number');
    add(new RegExp(UNITS,'gu'),'unit_or_latin');add(/不(?:能|是|会|要|再|用|需|得|可)?|没(?:有)?|无(?:需|法)?|未(?:必|能)?|非|勿|别|莫/gu,'negation');add(/[我你您他她它谁咱俺]/gu,'identity_pronoun');
    if(stickyIdentity||NAME.test(value))tokens.push({kind:'named_identity',text:value,start:0,end:Array.from(value).length});return tokens.sort((a,b)=>a.start-b.start||a.end-b.end||a.kind.localeCompare(b.kind));}
  function characterScore(record,index){const chars=Array.from(record.reading.text),c=record.reading.charConfidences?.[index];return c?.text===chars[index]&&finite(c.confidence)&&c.confidence>=0&&c.confidence<=100?c.confidence:null;}
  function analyzeConflict(input){const normalize=typeof input?.normalize==='function'?input.normalize:x=>x,records=Array.isArray(input?.readings)?input.readings:[],supplemental=Array.isArray(input?.supplementalReadings)?input.supplementalReadings:[],source=input?.source,
    current=records.find(r=>r.id===input?.currentReadingId),rejected=[],accepted=[],ids=new Set(),transforms=new Set();
    const originals=clone(records),attempts=clone(supplemental);for(const [list,isSupplemental]of[[records,false],[supplemental,true]])for(const record of list){let reason=bindingReason(record,source,isSupplemental);
      if(ids.has(record?.id))reason='duplicate_read_variant_id';ids.add(record?.id);if(isSupplemental){if(transforms.has(record?.receipt?.transformId))reason='duplicate_fixed_transform_attempt';transforms.add(record?.receipt?.transformId);if(supplemental.length>POLICY.maximumSupplementalReads)reason='supplemental_read_budget_exceeded';}
      if(reason)rejected.push({id:record?.id||null,reason,record:clone(record)});else accepted.push({record,isSupplemental});}
    const sourceValid=validSource(source),currentValid=!!current&&!bindingReason(current,source,false),stickyIdentity=accepted.some(v=>NAME.test(normalize(v.record?.reading?.text||''))),
      signatures=accepted.map(({record})=>JSON.stringify(criticalTokens(record.reading.text,normalize,stickyIdentity).map(t=>({kind:t.kind,text:t.text})))),conflict=new Set(signatures).size>1,
      scored=accepted.map(({record,isSupplemental})=>{const normalized=normalize(record.reading.text),tokens=criticalTokens(record.reading.text,normalize,stickyIdentity),positionMapAvailable=Array.from(normalized).length===Array.from(record.reading.text).length,
        positions=[...new Set(tokens.flatMap(t=>Array.from({length:t.end-t.start},(_,i)=>t.start+i)))].sort((a,b)=>a-b),scores=positions.map(index=>({index,text:Array.from(normalized)[index],confidence:positionMapAvailable?characterScore(record,index):null}));
        return {id:record.id,isSupplemental,text:record.reading.text,normalizedText:normalized,criticalTokens:tokens,criticalPositions:scores,positionMapAvailable,
          minimumCriticalCharacterConfidence:scores.length&&scores.every(s=>s.confidence!==null)?Math.min(...scores.map(s=>s.confidence)):null,
          fullReadingKey:normalized,correlatedWithSameNativeCrop:true,sourceIdentityKey:source?.sourceIdentityKey};});
    const groups=new Map();for(const record of scored){if(!groups.has(record.fullReadingKey))groups.set(record.fullReadingKey,[]);groups.get(record.fullReadingKey).push(record);}
    return {...POLICY,source:sourceValid?clone(source):null,currentReadingId:input?.currentReadingId||null,currentReading:current?clone(current.reading):null,sourceValid,currentValid,
      status:!sourceValid||!currentValid?'invalid_source_bound_readings':conflict?'unresolved_critical_conflict':'critical_readings_agree',hasCriticalConflict:conflict,
      originalReadings:originals,supplementalReadings:attempts,rejectedReadings:rejected,acceptedReadings:scored,stickyNamedIdentityScope:stickyIdentity,
      advisoryAgreementGroups:[...groups].map(([text,values])=>({text,readingIds:values.map(v=>v.id),supplementalCount:values.filter(v=>v.isSupplemental).length,
        criticalMinimums:values.map(v=>v.minimumCriticalCharacterConfidence),isIndependentTruth:false,isSelectionAuthority:false})),
      resolved:false,requiresReview:!sourceValid||!currentValid||conflict,protectedMergeAllowed:false,
      limitation:'Same-model contrast reads are correlated candidates; complete source shape correspondence is not a semantic glyph-label certificate.'};}
  function selectCriticalReading(input){const a=analyzeConflict(input),candidates=[...new Set(a.acceptedReadings.map(r=>r.text))],notice=a.requiresReview?'[关键字符读数未解决，以下均为实际机器候选]\n'+candidates.map((text,i)=>'候选'+(i+1)+'：'+text).join('\n'):a.currentReading?.text||'';
    return {...a,decision:!a.currentValid?'invalid_binding_keep_original_candidate':a.hasCriticalConflict?'retain_current_with_explicit_critical_candidates':'normal_reading_unchanged',
    selectedReadingId:a.currentValid?a.currentReadingId:null,selectedReading:a.currentValid?a.currentReading:null,criticalConflictResolved:false,
    workingDisplayText:notice,workingDisplayIsUnresolvedCandidateNotice:a.requiresReview,distinctActualCandidateTexts:candidates,
    // No self-reported verified flag, old resume conclusion or confidence total
    // can bypass fresh source binding or authorize changing a critical label.
    externallyClaimedResolutionAccepted:false,semanticCorrectnessVerified:false};}
  function applyFixedTransform(image,transformId){const t=TRANSFORMS.find(t=>t.id===transformId);if(!t||!Number.isSafeInteger(image?.width)||!Number.isSafeInteger(image?.height)||image.data?.length!==image.width*image.height*4)throw Error('Invalid fixed contrast source');
    const data=new Uint8ClampedArray(image.data.length);for(let i=0;i<data.length;i+=4){for(let c=0;c<3;c++)data[i+c]=Math.max(0,Math.min(255,Math.round((image.data[i+c]-t.center)*t.gain+t.center)));data[i+3]=image.data[i+3];}
    return {width:image.width,height:image.height,data,transform:clone(t)};}
  function nativeComponents(image,minimum,polarity='bright'){const w=image.width,h=image.height,n=w*h,bits=new Uint8Array(n),seen=new Uint8Array(n),out=[];
    for(let i=0;i<n;i++){const x=image.data.subarray(i*4,i*4+3);bits[i]=(polarity==='dark'?Math.max(...x)<=minimum:Math.min(...x)>=minimum)&&Math.max(...x)-Math.min(...x)<=55?1:0;}
    for(let seed=0;seed<n;seed++){if(!bits[seed]||seen[seed])continue;const queue=[seed];seen[seed]=1;let left=w,right=0,top=h,bottom=0;for(let q=0;q<queue.length;q++){const i=queue[q],x=i%w,y=Math.floor(i/w);left=Math.min(left,x);right=Math.max(right,x+1);top=Math.min(top,y);bottom=Math.max(bottom,y+1);
        for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++){const xx=x+dx,yy=y+dy,j=yy*w+xx;if(xx>=0&&xx<w&&yy>=0&&yy<h&&bits[j]&&!seen[j]){seen[j]=1;queue.push(j);}}}
      let boundary=0,dark=0;for(const i of queue){const x=i%w,y=Math.floor(i/w);if([[x-1,y],[x+1,y],[x,y-1],[x,y+1]].every(([xx,yy])=>xx>=0&&xx<w&&yy>=0&&yy<h&&bits[yy*w+xx]))continue;boundary++;
        if([1,2,3].some(d=>[[x-d,y],[x+d,y],[x,y-d],[x,y+d]].some(([xx,yy])=>xx>=0&&xx<w&&yy>=0&&yy<h&&Math.max(...image.data.subarray((yy*w+xx)*4,(yy*w+xx)*4+3))<125)))dark++;}
      const mask=new Uint8Array((right-left)*(bottom-top));for(const i of queue)mask[(Math.floor(i/w)-top)*(right-left)+i%w-left]=1;
      out.push({id:'native-'+polarity+'-'+minimum+'-'+out.length,left,right,top,bottom,count:queue.length,sourceMask:Array.from(mask).join(''),outlineFraction:boundary?dark/boundary:0,touchesCropEdge:left===0||right===w||top===0||bottom===h});}
    return out;}
  async function diagnoseNativeHorizontalBars({image,source,readings,index}){if(!validSource(source)||image?.width!==source.inputWidth||image?.height!==source.inputHeight||image.data?.length!==image.width*image.height*4)throw Error('Invalid original native bar source');
    const digest=[...new Uint8Array(await root.crypto.subtle.digest('SHA-256',image.data))].map(n=>n.toString(16).padStart(2,'0')).join('');if(digest!==source.nativeCropPixelsSha256)throw Error('Native bar pixels do not match the original crop hash');
    const windows=[];for(const record of readings){if(bindingReason(record,source,false))continue;const a=record.reading.tokenAlignment,b=a?.bands;if(a?.schema!=='ctc-temporal-bands-v1'||a.sourceWidth!==image.width||a.sourceHeight!==image.height||!Array.isArray(b)||!b[index]||b.some((v,i)=>!finite(v.peak)||i&&v.peak<=b[i-1].peak))continue;
      const peak=b[index].peak,previous=b[index-1]?.peak,next=b[index+1]?.peak,pitches=[previous===undefined?null:peak-previous,next===undefined?null:next-peak].filter(x=>finite(x)&&x>0),pitch=pitches.reduce((a,b)=>a+b,0)/pitches.length;
      if(!finite(pitch))continue;windows.push({readingId:record.id,left:Math.max(0,Math.floor(previous===undefined?peak-pitch/2:(previous+peak)/2)),right:Math.min(image.width,Math.ceil(next===undefined?peak+pitch/2:(peak+next)/2)),pitch,peak});}
    if(!windows.length)return {status:'actual_native_anchor_unavailable',semanticCorrectnessVerified:false,overrideAuthorized:false};
    const cell={left:Math.max(...windows.map(w=>w.left)),right:Math.min(...windows.map(w=>w.right)),top:0,bottom:image.height},pitch=Math.min(...windows.map(w=>w.pitch)),white=nativeComponents(image,205),aa=nativeComponents(image,150),intersects=c=>c.left<cell.right&&c.right>cell.left,
      core=white.filter(intersects),contained=core.filter(c=>c.left>=cell.left&&c.right<=cell.right&&!c.touchesCropEdge),bars=contained.filter(c=>(c.right-c.left)>=pitch*.5&&(c.bottom-c.top)<=pitch*.25&&(c.right-c.left)/(c.bottom-c.top)>=3&&c.outlineFraction>=.65),
      others=core.filter(c=>!bars.includes(c)),possibleAdditionalInk=aa.filter(intersects).filter(c=>!bars.some(b=>c.left<=b.left&&c.right>=b.right&&c.top<=b.top&&c.bottom>=b.bottom)),darkComponents=nativeComponents(image,125,'dark'),darkInCell=darkComponents.filter(intersects),
      darkBars=darkInCell.filter(c=>c.left>=cell.left&&c.right<=cell.right&&!c.touchesCropEdge&&(c.right-c.left)>=pitch*.5&&(c.bottom-c.top)<=pitch*.25&&(c.right-c.left)/(c.bottom-c.top)>=3),darkOther=darkInCell.filter(c=>!darkBars.includes(c));
    return {schema:'native-horizontal-bar-geometry-diagnostic-v197',source:clone(source),nativePixelsSha256:digest,index,cell,anchorWindows:windows,pitch,
      unfilteredWhiteComponentCount:white.length,unfilteredPossibleAntiAliasComponentCount:aa.length,horizontalLongBarCount:bars.length,bars,otherWhiteComponents:others,possibleAdditionalInk,
      darkPolarityDiagnostic:{thresholdMaximumChannel:125,unfilteredComponentCount:darkComponents.length,horizontalLongBarCount:darkBars.length,bars:darkBars,otherComponents:darkOther,semanticCorrectnessVerified:false,overrideAuthorized:false},
      status:bars.length&&others.length===0&&possibleAdditionalInk.length===0?'isolated_horizontal_bar_geometry_observed':'horizontal_bar_geometry_with_unresolved_context',
      limitation:'Machine pixel geometry, not OCR truth. CTC only locates an uncertain cell; whole components crossing it or extra possible ink remain explicit. No stroke erosion, resizing, token substitution or glyph-label certificate.',
      semanticCorrectnessVerified:false,overrideAuthorized:false};}
  return {POLICY,TRANSFORMS,ORIGINAL_MODELS,validSource,sourceKey,bindingReason,criticalTokens,analyzeConflict,selectCriticalReading,applyFixedTransform,nativeComponents,diagnoseNativeHorizontalBars};
});
