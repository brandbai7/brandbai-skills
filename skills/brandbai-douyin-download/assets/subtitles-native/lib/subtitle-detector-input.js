/* Diagnostic only. Textness support is not spelling, complete text geometry,
 * subtitle ownership, or a safe deletion gate. No source text is accepted here. */
(function(root,factory){const api=factory();if(typeof module==="object"&&module.exports)module.exports=api;root.BrandbaiTextRegionEvidenceV1=api;})(globalThis,function(){
  "use strict";
  const POLICY="same_image_detector_probability_support_not_subtitle_or_deletion_certificate_v1";
  const THRESHOLDS=[.3,.5,.7].map(Math.fround);
  const ROUNDING_TOLERANCE=1e-6;
  const integer=(n,min,max)=>Number.isSafeInteger(n)&&n>=min&&n<=max;
  function fail(message){throw new TypeError(message);}
  function roundEven(n){const floor=Math.floor(n),fraction=n-floor;return fraction===.5?floor+(floor%2):Math.round(n);}
  function dimensions(width,height,maxSide){
    if(!integer(width,1,4096)||!integer(height,1,4096)||![736,1280].includes(maxSide))fail("Invalid bounded detector dimensions");
    const ratio=Math.min(1,maxSide/Math.max(width,height));
    const resizedWidth=roundEven(Math.floor(width*ratio)/32)*32,resizedHeight=roundEven(Math.floor(height*ratio)/32)*32;
    if(!resizedWidth||!resizedHeight)fail("Aspect ratio cannot be represented by detector stride");
    return {width:resizedWidth,height:resizedHeight,limitType:"max",maxSide,
      coordinatePolicy:"map_x_to_original_x_by_width_ratio_and_y_by_height_ratio"};
  }
  function tensorFromRGBA(image){
    if(!image||!integer(image.width,1,1280)||!integer(image.height,1,1280)||image.width%32||image.height%32
      ||!(image.data instanceof Uint8ClampedArray||image.data instanceof Uint8Array)||image.data.length!==image.width*image.height*4)fail("Invalid detector RGBA input");
    const size=image.width*image.height,data=new Float32Array(size*3);
    for(let i=0;i<size;i++)for(let c=0;c<3;c++)data[c*size+i]=(image.data[i*4+2-c]/255-.5)/.5;
    return {data,dims:[1,3,image.height,image.width]};
  }
  function validateMap(map){
    if(!map||!integer(map.width,1,1280)||!integer(map.height,1,1280)||!(map.data instanceof Float32Array)
      ||map.data.length!==map.width*map.height)fail("Invalid bounded detector probability map");
    let rawMin=Infinity,rawMax=-Infinity,belowZeroCount=0,aboveOneCount=0;
    for(let i=0;i<map.data.length;i++){const n=map.data[i];if(!Number.isFinite(n)||n < -ROUNDING_TOLERANCE||n > 1+ROUNDING_TOLERANCE)fail(`Invalid detector probability: value=${n} index=${i}`);
      rawMin=Math.min(rawMin,n);rawMax=Math.max(rawMax,n);belowZeroCount+=n<0?1:0;aboveOneCount+=n>1?1:0;}
    return {rawMin,rawMax,belowZeroCount,aboveOneCount,roundingTolerance:ROUNDING_TOLERANCE,clamped:false};
  }
  function validateROI(roi){
    if(!roi||typeof roi!=="object"||Array.isArray(roi)||!["left","top","right","bottom"].every(k=>Number.isFinite(roi[k])&&roi[k]>=0&&roi[k]<=1)
      ||roi.right<=roi.left||roi.bottom<=roi.top)fail("Invalid ROI");
  }
  function measure(map,rois){
    validateMap(map);
    if(!Array.isArray(rois)||rois.length>64)fail("Too many ROI measurements");
    return rois.map(roi=>{
      validateROI(roi);
      const left=Math.floor(roi.left*map.width),right=Math.min(map.width,Math.ceil(roi.right*map.width)),
        top=Math.floor(roi.top*map.height),bottom=Math.min(map.height,Math.ceil(roi.bottom*map.height));
      let sum=0,max=-Infinity,above03=0,above05=0,above07=0;
      for(let y=top;y<bottom;y++)for(let x=left;x<right;x++){
        const n=map.data[y*map.width+x];sum+=n;max=Math.max(max,n);
        above03+=n>THRESHOLDS[0]?1:0;above05+=n>THRESHOLDS[1]?1:0;above07+=n>THRESHOLDS[2]?1:0;
      }
      const count=(right-left)*(bottom-top);
      return {roi:{left:roi.left,top:roi.top,right:roi.right,bottom:roi.bottom},mapBounds:{left,top,right,bottom},
        mean:sum/count,max,samples:count,above03,above05,above07,fractionAbove03:above03/count,
        support:above03?"textness_observed":"no_textness_observed_at_this_scale",policy:POLICY,
        mayDelete:false,completeGlyphBounds:false,spellingVerified:false,subtitleOwnershipVerified:false};
    });
  }
  return {POLICY,dimensions,tensorFromRGBA,measure,validateMap};
});
