"use strict";
globalThis.BrandbaiCreateSubtitleRecognizer = async function (_language, _mode, options) {
  if (options.signal?.aborted) throw new Error("识别任务已结束");
  const base = new URL("../", options.workerPath);
  const worker = new Worker(new URL("recognizer-worker.js", base));
  let sequence = 0, closed = false;
  const pending = new Map();
  function rejectAll(error) { for (const item of pending.values()) item.reject(error); pending.clear(); }
  worker.onmessage = ({data}) => {
    const item = pending.get(data.id); if (!item) return;
    pending.delete(data.id); data.error ? item.reject(new Error(data.error)) : item.resolve(data.result);
  };
  worker.onerror = () => { closed = true; worker.terminate(); rejectAll(new Error("本地识别模块加载失败")); };
  function call(type, payload = {}, transfer = []) {
    if (closed) return Promise.reject(new Error("识别任务已结束"));
    return new Promise((resolve,reject) => { const id = ++sequence; pending.set(id,{resolve,reject}); worker.postMessage({id,type,...payload},transfer); });
  }
  const api = {
    setParameters: parameters => call("parameters", {lineMode: parameters.tessedit_pageseg_mode}),
    recognize: canvas => { const pixels = canvas.getContext("2d").getImageData(0,0,canvas.width,canvas.height); return call("recognize", {width:canvas.width,height:canvas.height,pixels:pixels.data.buffer},[pixels.data.buffer]); },
    terminate: async () => { closed = true; options.signal?.removeEventListener("abort", abort); worker.terminate(); rejectAll(new Error("识别任务已结束")); },
  };
  // The caller needs to stop the worker while initialization is still pending,
  // not only after the ready API has been returned.
  const abort = () => { api.terminate().catch(() => {}); };
  options.signal?.addEventListener("abort", abort, { once: true });
  if (options.signal?.aborted) abort();
  try { await call("init"); return api; } catch (error) { await api.terminate(); throw error; }
};
