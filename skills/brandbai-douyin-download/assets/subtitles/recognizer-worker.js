"use strict";
// PP-OCRv4 recognition only: user chooses the text area. No audio or cloud code.
importScripts("vendor/ort/ort.wasm.min.js");
let model = null, characters = null, lineMode = "7";
async function recognizeLine(canvas) {
  const width = Math.min(1600, Math.max(320, Math.ceil(48 * canvas.width / canvas.height)));
  const resizedWidth = Math.min(width, Math.ceil(48 * canvas.width / canvas.height));
  const resized = new OffscreenCanvas(resizedWidth, 48);
  const ctx = resized.getContext("2d", {willReadFrequently:true});
  ctx.drawImage(canvas,0,0,resizedWidth,48);
  const rgba = ctx.getImageData(0,0,resizedWidth,48).data;
  const tensor = new Float32Array(3 * 48 * width);
  for (let y=0;y<48;y++) for (let x=0;x<resizedWidth;x++) for (let c=0;c<3;c++) {
    // PP-OCR exported input uses BGR channel order and [-1,1] normalization.
    tensor[c*48*width+y*width+x] = rgba[(y*resizedWidth+x)*4+(2-c)]/127.5-1;
  }
  const values = await model.run({[model.inputNames[0]]:new ort.Tensor("float32",tensor,[1,3,48,width])});
  const output = values[model.outputNames[0]], classes = output.dims[2];
  if (classes !== characters.length) throw new Error("字典与识别模型不匹配");
  let text="", previous=-1, sum=0, count=0;
  const charConfidences=[];
  for (let t=0;t<output.dims[1];t++) {
    let winner=0, probability=-Infinity;
    for (let c=0;c<classes;c++) {const value=output.data[t*classes+c];if(value>probability){winner=c;probability=value;}}
    if (winner && winner!==previous) {
      text+=characters[winner];sum+=probability;count++;
      charConfidences.push({text:characters[winner],confidence:probability*100});
    }
    previous=winner;
  }
  // Scores describe model certainty, not verified spelling. Keep token evidence
  // so a weak character cannot be hidden by a high line-average score.
  return {text,confidence:count ? sum/count*100 : 0,charConfidences,
    minCharConfidence:count ? Math.min(...charConfidences.map(row=>row.confidence)) : 0};
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
    } else throw new Error("不支持的字幕操作");
    self.postMessage({id:data.id,result});
  } catch (_error) {self.postMessage({id:data.id,error:"本地识别执行失败"});}
};
