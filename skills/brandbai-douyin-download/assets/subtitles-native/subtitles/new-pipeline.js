/* Shared, local-only detected-line pipeline. Raw recognition is never rewritten.
 * Native frames -> detector(1280) -> original-colour mobile rows -> frozen V7
 * role proposals -> one actual native representative crop precision read/event.
 * Row IDs and frame IDs have different namespaces. Do not run legacy finalizer.
 */
(function(root,factory){const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;root.BrandbaiHighQualitySubtitles=api;})(globalThis,function(root){
  'use strict';
  const PIPELINE='detected-lines-precision-v193', FULL=Object.freeze({left:0,top:0,right:1,bottom:1});
  // Input/output tensors are disposed after each call. Reuse the lazy V6
  // session across representative and expanded reads, with a hard call cap.
  const LIMITS=Object.freeze({frames:361,rowsPerFrame:128,totalRows:12000,cropBytes:96*1024*1024,precisionBatch:512,precisionRecoveries:1});
  const PIXELS_CACHE_LIMIT=16*1024*1024;
  const RECOVERABLE_PRECISION_ERRORS=new Set(['精读模型加载失败','精读识别执行失败','本地识别模块加载失败','本地识别器准备超时','识别器设置超时','字幕原图校准超时','精读暂时超时，已保存已读内容，可继续','扩展字幕精读暂时超时，原始文字已保留，可继续']);
  const PRECISION_MODEL=Object.freeze({modelId:'PP-OCRv6_medium_rec',modelSha256:'9c09abf0957f7968c7586464b7397b84ad2387a0497a351af40e9acc71b673ba'});
  const EXPANSION=Object.freeze({schema:'caption-lane-native-expanded-read-v195',heightPadding:1.5,maximumHeightPadding:2,minimumCharConfidence:95,glyphWidth:16,glyphHeight:24});
  const OWNED_GLYPHS=Object.freeze({schema:'actual-native-owned-glyphs-v196',receiptSchema:'native-owned-glyph-receipt-v196',width:32,height:48,registrationPixels:1,boundaryPixels:1,maximumDimensionDrift:2,minimumOutlineFraction:.65,minimumStrokeResolution:24});
  const READ_SELECTION=Object.freeze({schema:'actual-native-read-selection-v196-r1',policy:'native-base-completeness-endpoint-v196-r1'});
  // Conservative union of legacy protected units and the frozen evaluator's
  // unit inventory; shared by the raw barrier and positional glyph audit.
  const PROTECTED_UNIT_PATTERN='[A-Za-z]+|千克|公斤|毫克|毫升|分钟|小时|厘米|毫米|摄氏度|百分之|克|斤|升|秒|杯|次|片|粒|瓶|袋|箱|罐|打|套|层|勺|天|周|月|年|度';
  const NAMED_IDENTITY_PATTERN=/我叫|名叫|姓名|作者|嘉宾|达人|名为|叫做|先生|女士|老师|演员|明星|艺人|歌手|导演|医生/u;
  const protectedUnits=value=>[...value.matchAll(new RegExp(PROTECTED_UNIT_PATTERN,'gu'))];
  const shaPattern=/^[a-f0-9]{64}$/, clone=x=>JSON.parse(JSON.stringify(x));
  const api=()=>root.BrandbaiSubtitles, roleApi=()=>root.BrandbaiCaptionRoleV7;
  function simplified(){const value=root.BrandbaiSubtitleSimplified;if(!value||typeof value.assertReady!=='function'||typeof value.text!=='function'||typeof value.normalize!=='function')throw Error('简体整理组件未就绪，请重新加载插件后重试。');value.assertReady();return value;}
  const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b), finite=Number.isFinite;
  const roleStyleApi=()=>root.BrandbaiSubtitleRoleStyleV197, cueApi=()=>root.BrandbaiSubtitleCueMergeV197, gapApi=()=>root.BrandbaiSubtitleRegionRecoveryV197;
  const workingGroupApi=()=>root.BrandbaiSubtitleWorkingGroupsV198;
  function applyWorkingPresentation(result,options={}){
    if(!workingGroupApi()?.groupWorkingSegments)return result;
    const grouped=workingGroupApi().groupWorkingSegments(result.segments,result.raw.rows,{nativeApi:root.BrandbaiHighQualitySubtitles,frames:result.raw.frames,retainedGroups:options.retainedGroups||[]});
    result.segments=grouped.segments;
    result.workingPresentation={schema:grouped.schema,policy:grouped.policy,presentationOnly:true,semanticCorrectnessVerified:false,groups:grouped.groups,decisions:grouped.decisions,groupedObservations:grouped.presentationGroups.reduce((n,g)=>n+g.memberCount-1,0),newOcrCalls:0};
    if(root.BrandbaiSubtitleWorkingCandidatesV198?.groupWorkingCandidates){
      const candidates=root.BrandbaiSubtitleWorkingCandidatesV198.groupWorkingCandidates(result.segments,result.raw.rows,{nativeApi:root.BrandbaiHighQualitySubtitles,frames:result.raw.frames,retainedGroups:options.retainedGroups||[]});
      result.segments=candidates.segments;
      result.workingPresentation.candidates={schema:candidates.schema,policy:candidates.policy,groups:candidates.presentationCandidateGroups,decisions:candidates.decisions,selectionAuthorityGranted:false};
    }
    if(root.BrandbaiSubtitleProgressiveWorkingV199?.groupProgressiveWorkingSegments){
      const progressive=root.BrandbaiSubtitleProgressiveWorkingV199.groupProgressiveWorkingSegments(result.segments,result.raw.rows,{nativeApi:root.BrandbaiHighQualitySubtitles,frames:result.raw.frames,retainedGroups:options.retainedGroups||[]});
      result.segments=progressive.segments;
      result.workingPresentation.progressive={schema:progressive.schema,policy:progressive.policy,groups:progressive.groups,decisions:progressive.decisions,presentationOnly:true,usesExistingActualFullReading:true,semanticCorrectnessVerified:false,newOcrCalls:0};
    }
    return result;
  }
  function actualReceipt(event,selection,rows,frames){const row=rows[event.selectedRowIndex],frame=frames[row?.frameIndex];if(!row||!frame)return null;
    if(selection.expanded)return {...clone(selection.expanded),kind:selection.kind,sourceIdentityKey:null};
    if(selection.kind!=='precision_native_representative'||!validRepresentative(event,rows))return null;
    return {...clone(event.precision),kind:selection.kind,inputWidth:row.inputWidth,inputHeight:row.inputHeight,sourceWidth:row.sourceWidth,sourceHeight:row.sourceHeight,
      sourceRect:clone(row.sourceRect),parentPixelsSha256:frame.sourcePixelSha256,originalCropPixelsSha256:row.cropPixelsSha256};}
  function actualRoleStyle(event,selection,rows,frames){const row=rows[selection.expanded?.rowIndex??event.selectedRowIndex],frame=frames[row?.frameIndex],box=selection.expanded?.sourceRect||row?.sourceRect,hash=selection.expanded?.cropPixelsSha256||row?.cropPixelsSha256;
    return (event.nativeRoleStyles||[]).find(p=>p.kind===selection.kind&&same(p.reading,selection.actual)&&same(p.style?.sourceRect,box)&&p.style?.receipt?.frameId===row.frameId&&p.style.receipt.time===row.time&&p.style.receipt.parentPixelsSha256===frame.sourcePixelSha256&&p.style.receipt.cropPixelsSha256===hash)?.style||null;}
  function criticalReadStatus(event,selection,rows,frames,sourceIdentity){const critical=root.BrandbaiCriticalReadV197,row=rows[event.selectedRowIndex],frame=frames[row?.frameIndex];if(!critical||!['precision_native_representative','precision_native_expanded'].includes(selection.kind)||!validRepresentative(event,rows))return null;
    const source={schema:'native-critical-crop-source-v197',sourceIdentityKey:JSON.stringify(sourceIdentity),rowIndex:row.index,frameIndex:row.frameIndex,frameId:row.frameId,time:row.time,parentPixelsSha256:frame.sourcePixelSha256,nativeCropPixelsSha256:row.cropPixelsSha256,sourceWidth:row.sourceWidth,sourceHeight:row.sourceHeight,sourceRect:clone(row.sourceRect),inputWidth:row.inputWidth,inputHeight:row.inputHeight};
    const record=(id,value,modelId,modelSha256)=>({id,reading:clone(value),receipt:{...clone(source),readVariantId:id,originatingReading:clone(value),recognitionInputCropPixelsSha256:row.cropPixelsSha256,transformId:'original_native_rgba',modelId,modelSha256}}),verdict=critical.selectCriticalReading({source,currentReadingId:'precision_native_representative',readings:[record('detected_line_original_color',reading(row),'PP-OCRv5_mobile_rec','5825fc7ebf84ae7a412be049820b4d86d77620f204a041697b0494669b1742c5'),record('precision_native_representative',event.precision.reading,PRECISION_MODEL.modelId,PRECISION_MODEL.modelSha256)],normalize:simplified().text});
    if(!verdict.currentValid)return {schema:critical.POLICY.schema,status:'invalid_actual_read_binding',hasCriticalConflict:false,evidenceIncomplete:true,protectedMergeAllowed:false,requiresReview:true,candidates:[],semanticCorrectnessVerified:false};
    const candidates=verdict.acceptedReadings.map(r=>({readingId:r.id,text:r.normalizedText,criticalPositions:r.criticalPositions}));let expandedConflict=false;
    const erow=rows[selection.expanded?.rowIndex],eframe=frames[selection.expanded?.frameIndex];
    if(selection.kind==='precision_native_expanded'&&selection.expanded&&event.rowIndices.includes(selection.expanded.rowIndex)&&erow&&eframe&&validExpanded(selection.expanded,erow,eframe,false,rows)){const value=simplified().text(selection.actual.text),tokens=critical.criticalTokens(value),key=v=>JSON.stringify(critical.criticalTokens(v).map(t=>[t.kind,t.text]));expandedConflict=candidates.some(c=>key(c.text)!==key(value));candidates.push({readingId:'precision_native_expanded',text:value,criticalPositions:tokens,rowIndex:erow.index,frameIndex:eframe.frameIndex,frameId:eframe.frameId,time:erow.time,sourceRect:clone(selection.expanded.sourceRect),nativeCropPixelsSha256:selection.expanded.cropPixelsSha256,parentPixelsSha256:selection.expanded.parentPixelsSha256,sourceScope:erow.frameIndex===row.frameIndex?'same_parent_actual_frame_distinct_native_crop_not_an_independent_truth_vote':'same_source_owned_event_member_frame_distinct_native_crop_not_an_independent_truth_vote'});}
    const plan=selection.evidence?.endpointPlan,owned=selection.evidence?.endpointOwnedProof,criticalPositions=[...new Set(critical.criticalTokens(selection.actual.text,simplified().text,verdict.stickyNamedIdentityScope).flatMap(t=>Array.from({length:t.end-t.start},(_,i)=>t.start+i)))];
    // A claimed endpoint gain cannot erase a critical conflict merely because
    // an older signature missed a unit or retained identity scope. Both the
    // plan and source-owned proof must cover every actual protected position.
    const protectedExtentBound=owned?.reason==='all_selected_critical_positions_source_owned_and_new_extent_ink_present'&&criticalPositions.every(i=>plan?.criticalIndices?.includes(i)&&owned?.criticalIndices?.includes(i));
    const extentOnly=expandedConflict&&!verdict.hasCriticalConflict&&owned?.passed===true&&plan?.passed===true&&protectedExtentBound&&candidates.filter(c=>c.readingId!=='precision_native_expanded').every(c=>c.text===simplified().text(event.precision.reading.text));
    return {schema:critical.POLICY.schema,status:extentOnly?'source_supported_native_extent_difference':expandedConflict?'unresolved_critical_cross_crop_conflict':verdict.status,hasCriticalConflict:verdict.hasCriticalConflict||expandedConflict&&!extentOnly,requiresReview:verdict.requiresReview||expandedConflict&&!extentOnly,nativeExtentSupported:extentOnly,namedIdentityScope:verdict.stickyNamedIdentityScope||candidates.some(c=>NAMED_IDENTITY_PATTERN.test(c.text)),candidates,semanticCorrectnessVerified:false,correlatedCandidatesAreNotIndependentTruth:true};
  }
  function styleWorkingAuthority(result,s,p,style,segments,boundRows){const deny=reason=>({allowed:false,reason,semanticRoleVerified:false}),allow=(reason,evidence)=>({allowed:true,reason,evidence,semanticRoleVerified:false});if(!['projected','diverted'].includes(p.status))return allow('no_negative_style_change',[]);if(!style?.receipt||!style.sourceRect||!Array.isArray(style.tokens))return deny('style_proposal_has_no_independent_negative_authority');
    const rows=result.raw.rows,frames=result.raw.frames,source=style.receipt,row=rows.find(r=>s.rowIndices.includes(r.index)&&r.frameId===source.frameId&&r.time===source.time),frame=frames[source.frameIndex],ownDecision=result.roleDecisions.find(d=>d.rowIndex===row?.index),key=JSON.stringify(result.sourceIdentity),prefix=result.sourceIdentity?.kind==='local_file_sha256'&&shaPattern.test(result.sourceIdentity.sha256)?'file:'+result.sourceIdentity.sha256+':frame:':result.sourceIdentity?.kind==='locked_visible_video'?'task:'+result.sourceIdentity.intentId+':frame:':null;if(!row||!frame||!prefix||s.sourceIdentityKey!==key||row.frameId!==prefix+row.frameIndex||source.frameIndex!==row.frameIndex||frame.frameIndex!==row.frameIndex||frame.frameId!==row.frameId||frame.time!==row.time||frame.frameId!==source.frameId||frame.time!==source.time||frame.sourcePixelSha256!==source.parentPixelsSha256)return deny('negative_source_binding_invalid');
    const overlap=(a,b,axis)=>Math.max(0,Math.min(a[axis==='y'?'bottom':'right'],b[axis==='y'?'bottom':'right'])-Math.max(a[axis==='y'?'top':'left'],b[axis==='y'?'top':'left'])),h=b=>b.bottom-b.top,w=b=>b.right-b.left;
    if(p.status==='diverted'){
      // The detector/role-qualified primary may change font, colour or lane.
      // A style vote alone cannot remove it. Only a separately promoted block,
      // with an independent same-frame outlined caption, can be diverted.
      if(!/^scene_local_caption_lane_(?:companion|replacement)$/u.test(ownDecision?.roleEvidence?.kind||''))return deny('qualified_primary_retained_despite_style_difference');
      const features=style.tokens.filter(t=>t.status==='measured').map(t=>t.feature);if(!features.length)return deny('caption_foreground_cannot_be_negatively_classified');
      const other=boundRows.filter(r=>r.index!==row.index&&r.frameId===source.frameId&&r.time===source.time).find(r=>{const d=result.roleDecisions.find(d=>d.rowIndex===r.index),f=r.roleStyle?.summary,smallDarkLayer=style.summary?.kind==='dark'&&finite(style.summary.inkHeight)&&f&&style.summary.inkHeight<=f.inkHeight*.6&&features.filter(x=>x.kind==='dark').length>=features.length*.65;return d?.decision==='proposed_caption'&&d.roleEvidence?.kind==='existing_qualified_caption_observation'&&f?.kind==='light'&&f.outlineFraction>=.8&&f.inkHeight>=16&&r.text.trim()&&(overlap(style.sourceRect,r.sourceRect,'y')/Math.min(h(style.sourceRect),h(r.sourceRect))<=.25||smallDarkLayer);});
      if(!other)return deny('no_independent_same_frame_caption_block');const smallSeparateInk=finite(style.summary?.inkHeight)&&style.summary.inkHeight<other.roleStyle.summary.inkHeight*.75,nonCaptionForeground=features.filter(f=>f.outlineFraction<.65).length>=features.length*.65;if(!smallSeparateInk&&!nonCaptionForeground)return deny('caption_foreground_cannot_be_negatively_classified');
      return allow('separate_promoted_block_with_actual_same_frame_caption',[{rowIndex:other.index,frameId:other.frameId,time:other.time,sourceRect:clone(other.sourceRect),cropPixelsSha256:other.cropPixelsSha256,parentPixelsSha256:frame.sourcePixelSha256,foregroundComparedToIndependentCaption:{smallSeparateInk,nonCaptionForeground,candidateInkHeight:style.summary.inkHeight,captionInkHeight:other.roleStyle.summary.inkHeight}}]);
    }
    const range=p.selectedTokenRange,chars=Array.from(p.parentReading?.text||''),removed=range&&chars.slice(0,range[0]).concat(chars.slice(range[1])).join('');if(!range||!removed||!/^[A-Za-z\s.,'’\-]+$/u.test(removed)||s.criticalReadingStatus?.namedIdentityScope)return deny('no_source_bound_mixed_line_boundary_for_partial_change');
    const ts=style.tokens.slice(...range).filter(t=>t.status==='measured'),removedTokens=style.tokens.filter((t,i)=>(i<range[0]||i>=range[1])&&t.status!=='layout');if(!ts.length||removedTokens.some(t=>t.status!=='measured')||ts.some(t=>t.feature.kind!=='light'||t.feature.outlineFraction<.85))return deny('mixed_line_caption_component_evidence_incomplete');
    const envelope={left:Math.floor(style.sourceRect.left+Math.min(...ts.map(t=>t.horizontalWindow.left))),right:Math.ceil(style.sourceRect.left+Math.max(...ts.map(t=>t.horizontalWindow.right))),top:Math.min(...ts.map(t=>t.feature.top)),bottom:Math.max(...ts.map(t=>t.feature.baseline))};if(h(style.sourceRect)<h(envelope)*1.65)return deny('same_caption_line_must_not_be_trimmed_by_style');
    const supports=[];for(const other of segments){if(other.id===s.id||(other.captionLaneId||other.familyId)!==(s.captionLaneId||s.familyId)||other.sourceIdentityKey!==s.sourceIdentityKey)continue;const e=result.events.find(e=>e.id===other.id),q=e&&selectActualReading(e,rows,frames),r=rows[q?.expanded?.rowIndex??e?.selectedRowIndex],f=frames[r?.frameIndex];if(!e||!r||!f||r.frameId!==prefix+r.frameIndex||f.frameIndex!==r.frameIndex||f.frameId!==r.frameId||f.time!==r.time||f.frameIndex===source.frameIndex||Math.abs(r.time-source.time)>1.55||!['precision_native_representative','precision_native_expanded'].includes(q.kind)||q.actual.text!==p.selectedReading?.text||simplified().text(r.text)!==simplified().text(q.actual.text)||q.actual.minCharConfidence<95||q.actual.confidence<95)continue;const receipt=actualReceipt(e,q,rows,frames),box=q.expanded?.sourceRect||r.sourceRect;if(!receipt||receipt.rowIndex!==r.index||receipt.frameIndex!==r.frameIndex||receipt.frameId!==r.frameId||receipt.time!==r.time||receipt.parentPixelsSha256!==f.sourcePixelSha256||receipt.originalCropPixelsSha256!==r.cropPixelsSha256||h(box)*1.65>h(style.sourceRect)||overlap(envelope,box,'y')/Math.min(h(envelope),h(box))<.6||overlap(envelope,box,'x')/Math.min(w(envelope),w(box))<.5)continue;supports.push({eventId:e.id,rowIndex:r.index,frameId:r.frameId,time:r.time,sourceRect:clone(box),actualReading:clone(q.actual),receipt:clone(receipt)});}
    return supports.length?allow('mixed_parent_corroborated_by_independent_actual_full_read',supports):deny('no_independent_actual_full_caption_read_for_mixed_parent');
  }
  function projectWorkingBody(result,segments){const role=roleStyleApi(),track=result.captionStyleTrack,supports=new Map((result.captionStyleSupportRecords||[]).map(p=>[p.rowIndex,p.style])),boundRows=result.raw.rows.map(r=>({...r,roleStyle:supports.get(r.index)}));if(!role||!track||!role.validateTrack(track,boundRows,result.raw.frames).valid)return {body:segments,diverted:[],decisions:[]};
    const body=[],diverted=[],decisions=[];for(const s of segments){const event=result.events.find(e=>e.id===s.id),selection=event&&selectActualReading(event,result.raw.rows,result.raw.frames),style=selection&&actualRoleStyle(event,selection,result.raw.rows,result.raw.frames);let p=role.projectReading(selection?.actual,style,track),chosen=selection,chosenStyle=style;
      // A supported contiguous span of a real mobile parent may be retained
      // when the selected precision read has unresolved mixed-role endpoints.
      // This is an explicitly labelled actual-read route, not text repair.
      if(p.status==='unknown'&&event){const row=result.raw.rows[event.selectedRowIndex],light=(event.nativeRoleStyles||[]).find(v=>v.kind==='detected_line_original_color'&&same(v.reading,reading(row))&&same(v.style?.sourceRect,row.sourceRect)&&v.style?.receipt?.cropPixelsSha256===row.cropPixelsSha256&&v.style.receipt.parentPixelsSha256===result.raw.frames[row.frameIndex].sourcePixelSha256),q=role.projectReading(reading(row),light?.style,track);if(q.status==='projected'){p=q;chosenStyle=light.style;chosen={kind:'detected_line_original_color',actual:reading(row)};}}
      const authority=styleWorkingAuthority(result,s,p,chosenStyle,segments,boundRows);if(!authority.allowed){decisions.push({eventId:s.id,projection:clone(p),actualReadRoute:chosen?.kind||null,workingAuthority:authority,applied:false});body.push({...s,nativeStyleProposal:clone(p),nativeStyleWorkingAuthority:authority});continue;}
      const tokenRange=p.selectedTokenRange||[0,chosenStyle?.tokens?.length||0],tokens=chosenStyle?.tokens?.slice(...tokenRange).filter(t=>t.status==='measured')||[],envelope=tokens.length?{left:Math.floor(chosenStyle.sourceRect.left+Math.min(...tokens.map(t=>t.horizontalWindow.left))),right:Math.ceil(chosenStyle.sourceRect.left+Math.max(...tokens.map(t=>t.horizontalWindow.right))),top:Math.min(...tokens.map(t=>t.feature.top)),bottom:Math.max(...tokens.map(t=>t.feature.baseline))}:null;
      decisions.push({eventId:s.id,projection:clone(p),actualReadRoute:chosen?.kind||null,workingAuthority:authority,applied:true});if(p.status==='unknown'||p.status==='keep'){body.push({...s,...(p.status==='keep'?{nativeRoleProjection:clone(p),nativeRoleProjectionBodyRect:envelope}:{})});continue;}
      for(const d of p.diverted||[])diverted.push({...s,...simplified().normalize(d.text),id:s.id+':style-diverted-'+d.range.join('-'),layer:'screen',nativeRoleProjection:clone(p),divertedParentEventId:s.id,selectedReadingId:'native_style_other_actual_token_span_v197',selectedActualReadingReceipt:null,nativeSourceStyleReceipt:null,expandedEvidence:null,glyphEvidenceReceipt:null,readingSelection:null,criticalReadingStatus:null,roleConfirmed:false});
      if(p.status==='projected'){const critical=s.criticalReadingStatus?.hasCriticalConflict&&(s.criticalReadingStatus.namedIdentityScope||root.BrandbaiCriticalReadV197?.criticalTokens(simplified().text(p.selectedReading.text)).length)?s.criticalReadingStatus:null;body.push({...s,...simplified().normalize(p.selectedReading.text),selectedReadingId:'native_style_projected_actual_token_span_v197',selectedActualReading:p.selectedReading.text,selectedActualReadingReceipt:null,nativeSourceStyleReceipt:null,expandedEvidence:null,glyphEvidenceReceipt:null,readingSelection:null,criticalReadingStatus:critical,nativeRoleProjection:clone(p),nativeRoleProjectionBodyRect:envelope,workingReadRoute:chosen.kind,roleConfirmed:false});}
    }return{body,diverted,decisions};
  }
  function errorText(error){const value=String(error?.message||error||'');return value.length>180||/(?:https?:|blob:|file:|chrome:|[A-Za-z]:[\\/]|[?&][A-Za-z_]+=)/u.test(value)?'视频处理暂时停止，已有文字已保留。':value;}
  function signature(text){const value=simplified().text(text);return JSON.stringify([api()?.protectedSignature?.(value)||value,protectedUnits(value).map(m=>m[0]),value.match(/[我你您他她它谁咱俺]/gu)||[],
    NAMED_IDENTITY_PATTERN.test(value)?value:'']);}
  function precisionKey(text){const key=simplified().text(text).trim().replace(/(?<=\p{Script=Han})[ \t\u3000]+(?=\p{Script=Han})/gu,'');
    return /[\p{Nd}零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟萬億]/u.test(key)?key:key.replace(/[~～]+$/u,'');}
  const lane=e=>e.captionLaneId||e.familyId;
  function nearRows(a,b){const x=a?.sourceRect,y=b?.sourceRect;if(!x||!y||a.sourceWidth!==b.sourceWidth||a.sourceHeight!==b.sourceHeight)return false;
    const h=x.bottom-x.top,k=y.bottom-y.top,overlap=Math.max(0,Math.min(x.right,y.right)-Math.max(x.left,y.left));
    return h>0&&k>0&&h/k>=.55&&h/k<=1.8&&Math.abs((x.top+x.bottom-y.top-y.bottom)/2)<=Math.max(h,k)*.65
      &&overlap/Math.min(x.right-x.left,y.right-y.left)>=.6;}
  function expandedRect(row,rows){const b=row?.sourceRect,h=b&&b.bottom-b.top,w=row?.sourceWidth,H=row?.sourceHeight;
    if(!b||![b.left,b.top,b.right,b.bottom,w,H].every(Number.isSafeInteger)||h<12||h>256||b.left<0||b.right>w||b.top<0||b.bottom>H||b.right<=b.left)return null;
    const pad=Math.ceil(h*EXPANSION.heightPadding),maxPad=Math.ceil(h*EXPANSION.maximumHeightPadding);
    const box={left:Math.max(0,b.left-pad),top:b.top,right:Math.min(w,b.right+pad),bottom:b.bottom};
    // A detector neighbour of comparable height is an ownership veto. Do not
    // enlarge a single line into a second line or a neighbouring screen label.
    for(const peer of rows||[]){if(peer.index===row.index||peer.frameIndex!==row.frameIndex)continue;const p=peer.sourceRect;if(!p)continue;
      const ph=p.bottom-p.top,vertical=Math.max(0,Math.min(box.bottom,p.bottom)-Math.max(box.top,p.top));
      if(ph>=h*.55&&vertical>=Math.min(h,ph)*.5&&Math.max(box.left,p.left)<Math.min(box.right,p.right)
        &&(p.left<b.left||p.right>b.right))return null;}
    if(box.left<b.left-maxPad||box.right>b.right+maxPad||box.right-box.left>2560)return null;
    return box;
  }
  function glyphEvidence(image,read){const a=read?.tokenAlignment,chars=Array.from(read?.text||'');
    if(!image||!a||a.schema!=='ctc-temporal-bands-v1'||a.sourceWidth!==image.width||a.sourceHeight!==image.height||!Array.isArray(a.bands)||a.bands.length!==chars.length
      ||image.data?.length!==image.width*image.height*4||chars.length>300)return null;
    const w=image.width,h=image.height,n=w*h,bits=new Uint8Array(n),labels=new Int16Array(n),histogram=new Map(),radius=Math.max(1,Math.min(3,Math.round(h*.05)));
    const rgb=i=>[image.data[i*4],image.data[i*4+1],image.data[i*4+2]];
    for(let i=0;i<n;i++){const [r,g,b]=rgb(i),maximum=Math.max(r,g,b),minimum=Math.min(r,g,b);
      if(minimum>=205&&maximum-minimum<=55)labels[i]=1;
      else if(maximum>=205&&maximum-minimum>=80)labels[i]=2+(r>>5)*64+(g>>5)*8+(b>>5);}
    // Determine one repeated foreground colour from contrast around the actual
    // CTC centres. Scene pixels outside this colour are never glyph evidence.
    for(let y=radius;y<h-radius;y++)for(let x=radius;x<w-radius;x++){const i=y*w+x,label=labels[i];if(!label||y<h*.12||y>h*.88)continue;
      if(!a.bands.some(b=>Math.abs(x-b.peak)<=h*.3))continue;
      const color=rgb(i),minimum=Math.min(...color),maximum=Math.max(...color);let contrast=false;
      for(let d=1;d<=radius;d++){for(const j of [i-d,i+d,i-d*w,i+d*w]){const other=rgb(j);
        if(maximum-Math.max(...other)>=45||label===1&&minimum-Math.min(...other)>=35){contrast=true;break;}}if(contrast)break;}
      if(contrast)histogram.set(label,(histogram.get(label)||0)+1);}
    const ranked=[...histogram].sort((x,y)=>y[1]-x[1]),chosen=ranked[0]?.[0];if(!chosen||ranked[0][1]<12)return null;
    const compatible=label=>label===chosen||chosen!==1&&label>1&&Math.abs(Math.floor((label-2)/64)-Math.floor((chosen-2)/64))<=1
      &&Math.abs(Math.floor((label-2)%64/8)-Math.floor((chosen-2)%64/8))<=1&&Math.abs((label-2)%8-(chosen-2)%8)<=1;
    const seen=new Uint8Array(n),queue=new Int32Array(n);
    for(let seed=0;seed<n;seed++){if(seen[seed]||!compatible(labels[seed]))continue;let head=0,count=1,left=w,right=0,top=h,bottom=0;queue[0]=seed;seen[seed]=1;
      while(head<count){const i=queue[head++],x=i%w,y=Math.floor(i/w);left=Math.min(left,x);right=Math.max(right,x+1);top=Math.min(top,y);bottom=Math.max(bottom,y+1);
        for(let yy=Math.max(0,y-1);yy<Math.min(h,y+2);yy++)for(let xx=Math.max(0,x-1);xx<Math.min(w,x+2);xx++){const j=yy*w+xx;if(!seen[j]&&compatible(labels[j])){seen[j]=1;queue[count++]=j;}}}
      if(count>=3&&bottom-top<=h*.94&&right-left<=h*1.8&&Math.abs((top+bottom)/2-h/2)<=h*.4)for(let i=0;i<count;i++)bits[queue[i]]=1;
    }
    const glyphs=[];
    for(let p=0;p<chars.length;p++){const band=a.bands[p];if(band.text!==chars[p]||!finite(band.peak)||band.peak<0||band.peak>w)return null;
      const step=p?a.bands[p].peak-a.bands[p-1].peak:chars.length>1?a.bands[1].peak-band.peak:h;
      const next=p+1<chars.length?a.bands[p+1].peak-band.peak:step;
      const left=Math.max(0,Math.floor(band.peak-step*.55)),right=Math.min(w,Math.ceil(band.peak+next*.55));
      let l=right,r=left,t=h,b=0,count=0;
      for(let y=0;y<h;y++)for(let x=left;x<right;x++)if(bits[y*w+x]){l=Math.min(l,x);r=Math.max(r,x+1);t=Math.min(t,y);b=Math.max(b,y+1);count++;}
      if(count<12||r<=l||b<=t){glyphs.push({text:chars[p],mask:null,inkPixels:count});continue;}
      let mask='';for(let yy=0;yy<EXPANSION.glyphHeight;yy++)for(let xx=0;xx<EXPANSION.glyphWidth;xx++){
        const x=l+Math.min(r-l-1,Math.floor((xx+.5)*(r-l)/EXPANSION.glyphWidth)),y=t+Math.min(b-t-1,Math.floor((yy+.5)*(b-t)/EXPANSION.glyphHeight));mask+=bits[y*w+x];}
      glyphs.push({text:chars[p],mask,inkPixels:count,inkWidth:r-l,inkHeight:b-t});
    }
    return {schema:'actual-expanded-ctc-ink-shapes-v195',kernel:'dominant-foreground-components-v1',width:EXPANSION.glyphWidth,height:EXPANSION.glyphHeight,glyphs,
      limitation:'Source-pixel contrast shapes corroborate reads; no semantic or exact glyph-box claim'};
  }
  function glyphTopology(mask,w,h){const seen=new Uint8Array(mask.length);let components=0,holes=0;
    for(let seed=0;seed<mask.length;seed++){if(seen[seed])continue;const ink=mask[seed]==='1',queue=[seed];seen[seed]=1;let exterior=false;
      for(let head=0;head<queue.length;head++){const i=queue[head],x=i%w,y=Math.floor(i/w);if(!ink&&(x===0||x===w-1||y===0||y===h-1))exterior=true;
        const offsets=ink?[[-1,-1],[0,-1],[1,-1],[-1,0],[1,0],[-1,1],[0,1],[1,1]]:[[0,-1],[-1,0],[1,0],[0,1]];
        for(const [dx,dy]of offsets){const xx=x+dx,yy=y+dy,j=yy*w+xx;if(xx>=0&&xx<w&&yy>=0&&yy<h&&!seen[j]&&(mask[j]==='1')===ink){seen[j]=1;queue.push(j);}}}
      if(ink)components++;else if(!exterior)holes++;}
    return {components,holes};
  }
  function aspectMask(sourceMask,w,h){const W=OWNED_GLYPHS.width,H=OWNED_GLYPHS.height,scale=Math.min((W-2)/w,(H-2)/h),fw=Math.max(1,Math.round(w*scale)),fh=Math.max(1,Math.round(h*scale)),left=Math.floor((W-fw)/2),top=Math.floor((H-fh)/2);let mask='';
    for(let y=0;y<H;y++)for(let x=0;x<W;x++){if(x<left||x>=left+fw||y<top||y>=top+fh){mask+='0';continue;}
      mask+=sourceMask[Math.min(h-1,Math.floor((y-top+.5)*h/fh))*w+Math.min(w-1,Math.floor((x-left+.5)*w/fw))];}return mask;
  }
  function ownedGlyphEvidence(image,read){const a=read?.tokenAlignment,chars=Array.from(read?.text||''),w=image?.width,h=image?.height;
    if(!image||!Number.isSafeInteger(w)||!Number.isSafeInteger(h)||w<1||h<1||w>2560||h>256||image.data?.length!==w*h*4||!a||a.schema!=='ctc-temporal-bands-v1'
      ||a.sourceWidth!==w||a.sourceHeight!==h||!Array.isArray(a.bands)||a.bands.length!==chars.length||!chars.length||chars.length>300)return null;
    if(a.bands.some((b,i)=>b.text!==chars[i]||!finite(b.peak)||b.peak<0||b.peak>w||i&&b.peak<=a.bands[i-1].peak))return null;
    const n=w*h,labels=new Int16Array(n),hist=new Map(),radius=Math.max(1,Math.min(3,Math.round(h*.05))),rgb=i=>[image.data[i*4],image.data[i*4+1],image.data[i*4+2]];
    for(let i=0;i<n;i++){const c=rgb(i),maximum=Math.max(...c),minimum=Math.min(...c);if(minimum>=205&&maximum-minimum<=55)labels[i]=1;else if(maximum>=205&&maximum-minimum>=80)labels[i]=2+(c[0]>>5)*64+(c[1]>>5)*8+(c[2]>>5);}
    for(let y=radius;y<h-radius;y++)for(let x=radius;x<w-radius;x++){const i=y*w+x,label=labels[i];if(!label||y<h*.12||y>h*.88||!a.bands.some(b=>Math.abs(x-b.peak)<=h*.3))continue;
      const c=rgb(i),minimum=Math.min(...c),maximum=Math.max(...c);let contrast=false;for(let d=1;d<=radius;d++){for(const j of[i-d,i+d,i-d*w,i+d*w]){const o=rgb(j);if(maximum-Math.max(...o)>=45||label===1&&minimum-Math.min(...o)>=35){contrast=true;break;}}if(contrast)break;}if(contrast)hist.set(label,(hist.get(label)||0)+1);}
    const ranked=[...hist].sort((x,y)=>y[1]-x[1]),chosen=ranked[0]?.[0];if(!chosen||ranked[0][1]<12)return null;
    const compatible=label=>label===chosen||chosen!==1&&label>1&&Math.abs(Math.floor((label-2)/64)-Math.floor((chosen-2)/64))<=1&&Math.abs(Math.floor((label-2)%64/8)-Math.floor((chosen-2)%64/8))<=1&&Math.abs((label-2)%8-(chosen-2)%8)<=1;
    const seen=new Uint8Array(n),queue=new Int32Array(n),groups=chars.map(()=>[]),uncertainty=chars.map(()=>[]),components=[],pitches=a.bands.slice(1).map((b,i)=>b.peak-a.bands[i].peak).sort((x,y)=>x-y),pitch=pitches[Math.floor(pitches.length/2)]||h;
    for(let seed=0;seed<n;seed++){if(seen[seed]||!compatible(labels[seed]))continue;let head=0,count=1,left=w,right=0,top=h,bottom=0;queue[0]=seed;seen[seed]=1;
      while(head<count){const i=queue[head++],x=i%w,y=Math.floor(i/w);left=Math.min(left,x);right=Math.max(right,x+1);top=Math.min(top,y);bottom=Math.max(bottom,y+1);
        for(let yy=Math.max(0,y-1);yy<Math.min(h,y+2);yy++)for(let xx=Math.max(0,x-1);xx<Math.min(w,x+2);xx++){const j=yy*w+xx;if(!seen[j]&&compatible(labels[j])){seen[j]=1;queue[count++]=j;}}}
      if(count<3||bottom-top>h*.94||right-left>h*1.8||Math.abs((top+bottom)/2-h/2)>h*.4)continue;
      const pixels=Array.from(queue.subarray(0,count));let boundary=0,outlined=0;
      for(const i of pixels){const x=i%w,y=Math.floor(i/w);if([i-1,i+1,i-w,i+w].every(j=>j>=0&&j<n&&compatible(labels[j])))continue;boundary++;let dark=false;
        for(let d=1;d<=3&&!dark;d++)for(const[xx,yy]of[[x-d,y],[x+d,y],[x,y-d],[x,y+d]])if(xx>=0&&xx<w&&yy>=0&&yy<h&&Math.max(...rgb(yy*w+xx))<125){dark=true;break;}if(dark)outlined++;}
      const center=(left+right)/2,dist=a.bands.map((b,i)=>({i,d:Math.abs(center-b.peak)/pitch})).sort((x,y)=>x.d-y.d),id='component-'+components.length,outlineFraction=boundary?outlined/boundary:0;
      const c={id,left,right,top,bottom,count,outlineFraction,pixels};components.push(c);if(count<8||outlineFraction<OWNED_GLYPHS.minimumOutlineFraction||dist[0].d>.6)continue;
      if(left===0||right===w||top===0||bottom===h){uncertainty[dist[0].i].push('native_component_touches_crop_edge');continue;}
      if(dist[1]&&dist[1].d-dist[0].d<.05){uncertainty[dist[0].i].push('native_component_owner_ambiguous');uncertainty[dist[1].i].push('native_component_owner_ambiguous');continue;}
      groups[dist[0].i].push(c);
    }
    const glyphs=groups.map((values,index)=>{let left=w,right=0,top=h,bottom=0,count=0;const bits=new Uint8Array(n);
      for(const c of values){left=Math.min(left,c.left);right=Math.max(right,c.right);top=Math.min(top,c.top);bottom=Math.max(bottom,c.bottom);for(const i of c.pixels){if(!bits[i])count++;bits[i]=1;}}
      const reasons=[...new Set(uncertainty[index])];if(count<12||right<=left||bottom<=top){reasons.push('native_owned_ink_missing');return {index,text:chars[index],complete:false,uncertaintyReasons:reasons,componentIds:values.map(c=>c.id)};}
      let sourceMask='';for(let y=top;y<bottom;y++)for(let x=left;x<right;x++)sourceMask+=bits[y*w+x];const inkWidth=right-left,inkHeight=bottom-top;
      return {index,text:chars[index],complete:!reasons.length,uncertaintyReasons:reasons,componentIds:values.map(c=>c.id),sourceBox:{left,right,top,bottom},sourceMask,
        inkPixels:count,inkWidth,inkHeight,physicalAspectRatio:inkWidth/inkHeight,topology:glyphTopology(sourceMask,inkWidth,inkHeight),mask:aspectMask(sourceMask,inkWidth,inkHeight)};});
    for(let i=1;i<glyphs.length;i++){const x=glyphs[i-1],y=glyphs[i];if(x.sourceBox&&y.sourceBox&&x.sourceBox.right>y.sourceBox.left){x.complete=y.complete=false;x.uncertaintyReasons.push('owned_glyph_spans_overlap');y.uncertaintyReasons.push('owned_glyph_spans_overlap');}}
    return {schema:OWNED_GLYPHS.schema,kernel:'outlined-whole-components-unique-owner-v1',width:OWNED_GLYPHS.width,height:OWNED_GLYPHS.height,sourceWidth:w,sourceHeight:h,foregroundColorBucket:chosen,glyphs,
      components:components.map(({pixels,...c})=>{const mask=new Uint8Array((c.right-c.left)*(c.bottom-c.top));for(const i of pixels)mask[(Math.floor(i/w)-c.top)*(c.right-c.left)+i%w-c.left]=1;
        return {...c,sourceMask:Array.from(mask).join('')};}),semanticCorrectnessVerified:false};
  }
  function validOwnedGlyph(g,w,h){try{const b=g?.sourceBox;return g.complete===true&&Array.isArray(g.uncertaintyReasons)&&!g.uncertaintyReasons.length&&b&&['left','right','top','bottom'].every(k=>Number.isSafeInteger(b[k]))
      &&b.left>0&&b.top>0&&b.right<w&&b.bottom<h&&g.inkWidth===b.right-b.left&&g.inkHeight===b.bottom-b.top&&g.inkWidth>0&&g.inkHeight>0&&g.physicalAspectRatio===g.inkWidth/g.inkHeight
      &&typeof g.sourceMask==='string'&&g.sourceMask.length===g.inkWidth*g.inkHeight&&/^[01]+$/.test(g.sourceMask)&&Number.isSafeInteger(g.inkPixels)&&g.inkPixels>=12&&(g.sourceMask.match(/1/g)||[]).length===g.inkPixels
      &&Array.isArray(g.componentIds)&&g.componentIds.length>0&&new Set(g.componentIds).size===g.componentIds.length&&same(g.topology,glyphTopology(g.sourceMask,g.inkWidth,g.inkHeight))
      &&g.mask===aspectMask(g.sourceMask,g.inkWidth,g.inkHeight); }catch{return false;}}
  function compareOwnedGlyph(a,b){const fail=reason=>({passed:false,reason});if(!validOwnedGlyph(a,a?.sourceBox?.right+1,a?.sourceBox?.bottom+1)||!validOwnedGlyph(b,b?.sourceBox?.right+1,b?.sourceBox?.bottom+1))return fail('native_owned_glyph_incomplete');
    // At small native character sizes a one-pixel boundary change can itself be
    // a distinguishing stroke. Such glyphs do not authorize a protected merge.
    // A complete isolated long bar is an orientation-preserving exception, not
    // an exception for a recognized word or a particular character label.
    const longBar=g=>g.topology.components===1&&g.topology.holes===0&&g.physicalAspectRatio>=3&&g.inkWidth>=OWNED_GLYPHS.minimumStrokeResolution;
    if((a.inkHeight<OWNED_GLYPHS.minimumStrokeResolution||b.inkHeight<OWNED_GLYPHS.minimumStrokeResolution)&&!(longBar(a)&&longBar(b)))return fail('native_glyph_insufficient_stroke_resolution');
    if(Math.abs(a.inkWidth-b.inkWidth)>OWNED_GLYPHS.maximumDimensionDrift||Math.abs(a.inkHeight-b.inkHeight)>OWNED_GLYPHS.maximumDimensionDrift
      ||Math.max(a.physicalAspectRatio,b.physicalAspectRatio)/Math.min(a.physicalAspectRatio,b.physicalAspectRatio)>1.12)return fail('native_shape_geometry_changed');
    if(!same(a.topology,b.topology))return fail('native_shape_topology_changed');
    const at=(g,x,y)=>x>=0&&x<g.inkWidth&&y>=0&&y<g.inkHeight&&g.sourceMask[y*g.inkWidth+x]==='1',boundary=(g,x,y)=>{for(let yy=y-1;yy<=y+1;yy++)for(let xx=x-1;xx<=x+1;xx++)if(!at(g,xx,yy))return true;return false;};
    const centerChoices=delta=>[...new Set([Math.floor(delta/2),Math.ceil(delta/2)])].filter(n=>Math.abs(n)<=OWNED_GLYPHS.registrationPixels);
    for(const dy of centerChoices(b.inkHeight-a.inkHeight))for(const dx of centerChoices(b.inkWidth-a.inkWidth)){let unmatched=0,coreChanged=0,boundaryChanges=0;
      for(const [x,y,sx,sy]of[[a,b,dx,dy],[b,a,-dx,-dy]])for(let yy=0;yy<x.inkHeight;yy++)for(let xx=0;xx<x.inkWidth;xx++){if(!at(x,xx,yy)||at(y,xx+sx,yy+sy))continue;
        if(!boundary(x,xx,yy)){coreChanged++;continue;}let found=false;for(let oy=-1;oy<=1;oy++)for(let ox=-1;ox<=1;ox++)if(at(y,xx+sx+ox,yy+sy+oy))found=true;if(!found)unmatched++;else boundaryChanges++;}
      if(!unmatched&&!coreChanged)return {passed:true,reason:'registered_owned_native_strokes_agree',translation:{x:dx,y:dy},maxSourcePixelDistance:OWNED_GLYPHS.boundaryPixels,boundaryChanges,topology:clone(a.topology)};}
    return fail('native_unexplained_stroke_changed');
  }
  function validExpanded(value,row,frame,selection=true,rows=null){try{const b=value?.sourceRect,o=row.sourceRect,h=o.bottom-o.top,expected=rows?expandedRect(row,rows):null;
    return value?.schema===EXPANSION.schema&&value.status==='read'&&value.rowIndex===row.index&&value.frameIndex===row.frameIndex&&value.frameId===row.frameId&&value.time===row.time
      &&frame?.frameId===row.frameId&&frame.time===row.time&&value.parentPixelsSha256===frame.sourcePixelSha256&&value.originalCropPixelsSha256===row.cropPixelsSha256
      &&value.modelId===PRECISION_MODEL.modelId&&value.modelSha256===PRECISION_MODEL.modelSha256&&shaPattern.test(value.cropPixelsSha256)
      &&b&&['left','top','right','bottom'].every(k=>Number.isSafeInteger(b[k]))&&b.left>=0&&b.right<=row.sourceWidth&&b.left<=o.left&&b.right>=o.right&&b.top===o.top&&b.bottom===o.bottom
      &&o.left-b.left<=Math.ceil(h*EXPANSION.maximumHeightPadding)&&b.right-o.right<=Math.ceil(h*EXPANSION.maximumHeightPadding)
      &&value.inputWidth===b.right-b.left&&value.inputHeight===b.bottom-b.top&&value.interpolation==='none_integer_1_to_1'
      &&(!rows||expected&&same(b,expected))
      &&typeof value.reading?.text==='string'&&finite(value.reading.confidence)&&value.reading.confidence>=0&&value.reading.confidence<=100
      &&finite(value.reading.minCharConfidence)&&value.reading.minCharConfidence>=0&&value.reading.minCharConfidence<=100
      &&(!selection||value.reading.text.trim()&&!/[\r\n]/u.test(value.reading.text)&&value.reading.minCharConfidence>=EXPANSION.minimumCharConfidence);
  }catch{return false;}}
  function hasExpandedRead(e,rows,frames){return Array.isArray(e.nativeExpandedReads)&&e.nativeExpandedReads.some(p=>e.rowIndices.includes(p.rowIndex)&&validExpanded(p,rows[p.rowIndex],frames[p.frameIndex],false,rows));}
  function validSkippedExpansion(e,rows){return !(e.nativeExpandedReads?.length)&&e.nativeExpansion?.status==='not_attempted'&&(e.nativeExpansion.reason==='native_parent_source_unavailable'
    ||e.nativeExpansion.reason==='bounded_single_lane_expansion_ambiguous'&&!expandedRect(rows[e.selectedRowIndex],rows))
    ||e.nativeExpandedReads?.length&&!e.nativeGlyphReceipts?.length&&e.nativeGlyphStatus?.status==='not_attempted'&&e.nativeGlyphStatus.reason==='native_parent_source_unavailable';}
  function expansionSkipReason(e){return e.nativeGlyphStatus?.status==='not_attempted'?e.nativeGlyphStatus.reason:e.nativeExpansion?.reason;}
  function expandedSelection(e,rows,frames,selection=true){const records=(e.nativeExpandedReads||[]).filter(p=>e.rowIndices.includes(p.rowIndex)&&validExpanded(p,rows[p.rowIndex],frames[p.frameIndex],selection,rows));
    return records.find(p=>p.rowIndex===e.selectedRowIndex)||records[0]||null;}
  function alignedActualReading(read,box){const a=read?.tokenAlignment,chars=Array.from(read?.text||''),bands=a?.bands;
    return a?.schema==='ctc-temporal-bands-v1'&&a.sourceWidth===box.right-box.left&&a.sourceHeight===box.bottom-box.top&&Array.isArray(bands)&&bands.length===chars.length&&chars.length>0
      &&bands.every((b,i)=>b.text===chars[i]&&finite(b.left)&&finite(b.right)&&finite(b.peak)&&b.left>=0&&b.right<=a.sourceWidth&&b.left<=b.peak&&b.peak<=b.right&&(!i||b.peak>bands[i-1].peak));}
  function strongActualReading(read){const chars=Array.from(read?.text||''),scores=read?.charConfidences;
    return chars.length>0&&finite(read.minCharConfidence)&&read.minCharConfidence>=EXPANSION.minimumCharConfidence&&read.minCharConfidence<=100
      &&Array.isArray(scores)&&scores.length===chars.length&&scores.every((c,i)=>c.text===chars[i]&&finite(c.confidence)&&c.confidence>=0&&c.confidence<=100)
      &&read.minCharConfidence===Math.min(...scores.map(c=>c.confidence));}
  function containsSubsequence(shorter,longer){let i=0;for(const c of longer)if(c===shorter[i])i++;return i===shorter.length;}
  function comparableReadPair(e,p){const q=e.precision;return q?.status==='read'&&q.calibrationExact===true&&q.modelId===p.modelId&&q.modelSha256===p.modelSha256
    &&q.rowIndex===p.rowIndex&&q.frameIndex===p.frameIndex&&q.frameId===p.frameId&&q.time===p.time&&q.cropPixelsSha256===p.originalCropPixelsSha256;}
  function endpointExtentPlan(e,p,rows){const fail=reason=>({passed:false,reason}),q=e.precision?.reading,row=rows[p.rowIndex],base=Array.from(simplified().text(q?.text||'')),actual=Array.from(simplified().text(p.reading.text));
    if(!comparableReadPair(e,p)||!row)return fail('same_actual_row_required');
    if(base.length!==Array.from(q.text).length||actual.length!==Array.from(p.reading.text).length)return fail('normalization_position_map_unavailable');
    const starts=[];for(let i=0;i+base.length<=actual.length;i++)if(base.every((c,j)=>c===actual[i+j]))starts.push(i);
    if(!base.length||actual.length<=base.length||starts.length!==1)return fail('not_unique_contiguous_endpoint_extension');
    const old=row.sourceRect,box=p.sourceRect;if(!alignedActualReading(q,old)||!alignedActualReading(p.reading,box))return fail('actual_ctc_alignment_required');
    const offset=starts[0],added=actual.map((_,i)=>i).filter(i=>i<offset||i>=offset+base.length),a=q.tokenAlignment.bands,b=p.reading.tokenAlignment.bands,
      pitches=a.slice(1).map((v,i)=>v.peak-a[i].peak).sort((x,y)=>x-y),pitch=pitches[Math.floor(pitches.length/2)]||old.bottom-old.top,evidence=[],contacts=[];
    for(const i of added){const band=b[i],left=box.left+band.left,right=box.left+band.right,side=i<offset?'left':'right',c=p.reading.charConfidences?.[i];
      if(c?.text!==Array.from(p.reading.text)[i]||!finite(c.confidence)||c.confidence<EXPANSION.minimumCharConfidence||c.confidence>100||band.confidence!==c.confidence)return fail('added_actual_token_confidence_required');
      if(side==='left'?right>old.left:left<old.right)return fail('added_ctc_band_not_wholly_in_new_source_extent');
      const index=side==='left'?0:a.length-1,margin=side==='left'?a[index].left:old.right-old.left-a[index].right;
      const endpointBand=b[offset+index],shiftedMargin=side==='left'?box.left+endpointBand.left-old.left:old.right-box.left-endpointBand.right;
      contacts.push({index:offset+index,side,originalEndpointMargin:margin,expandedEndpointMargin:shiftedMargin,pitch,ctcContactVerified:margin<=pitch/2||shiftedMargin<=pitch/2});
      evidence.push({index:i,text:actual[i],side,sourceCtcSpan:{left,right},originalEdge:side==='left'?old.left:old.right,originalEndpointMargin:margin,expandedEndpointMargin:shiftedMargin,pitch,confidence:c.confidence});}
    const kinds=protectedGlyphKinds(p.reading.text),identityScope=[e.rawMobileText,q.text,p.reading.text].some(t=>NAMED_IDENTITY_PATTERN.test(simplified().text(t||''))),
      criticalChange=signature(q.text)!==signature(p.reading.text)||identityScope;
    if(identityScope)kinds.forEach(k=>k.push('named_identity_from_read_or_raw'));
    return {passed:true,reason:'unique_actual_endpoint_extension_with_new_source_ctc',addedEvidence:evidence,addedIndices:added,endpointContacts:contacts,ctcContactVerified:contacts.every(c=>c.ctcContactVerified),criticalChange,
      criticalIndices:criticalChange?kinds.flatMap((k,i)=>k.length?[i]:[]):[],unrelatedWeakSharedCharactersRetained:true,semanticCorrectnessVerified:false};
  }
  function endpointOwnedProof(e,p,plan,rows,frames){const g=glyphSelection(e,p,rows,frames),old=rows[p.rowIndex].sourceRect;
    for(const contact of plan.endpointContacts){if(contact.ctcContactVerified)continue;const glyph=g?.evidence.glyphs[contact.index];if(!g||!validOwnedGlyph(glyph,g.evidence.sourceWidth,g.evidence.sourceHeight))return {passed:false,reason:'original_endpoint_contact_unproved'};
      const margin=contact.side==='left'?p.sourceRect.left+glyph.sourceBox.left-old.left:old.right-p.sourceRect.left-glyph.sourceBox.right;if(margin>contact.pitch/2)return {passed:false,reason:'original_endpoint_not_near_crop_edge'};}
    if(!plan.criticalChange)return {passed:true,reason:'noncritical_endpoint_gain_only'};
    if(!g||plan.criticalIndices.some(i=>!validOwnedGlyph(g.evidence.glyphs[i],g.evidence.sourceWidth,g.evidence.sourceHeight)))return {passed:false,reason:'critical_endpoint_extension_owned_source_evidence_incomplete'};
    const kinds=protectedGlyphKinds(p.reading.text);for(const i of plan.addedIndices){if(!kinds[i]?.length&&!plan.criticalIndices.includes(i))continue;const glyph=g.evidence.glyphs[i],box=glyph.sourceBox,old=rows[p.rowIndex].sourceRect;let fresh=false;
      for(let y=0;y<glyph.inkHeight&&!fresh;y++)for(let x=0;x<glyph.inkWidth;x++){const sourceX=p.sourceRect.left+box.left+x;if(glyph.sourceMask[y*glyph.inkWidth+x]==='1'&&(sourceX<old.left||sourceX>=old.right)){fresh=true;break;}}
      if(!fresh)return {passed:false,reason:'added_critical_glyph_has_no_owned_ink_in_new_extent'};}
    return {passed:true,reason:'all_selected_critical_positions_source_owned_and_new_extent_ink_present',criticalIndices:[...plan.criticalIndices],semanticCorrectnessVerified:false};
  }
  function expandedCandidateState(e,p,rows,frames){const eligible=validExpanded(p,rows[p.rowIndex],frames[p.frameIndex],true,rows),base=e.precision?.reading;
    if(!base?.text.trim()||!comparableReadPair(e,p))return {p,eligible,mayAdopt:eligible,reason:'existing_expanded_path_no_comparable_base'};
    const a=simplified().text(base.text),b=simplified().text(p.reading.text);if(a===b)return {p,eligible,mayAdopt:eligible,reason:'same_normalized_full_actual_read_existing_path'};
    const strong=strongActualReading(base),shorter=Array.from(b),longer=Array.from(a);
    if(strong&&longer.length>shorter.length&&containsSubsequence(shorter,longer))return {p,eligible,mayAdopt:false,reason:'strong_base_character_deletion_veto'};
    const plan=endpointExtentPlan(e,p,rows);if(plan.passed){if(eligible&&!plan.criticalChange&&!plan.ctcContactVerified)return {p,eligible,mayAdopt:true,reason:'existing_v195_path_unchanged_unproved_variant_retained',plan};
      return {p,eligible,mayAdopt:true,adoptEndpoint:true,reason:plan.reason,plan};}
    // Even a weak base cannot admit a new critical endpoint merely because the
    // expanded emitted characters are confident. It still needs the new extent.
    if(longer.length&&shorter.length>longer.length&&startsWithUniqueSubstring(longer,shorter)&&signature(a)!==signature(b))return {p,eligible,mayAdopt:false,reason:'critical_endpoint_extension_without_source_proof',plan};
    if(strong&&signature(a)!==signature(b))return {p,eligible,mayAdopt:false,reason:'strong_base_critical_change_without_new_extent_proof',plan};
    return {p,eligible,mayAdopt:eligible,reason:'existing_v195_path_unchanged_unproved_variant_retained',plan};
  }
  function startsWithUniqueSubstring(base,actual){let count=0;for(let i=0;i+base.length<=actual.length;i++)if(base.every((c,j)=>c===actual[i+j]))count++;return count===1;}
  function canonicalExpandedCandidate(e,rows,frames){const records=(e.nativeExpandedReads||[]).filter(p=>e.rowIndices.includes(p.rowIndex)&&validExpanded(p,rows[p.rowIndex],frames[p.frameIndex],false,rows));
    records.sort((a,b)=>Number(b.rowIndex===e.selectedRowIndex)-Number(a.rowIndex===e.selectedRowIndex));const states=records.map(p=>expandedCandidateState(e,p,rows,frames));
    // This ordering never depends on whether a glyph attempt has arrived. Its
    // evidence can veto display, not redirect the attempt to a different record.
    return states.find(s=>s.eligible&&s.mayAdopt)||states.find(s=>s.plan?.passed&&s.mayAdopt)||states[0]||null;}
  function selectedForGlyph(e,rows,frames){return canonicalExpandedCandidate(e,rows,frames)?.p||null;}
  function selectActualReading(e,rows,frames){const row=rows[e.selectedRowIndex],precision=e.precision?.status==='read'&&e.precision.reading?.text.trim()?e.precision:null,candidate=canonicalExpandedCandidate(e,rows,frames),p=candidate?.p;
    let expanded=candidate?.mayAdopt?p:null,proof=null,reason=candidate?.reason||'no_actual_expanded_pair';
    if(expanded&&candidate.adoptEndpoint){proof=endpointOwnedProof(e,p,candidate.plan,rows,frames);if(!proof.passed){expanded=null;reason=proof.reason;}}
    if(expanded&&!candidate.eligible&&!candidate.plan?.passed)expanded=null;
    const actual=expanded?.reading||precision?.reading||reading(row),kind=expanded?'precision_native_expanded':precision?'precision_native_representative':'detected_line_original_color';
    return {actual,kind,expanded,candidate:p||null,evidence:{...READ_SELECTION,kind,reason,...(candidate?.plan?{endpointPlan:clone(candidate.plan)}:{}),...(proof?{endpointOwnedProof:clone(proof)}:{}),
      selectedActualRowIndex:expanded?p.rowIndex:row.index,canonicalExpandedRowIndex:p?.rowIndex??null,canonicalExpandedCropSha256:p?.cropPixelsSha256??null,
      canonicalOriginatingReading:p?clone(p.reading):null,protectedCrossEventMergeEligible:!!expanded&&candidate.eligible,semanticCorrectnessVerified:false}};}
  function validGlyphEvidence(value,read){const chars=Array.from(read?.text||'');return value?.schema==='actual-expanded-ctc-ink-shapes-v195'
    &&value.width===EXPANSION.glyphWidth&&value.height===EXPANSION.glyphHeight&&Array.isArray(value.glyphs)&&value.glyphs.length===chars.length&&chars.length>0
    &&value.glyphs.every((g,i)=>g.text===chars[i]&&Number.isSafeInteger(g.inkPixels)&&g.inkPixels>=12&&typeof g.mask==='string'
      &&g.mask.length===value.width*value.height&&/^[01]+$/.test(g.mask)&&(g.mask.match(/1/g)||[]).length>=12
      &&((g.mask.match(/0/g)||[]).length>=12||Number.isSafeInteger(g.inkWidth)&&Number.isSafeInteger(g.inkHeight)&&g.inkWidth>=g.inkHeight*3));}
  function validOwnedEvidence(g,read){try{const chars=Array.from(read.text),used=new Set(),components=new Map((g?.components||[]).map(c=>[c.id,c]));return g?.schema===OWNED_GLYPHS.schema
    &&g.width===OWNED_GLYPHS.width&&g.height===OWNED_GLYPHS.height&&Array.isArray(g.glyphs)&&g.glyphs.length===chars.length&&chars.length>0&&components.size===g.components.length
    &&g.glyphs.every((v,i)=>{if(v.index!==i||v.text!==chars[i]||!Array.isArray(v.componentIds)||!Array.isArray(v.uncertaintyReasons)||v.complete&&!validOwnedGlyph(v,g.sourceWidth,g.sourceHeight)||!v.complete&&!v.uncertaintyReasons.length)return false;
      const union=v.sourceBox?new Uint8Array(v.inkWidth*v.inkHeight):null;
      for(const id of v.componentIds){const c=components.get(id);if(!c||typeof id!=='string'||used.has(id)||!Number.isSafeInteger(c.count)||c.count<8||!finite(c.outlineFraction)||c.outlineFraction<OWNED_GLYPHS.minimumOutlineFraction||c.outlineFraction>1
        ||!['left','right','top','bottom'].every(k=>Number.isSafeInteger(c[k]))||c.left<0||c.top<0||c.right>g.sourceWidth||c.bottom>g.sourceHeight||c.right<=c.left||c.bottom<=c.top
        ||typeof c.sourceMask!=='string'||c.sourceMask.length!==(c.right-c.left)*(c.bottom-c.top)||!/^[01]+$/.test(c.sourceMask)||(c.sourceMask.match(/1/g)||[]).length!==c.count)return false;
        used.add(id);if(union){if(c.left<v.sourceBox.left||c.right>v.sourceBox.right||c.top<v.sourceBox.top||c.bottom>v.sourceBox.bottom)return false;
          for(let y=c.top;y<c.bottom;y++)for(let x=c.left;x<c.right;x++)if(c.sourceMask[(y-c.top)*(c.right-c.left)+x-c.left]==='1')union[(y-v.sourceBox.top)*v.inkWidth+x-v.sourceBox.left]=1;}}
      return !union||Array.from(union).join('')===v.sourceMask;});}catch{return false;}}
  function validNativeGlyphReceipt(g,e,rows,frames){try{const p=(e.nativeExpandedReads||[]).find(p=>same(g.originatingReading,p.reading)&&g.rowIndex===p.rowIndex&&g.cropPixelsSha256===p.cropPixelsSha256&&same(g.sourceRect,p.sourceRect));
    return g.schema===OWNED_GLYPHS.receiptSchema&&p&&validExpanded(p,rows[p.rowIndex],frames[p.frameIndex],false,rows)&&e.rowIndices.includes(g.rowIndex)
      &&g.frameIndex===p.frameIndex&&g.frameId===p.frameId&&g.time===p.time&&g.parentPixelsSha256===p.parentPixelsSha256&&g.modelId===p.modelId&&g.modelSha256===p.modelSha256
      &&g.sourcePixelsVerified===true&&g.originalCropPixelsSha256===p.originalCropPixelsSha256&&g.inputWidth===p.inputWidth&&g.inputHeight===p.inputHeight&&g.interpolation==='none_integer_1_to_1'
      &&(g.status==='derived'&&g.evidence?.sourceWidth===p.inputWidth&&g.evidence.sourceHeight===p.inputHeight&&validOwnedEvidence(g.evidence,p.reading)
        ||g.status==='unavailable'&&g.reason==='native_owned_glyphs_unavailable'&&g.evidence===null); }catch{return false;}}
  function nativeGlyphReceipt(p,evidence){return {schema:OWNED_GLYPHS.receiptSchema,status:evidence?'derived':'unavailable',...(!evidence?{reason:'native_owned_glyphs_unavailable'}:{}),
    rowIndex:p.rowIndex,frameIndex:p.frameIndex,frameId:p.frameId,time:p.time,parentPixelsSha256:p.parentPixelsSha256,cropPixelsSha256:p.cropPixelsSha256,
    originalCropPixelsSha256:p.originalCropPixelsSha256,sourceRect:clone(p.sourceRect),inputWidth:p.inputWidth,inputHeight:p.inputHeight,modelId:p.modelId,modelSha256:p.modelSha256,
    interpolation:'none_integer_1_to_1',sourcePixelsVerified:true,originatingReading:clone(p.reading),evidence:clone(evidence),newOcrCalls:0};}
  function receiptMatchesExpanded(g,p){return g&&p&&['rowIndex','frameIndex','frameId','time','parentPixelsSha256','cropPixelsSha256','originalCropPixelsSha256','modelId','modelSha256','inputWidth','inputHeight'].every(k=>g[k]===p[k])&&same(g.sourceRect,p.sourceRect)&&same(g.originatingReading,p.reading);}
  function glyphSelection(e,expanded,rows,frames){return expanded&&(e.nativeGlyphReceipts||[]).find(g=>g.status==='derived'&&receiptMatchesExpanded(g,expanded)&&validNativeGlyphReceipt(g,e,rows,frames))||null;}
  function hasGlyphAttempt(e,rows,frames){const p=selectedForGlyph(e,rows,frames);return p&&(e.nativeGlyphReceipts||[]).some(g=>receiptMatchesExpanded(g,p)&&validNativeGlyphReceipt(g,e,rows,frames));}
  function protectedGlyphKinds(text){const value=simplified().text(text),kinds=Array.from(value).map(()=>[]),mark=(regex,kind)=>{for(const m of value.matchAll(regex)){let offset=Array.from(value.slice(0,m.index)).length;for(const _ of m[0])kinds[offset++].push(kind);}};
    mark(/[+\-−－]?\s*(?:\p{Nd}+(?:[.．]\p{Nd}*)?|[.．]\p{Nd}+)(?:\s*[%％])?/gu,'number');mark(/[负正]?[零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟萬億点]+/gu,'chinese_number');
    mark(new RegExp(PROTECTED_UNIT_PATTERN,'gu'),'unit_or_latin');
    mark(/不(?:能|是|会|要|再|用|需|得|可)?|没(?:有)?|无(?:需|法)?|未(?:必|能)?|非|勿|别|莫/gu,'negation');mark(/[我你您他她它谁咱俺]/gu,'identity_pronoun');
    if(NAMED_IDENTITY_PATTERN.test(value))kinds.forEach(k=>k.push('named_identity'));return kinds;
  }
  function disputedGlyphFootprint(raw,actual){const x=Array.from(simplified().text(raw)),y=Array.from(simplified().text(actual)),n=x.length,m=y.length;if(n>300||m>300||!m)return null;
    const cols=m+1,dp=new Uint16Array((n+1)*cols),indices=new Set(),absence=new Map(),seen=new Set(),pending=[[n,m]];
    for(let i=0;i<=n;i++)dp[i*cols]=i;for(let j=0;j<=m;j++)dp[j]=j;
    for(let i=1;i<=n;i++)for(let j=1;j<=m;j++)dp[i*cols+j]=Math.min(dp[(i-1)*cols+j]+1,dp[i*cols+j-1]+1,dp[(i-1)*cols+j-1]+(x[i-1]===y[j-1]?0:1));
    // Trace the union of every minimum-cost positional explanation, not one
    // convenient edit path. This locates evidence only; it never merges text.
    while(pending.length){const[i,j]=pending.pop(),key=i*cols+j;if(seen.has(key))continue;seen.add(key);const d=dp[key];
      if(i&&j&&dp[(i-1)*cols+j-1]+(x[i-1]===y[j-1]?0:1)===d){if(x[i-1]!==y[j-1])indices.add(j-1);pending.push([i-1,j-1]);}
      if(j&&dp[i*cols+j-1]+1===d){indices.add(j-1);pending.push([i,j-1]);}
      if(i&&dp[(i-1)*cols+j]+1===d){if(j)indices.add(j-1);if(j<m)indices.add(j);const span={leftIndex:Math.max(0,j-1),rightIndex:Math.min(m-1,j),beforeFirst:j===0,afterLast:j===m};absence.set(JSON.stringify(span),span);pending.push([i-1,j]);}}
    return {indices:[...indices].sort((a,b)=>a-b),absenceSpans:[...absence.values()],editDistance:dp[n*cols+m],allOptimalPathsCovered:true};
  }
  function absenceSpanOwned(evidence,span){const a=evidence.glyphs[span.leftIndex],b=evidence.glyphs[span.rightIndex];if(!validOwnedGlyph(a,evidence.sourceWidth,evidence.sourceHeight)||!validOwnedGlyph(b,evidence.sourceWidth,evidence.sourceHeight))return false;
    const used=new Set(evidence.glyphs.flatMap(g=>g.componentIds)),margin=Math.max(a.inkHeight,b.inkHeight),left=span.beforeFirst?Math.max(0,a.sourceBox.left-margin):a.sourceBox.left,right=span.afterLast?Math.min(evidence.sourceWidth,b.sourceBox.right+margin):b.sourceBox.right;
    return !evidence.components.some(c=>!used.has(c.id)&&c.count>=8&&c.outlineFraction>=OWNED_GLYPHS.minimumOutlineFraction&&c.left<right&&c.right>left);
  }
  function protectedEdgeProof(a,b){const fail=reason=>({passed:false,reason,schema:'protected-native-glyph-edge-v196'}),x=a?.expandedEvidence,y=b?.expandedEvidence,g=a?.glyphEvidenceReceipt,h=b?.glyphEvidenceReceipt;
    // The endpoint display exception is not a confidence or glyph exemption
    // for protected cross-event merging. Preserve the old adopted-read floor.
    if((a?.tailReadingSelection||a?.readingSelection)?.protectedCrossEventMergeEligible===false||b?.readingSelection?.protectedCrossEventMergeEligible===false
      ||x&&x.reading.minCharConfidence<EXPANSION.minimumCharConfidence||y&&y.reading.minCharConfidence<EXPANSION.minimumCharConfidence)return fail('display_endpoint_gain_not_protected_merge_authority');
    if(!x||!y||!g||!h||g.status!=='derived'||h.status!=='derived'||a.sourceIdentityKey!==b.sourceIdentityKey||!a.sourceIdentityKey||lane(a)!==lane(b)||a.layer!=='body'||b.layer!=='body'
      ||a.observationIndices?.at(-1)+1!==b.observationIndices?.[0]||b.firstObserved<=a.lastObserved||b.firstObserved-a.lastObserved>.59
      ||x.frameIndex===y.frameIndex||x.parentPixelsSha256===y.parentPixelsSha256||x.modelSha256!==y.modelSha256||g.cropPixelsSha256!==x.cropPixelsSha256||h.cropPixelsSha256!==y.cropPixelsSha256
      ||!receiptMatchesExpanded(g,x)||!receiptMatchesExpanded(h,y)||precisionKey(x.reading.text)!==precisionKey(y.reading.text))return fail('independent_bound_owned_receipts_required');
    if(!validOwnedEvidence(g.evidence,x.reading)||!validOwnedEvidence(h.evidence,y.reading)||g.evidence.glyphs.length!==h.evidence.glyphs.length)return fail('owned_glyph_evidence_invalid');
    const actual=simplified().text(x.reading.text),kinds=protectedGlyphKinds(actual),rawA=a.tailRawMobileText??a.rawMobileText,rawB=b.rawMobileText,
      footprints=[disputedGlyphFootprint(rawA,actual),disputedGlyphFootprint(rawB,actual)];if(footprints.some(f=>!f)||kinds.length!==g.evidence.glyphs.length)return fail('raw_disputed_positions_unresolved');
    if([rawA,rawB].some(t=>NAMED_IDENTITY_PATTERN.test(simplified().text(t))))kinds.forEach(k=>k.push('named_identity_from_raw'));
    const disputed=new Set(footprints.flatMap(f=>f.indices)),required=new Set([...kinds.flatMap((k,i)=>k.length?[i]:[]),...disputed]);
    const checks=g.evidence.glyphs.map((v,i)=>({index:i,text:v.text,protectedKinds:kinds[i]||[],rawDisputed:disputed.has(i),required:required.has(i),
      ...(required.has(i)?compareOwnedGlyph(v,h.evidence.glyphs[i]):{passed:true,reason:'same_raw_and_actual_noncritical_position_not_in_override_scope'})}));
    if(checks.some(c=>!c.passed))return {passed:false,reason:'at_least_one_native_glyph_unproved',schema:'protected-native-glyph-edge-v196',checks};
    if(footprints.flatMap(f=>f.absenceSpans).some(span=>!absenceSpanOwned(g.evidence,span)||!absenceSpanOwned(h.evidence,span)))return {passed:false,reason:'deleted_raw_glyph_absence_unproved',schema:'protected-native-glyph-edge-v196',checks};
    return {passed:true,reason:'all_critical_and_disputed_owned_native_glyphs_corroborated',schema:'protected-native-glyph-edge-v196',fromRowIndex:x.rowIndex,toRowIndex:y.rowIndex,
      fromFrameIndex:x.frameIndex,toFrameIndex:y.frameIndex,rawSignatures:[signature(rawA),signature(rawB)],requiredIndices:[...required].sort((a,b)=>a-b),footprints,checks,semanticCorrectnessVerified:false};
  }
  function expandedAgreement(a,b){return protectedEdgeProof(a,b).passed;
  }
  function extentJobs(result){const body=result.events.filter(e=>e.layer==='body'),ids=new Set(),text=e=>e.precision?.reading?.text||e.rawMobileText,groups=new Map();
    for(const event of body){const key=event.captionLaneId||'legacy-body-geometric-neighbours';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(event);}
    for(const values of groups.values())for(let i=0;i<values.length;i++){const a=values[i],b=values[i+1],read=a.precision?.reading,x=precisionKey(text(a));
      if(read&&(read.minCharConfidence<95||signature(a.rawMobileText)!==signature(read.text)))ids.add(a.id);
      if(!b||b.firstObserved-a.lastObserved>.59||b.firstObserved<=a.lastObserved||!nearRows(result.raw.rows[a.selectedRowIndex],result.raw.rows[b.selectedRowIndex]))continue;
      const y=precisionKey(text(b));let common=0;while(common<Math.min(x.length,y.length)&&x[common]===y[common])common++;
      const fragment=x!==y&&Math.min(x.length,y.length)>=4&&(x.includes(y)||y.includes(x)||common>=4&&common/Math.max(x.length,y.length)>=.7);
      if(x===y&&signature(a.rawMobileText)!==signature(b.rawMobileText)||fragment){ids.add(a.id);ids.add(b.id);}}
    return body.filter(e=>ids.has(e.id));
  }
  function consolidate(segments,rows){const byFamily=new Map(),out=[];for(const s of segments){const k=JSON.stringify([s.layer,lane(s)]);if(!byFamily.has(k))byFamily.set(k,[]);byFamily.get(k).push(s);}
    for(const list of byFamily.values()){list.sort((a,b)=>a.firstObserved-b.firstObserved||a.rowIndices[0]-b.rowIndices[0]);let last=null;
      for(const value of list){const s=clone(value),a=last&&rows[last.rowIndices.at(-1)],b=rows[s.rowIndices[0]],h1=a&&a.sourceRect.bottom-a.sourceRect.top,h2=b&&b.sourceRect.bottom-b.sourceRect.top;
        const precise=s=>['precision_native_representative','precision_native_expanded'].includes(s.selectedReadingId);
        const tailRaw=last?.tailRawMobileText??last?.rawMobileText,rawSame=last&&signature(tailRaw)===signature(s.rawMobileText),edgeProof=last&&!rawSame?protectedEdgeProof(last,s):null,protectedSame=last&&(rawSame||edgeProof?.passed);
        const can=last&&a&&b&&precise(last)&&precise(s)
          &&last.text.trim()&&s.text.trim()&&precisionKey(last.text)===precisionKey(s.text)&&protectedSame
          &&last.observationIndices.at(-1)+1===s.observationIndices[0]&&s.firstObserved>last.lastObserved&&s.firstObserved-last.lastObserved<=.59
          &&a.sourceWidth===b.sourceWidth&&a.sourceHeight===b.sourceHeight&&h1>0&&h2>0&&h1/h2>=.55&&h1/h2<=1.8
          &&Math.abs((a.sourceRect.top+a.sourceRect.bottom-b.sourceRect.top-b.sourceRect.bottom)/2)<=Math.max(h1,h2)*.65&&s.lastObserved-last.firstObserved<=10;
        if(!can){last={...s,tailRawMobileText:s.rawMobileText,tailReadingSelection:s.readingSelection||null,sourceEventIds:[s.id],precisionReadRowIndices:precise(s)?[s.selectedRowIndex]:[],retainedEventIds:[s.id],protectedEdgeEvidence:[]};out.push(last);continue;}
        last.lastObserved=s.lastObserved;last.end=s.end;last.observationIndices.push(...s.observationIndices);last.observationTimes.push(...s.observationTimes);last.rowIndices.push(...s.rowIndices);last.frameIds.push(...s.frameIds);
        last.candidateReadings.push(...s.candidateReadings);last.sourceEventIds.push(s.id);last.retainedEventIds.push(s.id);last.precisionReadRowIndices.push(s.selectedRowIndex);
        last.needsReview ||= s.needsReview;last.readingChanged ||= s.readingChanged;last.protectedChange ||= s.protectedChange;last.merged=true;last.mergeReason='same_actual_precision_text_contiguous_family_protected_mobile_changes_unchanged';
        if(!rawSame){last.mergeReason='same_actual_expanded_reads_with_owned_native_stroke_corroboration';last.protectedConflictResolvedByVisualEvidence=true;last.protectedEdgeEvidence.push(edgeProof);}
        last.tailRawMobileText=s.rawMobileText;last.tailReadingSelection=s.readingSelection||null;last.expandedEvidence=s.expandedEvidence||null;last.glyphEvidenceReceipt=s.glyphEvidenceReceipt||null;
      }}return out.sort((a,b)=>a.firstObserved-b.firstObserved||a.rowIndices[0]-b.rowIndices[0]);}
  function identity(value){
    if(!value||typeof value!=='object')throw Error('请先固定本次视频来源');
    if(value.kind==='local_file_sha256'&&shaPattern.test(value.sha256))return {kind:value.kind,sha256:value.sha256};
    if(value.kind==='locked_visible_video'&&typeof value.workId==='string'&&/^\d{5,30}$/.test(value.workId)
      &&typeof value.intentId==='string'&&value.intentId.length>0&&value.intentId.length<=200
      &&Number.isSafeInteger(value.bindingGeneration)&&value.bindingGeneration>=0
      &&(value.sourceDocumentToken===undefined||typeof value.sourceDocumentToken==='string'&&value.sourceDocumentToken.length>0&&value.sourceDocumentToken.length<=200))
      return {kind:value.kind,workId:value.workId,intentId:value.intentId,bindingGeneration:value.bindingGeneration,...(value.sourceDocumentToken?{sourceDocumentToken:value.sourceDocumentToken}:{})};
    throw Error('视频来源信息不完整，不能把作品编号当作文件校验值');
  }
  async function digest(bytes){return [...new Uint8Array(await root.crypto.subtle.digest('SHA-256',bytes))].map(n=>n.toString(16).padStart(2,'0')).join('');}
  function reading(value){const r=value?.data||value;if(!r||typeof r.text!=='string'||!finite(r.confidence)||r.confidence<0||r.confidence>100)throw Error('识别结果无效');
    return {text:r.text,confidence:r.confidence,charConfidences:clone(r.charConfidences||[]),minCharConfidence:finite(r.minCharConfidence)?r.minCharConfidence:0,...(r.tokenAlignment?{tokenAlignment:clone(r.tokenAlignment)}:{})};}
  function validRepresentative(e,rows){const p=e.precision,r=rows[e.selectedRowIndex];return p?.status==='read'&&r&&p.rowIndex===r.index&&p.frameId===r.frameId&&p.frameIndex===r.frameIndex
    &&p.time===r.time&&p.cropPixelsSha256===r.cropPixelsSha256&&p.modelId===PRECISION_MODEL.modelId&&p.modelSha256===PRECISION_MODEL.modelSha256
    &&p.calibrationExact===true&&typeof p.reading?.text==='string'&&finite(p.reading.confidence)&&p.reading.confidence>=0&&p.reading.confidence<=100;}
  function rect(candidate,w,h){const b=candidate?.sourceBBox;if(!b||!['left','top','right','bottom'].every(k=>finite(b[k])))return null;
    const x={left:Math.max(0,Math.floor(b.left)),top:Math.max(0,Math.floor(b.top)),right:Math.min(w,Math.ceil(b.right)),bottom:Math.min(h,Math.ceil(b.bottom))};return x.right>x.left&&x.bottom>x.top?x:null;}
  function canvas(w,h){const c=root.document?.createElement('canvas')||new root.OffscreenCanvas(w,h);c.width=w;c.height=h;return c;}
  function crop(full,b){const c=canvas(b.right-b.left,b.bottom-b.top);c.getContext('2d').drawImage(full,b.left,b.top,c.width,c.height,0,0,c.width,c.height);return c;}
  // This cache owns copies of native crop RGBA, never a mutable full-frame
  // canvas. It is an optional transport optimization, not another OCR vote.
  class NativePixelsCache {
    #entries=new Map();#bytes=0;
    constructor(limit){this.limit=Math.max(0,Math.min(PIXELS_CACHE_LIMIT,Number.isSafeInteger(limit)?limit:PIXELS_CACHE_LIMIT));this.stats={hits:0,misses:0,stores:0,evictions:0,rejected:0};}
    async put(key,image,hash){const size=image?.width*image?.height*4;if(!key||!Number.isSafeInteger(size)||size<=0||size>this.limit||image.data?.byteLength!==size){this.stats.rejected++;return false;}
      const data=new Uint8ClampedArray(image.data);if(await digest(data)!==hash){this.stats.rejected++;return false;}
      this.delete(key);while(this.#bytes+size>this.limit){const oldest=this.#entries.keys().next().value;this.delete(oldest);this.stats.evictions++;}
      this.#entries.set(key,{width:image.width,height:image.height,data,hash});this.#bytes+=size;this.stats.stores++;return true;}
    async get(key,hash){const value=key&&this.#entries.get(key);if(!value){this.stats.misses++;return null;}
      // Re-hash owned pixels even on a hit; neither caller mutation nor a
      // string-level resemblance can substitute for source pixel identity.
      if(value.hash!==hash||await digest(value.data)!==hash){this.delete(key);this.stats.rejected++;this.stats.misses++;return null;}
      this.#entries.delete(key);this.#entries.set(key,value);this.stats.hits++;return {width:value.width,height:value.height,data:new Uint8ClampedArray(value.data)};}
    delete(key){const value=this.#entries.get(key);if(value){this.#bytes-=value.data.byteLength;this.#entries.delete(key);}}
    summary(){return {schema:'bounded-native-crop-pixels-cache-v201',limitBytes:this.limit,bytes:this.#bytes,entries:this.#entries.size,...this.stats,ocrVotesAdded:0};}
  }
  function fallbackRoles(rows,reason){return rows.map(r=>({rowIndex:r.index,familyId:'unresolved:'+r.index,decision:'retained_other_or_uncertain',reason}));}
  function mapRoles(selection,rows,roleInput){
    const globallyComplete=selection?.roleGraphAnalysisComplete===true&&selection?.samplingPlanComplete===true;
    const locallyBound=!globallyComplete&&selection?.localRoleDecisionUsable===true&&roleInput&&roleApi()?.validateLocalRoleDecisionUsable?.({...roleInput,rows},selection)?.valid===true;
    if(!globallyComplete&&!locallyBound)return fallbackRoles(rows,'role_analysis_incomplete');
    const mapped=new Map();for(const d of selection.decisions||[]){const match=/^source-rect-row-(\d+)$/.exec(d.ref?.rowId||'');if(!match)throw Error('角色行对应关系无效');const index=Number(match[1]);
      if(mapped.has(index)||!rows[index]||rows[index].index!==index||rows[index].time!==d.ref.time)throw Error('角色行对应关系不一致');
      mapped.set(index,{rowIndex:index,familyId:String(d.familyId||'unresolved:'+index),decision:d.decision,reason:d.reason,
        ...(d.previousRoleRevisionDecision?{previousRoleRevisionDecision:clone(d.previousRoleRevisionDecision)}:{}),
        ...(['proposed_caption','visible_recovery_candidate','retained_other_or_uncertain'].includes(d.previousLaneDecision)?{previousLaneDecision:d.previousLaneDecision}:{}),
        ...(typeof d.captionLaneId==='string'&&d.captionLaneId?{captionLaneId:d.captionLaneId}:{}),...(d.roleEvidence?{roleEvidence:clone(d.roleEvidence)}:{})});}
    if(mapped.size!==rows.length)throw Error('角色结果缺少原始行');return rows.map(r=>mapped.get(r.index));
  }
  function buildEvents(rows,frames,decisions){
    const byFrame=new Map(frames.map(f=>[f.frameIndex,f])), groups=new Map();
    for(const d of decisions){const r=rows[d.rowIndex];if(!r||!r.text.trim())continue;const layer=d.decision==='proposed_caption'?'body':d.decision==='visible_recovery_candidate'?'recovery':'screen';
      const key=JSON.stringify([layer,d.familyId,d.captionLaneId||null]);if(!groups.has(key))groups.set(key,[]);groups.get(key).push({r,d,layer});}
    const events=[];
    for(const list of groups.values()){
      list.sort((a,b)=>a.r.frameIndex-b.r.frameIndex||a.r.index-b.r.index);const counts=new Map();for(const x of list)counts.set(x.r.frameIndex,(counts.get(x.r.frameIndex)||0)+1);
      let previous=null,event=null;
      for(const {r,d,layer}of list){const f=byFrame.get(r.frameIndex),ambiguous=counts.get(r.frameIndex)>1;
        const continuous=previous&&!ambiguous&&counts.get(previous.frameIndex)===1&&f?.status==='observed'&&byFrame.get(previous.frameIndex)?.status==='observed'
          &&r.frameIndex===previous.frameIndex+1&&r.time>previous.time&&r.time-previous.time<=.59&&r.sourceWidth===previous.sourceWidth&&r.sourceHeight===previous.sourceHeight;
        if(!event||!continuous||r.text!==previous.text){event={id:'',layer,familyId:d.familyId,...(d.captionLaneId?{captionLaneId:d.captionLaneId}:{}),text:r.text,rawMobileText:r.text,rowIndices:[],frameIndices:[],frameIds:[],observationTimes:[],roleReasons:[],roleConfirmed:false,needsReview:true};events.push(event);}
        event.rowIndices.push(r.index);event.frameIndices.push(r.frameIndex);event.frameIds.push(r.frameId);event.observationTimes.push(r.time);event.roleReasons.push(d.reason);previous=r;if(ambiguous){previous=null;event=null;}
      }
    }
    events.sort((a,b)=>a.observationTimes[0]-b.observationTimes[0]||a.rowIndices[0]-b.rowIndices[0]);
    events.forEach((e,i)=>{e.id='line-event-'+String(i+1).padStart(5,'0');e.firstObserved=e.observationTimes[0];e.lastObserved=e.observationTimes.at(-1);e.selectedRowIndex=e.rowIndices[Math.floor((e.rowIndices.length-1)/2)];e.selectedReadingId='detected_line_original_color';});return events;
  }
  function validResume(old){try{
    if(!old?.raw||!Array.isArray(old.raw.frames)||!Array.isArray(old.raw.rows)||!Array.isArray(old.events)||old.raw.frames.length!==old.total||old.processed!==old.total
      ||old.total<1||old.total>LIMITS.frames||old.raw.rows.length>LIMITS.totalRows)return false;
    const source=identity(old.sourceIdentity),prefix=source.kind==='local_file_sha256'?'file:'+source.sha256+':frame:':'task:'+source.intentId+':frame:';
    if(old.roleOwnership?.kind==='actual_local_file_sha256'&&old.roleOwnership.digest!==source.sha256)return false;
    if(old.roleOwnership?.kind==='internal_locked_source_identity_digest_not_video_hash'&&cueApi()?.sha256&&old.roleOwnership.digest!==cueApi().sha256(JSON.stringify(source)))return false;
    for(let i=0;i<old.raw.frames.length;i++){const f=old.raw.frames[i];if(f.frameIndex!==i||typeof f.frameId!=='string'||!f.frameId||!finite(f.time)||!shaPattern.test(f.sourcePixelSha256)||/^(?:file:|task:)/u.test(f.frameId)&&f.frameId!==prefix+i)return false;}
    for(let i=0;i<old.raw.rows.length;i++){const r=old.raw.rows[i],f=old.raw.frames[r.frameIndex],b=r.sourceRect;if(r.index!==i||!f||f.frameId!==r.frameId||f.time!==r.time||r.time!==r.frameTime
      ||!shaPattern.test(r.cropPixelsSha256)||typeof r.text!=='string'||!b||!['left','top','right','bottom'].every(k=>Number.isSafeInteger(b[k]))
      ||b.left<0||b.top<0||b.right>r.sourceWidth||b.bottom>r.sourceHeight||r.inputWidth!==b.right-b.left||r.inputHeight!==b.bottom-b.top||r.inputWidth<=0||r.inputHeight<=0)return false;}
    const roleRows=new Map();if(old.roleDecisions!==undefined){if(!Array.isArray(old.roleDecisions)||old.roleDecisions.length!==old.raw.rows.length)return false;
      for(const d of old.roleDecisions){if(!Number.isSafeInteger(d.rowIndex)||!old.raw.rows[d.rowIndex]||roleRows.has(d.rowIndex))return false;roleRows.set(d.rowIndex,d);}}
    else if(['195','196'].includes(old.engineBuild)&&(old.roleMappingCompatibility?.schema!=='legacy-missing-role-decisions-v195'
      ||old.roleMappingCompatibility.captionLaneEvidenceUnavailable!==true||old.events.some(e=>e.captionLaneId||e.roleEvidence)))return false;
    const seen=new Set(),eventIds=new Set();for(const e of old.events){if(typeof e.id!=='string'||!e.id||eventIds.has(e.id)||!['body','recovery','screen'].includes(e.layer)||!Array.isArray(e.rowIndices)||!e.rowIndices.length||!e.rowIndices.includes(e.selectedRowIndex)
      ||e.rowIndices.length!==e.frameIndices?.length||e.rowIndices.length!==e.observationTimes?.length||e.rowIndices.length!==e.frameIds?.length)return false;
      eventIds.add(e.id);if(e.firstObserved!==e.observationTimes[0]||e.lastObserved!==e.observationTimes.at(-1))return false;
      for(let i=0;i<e.rowIndices.length;i++){const r=old.raw.rows[e.rowIndices[i]],d=roleRows.get(r?.index);if(!r||seen.has(r.index)||e.frameIndices[i]!==r.frameIndex||e.frameIds[i]!==r.frameId||e.observationTimes[i]!==r.time
        ||r.text!==e.rawMobileText||e.text!==e.rawMobileText)return false;
        if(d){const layer=d.decision==='proposed_caption'?'body':d.decision==='visible_recovery_candidate'?'recovery':'screen';
          if(e.layer!==layer||e.familyId!==d.familyId||(e.captionLaneId||null)!==(d.captionLaneId||null))return false;}seen.add(r.index);}
      if(e.precision?.status==='read'&&!validRepresentative(e,old.raw.rows))return false;
      for(const p of e.nativeExpandedReads||[]){if(!e.rowIndices.includes(p.rowIndex)||!validExpanded(p,old.raw.rows[p.rowIndex],old.raw.frames[p.frameIndex],false,old.raw.rows))return false;}
      for(const g of e.nativeGlyphReceipts||[]){if(!validNativeGlyphReceipt(g,e,old.raw.rows,old.raw.frames))return false;}
      if(e.nativeExpansion?.status==='complete'&&!hasExpandedRead(e,old.raw.rows,old.raw.frames))return false;}
    if(old.raw.rows.some(r=>r.text.trim()&&!seen.has(r.index)))return false;
    if(old.phase==='extent_precision'){const jobs=old.events.filter(e=>e.layer!=='screen'),q=old.precisionCheckpoint;
      if(jobs.some(e=>!validRepresentative(e,old.raw.rows))||!q||!Array.isArray(q.completed)||!Array.isArray(q.pending)||q.pending.length
        ||new Set(q.completed).size!==q.completed.length||q.completed.length!==jobs.length||jobs.some(e=>!q.completed.includes(e.id)))return false;}
    if(old.extentPrecisionCheckpoint){const q=old.extentPrecisionCheckpoint,jobs=extentJobs(old),ids=new Set(jobs.map(e=>e.id)),done=new Set(),pending=new Set();
      if(!Number.isSafeInteger(q.total)||q.total!==jobs.length||!Number.isSafeInteger(q.processed)||!Array.isArray(q.completed)||!Array.isArray(q.skipped)||!Array.isArray(q.pending)||!Array.isArray(q.failed))return false;
      for(const id of q.completed){const e=jobs.find(e=>e.id===id);if(!e||done.has(id)||!hasExpandedRead(e,old.raw.rows,old.raw.frames)||old.engineBuild==='196'&&!hasGlyphAttempt(e,old.raw.rows,old.raw.frames))return false;done.add(id);}
      for(const entry of q.skipped){const e=jobs.find(e=>e.id===entry.eventId);if(!e||done.has(e.id)||!validSkippedExpansion(e,old.raw.rows)||expansionSkipReason(e)!==entry.reason)return false;done.add(e.id);}
      for(const id of q.pending){if(!ids.has(id)||done.has(id)||pending.has(id))return false;pending.add(id);}
      if(q.processed!==done.size||done.size+pending.size!==ids.size||jobs.some(e=>hasExpandedRead(e,old.raw.rows,old.raw.frames)&&(old.engineBuild!=='196'||hasGlyphAttempt(e,old.raw.rows,old.raw.frames))&&!done.has(e.id)||validSkippedExpansion(e,old.raw.rows)&&!done.has(e.id)))return false;}
    return true;
  }catch{return false;}}
  function adaptResult(result,options={}){
    const normalizer=simplified();
    const rows=result.raw.rows, frames=result.raw.frames, byFrame=new Map();
    for(const row of rows){if(!byFrame.has(row.frameIndex))byFrame.set(row.frameIndex,[]);byFrame.get(row.frameIndex).push(row);}
    result.observations=frames.map(f=>{const own=byFrame.get(f.frameIndex)||[],read=own.filter(r=>r.text.trim());return {index:f.frameIndex,time:f.time,frameId:f.frameId,
      frameIndex:f.frameIndex,accepted:read.length>0,text:read.map(r=>r.text).join('\n'),confidence:read.length?Math.min(...read.map(r=>r.confidence)):0,rowIndices:own.map(r=>r.index),
      status:f.status,meaning:'frame_has_read_text_not_verified_caption_role'};});
    const segment=e=>{const row=rows[e.selectedRowIndex],precision=e.precision?.status==='read'&&e.precision.reading?.text.trim()?e.precision:null,selection=selectActualReading(e,rows,frames),expanded=selection.expanded,glyph=glyphSelection(e,expanded,rows,frames),actual=selection.actual;
      return {id:e.id,...normalizer.normalize(actual.text),confidence:actual.confidence,firstObserved:e.firstObserved,lastObserved:e.lastObserved,start:e.firstObserved,end:e.lastObserved,
        observationIndices:[...new Set(e.frameIndices)],observationTimes:[...e.observationTimes],rowIndices:[...e.rowIndices],frameIds:[...e.frameIds],selectedRowIndex:e.selectedRowIndex,
        selectedReadingId:selection.kind,readingSelection:clone(selection.evidence),familyId:e.familyId,...(e.captionLaneId?{captionLaneId:e.captionLaneId}:{}),layer:e.layer,sourceIdentityKey:JSON.stringify(result.sourceIdentity),needsReview:true,...(expanded?{expandedEvidence:clone(expanded)}:{}),...(glyph?{glyphEvidenceReceipt:clone(glyph)}:{}),
        selectedActualReading:actual.text,criticalReadingStatus:criticalReadStatus(e,selection,rows,frames,result.sourceIdentity),selectedActualReadingReceipt:(()=>{const p=actualReceipt(e,selection,rows,frames);if(p)p.sourceIdentityKey=JSON.stringify(result.sourceIdentity);return p;})(),
        nativeSourceStyleReceipt:(()=>{const actualRow=rows[expanded?.rowIndex??row.index],v=(e.nativeSourceStyles||[]).find(v=>same(v.originatingReading,actual)&&v.rowIndex===actualRow.index&&v.frameId===actualRow.frameId&&v.nativeCropPixelsSha256===(expanded?.cropPixelsSha256||actualRow.cropPixelsSha256));return v?{schema:v.schema,policy:v.policy,evidenceSha256:v.evidenceSha256}:null;})(),
        protectedChange:signature(row.text)!==signature(actual.text),
        representativeOnly:true,rawMobileText:e.rawMobileText,readingChanged:actual.text!==row.text,
        candidateReadings:[{rowIndex:row.index,kind:'detected_line_original_color',reading:reading(row)},...(precision?[{rowIndex:row.index,kind:'precision_native_representative',reading:clone(precision.reading)}]:[]),...(e.nativeExpandedReads||[]).map(p=>({rowIndex:p.rowIndex,kind:'precision_native_expanded',reading:clone(p.reading),receipt:clone(p)}))]};};
    result.baselineSegments=result.events.filter(e=>e.layer==='body').map(segment);
    const projected=projectWorkingBody(result,result.baselineSegments);result.captionRoleProjections=projected.decisions;
    result.segments=cueApi()?.mergeWorkingCues?cueApi().mergeWorkingCues(projected.body,rows,{nativeApi:root.BrandbaiHighQualitySubtitles,events:result.events,frames,nativeSourceStyles:result.events.flatMap(e=>e.nativeSourceStyles||[])}):consolidate(projected.body,rows);
    if(gapApi()?.mergeNonCriticalProjectedSpans)result.segments=gapApi().mergeNonCriticalProjectedSpans(result.segments,rows,{nativeApi:root.BrandbaiHighQualitySubtitles,frames});
    if(gapApi()?.composeWorkingLines)result.segments=gapApi().composeWorkingLines(result.segments,rows);
    applyWorkingPresentation(result,options);
    result.captionRecovery=consolidate(result.events.filter(e=>e.layer==='recovery').map(segment),rows);result.screenText=[...result.events.filter(e=>e.layer==='screen').map(segment),...projected.diverted];
    result.consolidatedSegments=result.segments.filter(s=>s.merged||s.presentationMemberCount>1).length;
    result.rowFrameMap=rows.map(r=>({rowIndex:r.index,frameIndex:r.frameIndex,frameId:r.frameId,time:r.time}));result.reviewSegments=result.segments.filter(s=>s.readingChanged||s.confidence<85).length;
    result.emptyFrames=frames.filter(f=>!(byFrame.get(f.frameIndex)||[]).some(r=>r.text.trim())).length;
    result.uncertainFrames=frames.filter(f=>f.status!=='observed'||f.detectorStatus!=='complete').length;
    result.normalizationPolicy=normalizer.POLICY;result.normalizationComplete=true;result.readingSelectionPolicy={...READ_SELECTION};
    result.outputPolicy='clean-business-text-v200';
    result.viewRevision=(Number.isSafeInteger(result.viewRevision)?result.viewRevision:0)+1;
    return result;
  }
  class Session extends (root.BrandbaiSubtitles?.Session||class{}) {
    constructor(options){super({...options,region:FULL});simplified();this.options=options;this.worker=null;this.precisionWorker=null;this.precisionUses=0;this.precisionRecoveries=0;this.precisionWorkerLoading=null;this.workerLoads=new Set();this.retiringWorkers=new Set();this.scanWorkers=new Set();this.scanInferencePromises=new Set();this.crops=new Map();this.expandedCache=new Map();this.cropBytes=0;this.roleStyles=new Map();this.nativePixelsCache=options.nativePixelsCache===true?new NativePixelsCache(options.nativePixelsCacheBytes):null;
      this.paused=false;this.cancelled=false;this.finished=false;this.controller=new AbortController();this.resumeSignal=null;this.pauseRevision=0;
      const sourceIdentity=identity(options.sourceIdentity);
      this.result={state:'ready',source:'screen_ocr',accuracy:'machine_unverified',engine:'PP-OCRv5-mobile + PP-OCRv6_medium_rec',engineBuild:'196',pipelineId:PIPELINE,
        readingPolicy:'native-detected-line-source-role-v199-precision-opencc-t2s-v194-native-expanded-v195-owned-glyph-v196-progressive-work-v199',candidateIteration:'199',skipLegacyFinalize:true,sourceIdentity,processed:0,total:0,interval:.5,region:{...FULL},phase:'frames',
        observations:[],segments:[],captionRecovery:[],screenText:[],events:[],rowFrameMap:[],raw:{frames:[],rows:[]},precisionCheckpoint:{completed:[],pending:[],failed:[]},
        qualityVerified:false,roleConfirmed:false,canContinue:false,reviewSegments:0,uncertainFrames:0,emptyFrames:0,variationSegments:0,variationFrames:0,consolidatedSegments:0};
      if(options.resumeResult){const old=options.resumeResult;if(old.pipelineId!==PIPELINE||!same(identity(old.sourceIdentity),sourceIdentity)||!['precision','extent_precision'].includes(old.phase)||!old.canContinue||!validResume(old))throw Error('保存记录不属于当前视频或不能继续');
        this.result=clone(old);if(old.roleDecisions===undefined&&!old.roleMappingCompatibility)this.result.roleMappingCompatibility={schema:'legacy-missing-role-decisions-v195',sourceEngineBuild:String(old.engineBuild||'unknown'),captionLaneEvidenceUnavailable:true};
        if(old.engineBuild!=='196'&&old.extentPrecisionCheckpoint){this.result.legacyExtentPrecisionCheckpoint=clone(old.extentPrecisionCheckpoint);const jobs=extentJobs(this.result),completed=jobs.filter(e=>hasGlyphAttempt(e,this.result.raw.rows,this.result.raw.frames)).map(e=>e.id);
          this.result.extentPrecisionCheckpoint={total:jobs.length,processed:completed.length,completed,skipped:[],pending:jobs.filter(e=>!completed.includes(e.id)).map(e=>e.id),failed:clone(old.extentPrecisionCheckpoint.failed||[])};}
        this.result.state='ready';this.result.error=null;this.result.canContinue=false;this.result.skipLegacyFinalize=true;this.result.engineBuild='196';this.result.engine='PP-OCRv5-mobile + PP-OCRv6_medium_rec';this.result.candidateIteration='199';this.result.readingPolicy='native-detected-line-source-role-v199-precision-opencc-t2s-v194-native-expanded-v195-owned-glyph-v196-progressive-work-v199';adaptResult(this.result);}
      this.result.workerRuntime={schema:'subtitle-worker-runtime-v199',precisionCallLimit:LIMITS.precisionBatch,precisionRecoveryLimit:LIMITS.precisionRecoveries,precisionWorkerCreates:0,precisionCalls:0,recoveryAttempts:[],cleanupFailures:0};
      this.result.runtimeTiming={schema:'subtitle-local-phase-timing-v199',scope:'this_session_invocation_excludes_export',phaseMs:{},phaseCalls:{},totalMs:0};
    }
    async timedPhase(name,operation){const start=Date.now();try{return await operation();}finally{const t=this.result.runtimeTiming;t.phaseMs[name]=(t.phaseMs[name]||0)+Math.max(0,Date.now()-start);t.phaseCalls[name]=(t.phaseCalls[name]||0)+1;}}
    async timedDetail(name,operation){const start=Date.now();try{return await operation();}finally{const t=this.result.runtimeTiming;t.detailMs??={};t.detailCalls??={};t.detailMs[name]=(t.detailMs[name]||0)+Math.max(0,Date.now()-start);t.detailCalls[name]=(t.detailCalls[name]||0)+1;if(this.nativePixelsCache)t.nativePixelsCache=this.nativePixelsCache.summary();}}
    progressSummary(){const r=this.result;return Object.freeze({state:r.state,phase:r.phase,processed:r.processed,total:r.total,viewRevision:r.viewRevision||0,
      bodyCount:r.segments.length,recoveryCount:r.captionRecovery.length,processingComplete:r.processingComplete===true,canContinue:r.canContinue===true});}
    emit(){if(typeof this.options.onProgressSummary==='function')this.options.onProgressSummary(this.progressSummary());else this.options.onProgress?.(clone(this.result));}
    async stopWorker(){const workers=[...new Set([this.worker,this.precisionWorker,...this.scanWorkers,...this.retiringWorkers].filter(Boolean))];this.worker=this.precisionWorker=null;this.scanWorkers.clear();this.precisionUses=0;for(const controller of this.workerLoads)controller.abort();const closed=await Promise.all(workers.map(w=>Promise.resolve().then(()=>w.terminate()).then(()=>{this.retiringWorkers.delete(w);return true;},()=>{this.retiringWorkers.add(w);return false;})));this.result.workerRuntime.cleanupFailures+=closed.filter(value=>!value).length;return closed.every(Boolean);}
    async bounded(factory,ms,label,signal=this.controller.signal){let timer,abort;try{
      const value=await Promise.race([Promise.resolve().then(()=>{if(signal.aborted)throw Error('已停止提取');return factory();}),new Promise((_,reject)=>timer=setTimeout(()=>reject(Error(label)),ms)),new Promise((_,reject)=>{abort=()=>reject(Error('已停止提取'));signal.addEventListener('abort',abort,{once:true});if(signal.aborted)abort();})]);
      if(signal.aborted)throw Error('已停止提取');return value;
    }finally{clearTimeout(timer);if(abort)signal.removeEventListener('abort',abort);}}
    async createWorker(){const factory=this.options.workerFactory||root.BrandbaiCreateSubtitleRecognizer,signal=this.controller.signal,controller=new AbortController(),abort=()=>controller.abort();let w,p,discarded=false;
      this.workerLoads.add(controller);signal.addEventListener('abort',abort,{once:true});if(signal.aborted)abort();
      const terminate=value=>Promise.resolve().then(()=>value.terminate()).catch(()=>{});
      try{p=Promise.resolve().then(()=>{if(controller.signal.aborted)throw Error('已停止提取');return factory('chi_sim+eng',1,{workerPath:new URL('vendor/worker.min.js',this.options.baseUrl).href,signal:controller.signal});});
        // A factory that ignores abort may settle after the timeout or stop.
        p.then(value=>{if(discarded||controller.signal.aborted||this.cancelled||this.finished)return terminate(value);}).catch(()=>{});
        w=await this.bounded(()=>p,90000,'本地识别器准备超时',controller.signal);await this.bounded(()=>w.setParameters({tessedit_pageseg_mode:'7'}),15000,'识别器设置超时',controller.signal);
        if(controller.signal.aborted||this.cancelled||this.finished)throw Error('已停止提取');return w;
      }catch(error){discarded=true;controller.abort();if(w)await terminate(w);throw error;}
      finally{this.workerLoads.delete(controller);signal.removeEventListener('abort',abort);}}
    async sample(time,internal={}){const {frameProvider,video}=this.options;if(internal.skipPausedCheckpoint===true)this.scanAbortCheck();else await this.checkpoint();let sampled;
      if(frameProvider)sampled=await this.bounded(()=>api().providerFrame(frameProvider,time,FULL,this.controller.signal),15000,'视频画面读取超时');
      else {video.pause();video.muted=true;await api().seek(video,time,this.controller.signal);const c=canvas(video.videoWidth,video.videoHeight);c.getContext('2d').drawImage(video,0,0);sampled={canvas:c,time:video.currentTime};}
      const c=sampled.canvas,w=frameProvider?.width||video?.videoWidth,h=frameProvider?.height||video?.videoHeight;
      if(c.width!==w||c.height!==h||!finite(sampled.time)||Math.abs(sampled.time-time)>.12)throw Error('画面尺寸或时间与当前视频不对应');
      if(frameProvider)await api().validateProvider(frameProvider,this.controller.signal);return sampled;}
    cropCacheBinding(row){const frame=this.result.raw.frames[row?.frameIndex],source=identity(this.result.sourceIdentity),b=row?.sourceRect,prefix=source.kind==='local_file_sha256'?'file:'+source.sha256+':frame:':'task:'+source.intentId+':frame:';
      if(!row||!frame||!Number.isSafeInteger(row.index)||row.index<0||!Number.isSafeInteger(row.frameIndex)||row.frameIndex<0||row.frameId!==prefix+row.frameIndex||frame.frameId!==row.frameId||frame.frameIndex!==row.frameIndex||frame.time!==row.time||row.frameTime!==row.time||!finite(row.time)||!shaPattern.test(frame.sourcePixelSha256)||!shaPattern.test(row.cropPixelsSha256)
        ||!b||!['left','top','right','bottom'].every(k=>Number.isSafeInteger(b[k]))||![row.sourceWidth,row.sourceHeight,row.inputWidth,row.inputHeight].every(n=>Number.isSafeInteger(n)&&n>0)||b.left<0||b.top<0||b.right>row.sourceWidth||b.bottom>row.sourceHeight||b.right-b.left!==row.inputWidth||b.bottom-b.top!==row.inputHeight)return null;
      return JSON.stringify([source,row.index,row.frameIndex,row.frameId,row.time,frame.sourcePixelSha256,row.sourceWidth,row.sourceHeight,b.left,b.top,b.right,b.bottom,row.inputWidth,row.inputHeight,row.cropPixelsSha256]);}
    async keepCrop(row,c,nativePixels){if(this.nativePixelsCache){const image=nativePixels?{data:nativePixels.data||nativePixels,width:c.width,height:c.height}:c.getContext('2d').getImageData(0,0,c.width,c.height);await this.nativePixelsCache.put(this.cropCacheBinding(row),image,row.cropPixelsSha256);}
      // PNG remains the independently decodable fallback after eviction or
      // interruption. Cache residency is never a prerequisite for recovery.
      let blob;if(typeof c.convertToBlob==='function')blob=await c.convertToBlob({type:'image/png'});else blob=await new Promise((resolve,reject)=>{let timer=setTimeout(()=>reject(Error('原生画面保存超时')),5000);c.toBlob(b=>{clearTimeout(timer);b?resolve(b):reject(Error('原生画面保存失败'));},'image/png');});
      if(this.cropBytes+blob.size<=LIMITS.cropBytes){this.crops.set(row.index,blob);this.cropBytes+=blob.size;}else this.result.cropMemoryLimitReached=true;}
    measureRoleStyle(row,c,read=reading(row)){const frame=this.result.raw.frames[row.frameIndex],image=c.getContext('2d').getImageData(0,0,c.width,c.height);return roleStyleApi()?.analyzeNativeCrop({...image,data:image.data,width:c.width,height:c.height,frameId:row.frameId,frameIndex:row.frameIndex,time:row.time,sourceWidth:row.sourceWidth,sourceHeight:row.sourceHeight,parentPixelsSha256:frame.sourcePixelSha256,cropPixelsSha256:row.cropPixelsSha256},read,row.sourceRect)||null;}
    keepRoleStyle(event,kind,read,row,c,box=row.sourceRect,hash=row.cropPixelsSha256){if(!roleStyleApi())return;const image=c.getContext('2d').getImageData(0,0,c.width,c.height),frame=this.result.raw.frames[row.frameIndex],style=roleStyleApi().analyzeNativeCrop({data:image.data,width:c.width,height:c.height,frameId:row.frameId,frameIndex:row.frameIndex,time:row.time,sourceWidth:row.sourceWidth,sourceHeight:row.sourceHeight,parentPixelsSha256:frame.sourcePixelSha256,cropPixelsSha256:hash},read,box);event.nativeRoleStyles??=[];event.nativeRoleStyles.push({kind,reading:clone(read),style});}
    async cropFor(row){let c;const owned=this.nativePixelsCache&&await this.nativePixelsCache.get(this.cropCacheBinding(row),row.cropPixelsSha256);
      if(owned){c=canvas(owned.width,owned.height);const context=c.getContext('2d'),image=context.createImageData(owned.width,owned.height);image.data.set(owned.data);context.putImageData(image,0,0);}
      else if(this.crops.has(row.index)){const image=await root.createImageBitmap(this.crops.get(row.index));try{c=canvas(image.width,image.height);c.getContext('2d').drawImage(image,0,0);}finally{image.close();}}
      else{const sample=await this.sample(row.time),pixels=sample.canvas.getContext('2d').getImageData(0,0,sample.canvas.width,sample.canvas.height),hash=await digest(pixels.data),frame=this.result.raw.frames[row.frameIndex];
        if(hash!==frame.sourcePixelSha256||Math.abs(sample.time-row.time)>.005)throw Error('这次画面与已保存记录不相同，已有文字已保留');c=crop(sample.canvas,row.sourceRect);}
      if(c.width!==row.inputWidth||c.height!==row.inputHeight||await digest(c.getContext('2d').getImageData(0,0,c.width,c.height).data)!==row.cropPixelsSha256)throw Error('字幕原图校验不一致');return c;}
    async expandedCropFor(row,box){const sampled=await this.sample(row.time),full=sampled.canvas,frame=this.result.raw.frames[row.frameIndex];
      const parentPixelsSha256=await digest(full.getContext('2d').getImageData(0,0,full.width,full.height).data);
      if(parentPixelsSha256!==frame.sourcePixelSha256||Math.abs(sampled.time-row.time)>.005)throw Error('扩展字幕画面与原记录不一致，已保留原始文字');
      const original=crop(full,row.sourceRect);if(await digest(original.getContext('2d').getImageData(0,0,original.width,original.height).data)!==row.cropPixelsSha256)throw Error('扩展字幕原框校验不一致');
      return {canvas:crop(full,box),parentPixelsSha256};}
    async precisionWorkerReady(){if(this.precisionWorker&&this.precisionUses<LIMITS.precisionBatch)return this.precisionWorker;if(this.precisionWorkerLoading)return this.precisionWorkerLoading;
      const loading=(async()=>{if(!await this.stopWorker())throw Error('识别器清理失败，已有文字已保留');const worker=await this.createWorker();if(this.controller.signal.aborted||this.cancelled||this.finished){await Promise.resolve().then(()=>worker.terminate()).catch(()=>{});throw Error('已停止提取');}this.precisionWorker=worker;this.precisionUses=0;this.result.workerRuntime.precisionWorkerCreates++;return worker;})();
      this.precisionWorkerLoading=loading;try{return await loading;}finally{if(this.precisionWorkerLoading===loading)this.precisionWorkerLoading=null;}}
    async withPrecision(factory){for(;;){await this.checkpoint();try{const worker=await this.precisionWorkerReady(),output=await factory(worker);if(this.controller.signal.aborted||this.cancelled)throw Error('已停止提取');this.precisionUses++;this.result.workerRuntime.precisionCalls++;return output;}
        catch(error){const released=await this.stopWorker();if(!released||this.controller.signal.aborted||this.cancelled||this.finished||this.precisionRecoveries>=LIMITS.precisionRecoveries||!RECOVERABLE_PRECISION_ERRORS.has(error?.message))throw error;
          this.precisionRecoveries++;this.result.workerRuntime.recoveryAttempts.push({attempt:this.precisionRecoveries,reason:errorText(error),previousWorkerTerminated:true});await this.saveCheckpoint();this.emit();}}
    }
    async deriveGlyphReceipt(event,p){const selected=selectedForGlyph(event,this.result.raw.rows,this.result.raw.frames);if(!selected)throw Error('字形取证缺少有效原生读数');p=selected;if(hasGlyphAttempt(event,this.result.raw.rows,this.result.raw.frames))return;
      if(!this.options.video&&!this.options.frameProvider){event.nativeGlyphStatus={status:'not_attempted',reason:'native_parent_source_unavailable'};return;}
      const row=this.result.raw.rows[p.rowIndex],sampled=await this.expandedCropFor(row,p.sourceRect),c=sampled.canvas,image=c.getContext('2d').getImageData(0,0,c.width,c.height);
      if(await digest(image.data)!==p.cropPixelsSha256)throw Error('字形取证原图与补读回执不一致');
      const g=nativeGlyphReceipt(p,ownedGlyphEvidence(image,p.reading));if(!validNativeGlyphReceipt(g,event,this.result.raw.rows,this.result.raw.frames))throw Error('字形取证原生回执无效');
      event.nativeGlyphReceipts??=[];event.nativeGlyphReceipts.push(g);event.nativeGlyphStatus={status:'complete',policy:OWNED_GLYPHS.receiptSchema,newOcrCalls:0};adaptResult(this.result);
    }
    async expandEvent(event){
      if(event.layer!=='body')return;
      if(hasExpandedRead(event,this.result.raw.rows,this.result.raw.frames)){const p=selectedForGlyph(event,this.result.raw.rows,this.result.raw.frames);await this.deriveGlyphReceipt(event,p);return;}
      if(event.nativeExpansion?.status==='complete')throw Error('补读保存记录缺少有效原生回执');
      // Saved records can still be inspected without reopening their video.
      // Additional actual reads require a current native source provider.
      if(!this.options.video&&!this.options.frameProvider){event.nativeExpansion={status:'not_attempted',reason:'native_parent_source_unavailable'};return;}
      const row=this.result.raw.rows[event.selectedRowIndex],box=expandedRect(row,this.result.raw.rows);
      if(!box){event.nativeExpansion={status:'not_attempted',reason:'bounded_single_lane_expansion_ambiguous'};return;}
      const frame=this.result.raw.frames[row.frameIndex],key=JSON.stringify([identity(this.result.sourceIdentity),row.index,row.frameIndex,row.frameId,row.time,frame.sourcePixelSha256,row.cropPixelsSha256,row.sourceRect,box,PRECISION_MODEL.modelSha256]);
      let cached=this.expandedCache.get(key),cacheReused=Boolean(cached),ownedSample=null;
      if(!cached){const sampled=await this.expandedCropFor(row,box),c=sampled.canvas,image=c.getContext('2d').getImageData(0,0,c.width,c.height),start=Date.now();
        ownedSample=sampled;
        const output=await this.withPrecision(worker=>this.bounded(()=>worker.recognizePrecision(c),90000,'扩展字幕精读暂时超时，原始文字已保留，可继续'));
        if(output.modelId!==PRECISION_MODEL.modelId||output.modelSha256!==PRECISION_MODEL.modelSha256)throw Error('扩展精读模型来源不符');
        const read=reading(output);cached={reading:read,glyphEvidence:glyphEvidence(image,read),ownedEvidence:ownedGlyphEvidence(image,read),cropPixelsSha256:await digest(image.data),parentPixelsSha256:sampled.parentPixelsSha256,elapsedMs:Date.now()-start};this.expandedCache.set(key,cached);
      }
      const {ownedEvidence,...legacyCached}=cached;
      const record={schema:EXPANSION.schema,status:'read',rowIndex:row.index,frameIndex:row.frameIndex,frameId:row.frameId,time:row.time,sourceWidth:row.sourceWidth,sourceHeight:row.sourceHeight,
        originalSourceRect:clone(row.sourceRect),originalCropPixelsSha256:row.cropPixelsSha256,sourceRect:box,inputWidth:box.right-box.left,inputHeight:box.bottom-box.top,
        interpolation:'none_integer_1_to_1',nativeOriginalColor:true,secondSeekSourceVerified:true,modelId:PRECISION_MODEL.modelId,modelSha256:PRECISION_MODEL.modelSha256,
        ...clone(legacyCached),cacheReused};
      if(!validExpanded(record,row,frame,false,this.result.raw.rows))throw Error('扩展字幕精读回执无效');
      event.nativeExpandedReads??=[];event.nativeExpandedReads.push(record);event.nativeExpansion={status:'complete',policy:EXPANSION.schema,actualCalls:cacheReused?0:1};
      const g=nativeGlyphReceipt(record,ownedEvidence);if(!validNativeGlyphReceipt(g,event,this.result.raw.rows,this.result.raw.frames))throw Error('字形取证原生回执无效');
      event.nativeGlyphReceipts??=[];event.nativeGlyphReceipts.push(g);event.nativeGlyphStatus={status:'complete',policy:OWNED_GLYPHS.receiptSchema,newOcrCalls:0};
      if(roleStyleApi()){const sampled=ownedSample||await this.expandedCropFor(row,box),c=sampled.canvas;if(sampled.parentPixelsSha256!==record.parentPixelsSha256||c.width!==record.inputWidth||c.height!==record.inputHeight||await digest(c.getContext('2d').getImageData(0,0,c.width,c.height).data)!==record.cropPixelsSha256)throw Error('扩展字幕样式原图与补读回执不一致');
        this.keepRoleStyle(event,'precision_native_expanded',record.reading,row,c,box,record.cropPixelsSha256);}
      // The extent queue and its actual receipt are persisted atomically by
      // extentPrecision; no intermediate checkpoint can self-report completion.
      adaptResult(this.result);
    }
    scanAbortCheck(){if(this.controller.signal.aborted||this.cancelled||this.finished)throw Error('已停止提取');}
    async scanCheckpoint(){this.scanAbortCheck();
      // A paused online UI may release its player lease in checkpoint(). Let
      // both existing computations drain before that callback, never invoke it
      // from inside an inference task (which would wait on itself).
      if(this.paused&&this.scanInferencePromises.size)await Promise.all([...this.scanInferencePromises].map(p=>p.catch(()=>{})));
      this.scanAbortCheck();await this.checkpoint();this.scanAbortCheck();}
    async validateScanSource(key,phase){this.scanAbortCheck();if(JSON.stringify(identity(this.result.sourceIdentity))!==key)throw Error('视频来源已变化，已有文字已保留');
      if(this.options.frameProvider)await this.timedDetail('scan_'+phase+'_source_validation',()=>this.bounded(()=>api().validateProvider(this.options.frameProvider,this.controller.signal),15000,'视频来源核验超时'));
      this.scanAbortCheck();if(JSON.stringify(identity(this.result.sourceIdentity))!==key)throw Error('视频来源已变化，已有文字已保留');}
    async prepareScanFrame(index,time,key){await this.validateScanSource(key,'prepare');const runtime=this.result.runtimeTiming.scanQueue;
      runtime.activeSeeks++;runtime.maximumConcurrentSeeks=Math.max(runtime.maximumConcurrentSeeks,runtime.activeSeeks);let sampled;
      try{sampled=await this.timedDetail('scan_sample',()=>this.sample(time,{skipPausedCheckpoint:true}));}finally{runtime.activeSeeks--;}
      this.scanAbortCheck();const source=identity(this.result.sourceIdentity),frameId=source.kind==='local_file_sha256'?'file:'+source.sha256+':frame:'+index:'task:'+source.intentId+':frame:'+index;
      // A provider may reuse a canvas on the next getFrame(). Own one native
      // copy for each bounded slot; callbacks never see that inference canvas.
      const full=canvas(sampled.canvas.width,sampled.canvas.height);full.getContext('2d').drawImage(sampled.canvas,0,0);
      if(index===0){this.result.sourceVideoWidth=full.width;this.result.sourceVideoHeight=full.height;}
      if(full.width!==this.result.sourceVideoWidth||full.height!==this.result.sourceVideoHeight)throw Error('视频画面尺寸发生变化');
      const sourcePixelSha256=await this.timedDetail('scan_parent_hash',()=>digest(full.getContext('2d').getImageData(0,0,full.width,full.height).data));
      if(this.options.onFrame){const view=canvas(full.width,full.height);view.getContext('2d').drawImage(full,0,0);await this.timedDetail('scan_frame_callback',()=>this.options.onFrame({frameIndex:index,frameId,time:sampled.time,canvas:view}));}
      else await this.timedDetail('scan_frame_callback',()=>{});
      await this.validateScanSource(key,'prepare');runtime.prepared++;runtime.inFlight++;runtime.peakInFlight=Math.max(runtime.peakInFlight,runtime.inFlight);
      return {index,frameId,time:sampled.time,sourceIdentityKey:key,sourcePixelSha256,full};}
    async inferScanFrame(payload,worker){this.scanAbortCheck();const {full,frameId,time}=payload;
      const detection=await this.timedDetail('scan_detect',()=>this.bounded(()=>worker.detectLines(full,{frameId,time,maxSide:1280}),90000,'画面文字区域读取超时'));
      if(detection.frameId!==frameId||detection.time!==time||detection.sourceWidth!==full.width||detection.sourceHeight!==full.height||detection.sourcePixelSha256!==payload.sourcePixelSha256||!shaPattern.test(detection.sourcePixelSha256))throw Error('检测画面来源不一致');
      const ordered=[...detection.candidates].sort((a,b)=>a.sourceBBox.top-b.sourceBBox.top||a.sourceBBox.left-b.sourceBBox.left);if(ordered.length>LIMITS.rowsPerFrame)throw Error('此帧文字区域过多，已保存此前结果');
      const rows=[];for(const candidate of ordered){this.scanAbortCheck();const b=rect(candidate,full.width,full.height);if(!b)continue;
        const c=crop(full,b),read=reading(await this.timedDetail('scan_mobile',()=>this.bounded(()=>worker.recognize(c),30000,'字幕原图读取超时'))),pixels=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
        // Retain compact metadata, not up to 128 additional crop canvases and
        // RGBA buffers per slot. The private parent is retained and recropped
        // at ordered commit with an exact SHA check; no candidate is skipped.
        rows.push({candidate,sourceRect:b,read,cropPixelsSha256:await this.timedDetail('scan_crop_hash',()=>digest(pixels))});}
      this.scanAbortCheck();return {detection,rows};}
    async commitScanFrame(payload,inferred,index,key){await this.validateScanSource(key,'commit');const {full,frameId,time}=payload,{detection,rows}=inferred;
      if(payload.index!==index||payload.sourceIdentityKey!==key||this.result.raw.frames.length!==index||payload.sourcePixelSha256!==detection.sourcePixelSha256||frameId!==(this.result.sourceIdentity.kind==='local_file_sha256'?'file:'+this.result.sourceIdentity.sha256+':frame:'+index:'task:'+this.result.sourceIdentity.intentId+':frame:'+index))throw Error('字幕队列画面归属不一致');
      const frame={frameIndex:index,frameId,time,status:'uncertain',detectorStatus:detection.status,sourcePixelSha256:detection.sourcePixelSha256,detectedRegions:detection.candidates.length,completeTextExtentKnown:false};
      this.result.raw.frames.push(frame);this.result.observations.push({index,time,frameId,frameIndex:index,accepted:false,text:'',confidence:0,rowIndices:[]});
      for(const staged of rows){await this.scanCheckpoint();if(this.result.raw.rows.length>=LIMITS.totalRows)throw Error('本次文字量达到处理上限，已保存已有结果');const {candidate,sourceRect:b,read,cropPixelsSha256}=staged,c=crop(full,b),pixels=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
        if(await this.timedDetail('scan_commit_crop_reverify',()=>digest(pixels))!==cropPixelsSha256)throw Error('字幕队列原生裁剪像素已变化');
        const row={index:this.result.raw.rows.length,frameIndex:index,frameId,time,frameTime:time,sourceWidth:full.width,sourceHeight:full.height,sourceRect:b,inputWidth:c.width,inputHeight:c.height,
          detectorCandidateId:candidate.id,detectorScore:candidate.score,complete:false,completenessStatus:'detector_proposal_not_full_line_certificate',...read,
          selectedReadingId:'detected_line_original_color',alternatives:[],cropPixelsSha256,cropReceipt:{schema:'source-rect-native-crop-v190',frameId,time,sourceRect:{...b},inputWidth:c.width,inputHeight:c.height,interpolation:'none_integer_1_to_1'}};
        this.result.raw.rows.push(row);if(row.text.trim()&&c.height>=12&&c.height<=Math.min(256,full.height*.15))this.roleStyles.set(row.index,await this.timedDetail('scan_style',()=>this.measureRoleStyle(row,c)));await this.timedDetail('scan_crop_save',()=>this.keepCrop(row,c,pixels));await this.timedDetail('scan_line_callback',()=>this.options.onLineReading?.({row:clone(row),canvas:c}));}
      frame.status='observed';this.result.processed++;this.result.runtimeTiming.scanQueue.committed++;this.result.runtimeTiming.scanQueue.inFlight--;await this.timedDetail('scan_projection',()=>adaptResult(this.result));this.emit();}
    async scan(){const {video,frameProvider}=this.options,duration=frameProvider?.duration||video?.duration,times=api().sampleTimes(duration,.5);if(times.length>LIMITS.frames)throw Error('本次视频超过处理范围');
      const capacity=this.options.scanConcurrency===2?2:1,queue=root.BrandbaiSubtitleFrameQueueV201,key=JSON.stringify(identity(this.result.sourceIdentity)),workers=[],active=new Map();
      if(capacity===2&&typeof queue?.runOrderedFrames!=='function')throw Error('字幕并行处理模块未就绪');
      this.result.videoDuration=duration;this.result.total=times.length;const runtime=this.result.runtimeTiming.scanQueue={schema:'bounded-native-frame-scan-v201',configuredCapacity:capacity,workerCreates:0,peakInFlight:0,prepared:0,committed:0,inFlight:0,activeSeeks:0,maximumConcurrentSeeks:0,maximumCallsPerWorker:0,operationTimingScope:'per_operation_sum_can_overlap_between_two_independent_workers',samplingInterval:.5,orderedCommit:true};
      const run=(payload,slot)=>{const worker=workers[slot],count=(active.get(worker)||0)+1;active.set(worker,count);runtime.maximumCallsPerWorker=Math.max(runtime.maximumCallsPerWorker,count);if(count>1)throw Error('同一识别器不能并行读取');
        const pending=this.inferScanFrame(payload,worker);this.scanInferencePromises.add(pending);return pending.finally(()=>{this.scanInferencePromises.delete(pending);active.set(worker,(active.get(worker)||1)-1);});};
      const cleanup=async()=>{runtime.inFlight=0;if(!await this.stopWorker())throw Error('识别器清理失败，已有文字已保留');};
      try{for(let slot=0;slot<capacity;slot++){const w=await this.timedDetail('scan_worker_init',()=>this.createWorker());if(workers.includes(w))throw Error('本地识别器未独立准备');this.scanWorkers.add(w);workers.push(w);runtime.workerCreates++;if(slot===0)this.worker=w;if(typeof w.detectLines!=='function')throw Error('完整字幕行检测模块不可用');}
        if(capacity===2)await queue.runOrderedFrames({count:times.length,capacity,signal:this.controller.signal,checkpoint:()=>this.scanCheckpoint(),prepare:index=>this.prepareScanFrame(index,times[index],key),run,commit:(payload,inferred,index)=>this.commitScanFrame(payload,inferred,index,key),cleanup});
        else{for(let index=0;index<times.length;index++){await this.scanCheckpoint();const payload=await this.prepareScanFrame(index,times[index],key),inferred=await run(payload,0);await this.scanCheckpoint();await this.commitScanFrame(payload,inferred,index,key);}await cleanup();}
        this.result.phase='roles';
      }finally{await this.stopWorker();runtime.inFlight=0;}
    }
    async roles(){
      // V7's legacy SHA-shaped key is ONLY an internal ownership namespace for
      // locked live sources; never exported as a file/content SHA.
      const realFile=this.result.sourceIdentity.kind==='local_file_sha256',key=realFile?this.result.sourceIdentity.sha256:await digest(new TextEncoder().encode(JSON.stringify(this.result.sourceIdentity)));
      this.result.roleOwnership={kind:realFile?'actual_local_file_sha256':'internal_locked_source_identity_digest_not_video_hash',digest:key};
      let selection;
      try{if(!roleApi()?.selectNative)throw Error('角色模块未加载');selection=roleApi().selectNative({sourceSha256:key,videoDuration:this.result.videoDuration,total:this.result.total,processed:this.result.processed,
        sourceVideoWidth:this.result.sourceVideoWidth,sourceVideoHeight:this.result.sourceVideoHeight,frames:this.result.raw.frames,rows:this.result.raw.rows});
        const roleInput={sourceSha256:key,videoDuration:this.result.videoDuration,total:this.result.total,processed:this.result.processed,sourceVideoWidth:this.result.sourceVideoWidth,sourceVideoHeight:this.result.sourceVideoHeight,frames:this.result.raw.frames,rows:this.result.raw.rows};
        this.result.roleDecisions=mapRoles(selection,this.result.raw.rows,roleInput);
        this.result.roleAnalysis={status:selection.status,policy:clone(selection.policy),arithmeticPolicy:selection.arithmeticPolicy,analysisComplete:selection.roleGraphAnalysisComplete===true,
          samplingComplete:selection.samplingPlanComplete===true,reasons:clone(selection.roleGraphAnalysisReasons||[]),allRowsRetained:true,semanticTruthVerified:false,
          ...(selection.anchorCompetition?{anchorCompetition:clone(selection.anchorCompetition)}:{}),
          ...(selection.roleRevisionAudit?{roleRevisionAudit:clone(selection.roleRevisionAudit)}:{}),
          localRoleDecisionUsable:selection.localRoleDecisionUsable===true,
          ...(selection.localRoleAnalysis?{localRoleAnalysis:clone(selection.localRoleAnalysis)}:{}),
          ...(selection.captionLanePolicy?{captionLanePolicy:clone(selection.captionLanePolicy),captionLaneAnalysisComplete:selection.captionLaneAnalysisComplete===true,
            captionLaneAnalysisReasons:clone(selection.captionLaneAnalysisReasons||[]),captionLaneEvidenceCount:selection.captionLaneEvidence?.length||0,
            captionLaneAssignedRows:this.result.roleDecisions.filter(d=>d.captionLaneId).length,captionLaneInheritedRows:this.result.roleDecisions.filter(d=>d.previousLaneDecision).length}:{} )};
      }catch(e){this.result.roleDecisions=fallbackRoles(this.result.raw.rows,'role_analysis_unavailable');this.result.roleAnalysis={status:'unresolved',analysisComplete:false,allRowsRetained:true,error:String(e.message||e)};}
      if(root.BrandbaiSubtitleNativeShortSlotV199?.propose){const slots=root.BrandbaiSubtitleNativeShortSlotV199.propose({rows:this.result.raw.rows,frames:this.result.raw.frames,roleDecisions:this.result.roleDecisions,sourceIdentity:this.result.sourceIdentity,styles:this.roleStyles});this.result.roleAnalysis.nativeShortSlots=clone(slots);for(const p of slots.rowEvidence){const d=this.result.roleDecisions.find(v=>v.rowIndex===p.rowIndex);if(d?.decision==='retained_other_or_uncertain'){d.previousNativeSlotRoleDecision=clone(d);d.decision='proposed_caption';d.reason=p.reason;d.captionLaneId=p.captionLaneId;d.roleEvidence={...(d.roleEvidence||{}),nativeShortSlot:clone(p)};}}}
      if(roleStyleApi()){this.result.captionStyleTrack=roleStyleApi().deriveTrack(this.result.raw.rows.map(r=>({...r,roleStyle:this.roleStyles.get(r.index)})),this.result.roleDecisions);const ids=[...new Set(this.result.captionStyleTrack.tracks.flatMap(t=>t.supports.map(s=>s.rowIndex)))];this.result.captionStyleSupportRecords=ids.map(rowIndex=>({rowIndex,style:roleStyleApi().compactSupportStyle(this.roleStyles.get(rowIndex))})).filter(p=>p.style);}
      if(gapApi()&&roleStyleApi()&&this.result.captionStyleTrack?.status==='proposed')await this.recoverDetectionGaps();
      this.result.events=buildEvents(this.result.raw.rows,this.result.raw.frames,this.result.roleDecisions);this.result.phase='precision';adaptResult(this.result);this.emit();
    }
    async recoverDetectionGaps(){const plan=gapApi().planGaps(this.result.raw,this.result.roleDecisions);this.result.detectionGapRecovery={schema:plan.schema,policy:plan.policy,plan:clone(plan),attempts:[],allActualReadingsRetained:true};if(!plan.proposals.length)return;
      this.worker=await this.createWorker();try{for(const proposal of plan.proposals){await this.checkpoint();const sampled=await this.sample(proposal.time),full=sampled.canvas,hash=await digest(full.getContext('2d').getImageData(0,0,full.width,full.height).data);if(hash!==proposal.parentPixelsSha256||Math.abs(sampled.time-proposal.time)>.005)throw Error('补查字幕画面与本次视频不对应');const band=crop(full,proposal.sourceRect),detection=await this.bounded(()=>this.worker.detectLines(band,{frameId:proposal.frameId+':local-caption-gap',time:proposal.time,maxSide:1280}),90000,'字幕区域补查暂时停止');
        const H=band.height,plausible=detection.candidates.filter(x=>x.sourceBBox.bottom-x.sourceBBox.top>=12&&(x.sourceBBox.bottom-x.sourceBBox.top)/H>=.25&&x.sourceBBox.right-x.sourceBBox.left>=12).sort((a,b)=>Math.abs((a.sourceBBox.top+a.sourceBBox.bottom)/2-H/2)-Math.abs((b.sourceBBox.top+b.sourceBBox.bottom)/2-H/2)||b.score-a.score),attempt={proposal:clone(proposal),regionalDetection:clone(detection),status:'no_plausible_local_detector_line'};this.result.detectionGapRecovery.attempts.push(attempt);if(!plausible.length)continue;
        const local=rect(plausible[0],band.width,band.height);if(!local)continue;const b={left:local.left+proposal.sourceRect.left,top:local.top+proposal.sourceRect.top,right:local.right+proposal.sourceRect.left,bottom:local.bottom+proposal.sourceRect.top},c=crop(full,b),read=reading(await this.bounded(()=>this.worker.recognize(c),30000,'补查字幕读取暂时停止')),pixels=c.getContext('2d').getImageData(0,0,c.width,c.height);if(this.result.raw.rows.length>=LIMITS.totalRows)throw Error('文字量达到处理上限，已有补查结果已保留');
        const row={index:this.result.raw.rows.length,frameIndex:proposal.frameIndex,frameId:proposal.frameId,time:proposal.time,frameTime:proposal.time,sourceWidth:full.width,sourceHeight:full.height,sourceRect:b,inputWidth:c.width,inputHeight:c.height,detectorCandidateId:'local-caption-gap:'+proposal.frameIndex+':'+plausible[0].id,detectorScore:plausible[0].score,complete:false,completenessStatus:'regional_detector_proposal_not_full_line_certificate',...read,selectedReadingId:'detected_line_original_color',alternatives:[],cropPixelsSha256:await digest(pixels.data),cropReceipt:{schema:'source-rect-native-crop-v190',frameId:proposal.frameId,time:proposal.time,sourceRect:{...b},inputWidth:c.width,inputHeight:c.height,interpolation:'none_integer_1_to_1'},detectorOrigin:{schema:'local-region-detector-origin-v197',proposal:clone(proposal),localCandidate:clone(plausible[0]),regionalPixelsSha256:detection.sourcePixelSha256,originalWholeFrameDetectorRowCountUnchanged:true}};
        this.result.raw.rows.push(row);const style=this.measureRoleStyle(row,c),project=roleStyleApi().projectReading(read,style,this.result.captionStyleTrack),keep=project.status==='keep';this.roleStyles.set(row.index,style);this.result.roleDecisions.push({rowIndex:row.index,familyId:'regional-caption-gap:'+proposal.captionLaneId,captionLaneId:proposal.captionLaneId,decision:keep?'proposed_caption':'visible_recovery_candidate',reason:keep?'real_local_detection_matches_existing_native_caption_style':'real_local_detection_style_unresolved',roleEvidence:{proposal:clone(proposal),projection:clone(project),semanticRoleVerified:false}});await this.keepCrop(row,c);await this.options.onLineReading?.({row:clone(row),canvas:c});attempt.status=keep?'actual_caption_style_candidate':'actual_recovery_candidate';attempt.rowIndex=row.index;attempt.actualMobileRead=clone(read);attempt.styleProjection=clone(project);
      }
        if(gapApi().validateRegionalCaptionContinuity){const continuity=gapApi().validateRegionalCaptionContinuity(this.result.raw,this.result.roleDecisions,this.result.detectionGapRecovery.attempts,this.roleStyles);this.result.detectionGapRecovery.continuity=clone(continuity);for(const proof of continuity.proofs){const d=this.result.roleDecisions.find(v=>v.rowIndex===proof.rowIndex);if(d?.decision==='visible_recovery_candidate'){d.previousRegionalRoleDecision=clone(d);d.decision='proposed_caption';d.reason='source_bound_regional_caption_continuity';d.roleEvidence.regionalContinuity=clone(proof);}}}
      }finally{await this.stopWorker();}
    }
    async precision(){
      const jobs=this.result.events.filter(e=>e.layer!=='screen');this.result.precisionCheckpoint.pending=jobs.filter(e=>e.precision?.status!=='read').map(e=>e.id);
      for(const event of jobs){await this.checkpoint();if(event.precision?.status==='read')continue;
        const row=this.result.raw.rows[event.selectedRowIndex],c=await this.timedDetail('representative_crop',()=>this.cropFor(row));let start,output;
        try{output=await this.timedDetail('representative_model_including_preparation',()=>this.withPrecision(async worker=>{const light=reading(await this.bounded(()=>worker.recognize(c),30000,'字幕原图校准超时'));
          event.precisionCalibration={reading:clone(light),rowIndex:row.index,exact:same(light,reading(row))};if(!same(light,reading(row)))throw Error('同一字幕原图的校准结果变化，已保留原记录');
          start=Date.now();return this.bounded(()=>worker.recognizePrecision(c),90000,'精读暂时超时，已保存已读内容，可继续');}));}
        catch(e){if(start!==undefined){event.precision={status:'failed',error:errorText(e),rowIndex:row.index};this.result.precisionCheckpoint.failed.push({eventId:event.id,rowIndex:row.index,error:errorText(e)});}throw e;}
        if(output.modelId!==PRECISION_MODEL.modelId||output.modelSha256!==PRECISION_MODEL.modelSha256)throw Error('精读模型来源不符');
        event.precision={status:'read',reading:reading(output),rowIndex:row.index,frameIndex:row.frameIndex,frameId:row.frameId,time:row.time,cropPixelsSha256:row.cropPixelsSha256,
          sourceRect:clone(row.sourceRect),modelId:output.modelId,modelSha256:output.modelSha256,elapsedMs:Date.now()-start,nativeOriginalColor:true,calibrationExact:true,representativeOnly:true};
        await this.timedDetail('representative_style',()=>{this.keepRoleStyle(event,'detected_line_original_color',reading(row),row,c);this.keepRoleStyle(event,'precision_native_representative',event.precision.reading,row,c);});
        this.result.precisionCheckpoint.completed.push(event.id);this.result.precisionCheckpoint.pending=this.result.precisionCheckpoint.pending.filter(id=>id!==event.id);
        await this.timedDetail('representative_projection',()=>adaptResult(this.result));await this.timedDetail('checkpoint_wait',()=>this.saveCheckpoint());this.emit();
      }
      this.result.phase='extent_precision';
    }
    async extentPrecision(){if(this.result.events.some(e=>e.layer!=='screen'&&!validRepresentative(e,this.result.raw.rows)))throw Error('代表精读尚未完成，不能跳过后继续补读');
      const jobs=extentJobs(this.result),old=this.result.extentPrecisionCheckpoint;
      const completed=jobs.filter(e=>hasExpandedRead(e,this.result.raw.rows,this.result.raw.frames)&&hasGlyphAttempt(e,this.result.raw.rows,this.result.raw.frames)).map(e=>e.id);
      const skipped=jobs.filter(e=>e.nativeExpansion?.status==='not_attempted'&&(e.nativeExpansion.reason==='bounded_single_lane_expansion_ambiguous'&&!expandedRect(this.result.raw.rows[e.selectedRowIndex],this.result.raw.rows)
        ||e.nativeExpansion.reason==='native_parent_source_unavailable'&&!this.options.video&&!this.options.frameProvider)
        ||e.nativeGlyphStatus?.status==='not_attempted'&&e.nativeGlyphStatus.reason==='native_parent_source_unavailable'&&!this.options.video&&!this.options.frameProvider).map(e=>({eventId:e.id,reason:expansionSkipReason(e)})),done=new Set([...completed,...skipped.map(v=>v.eventId)]);
      this.result.extentPrecisionCheckpoint={total:jobs.length,processed:done.size,completed:[...completed],skipped:clone(skipped),pending:jobs.filter(e=>!done.has(e.id)).map(e=>e.id),failed:clone(old?.failed||[])};
      await this.saveCheckpoint();this.emit();
      for(const event of jobs){if(done.has(event.id))continue;await this.checkpoint();const q=this.result.extentPrecisionCheckpoint;
        try{await this.expandEvent(event);}catch(error){q.failed.push({eventId:event.id,error:errorText(error)});throw error;}
        if(hasExpandedRead(event,this.result.raw.rows,this.result.raw.frames)&&hasGlyphAttempt(event,this.result.raw.rows,this.result.raw.frames))q.completed.push(event.id);
        else if(validSkippedExpansion(event,this.result.raw.rows))q.skipped.push({eventId:event.id,reason:expansionSkipReason(event)});
        else throw Error('补读保存记录缺少有效原生回执');
        q.processed++;q.pending=q.pending.filter(id=>id!==event.id);await this.saveCheckpoint();this.emit();
      }
    }
    async run(){if(this.result.state!=='ready')throw Error('任务已经开始');const started=Date.now();this.result.runtimeTiming={schema:'subtitle-local-phase-timing-v199',scope:'this_session_invocation_excludes_export',phaseMs:{},phaseCalls:{},totalMs:0};this.result.state='running';this.emit();
      try{if(this.result.phase==='frames')await this.timedPhase('frames',()=>this.scan());if(this.result.phase==='roles')await this.timedPhase('roles',()=>this.roles());if(this.result.phase==='precision')await this.timedPhase('precision',()=>this.precision());if(this.result.phase==='extent_precision')await this.timedPhase('extent_precision',()=>this.extentPrecision());
        await this.timedPhase('working_evidence',()=>this.prepareWorkingCueEvidence());this.result.state=this.result.uncertainFrames||this.result.roleAnalysis?.analysisComplete!==true?'partial':this.result.events.length?'processed':'empty';this.result.canContinue=false;this.result.processingComplete=true;
      }catch(e){this.result.state=this.cancelled?'cancelled':'partial';this.result.error=errorText(e);this.result.canContinue=!this.cancelled&&['precision','extent_precision'].includes(this.result.phase);this.result.processingComplete=false;
        if(!this.result.events.length){this.result.roleDecisions=fallbackRoles(this.result.raw.rows,'processing_incomplete');this.result.events=buildEvents(this.result.raw.rows,this.result.raw.frames,this.result.roleDecisions);}}
      finally{this.finished=true;await this.stopWorker();adaptResult(this.result);this.result.runtimeTiming.totalMs=Math.max(0,Date.now()-started);await this.saveCheckpoint();this.emit();}return this.result;
    }
    async saveCheckpoint(){try{if(typeof this.options.onCheckpointSummary==='function')await this.options.onCheckpointSummary(this.progressSummary());else await this.options.onCheckpoint?.(clone(this.result));}catch{this.result.persistenceError='本机记录暂未保存，当前文字仍可导出';}}
    async prepareWorkingCueEvidence(){if(!cueApi()?.deriveSourceStyle)return;const groups=new Map();for(const e of this.result.events.filter(e=>e.layer==='body')){const k=e.captionLaneId||e.familyId;if(!groups.has(k))groups.set(k,[]);groups.get(k).push(e);}const wanted=new Set();for(const values of groups.values()){values.sort((a,b)=>a.firstObserved-b.firstObserved);for(let i=1;i<values.length;i++){const a=values[i-1],b=values[i],x=selectActualReading(a,this.result.raw.rows,this.result.raw.frames),y=selectActualReading(b,this.result.raw.rows,this.result.raw.frames);if(b.firstObserved-a.lastObserved<=.59&&b.firstObserved>a.lastObserved&&precisionKey(x.actual.text)===precisionKey(y.actual.text)&&nearRows(this.result.raw.rows[a.selectedRowIndex],this.result.raw.rows[b.selectedRowIndex])){wanted.add(a);wanted.add(b);}}}
      for(const event of wanted){await this.checkpoint();const selected=selectActualReading(event,this.result.raw.rows,this.result.raw.frames),p=actualReceipt(event,selected,this.result.raw.rows,this.result.raw.frames);if(!p||!alignedActualReading(p.reading,p.sourceRect))continue;p.sourceIdentityKey=JSON.stringify(this.result.sourceIdentity);if((event.nativeSourceStyles||[]).some(s=>cueApi().validateSourceStyle(s,p,{nativeApi:root.BrandbaiHighQualitySubtitles})))continue;const row=this.result.raw.rows[p.rowIndex];if(!this.options.video&&!this.options.frameProvider&&!this.crops.has(row.index)){event.nativeSourceStyleUnavailable='original_native_source_unavailable';continue;}const sampled=selected.expanded?await this.expandedCropFor(row,p.sourceRect):{canvas:await this.cropFor(row)},c=sampled.canvas;const image=c.getContext('2d').getImageData(0,0,c.width,c.height),style=await cueApi().deriveSourceStyle(image,p,{nativeApi:root.BrandbaiHighQualitySubtitles});event.nativeSourceStyles??=[];event.nativeSourceStyles.push(style);
      }adaptResult(this.result);
    }
    async continue(){if(!this.result.canContinue||!['precision','extent_precision'].includes(this.result.phase))throw Error('当前没有可继续的精读任务');this.cancelled=false;this.finished=false;this.controller=new AbortController();this.result.state='ready';this.result.error=null;this.result.canContinue=false;return this.run();}
  }
  return {Session,PIPELINE,LIMITS,PRECISION_MODEL,EXPANSION,OWNED_GLYPHS,READ_SELECTION,PROTECTED_UNIT_PATTERN,protectedUnits,identity,reading,rect,mapRoles,buildEvents,adaptResult,consolidate,precisionKey,signature,validResume,nearRows,expandedRect,glyphEvidence,validGlyphEvidence,validExpanded,expandedSelection,selectedForGlyph,selectActualReading,alignedActualReading,strongActualReading,endpointExtentPlan,endpointOwnedProof,expandedAgreement,extentJobs,actualReceipt,criticalReadStatus,projectWorkingBody,
    glyphTopology,aspectMask,ownedGlyphEvidence,validOwnedGlyph,compareOwnedGlyph,validOwnedEvidence,validNativeGlyphReceipt,nativeGlyphReceipt,receiptMatchesExpanded,glyphSelection,hasGlyphAttempt,protectedGlyphKinds,disputedGlyphFootprint,absenceSpanOwned,protectedEdgeProof};
});
