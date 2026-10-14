/* Execution-only adapter. Original model/runtime files and manifest remain frozen. */
(function(root,factory){const api=factory(root);if(typeof module==="object"&&module.exports)module.exports=api;root.BrandbaiDetectedSubtitleResume=api;})(globalThis,function(root){
"use strict";
const SCHEMA="local-native-pending-precision-resume-adapter-v064-r2",clone=x=>JSON.parse(JSON.stringify(x)),same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
const ROLE_KEYS=["roleOwnership","roleDecisions","roleAnalysis","captionStyleTrack","captionStyleSupportRecords","detectionGapRecovery"];
const APPEND_KEYS=["nativeExpandedReads","nativeGlyphReceipts","nativeRoleStyles","nativeSourceStyles"];
const EXTENT_KEYS=[...APPEND_KEYS,"nativeExpansion","nativeGlyphStatus","nativeSourceStyleUnavailable"];
function readValid(event,record){
 const row=record.raw?.rows?.[event.selectedRowIndex],p=event.precision,cal=event.precisionCalibration,api=root.BrandbaiHighQualitySubtitles;
 return Boolean(row&&p?.status==="read"&&p.rowIndex===row.index&&p.frameIndex===row.frameIndex&&p.frameId===row.frameId&&p.time===row.time
  &&p.cropPixelsSha256===row.cropPixelsSha256&&same(p.sourceRect,row.sourceRect)&&p.modelId===api.PRECISION_MODEL.modelId&&p.modelSha256===api.PRECISION_MODEL.modelSha256
  &&p.nativeOriginalColor===true&&p.representativeOnly===true&&p.calibrationExact===true&&cal?.rowIndex===row.index&&cal.exact===true&&same(cal.reading,api.reading(row))
  &&typeof p.reading?.text==="string"&&Number.isFinite(p.reading.confidence)&&p.reading.confidence>=0&&p.reading.confidence<=100);
}
function validateCheckpointQueue(record){
 const jobs=record.events?.filter(e=>e.layer!=="screen"),q=record.precisionCheckpoint;
 if(!Array.isArray(jobs)||!q||![q.completed,q.pending,q.failed].every(Array.isArray)||q.failed.length)throw Error("Resume base precision queue is incomplete or failed");
 const completed=jobs.filter(e=>e.precision?.status==="read"),pending=jobs.filter(e=>e.precision?.status!=="read");
 if(completed.some(e=>!readValid(e,record))||pending.some(e=>e.precision!=null||e.precisionCalibration!=null))throw Error("Resume precision reading or calibration is not a strict original receipt");
 if(!same(q.completed,completed.map(e=>e.id))||!same(q.pending,pending.map(e=>e.id))||new Set([...q.completed,...q.pending]).size!==jobs.length)throw Error("Resume precision queue is not the exact unique event partition");
 if(!same(jobs.map(e=>e.id),[...q.completed,...q.pending]))throw Error("Resume precision queue is not the original sequential prefix");
 if(record.phase==="precision"){
  if(!q.pending.length||record.extentPrecisionCheckpoint!=null||record.events.some(e=>(e.nativeExpandedReads||[]).length||(e.nativeGlyphReceipts||[]).length||e.nativeExpansion!=null||e.nativeGlyphStatus!=null))throw Error("Resume precision checkpoint contains later-phase or no pending work");
 }else if(record.phase==="extent_precision"){
  if(q.pending.length||!Array.isArray(record.extentPrecisionCheckpoint?.pending)||!record.extentPrecisionCheckpoint.pending.length||record.extentPrecisionCheckpoint.failed?.length)throw Error("Resume extent checkpoint is not pending after complete base precision");
 }else throw Error("Resume checkpoint phase is unsupported");
 return {phase:record.phase,completedBaseIds:[...q.completed],basePendingIds:[...q.pending],initialExtentPendingIds:[...(record.extentPrecisionCheckpoint?.pending||[])]};
}
function prepareSeed(record,videoSha256,runtime){
 const api=root.BrandbaiHighQualitySubtitles;
 if(record?.video_sha256!==videoSha256||record.sourceIdentity?.kind!=="local_file_sha256"||record.sourceIdentity.sha256!==videoSha256)throw Error("Resume source identity mismatch");
 if(!same(record.runtime,runtime))throw Error("Resume runtime identity mismatch");
 if(!["precision","extent_precision"].includes(record.phase)||record.processingComplete===true||!["partial","cancelled"].includes(record.state)||record.engineBuild!=="196"||!api.validResume(record))throw Error("Resume checkpoint is not a complete native pending record");
 validateCheckpointQueue(record);
 const seed=clone(record);seed.state="partial";seed.error=null;seed.canContinue=true;seed.processingComplete=false;
 if(!api.validResume(seed))throw Error("Resume checkpoint failed lifecycle validation");
 return seed;
}
function assertOriginals(seed,result){
 if(!same(seed.raw,result.raw)||ROLE_KEYS.some(k=>!same(seed[k]??null,result[k]??null)))throw Error("Resume changed original native observations or roles");
 if(!same(seed.events.map(e=>e.id),result.events?.map(e=>e.id)))throw Error("Resume changed the original event identities or order");
 const allowedBase=new Set(seed.phase==="precision"?seed.precisionCheckpoint.pending:[]),q=result.precisionCheckpoint,oldq=seed.precisionCheckpoint;
 if(!q||!same(oldq.completed,q.completed.slice(0,oldq.completed.length))||q.completed.slice(oldq.completed.length).some(id=>!allowedBase.has(id))||new Set(q.completed).size!==q.completed.length
  ||q.pending.some(id=>!allowedBase.has(id)||q.completed.includes(id))||new Set(q.pending).size!==q.pending.length||q.failed.some(x=>!allowedBase.has(x.eventId)))throw Error("Resume rewrote or repeated a completed base precision job");
 const jobs=result.events.filter(e=>e.layer!=="screen");if(!same(q.completed,jobs.filter(e=>e.precision?.status==="read").map(e=>e.id))||!same(q.pending,jobs.filter(e=>e.precision?.status!=="read").map(e=>e.id))||jobs.filter(e=>e.precision?.status==="read").some(e=>!readValid(e,result)))throw Error("Resume lost a pending job or forged a completed reading");
 if(seed.phase==="extent_precision"&&!same(oldq,q))throw Error("Resume changed completed base precision checkpoint");
 for(let i=0;i<seed.events.length;i++){
  const old=seed.events[i],current=result.events[i];
  for(const key of new Set([...Object.keys(old),...Object.keys(current)])){
   if(EXTENT_KEYS.includes(key)||allowedBase.has(old.id)&&["precision","precisionCalibration"].includes(key))continue;
   if(!same(old[key]??null,current[key]??null))throw Error("Resume changed an original event or completed representative reading");
  }
  for(const key of APPEND_KEYS){const retained=old[key]||[],actual=current[key]||[];if(actual.length<retained.length||!same(retained,actual.slice(0,retained.length)))throw Error("Resume changed existing actual reading evidence");}
 }
 return true;
}
async function hash(bytes){return Array.from(new Uint8Array(await root.crypto.subtle.digest("SHA-256",bytes))).map(n=>n.toString(16).padStart(2,"0")).join("");}
async function pixels(canvas){return hash(canvas.getContext("2d").getImageData(0,0,canvas.width,canvas.height).data);}
function createSerializedProgress(forwardSerialized){
 if(typeof forwardSerialized!=="function")throw Error("Serialized native progress bridge is required");
 let queue=Promise.resolve(),last=null;
 const persist=result=>{const serialized=JSON.stringify(result);if(serialized===last)return queue;last=serialized;queue=queue.then(()=>forwardSerialized(serialized));return queue;};
 persist.flush=()=>queue;return persist;
}
function createExecutionGuard(seed,getResult,expectedExpandedCrop){
 const api=root.BrandbaiHighQualitySubtitles,plan=validateCheckpointQueue(seed),baseAllowed=new Set(plan.basePendingIds),baseUsed=new Set(),calibrated=new Set(),extentUsed=new Set(),calibrationInFlight=new Set(),baseInFlight=new Set(),extentInFlight=new Set();
 const counts={detectLines:0,mobile:0,precision:0,basePrecision:0,expandedPrecision:0,calibrationInterfaceCalls:0,cachedMobileCalibrations:0},calibrationReuseReceipts=[];
 let extentAllowed=null;
 const pendingEvent=(phase)=>{const result=getResult(),q=phase==="precision"?result.precisionCheckpoint:result.extentPrecisionCheckpoint;if(result.phase!==phase||!q?.pending?.length)throw Error("Resume model call is not an active pending job");const event=result.events.find(e=>e.id===q.pending[0]),original=seed.events.find(e=>e.id===event?.id);if(!event||!original||["layer","familyId","captionLaneId","selectedRowIndex","rowIndices","frameIndices","frameIds","observationTimes"].some(k=>!same(original[k]??null,event[k]??null)))throw Error("Resume pending event source binding changed");return {result,event,row:seed.raw.rows[original.selectedRowIndex]};};
 async function verifyBase(canvas,row){if(!row||canvas.width!==row.inputWidth||canvas.height!==row.inputHeight||await pixels(canvas)!==row.cropPixelsSha256)throw Error("Resume pending representative crop pixels differ");}
 function wrapWorker(worker){return {...worker,
  detectLines(){counts.detectLines++;throw Error("Resume cannot repeat line detection");},
  async recognize(canvas){
   counts.calibrationInterfaceCalls++;const {event,row}=pendingEvent("precision");
   if(!baseAllowed.has(event.id)||calibrated.has(event.id)||baseUsed.has(event.id)||calibrationInFlight.has(event.id))throw Error("Resume cannot calibrate a completed or repeated job");
   calibrationInFlight.add(event.id);try{await verifyBase(canvas,row);}catch(error){calibrationInFlight.delete(event.id);throw error;}calibrated.add(event.id);calibrationInFlight.delete(event.id);counts.cachedMobileCalibrations++;
   const saved=api.reading(row);calibrationReuseReceipts.push({schema:"resume-frozen-mobile-reading-reuse-v199",eventId:event.id,rowIndex:row.index,frameId:row.frameId,frameIndex:row.frameIndex,time:row.time,cropPixelsSha256:row.cropPixelsSha256,readingSha256:await hash(new TextEncoder().encode(JSON.stringify(saved))),nativeCropIdentityVerified:true,source:"original_checkpoint_actual_mobile_read",freshMobileInference:false,actualMobileModelCalls:0});
   return clone(saved);
  },
  async recognizePrecision(canvas){
   const result=getResult();let kind,event,row;
   if(result.phase==="precision"){
    ({event,row}=pendingEvent("precision"));if(!baseAllowed.has(event.id)||!calibrated.has(event.id)||baseUsed.has(event.id)||baseInFlight.has(event.id))throw Error("Resume cannot reread a completed or repeated representative");
    baseInFlight.add(event.id);try{await verifyBase(canvas,row);}catch(error){baseInFlight.delete(event.id);throw error;}baseUsed.add(event.id);baseInFlight.delete(event.id);kind="basePrecision";
   }else if(result.phase==="extent_precision"){
    ({event,row}=pendingEvent("extent_precision"));
    if(extentAllowed===null){assertOriginals(seed,result);if(!api.validResume(result))throw Error("Resume derived extent queue is invalid");extentAllowed=new Set(api.extentJobs(result).filter(e=>result.extentPrecisionCheckpoint.pending.includes(e.id)).map(e=>e.id));}
    if(!extentAllowed.has(event.id)||extentUsed.has(event.id)||extentInFlight.has(event.id)||(event.nativeExpandedReads||[]).length)throw Error("Resume expanded model call is not a new legal extent job");
    const box=api.expandedRect(row,seed.raw.rows);if(!box||typeof expectedExpandedCrop!=="function")throw Error("Resume expanded native crop source is unavailable");
    extentInFlight.add(event.id);try{const expected=await expectedExpandedCrop(row,box);if(canvas.width!==box.right-box.left||canvas.height!==box.bottom-box.top||expected.width!==canvas.width||expected.height!==canvas.height||await pixels(canvas)!==await pixels(expected))throw Error("Resume expanded crop does not match its original native source");}catch(error){extentInFlight.delete(event.id);throw error;}
    extentUsed.add(event.id);extentInFlight.delete(event.id);kind="expandedPrecision";
   }else throw Error("Resume precision call is outside the allowed stages");
   counts.precision++;counts[kind]++;return worker.recognizePrecision(canvas);
  }
 };}
 return {counts,calibrationReuseReceipts,wrapWorker,get maximumNewBasePrecisionCalls(){return baseAllowed.size;},get maximumNewExpandedPrecisionCalls(){return extentAllowed?.size??null;}};
}
async function encode(blob){const bytes=new Uint8Array(await blob.arrayBuffer());let binary="";for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));return btoa(binary);}
async function run({videoSha256,title,workId="",checkpointSha256,runtime,adapterSha256,includeFrames=false}){
 if(typeof includeFrames!=="boolean")throw Error("includeFrames must be an explicit boolean");
 const captureMode=includeFrames?"with_frames":"text_only";
 const scheduling=root.BrandbaiSubtitleFrameQueueV201;
 if(typeof scheduling?.selectFrameConcurrency!=="function")throw Error("Incomplete local scan scheduling module");
 const scanScheduling=scheduling.selectFrameConcurrency({hardwareConcurrency:root.navigator?.hardwareConcurrency,deviceMemory:root.navigator?.deviceMemory,resume:true});
 const checkpointBytes=new Uint8Array(await(await fetch("/__resume_checkpoint__")).arrayBuffer());
 if(await hash(checkpointBytes)!==checkpointSha256)throw Error("Resume checkpoint bytes changed");
 const record=JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(checkpointBytes)),seed=prepareSeed(record,videoSha256,runtime);
 const blob=await(await fetch("/__input_video__")).blob();if(await hash(await blob.arrayBuffer())!==videoSha256)throw Error("Resume video bytes changed");
 const video=document.getElementById("video"),url=URL.createObjectURL(blob),api=root.BrandbaiHighQualitySubtitles,legacy=root.BrandbaiSubtitles;
 const source={title:record.title||title,workId:record.workId||workId,sourceKind:record.workId||workId?"completed_download":"local_file"};
 const collector=includeFrames?new root.BrandbaiSubtitleStoryboard.Collector({id:"cli-resume:"+checkpointSha256,source,region:{left:0,top:0,right:1,bottom:1}}):null;
 let session,recapturedFrames=0,verifiedCrops=0;
 const progress=createSerializedProgress(root.subtitleNativeProgressSerialized);
 const persist=result=>progress({...result,captureMode,scanScheduling});
 persist.flush=()=>progress.flush();
 const guard=createExecutionGuard(seed,()=>session.result,async(row,box)=>(await session.expandedCropFor(row,box)).canvas),factory=root.BrandbaiCreateSubtitleRecognizer;
 try{
  await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error("Resume video decode timeout")),15000);video.onloadeddata=()=>{clearTimeout(timer);resolve();};video.onerror=()=>{clearTimeout(timer);reject(Error("Resume video decode failed"));};video.src=url;});
  if(Math.abs(video.duration-seed.videoDuration)>.02||video.videoWidth!==seed.sourceVideoWidth||video.videoHeight!==seed.sourceVideoHeight)throw Error("Resume video dimensions or duration changed");
  for(const frame of seed.raw.frames){await legacy.seek(video,frame.time);const c=document.createElement("canvas");c.width=video.videoWidth;c.height=video.videoHeight;c.getContext("2d").drawImage(video,0,0);
   if(Math.abs(video.currentTime-frame.time)>.005||await pixels(c)!==frame.sourcePixelSha256)throw Error("Resume original native frame differs");
   for(const row of seed.raw.rows.filter(row=>row.frameIndex===frame.frameIndex)){const b=row.sourceRect,crop=document.createElement("canvas");crop.width=b.right-b.left;crop.height=b.bottom-b.top;crop.getContext("2d").drawImage(c,b.left,b.top,crop.width,crop.height,0,0,crop.width,crop.height);if(crop.width!==row.inputWidth||crop.height!==row.inputHeight||await pixels(crop)!==row.cropPixelsSha256)throw Error("Resume original native crop differs");verifiedCrops++;}
   if(collector)await collector.capture(c,frame.time,frame.frameIndex);recapturedFrames++;}
  const workerFactory=async(...args)=>guard.wrapWorker(await factory(...args));
  session=new api.Session({video,baseUrl:new URL("/subtitles/",location.href),sourceIdentity:{kind:"local_file_sha256",sha256:videoSha256},resumeResult:seed,workerFactory,onProgress:persist,onCheckpoint:persist});
  assertOriginals(seed,session.result);
  const result={...await session.run(),captureMode,scanScheduling};await persist.flush();assertOriginals(seed,result);
  if(!api.validResume(result))throw Error("Resume final native observations or job receipts are invalid");
  const data=root.BrandbaiDetectedSubtitleRunner.outputs(result,source,collector);
  for(const row of data.plan.rows)for(const frame of row.images)await root.subtitleNativeImage({path:frame.path,base64:await encode(frame.blob),frameIndex:frame.index,frameId:frame.sourceFrameId,time:frame.time,parentPixelsSha256:frame.sourcePixelSha256});
  return {result,source,timed:data.timed,plain:data.plain,review:data.review,recovery:data.recovery,csv:data.csv,documents:data.documents,frameStorage:{captureMode,sampled:collector?.frames.size||0,bytes:collector?.bytes||0,warning:collector?.warning||null},runtimeBrowser:{documentEncoding:document.characterSet,sourceFileSha256:videoSha256,regionMode:"native_detected_lines",regionManuallyConfirmed:false},
   resumeExecution:{schema:SCHEMA,checkpointSha256,adapterSha256,originalRuntimeManifestSha256:runtime.manifestSha256,originalPhase:seed.phase,originalCaptureMode:record.captureMode||"with_frames",captureMode,executionOnlyRearm:true,originalObservationsAndReadsUnchanged:true,originalProtectedSectionsSha256:{raw:await hash(new TextEncoder().encode(JSON.stringify(seed.raw))),roles:await hash(new TextEncoder().encode(JSON.stringify(ROLE_KEYS.map(k=>[k,seed[k]??null])))),completedRepresentativeReadings:await hash(new TextEncoder().encode(JSON.stringify(seed.events.filter(e=>seed.precisionCheckpoint.completed.includes(e.id)).map(e=>({id:e.id,precision:e.precision,precisionCalibration:e.precisionCalibration})))))},counts:{...guard.counts,recapturedFrames,verifiedCrops},maximumNewBasePrecisionCalls:guard.maximumNewBasePrecisionCalls,maximumNewExpandedPrecisionCalls:guard.maximumNewExpandedPrecisionCalls??result.extentPrecisionCheckpoint?.total??0,calibrationReuseReceipts:clone(guard.calibrationReuseReceipts),progressBridge:"serialized_json_string"}};
 }finally{video.removeAttribute("src");video.load();URL.revokeObjectURL(url);}
}
return {SCHEMA,validateCheckpointQueue,prepareSeed,assertOriginals,createExecutionGuard,createSerializedProgress,run};
});
