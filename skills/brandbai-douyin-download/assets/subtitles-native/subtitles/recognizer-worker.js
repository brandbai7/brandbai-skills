"use strict";
// Local PP-OCR recognition only. Mobile reads and precision reads stay separate.
importScripts("vendor/ort/ort.wasm.min.js");
let model = null, characters = null, lineMode = "7";
let detector = null;
let precisionModel = null, precisionCharacters = null;
const MOBILE_PROFILE = Object.freeze({maxWidth:1600,roundWidth:Math.ceil,strictOutput:false});
const PRECISION_PROFILE = Object.freeze({maxWidth:3200,roundWidth:Math.floor,strictOutput:true});
const PRECISION_MODEL_ID = "PP-OCRv6_medium_rec";
const PRECISION_MODEL_SHA256 = "9c09abf0957f7968c7586464b7397b84ad2387a0497a351af40e9acc71b673ba";
const SAFE_ERRORS = new Set(["模型未就绪", "字典与识别模型不匹配", "精读字典加载失败", "精读模型加载失败", "精读模型输出无效", "精读识别执行失败", "不支持的字幕操作"]);
async function detectLines(canvas, provenance) {
  if (!provenance || typeof provenance.frameId !== "string" || !provenance.frameId
    || !Number.isFinite(provenance.time) || provenance.time < 0 || provenance.time > 180
    || canvas.width > 2560 || canvas.height > 4096 || canvas.width * canvas.height > 4000000) throw new Error("检测画面无效");
  if (!detector) {
    importScripts("../lib/subtitle-db-lines.js", "../lib/subtitle-detector-input.js");
    detector = await ort.InferenceSession.create(new URL("vendor/det.onnx",location.href).href,{executionProviders:["wasm"],graphOptimizationLevel:"all"});
  }
  const maxSide=provenance.maxSide===undefined?736:provenance.maxSide;
  if(![736,1280].includes(maxSide))throw new Error("不支持的文字检测尺寸");
  const dims=BrandbaiTextRegionEvidenceV1.dimensions(canvas.width,canvas.height,maxSide), scaled=new OffscreenCanvas(dims.width,dims.height);
  scaled.getContext("2d").drawImage(canvas,0,0,scaled.width,scaled.height);
  const tensor=BrandbaiTextRegionEvidenceV1.tensorFromRGBA(scaled.getContext("2d").getImageData(0,0,scaled.width,scaled.height));
  const pixels=canvas.getContext("2d").getImageData(0,0,canvas.width,canvas.height).data;
  const hash=[...new Uint8Array(await crypto.subtle.digest("SHA-256",pixels))].map(n=>n.toString(16).padStart(2,"0")).join("");
  const values=await detector.run({[detector.inputNames[0]]:new ort.Tensor("float32",tensor.data,tensor.dims)});
  try {
    const output=values[detector.outputNames[0]];
    const result=BrandbaiDBTextLinesV2.detect({data:output.data,width:dims.width,height:dims.height,
      sourceWidth:canvas.width,sourceHeight:canvas.height,frameId:provenance.frameId,time:provenance.time,sourceSha256:hash,
      threshold:.3,boxThreshold:.5,unclipRatio:1.5,limits:{maxLines:128,maxCandidates:512}});
    return {status:result.status,sourceWidth:canvas.width,sourceHeight:canvas.height,frameId:provenance.frameId,time:provenance.time,
      sourcePixelSha256:hash,modelSha256:"d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9",
      detectorScale:{maxSide,width:dims.width,height:dims.height},
      completeTextExtentKnown:false,singleLineCertified:false,proposalOnly:true,
      candidates:result.candidates.map(row=>({id:row.id,sourceBBox:row.sourceBBox,sourceQuad:row.sourceQuad,originQuad:row.originQuad,
        score:row.score,angleRadians:row.angleRadians,outsideSource:row.outsideSource,proposalOnly:true,textConfirmed:false,singleLineCertified:false})),
      diagnostics:result.diagnostics,overflow:result.overflow,rejectedCandidates:result.rejectedCandidates,warnings:result.warnings};
  } finally { Object.values(values).forEach(value=>value.dispose?.()); }
}
function tokenAlignment(canvas, modelWidth, contentWidth, steps, runs, maxWidth = 1600) {
  // CTC steps describe a model sequence, not exact glyph boxes. Convert only
  // the unpadded sequence bands to the input ROI's x axis; no inferred y axis.
  const sourceWidth = canvas.width, sourceHeight = canvas.height;
  if (![sourceWidth, sourceHeight, modelWidth, contentWidth, steps].every(value => Number.isSafeInteger(value) && value > 0)
    || contentWidth > modelWidth || modelWidth > maxWidth || steps > 4096 || !runs.length) return null;
  const bands = [];
  for (const run of runs) {
    if (typeof run.text !== "string" || !run.text || !Number.isFinite(run.confidence) || run.confidence < 0 || run.confidence > 100
      || ![run.firstStep, run.lastStep, run.peakStep].every(Number.isSafeInteger)
      || run.firstStep < 0 || run.lastStep >= steps || run.firstStep > run.peakStep || run.peakStep > run.lastStep
      // A run touching padding cannot become a valid source-image band merely
      // by clamping its end. Keep the old text but omit this alignment metadata.
      || (run.lastStep + 1) * modelWidth > contentWidth * steps) return null;
    const scale = modelWidth / steps / contentWidth * sourceWidth;
    const left = run.firstStep * scale, right = (run.lastStep + 1) * scale, peak = (run.peakStep + .5) * scale;
    if (![left, right, peak].every(Number.isFinite) || left < 0 || left > peak || peak > right || right > sourceWidth) return null;
    bands.push({ text: run.text, confidence: run.confidence, left, right, peak,
      firstStep: run.firstStep, lastStep: run.lastStep, peakStep: run.peakStep });
  }
  return { schema: "ctc-temporal-bands-v1", sourceWidth, sourceHeight, modelWidth, contentWidth, steps, bands };
}
async function recognizeLine(canvas, modelForCall = model, profile = MOBILE_PROFILE, dictionary = characters) {
  const width = Math.min(profile.maxWidth, Math.max(320, profile.roundWidth(48 * canvas.width / canvas.height)));
  const resizedWidth = Math.min(width, Math.ceil(48 * canvas.width / canvas.height));
  const resized = new OffscreenCanvas(resizedWidth, 48);
  const ctx = resized.getContext("2d", {willReadFrequently:true});
  ctx.drawImage(canvas,0,0,resizedWidth,48);
  const rgba = ctx.getImageData(0,0,resizedWidth,48).data;
  const tensor = new Float32Array(3 * 48 * width);
  for (let y=0;y<48;y++) for (let x=0;x<resizedWidth;x++) for (let c=0;c<3;c++) {
    // PP-OCR exported input uses BGR channel order and [-1,1] normalization.
    const pixel = rgba[(y*resizedWidth+x)*4+(2-c)];
    tensor[c*48*width+y*width+x] = profile.strictOutput ? (pixel/255-.5)/.5 : pixel/127.5-1;
  }
  const input = new ort.Tensor("float32",tensor,[1,3,48,width]);
  let values;
  try {
  try { values = await modelForCall.run({[modelForCall.inputNames[0]]:input}); }
  catch (error) { if (profile.strictOutput) throw new Error("精读识别执行失败"); throw error; }
  const output = values[modelForCall.outputNames[0]];
  if (profile.strictOutput && (!output || output.type !== "float32" || !Array.isArray(output.dims) || output.dims.length !== 3
    || output.dims[0] !== 1 || !Number.isSafeInteger(output.dims[1]) || output.dims[1] < 1 || output.dims[1] > 4096
    || output.dims[2] !== 18710 || dictionary.length !== 18710 || output.data?.length !== output.dims[1] * output.dims[2])) throw new Error("精读模型输出无效");
  const classes = output.dims[2];
  if (classes !== dictionary.length) throw new Error("字典与识别模型不匹配");
  let text="", previous=-1, sum=0, count=0;
  const charConfidences=[], runs=[]; let activeRun=null;
  for (let t=0;t<output.dims[1];t++) {
    let winner=0, probability=-Infinity;
    for (let c=0;c<classes;c++) {const value=output.data[t*classes+c];
      if(profile.strictOutput && (!Number.isFinite(value) || value < 0 || value > 1)) throw new Error("精读模型输出无效");
      if(value>probability){winner=c;probability=value;}}
    if (winner && winner!==previous) {
      text+=dictionary[winner];sum+=probability;count++;
      charConfidences.push({text:dictionary[winner],confidence:probability*100});
      activeRun={text:dictionary[winner],confidence:probability*100,firstStep:t,lastStep:t,peakStep:t,peakProbability:probability};
      runs.push(activeRun);
    } else if (winner && activeRun) {
      activeRun.lastStep=t;
      if (probability>activeRun.peakProbability) {activeRun.peakStep=t;activeRun.peakProbability=probability;}
    } else {
      activeRun=null;
    }
    previous=winner;
  }
  // Scores describe model certainty, not verified spelling. Keep token evidence
  // so a weak character cannot be hidden by a high line-average score.
  const alignment=tokenAlignment(canvas,width,resizedWidth,output.dims[1],runs,profile.maxWidth);
  return {text,confidence:count ? sum/count*100 : 0,charConfidences,
    minCharConfidence:count ? Math.min(...charConfidences.map(row=>row.confidence)) : 0,
    ...(alignment ? {tokenAlignment:alignment} : {})};
  } finally { input.dispose?.(); if(values)Object.values(values).forEach(value=>value.dispose?.()); }
}
self.onmessage = async ({data}) => {
  try {
    let result;
    if (data.type === "init") {
      ort.env.wasm.numThreads=1; ort.env.wasm.proxy=false;
      ort.env.wasm.wasmPaths=new URL("vendor/ort/",location.href).href;
      const keys=await(await fetch(new URL("vendor/keys.txt",location.href))).text();
      characters=["",...keys.replace(/\r/g,"").replace(/\n$/,"").split("\n")," "];
      model=await ort.InferenceSession.create(new URL("vendor/rec.onnx",location.href).href,{executionProviders:["wasm"],graphOptimizationLevel:"all"});
      result={ready:true};
    } else if (data.type === "parameters") { lineMode=data.lineMode; result={}; }
    else if (data.type === "recognize") {
      if(!model) throw new Error("模型未就绪");
      const canvas=new OffscreenCanvas(data.width,data.height);
      canvas.getContext("2d").putImageData(new ImageData(new Uint8ClampedArray(data.pixels),data.width,data.height),0,0);
      if(lineMode==="6") {
        const rows=[];
        for(let line=0;line<2;line++) {const half=new OffscreenCanvas(data.width,Math.floor(data.height/2));half.getContext("2d").drawImage(canvas,0,line*data.height/2,data.width,data.height/2,0,0,half.width,half.height);rows.push(await recognizeLine(half));}
        const nonempty=rows.filter(row=>row.text.trim());
        result={data:{text:nonempty.map(row=>row.text).join("\n"),confidence:nonempty.length?Math.min(...nonempty.map(row=>row.confidence)):0,
          charConfidences:nonempty.flatMap(row=>row.charConfidences),minCharConfidence:nonempty.length?Math.min(...nonempty.map(row=>row.minCharConfidence)):0}};
      } else result={data:await recognizeLine(canvas)};
    } else if(data.type === "recognizePrecision") {
      if(!model||!characters)throw new Error("模型未就绪");
      if(!precisionCharacters){
        try {
          const response=await fetch(new URL("vendor/precision-keys.txt",location.href));
          if(response.ok===false)throw Error();
          const keys=await response.text(), loaded=["",...keys.replace(/\r/g,"").replace(/\n$/,"").split("\n")," "];
          if(loaded.length!==18710||loaded.slice(1,-1).some(key=>!key))throw Error();
          precisionCharacters=loaded;
        } catch { throw new Error("精读字典加载失败"); }
      }
      if(!precisionModel){try{precisionModel=await ort.InferenceSession.create(new URL("vendor/precision-rec.onnx",location.href).href,{executionProviders:["wasm"],graphOptimizationLevel:"all"});}catch{throw new Error("精读模型加载失败");}}
      const canvas=new OffscreenCanvas(data.width,data.height);
      canvas.getContext("2d").putImageData(new ImageData(new Uint8ClampedArray(data.pixels),data.width,data.height),0,0);
      result={data:await recognizeLine(canvas,precisionModel,PRECISION_PROFILE,precisionCharacters),modelId:PRECISION_MODEL_ID,modelSha256:PRECISION_MODEL_SHA256};
    } else if(data.type === "detectLines") {
      const canvas=new OffscreenCanvas(data.width,data.height);
      canvas.getContext("2d").putImageData(new ImageData(new Uint8ClampedArray(data.pixels),data.width,data.height),0,0);
      result=await detectLines(canvas,data.provenance);
    } else throw new Error("不支持的字幕操作");
    self.postMessage({id:data.id,result});
  } catch (error) {self.postMessage({id:data.id,error:SAFE_ERRORS.has(error?.message)?error.message:"本地识别执行失败"});}
};
