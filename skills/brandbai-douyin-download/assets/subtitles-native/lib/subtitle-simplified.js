/* Display-only Traditional -> mainland Simplified conversion.
 * Recognition evidence is owned by the caller and must remain unchanged.
 */
(function(root,factory){const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;root.BrandbaiSubtitleSimplified=api;})(globalThis,function(root){
  'use strict';
  const POLICY='opencc-t2s-v194',FROM='t',TO='cn';
  const UNAVAILABLE='简体整理组件未就绪，请重新加载插件后重试。';
  const FAILED='简体整理执行失败，原始识别文字已保留。';
  let converter=null;
  function assertReady(){
    if(converter)return true;
    if(typeof root.OpenCC?.Converter!=='function')throw Error(UNAVAILABLE);
    try{const value=root.OpenCC.Converter({from:FROM,to:TO});if(typeof value!=='function')throw Error();converter=value;}
    catch{throw Error(UNAVAILABLE);}
    return true;
  }
  function text(value){
    if(typeof value!=='string')throw Error('待整理的识别文字无效');
    assertReady();
    let converted;try{converted=converter(value);}catch{throw Error(FAILED);}
    if(typeof converted!=='string')throw Error(FAILED);
    return converted;
  }
  function normalize(value){const converted=text(value);return {text:converted,recognizedText:value,
    normalization:{policy:POLICY,from:FROM,to:TO,changed:converted!==value}};}
  return Object.freeze({POLICY,FROM,TO,UNAVAILABLE,FAILED,assertReady,text,normalize});
});
