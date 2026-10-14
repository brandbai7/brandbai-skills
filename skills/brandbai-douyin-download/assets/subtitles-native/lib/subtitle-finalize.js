/* Deterministic, reversible view of completed caption observations.
 * No OCR, dictionary corrections, inferred words, or cross-event deduplication. */
(function (root, factory) {
  const api = factory(() => root.BrandbaiSubtitleVisualEvents ||
    (typeof require === "function" ? require("./subtitle-visual-events.js") : null));
  if (typeof module === "object" && module.exports) module.exports = api;
  root.BrandbaiSubtitleFinalize = api;
})(globalThis, function (visualApi) {
  "use strict";
  const SCHEMA = "subtitle-finalize-v1", POLICY_VERSION = "0.11.189.1";
  const lineApi=()=>globalThis.BrandbaiSubtitleCaptionLine || (typeof require==='function'?require('./subtitle-caption-line.js'):null);
  const MAX_OBSERVATIONS = 361, MAX_EVENT_SECONDS = 6;
  const COUNTERS = ["reviewSegments", "variationSegments", "variationFrames", "candidateGroups", "consolidatedSegments"];
  const COMPLETE_STATES = new Set(["processed", "partial", "cancelled", "failed", "empty"]);
  const copy = value => Array.isArray(value) ? value.map(copy)
    : value && typeof value === "object" ? Object.fromEntries(Object.entries(value).map(([k, v]) => [k, copy(v)])) : value;
  const dense = a => Array.isArray(a) && Array.from({ length: a.length }, (_, i) => i in a).every(Boolean);
  const finite = x => typeof x === "number" && Number.isFinite(x);
  const score = x => finite(x) && x >= 0 && x <= 100;
  function canonical(value) {
    if (Array.isArray(value)) return value.map(canonical);
    if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map(k => [k, canonical(value[k])]));
    return value;
  }
  function scope(value) {
    const fields = ["source", "sourceId", "sourceKind", "workId", "sourceWorkId", "localSourceId", "region", "regionId", "familyId",
      "sourceDocumentToken", "sourceContextKey", "sourceGeneration", "bindingGeneration"];
    return JSON.stringify(fields.map(k => [k, Object.hasOwn(value, k), canonical(value[k])]));
  }
  function protectedSignature(text) {
    return JSON.stringify([
      text.match(/[+\-−－]?\s*(?:\p{Nd}+(?:[.．]\p{Nd}*)?|[.．]\p{Nd}+)(?:\s*[%％])?/gu) || [],
      text.match(/[负正]?[零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟萬億点]+/gu) || [],
      text.match(/[A-Za-z]+|千克|公斤|毫克|毫升|分钟|小时|厘米|毫米|摄氏度|百分之|克|斤|升|杯|次|片|粒|瓶|袋|天|周|月|年|度/gu) || [],
      text.match(/不(?:能|是|会|要|再|用|需|得|可)?|没(?:有)?|无(?:需|法)?|未(?:必|能)?|非|勿|别|莫/gu) || [],
      text.match(/[我你您他她它谁咱俺]/gu) || [],
    ]);
  }
  function original(observation) {
    if (!dense(observation.alternatives)) return null;
    const values = observation.alternatives.filter(r => r?.mode === "original");
    if (values.length !== 1) return null; // Alternatives from one frame are not extra votes.
    const value = values[0];
    if (typeof value.text !== "string" || !value.text || value.text.length > 300 || /[\r\n]/u.test(value.text)
      || !value.text.trim() || !score(value.confidence) || value.confidence < 80) return null;
    return value;
  }
  function validGlyphs(reading) {
    return dense(reading.charConfidences) && reading.charConfidences.length === Array.from(reading.text).length
      && reading.charConfidences.every(g => g && typeof g.text === "string" && Array.from(g.text).length === 1 && score(g.confidence))
      && reading.charConfidences.map(g => g.text).join("") === reading.text;
  }
  // Experimental evidence-only proposal. NOT called by finalize/compute.
  // CTC time bands estimate x position; they are not detected character boxes.
  const SPATIAL_PROPOSAL_SCHEMA = "subtitle-spatial-evidence-proposal-v1";
  function checkedAlignment(reading, width, height) {
    const a = reading?.tokenAlignment, chars = Array.from(reading?.text || "");
    if (!a || a.schema !== "ctc-temporal-bands-v1" || a.sourceWidth !== width || a.sourceHeight !== height
      || ![a.sourceWidth,a.sourceHeight,a.modelWidth,a.contentWidth,a.steps].every(n => Number.isSafeInteger(n) && n > 0)
      || width > 2560 || height > 512 || a.modelWidth > 1600 || a.steps > 4096 || a.contentWidth > a.modelWidth
      || !dense(a.bands) || a.bands.length !== chars.length || !validGlyphs(reading)) return null;
    const scale = a.modelWidth/a.steps/a.contentWidth*width;
    for (let i=0; i<a.bands.length; i++) {
      const b=a.bands[i], previous=a.bands[i-1];
      if (!b || b.text !== chars[i] || !score(b.confidence) || Math.abs(b.confidence-reading.charConfidences[i].confidence) > 1e-6
        || ![b.firstStep,b.lastStep,b.peakStep].every(Number.isSafeInteger) || b.firstStep < 0 || b.lastStep >= a.steps
        || b.firstStep > b.peakStep || b.peakStep > b.lastStep || previous && b.firstStep <= previous.lastStep
        || (b.lastStep+1)*a.modelWidth > a.contentWidth*a.steps
        || ![b.left,b.right,b.peak].every(finite) || b.left < 0 || b.right > width || b.right <= b.left
        || Math.abs(b.left-b.firstStep*scale) > 1e-6 || Math.abs(b.right-(b.lastStep+1)*scale) > 1e-6
        || Math.abs(b.peak-(b.peakStep+.5)*scale) > 1e-6) return null;
    }
    return a;
  }
  function spatialProposal(observations, interval, allowSpatialOnly) {
    if (!dense(observations) || observations.length < 3 || observations.length > 13 || !finite(interval) || interval <= 0 || interval > 1) return null;
    let visual; try { visual=visualApi(); } catch (_) { return null; }
    if (!visual?.valid || !visual.same) return null;
    const first=observations[0], maxGap=Math.min(.8,interval*1.6);
    if (!first || !finite(first.time) || first.time < 0 || !Number.isSafeInteger(first.index) || first.index < 0) return null;
    let representative=null, originalVotes=0;
    const frames=[];
    for (let i=0; i<observations.length; i++) {
      const o=observations[i], previous=observations[i-1], v=o?.visualEvidence;
      if (!o || o.accepted !== true || !Number.isSafeInteger(o.index) || !finite(o.time) || !visual.valid(v) || v.spatialCropApplied
        || scope(o)!==scope(first) || o.time-first.time > MAX_EVENT_SECONDS
        || i && (o.index!==previous.index+1 || o.time<=previous.time || o.time-previous.time>maxGap
          || !visual.same(v,previous.visualEvidence) || !visual.same(v,first.visualEvidence))) return null;
      const full=original(o), candidates=(o.alternatives || []).filter(r=>r?.mode==='spatial_candidate');
      if (!full || candidates.length!==1) return null;
      const short=candidates[0], crop=short.cropEvidence, box=v.box;
      if (Object.hasOwn(short, "cropAssessment") && (short.cropAssessment?.schema !== "subtitle-crop-assessment-v1"
        || short.cropAssessment.status !== "complete" || short.cropAssessment.usableForConsolidation !== true)) return null;
      const hanCount=typeof short.text==='string' ? (short.text.match(/\p{Script=Han}/gu)||[]).length : 0;
      const visibleCharacters=typeof short.text==='string' ? (short.text.match(/[\p{L}\p{N}]/gu)||[]).length : 0;
      if (typeof short.text!=='string' || (allowSpatialOnly ? hanCount<4 || visibleCharacters<8 : hanCount<8) || /[\r\n]/u.test(short.text)
        || short.text!==short.text.trim() || !score(short.confidence) || short.confidence<95 || !validGlyphs(short)
        || short.charConfidences.some(g=>g.confidence<90)
        || /我叫|名叫|姓名|作者|嘉宾|达人|名为|叫做|先生|女士|老师|演员|明星|艺人|歌手|导演|医生/u.test(short.text+full.text)) return null;
      if (representative===null) representative=short.text;
      if (short.text!==representative || !crop || crop.schema!=='outlined-caption-spatial-crop-v1'
        || crop.inputWidth!==v.inputWidth || crop.inputHeight!==v.inputHeight
        || !crop.box || ['left','right','top','bottom'].some(k=>crop.box[k]!==box[k]) || box.right-box.left>=v.inputWidth) return null;
      const fullAlignment=checkedAlignment(full,v.inputWidth,v.inputHeight);
      const shortAlignment=checkedAlignment(short,box.right-box.left,v.inputHeight);
      if (!fullAlignment || !shortAlignment) return null;
      // Matching text must occur exactly once. No interior deletion or assembly
      // from several candidates is authorized by a bounding region.
      const start=full.text.indexOf(representative);
      if(start<0 || full.text.indexOf(representative,start+1)>=0) return null;
      const prefix=Array.from(full.text.slice(0,start)), core=Array.from(representative), suffix=Array.from(full.text.slice(start+representative.length));
      const extras=[...prefix,...suffix], extraText=extras.join('');
      if(extras.length>4 || extras.length>core.length/2) return null;
      // Chinese numerals and meaning-changing modifiers remain protected even
      // outside the estimated band. Only ASCII digit noise may be proposed.
      if(/[A-Za-z我你您他她它谁咱俺零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟萬億负正点不没无未非勿别莫能可会要须需必应得只仅限更最比较约近多至少超余再又也才还曾已都皆尽前后上下内外]/u.test(extraText)
        || /千克|公斤|毫克|毫升|分钟|小时|厘米|毫米|摄氏度|百分之|克|斤|升|杯|次|片|粒|瓶|袋|天|周|月|年|度|元/u.test(extraText)) return null;
      const glyphHeight=(v.ink.bottom-v.ink.top)/v.maskHeight*v.inputHeight, margin=glyphHeight*.5;
      const bands=fullAlignment.bands;
      for(let p=0;p<bands.length;p++) {
        const b=bands[p], inCore=p>=prefix.length && p<prefix.length+core.length;
        if(!inCore) {
          if(b.confidence>=60 || (p<prefix.length ? b.right>box.left-margin : b.left<box.right+margin)) return null;
        } else {
          const c=shortAlignment.bands[p-prefix.length], mappedPeak=c.peak+box.left;
          if(b.confidence<90 || b.left<box.left || b.right>box.right || c.left+box.left<box.left || c.right+box.left>box.right
            || Math.abs(b.peak-mappedPeak)>glyphHeight*.25) return null;
        }
      }
      if(!extras.length) {
        if(full.confidence<95 || full.charConfidences.some(g=>g.confidence<95)) return null;
        originalVotes++;
      }
      frames.push({index:o.index,time:o.time,originalText:full.text,spatialText:short.text,extraPrefix:prefix.join(''),extraSuffix:suffix.join(''),
        cropBox:copy(box),margin,spatialVote:1});
    }
    if((!allowSpatialOnly && !originalVotes) || !frames.some(f=>f.extraPrefix || f.extraSuffix)) return null;
    return {schema:SPATIAL_PROPOSAL_SCHEMA,policyVersion:POLICY_VERSION,activation:'candidate_only_not_applied',
      representativeOrigin:originalVotes ? 'full_original_anchor' : 'independent_original_color_crops',
      evidenceBranch:allowSpatialOnly ? 'spatial_only_diagnostic_v1' : 'full_original_anchor_v1',
      representative,originalFrameVotes:originalVotes,spatialFrameVotes:observations.length,observationIndices:observations.map(o=>o.index),
      firstObserved:first.time,lastObserved:observations.at(-1).time,frames,
      reasonCode:originalVotes ? 'original_anchor_same_frame_crop_and_outside_weak_ctc_bands' : 'three_original_color_crops_same_core_and_outside_weak_ctc_bands',
      limitation:'CTC时间带只是位置估计；此函数仅返回待验证候选，不改变正文或删除原始读数'};
  }
  function spatialCandidateProposal(observations, interval = .5) { return spatialProposal(observations, interval, false); }
  function spatialOnlyCandidateProposal(observations, interval = .5) { return spatialProposal(observations, interval, true); }
  function compute(segments, observations, interval) {
    const unchanged = reason => ({ segments: copy(segments), decisions: [], reason });
    if (!dense(segments) || !dense(observations) || observations.length > MAX_OBSERVATIONS
      || !finite(interval) || interval <= 0 || interval > 1) return unchanged("invalid_or_unbounded_input");
    let visual;
    try { visual = visualApi(); } catch (_) { return unchanged("visual_evidence_unavailable"); }
    if (!visual?.valid || !visual.same || !visual.sameGlyph) return unchanged("visual_evidence_unavailable");
    const byIndex = new Map(), referenced = new Set();
    for (const o of observations) {
      if (!o || !Number.isSafeInteger(o.index) || o.index < 0 || !finite(o.time) || o.time < 0 || byIndex.has(o.index))
        return unchanged("invalid_observation_identity");
      byIndex.set(o.index, o);
    }
    for (const s of segments) {
      if (!s || typeof s.text !== "string" || !dense(s.observationIndices) || !s.observationIndices.length) return unchanged("invalid_segment_identity");
      for (const index of s.observationIndices) {
        if (!Number.isSafeInteger(index) || !byIndex.has(index) || referenced.has(index)) return unchanged("duplicate_or_missing_observation");
        referenced.add(index);
      }
    }
    let line;try{line=lineApi();}catch(_){}
    const sameEvidence=(a,b)=>visual.same(a,b)||Boolean(line?.sameLine(a,b));
    const maxGap = Math.min(.8, interval * 1.6), maxSamples = Math.min(25, Math.ceil(MAX_EVENT_SECONDS / interval) + 1);
    function repeatedNearby(sample, text) {
      // A shorter greedy window must not consume the last frame of a stable
      // different reading immediately outside it (A / B B / A A).
      for (const direction of [-1, 1]) {
        let previous = sample;
        for (let n = 1; n <= maxSamples; n++) {
          const next = byIndex.get(sample.index + n*direction);
          if (!next || next.accepted !== true || !original(next) || scope(next) !== scope(previous)
            || Math.abs(next.time-sample.time) > MAX_EVENT_SECONDS || (next.time-previous.time)*direction <= 0
            || Math.abs(next.time-previous.time) > maxGap || !visual.same(next.visualEvidence,previous.visualEvidence)) break;
          if (original(next).text === text) return true;
          previous = next;
        }
      }
      return false;
    }
    const descriptors = segments.map(s => {
      const samples = s.observationIndices.map(i => byIndex.get(i));
      const valid = finite(s.firstObserved) && finite(s.lastObserved)
        && Math.abs(s.firstObserved - samples[0].time) <= .005 && Math.abs(s.lastObserved - samples.at(-1).time) <= .005
        && samples.every((o, i) => o.accepted === true && original(o) && visual.valid(o.visualEvidence)
          && (!i || (o.index === samples[i-1].index + 1 && o.time > samples[i-1].time && o.time-samples[i-1].time <= maxGap
            && scope(o) === scope(samples[i-1]) && sameEvidence(o.visualEvidence, samples[i-1].visualEvidence))));
      return { segment: s, samples, valid, scope: scope(s) };
    });
    function alignedGlyphVeto(a,b,positionA,positionB){
      const aa=original(a),bb=original(b);
      if(!aa.tokenAlignment&&!bb.tokenAlignment)return true; // legacy pixels-only evidence
      const va=a.visualEvidence,vb=b.visualEvidence;
      const ca=checkedAlignment(aa,va.inputWidth,va.inputHeight),cb=checkedAlignment(bb,vb.inputWidth,vb.inputHeight);
      return Boolean(ca&&cb&&line?.sameBand(va,vb,ca.bands[positionA],cb.bands[positionB]));
    }
    function proposal(samples) {
      if (samples.length < 3 || samples.length > maxSamples || samples.at(-1).time-samples[0].time > MAX_EVENT_SECONDS) return null;
      const sources = samples.map(original), votes = new Map();
      for (let i = 0; i < sources.length; i++) {
        const value = votes.get(sources[i].text) || { text: sources[i].text, positions: [] };
        value.positions.push(i); votes.set(value.text, value);
      }
      const ranked = [...votes.values()].sort((a,b) => b.positions.length-a.positions.length || a.positions[0]-b.positions[0]);
      const anchor = ranked[0];
      // Stable competing originals survive. Confidence is not a vote or accuracy.
      if (!anchor || anchor.positions.length < 2 || anchor.positions.length <= samples.length/2 || ranked.slice(1).some(v => v.positions.length >= 2)) return null;
      const chars = Array.from(anchor.text), signature = protectedSignature(anchor.text);
      for (let i = 0; i < samples.length; i++) {
        const source = sources[i];
        if (source.text === anchor.text) continue;
        if (repeatedNearby(samples[i], source.text)) return null;
        const other = Array.from(source.text);
        // No insertion/deletion without real character boxes; spatial candidates
        // remain diagnostic. This deliberately leaves 1777 / 一 / 又 edge noise.
        if (chars.length < 2 || other.length !== chars.length || protectedSignature(source.text) !== signature
          || /我叫|名叫|姓名|作者|嘉宾|达人|名为|叫做|先生|女士|老师|演员|明星|艺人|歌手|导演|医生/u.test(anchor.text + source.text)) return null;
        const differences = chars.map((c,p) => c === other[p] ? -1 : p).filter(p => p >= 0);
        if (differences.length !== 1) return null;
        const p = differences[0];
        if (!/^\p{Script=Han}$/u.test(chars[p]) || !/^\p{Script=Han}$/u.test(other[p])
          || !validGlyphs(source) || source.charConfidences[p].confidence >= 85) return null;
        // In addition to adjacent-frame stability, corroborate the changed glyph
        // against an actual original anchor frame. Never use a scene-level score.
        if (!anchor.positions.some(j => visual.sameGlyph(samples[i].visualEvidence, samples[j].visualEvidence, p, chars.length)
          && alignedGlyphVeto(samples[i],samples[j],p,p))) return null;
      }
      return { text: anchor.text, votes: anchor.positions.length, variantFrames: samples.length-anchor.positions.length };
    }
    function cropReading(o) {
      const v=o.visualEvidence, values=o.alternatives.filter(r=>r?.mode==='spatial_candidate');
      if(!line||values.length!==1||!visual.valid(v)||v.spatialCropApplied)return null;
      const r=values[0],c=r.cropEvidence;
      if (Object.hasOwn(r, "cropAssessment") && (r.cropAssessment?.schema !== "subtitle-crop-assessment-v1"
        || r.cropAssessment.status !== "complete" || r.cropAssessment.usableForConsolidation !== true)) return null;
      if(!c||c.schema!=='outlined-caption-spatial-crop-v1'||c.inputWidth!==v.inputWidth||c.inputHeight!==v.inputHeight
        ||!c.box||['left','right','top','bottom'].some(k=>c.box[k]!==v.box[k])||!score(r.confidence)||r.confidence<95
        ||!validGlyphs(r)||r.charConfidences.some(g=>g.confidence<80)
        ||!checkedAlignment(r,c.box.right-c.box.left,v.inputHeight)||!checkedAlignment(original(o),v.inputWidth,v.inputHeight))return null;
      const comparable=line.comparableReading(r);
      return comparable&&comparable.chars.length>=4?{reading:r,comparable}:null;
    }
    function mappedCore(o,fullView,cropped,key) {
      const full=original(o),fa=checkedAlignment(full,o.visualEvidence.inputWidth,o.visualEvidence.inputHeight);
      const ca=cropped?.reading.tokenAlignment,cv=cropped?.comparable,v=o.visualEvidence;
      if(!fa||!ca||cv.key!==key)return null;
      const start=fullView.key.indexOf(key);
      if(start<0||fullView.key.indexOf(key,start+1)>=0)return null;
      const prefix=Array.from(fullView.key.slice(0,start)),core=Array.from(key),suffix=Array.from(fullView.key.slice(start+key.length));
      if(prefix.length+suffix.length>2)return null;
      const height=(v.ink.bottom-v.ink.top)/v.maskHeight*v.inputHeight;
      for(let p=0;p<core.length;p++){
        const b=fa.bands[fullView.positions[prefix.length+p]],d=ca.bands[cv.positions[p]];
        if(!b||!d||b.text!==core[p]||d.text!==core[p]||b.left<v.box.left||b.right>v.box.right
          ||Math.abs(b.peak-(d.peak+v.box.left))>height*.25)return null;
      }
      return {fa,prefix,suffix,core,height};
    }
    function nearbyComparable(sample,key) {
      for(const direction of [-1,1]){let previous=sample;
        for(let n=1;n<=maxSamples;n++){
          const next=byIndex.get(sample.index+n*direction),r=next&&original(next);
          if(!next||next.accepted!==true||!r||scope(next)!==scope(previous)||Math.abs(next.time-sample.time)>MAX_EVENT_SECONDS
            ||(next.time-previous.time)*direction<=0||Math.abs(next.time-previous.time)>maxGap||!sameEvidence(next.visualEvidence,previous.visualEvidence))break;
          if(line.comparisonKey(r.text)===key)return true;previous=next;
        }
      }
      return false;
    }
    function lineProposal(samples) {
      if(!line||samples.length<3||samples.length>maxSamples||samples.at(-1).time-samples[0].time>MAX_EVENT_SECONDS)return null;
      const full=samples.map(original),views=full.map(r=>line.comparableReading(r)),crops=samples.map(cropReading);
      if(views.some(v=>!v||v.chars.length<4)||full.some(r=>!validGlyphs(r)))return null;
      const votes=new Map(),fullVotes=new Map();
      for(let i=0;i<samples.length;i++){
        const own=new Set([views[i].key]);if(crops[i])own.add(crops[i].comparable.key);
        for(const key of own){const row=votes.get(key)||[];row.push(i);votes.set(key,row);}
        const row=fullVotes.get(views[i].key)||[];row.push(i);fullVotes.set(views[i].key,row);
      }
      const ranked=[...votes].sort((a,b)=>b[1].length-a[1].length||a[1][0]-b[1][0]),key=ranked[0]?.[0];
      const anchors=fullVotes.get(key)||[];
      // Crops corroborate one source frame; they do not manufacture independent
      // time votes or override a stable alternate original sentence.
      if(!key||anchors.length<2||anchors.length<=samples.length/2||[...fullVotes].some(([k,v])=>k!==key&&v.length>=2)
        ||ranked[1]?.[1].length===ranked[0][1].length
        ||/我叫|名叫|姓名|作者|嘉宾|达人|名为|叫做|先生|女士|老师|演员|明星|艺人|歌手|导演|医生/u.test(full.map(r=>r.text).join('')))return null;
      const chars=Array.from(key);let edgeFrames=0,variantFrames=0;
      for(let i=0;i<samples.length;i++){
        if(views[i].key===key)continue;
        variantFrames++;
        if(nearbyComparable(samples[i],views[i].key))return null;
        const others=views[i].chars;
        if(others.length===chars.length){
          if(protectedSignature(views[i].key)!==protectedSignature(key))return null;
          const diff=chars.map((c,p)=>c===others[p]?-1:p).filter(p=>p>=0);
          if(diff.length!==1)return null;const p=diff[0],rawPosition=views[i].positions[p];
          if(!/^\p{Script=Han}$/u.test(chars[p])||!/^\p{Script=Han}$/u.test(others[p])||full[i].charConfidences[rawPosition].confidence>=85
            ||!anchors.some(j=>line.sameGlyph(samples[i].visualEvidence,samples[j].visualEvidence,p,chars.length)
              &&alignedGlyphVeto(samples[i],samples[j],rawPosition,views[j].positions[p])))return null;
        }else{
          // Edge Han noise needs actual crop receipts, unambiguous CTC-to-source
          // mapping and two full-original anchors. Digits/meaning words stay.
          if(crops.some(c=>!c||c.comparable.key!==key))return null;
          const mapped=mappedCore(samples[i],views[i],crops[i],key);if(!mapped)return null;
          const extra=mapped.prefix.join('')+mapped.suffix.join('');
          if(!extra||/[\p{N}A-Za-z我你您他她它谁咱俺零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟萬億负正点不没无未非勿别莫能可会要须需必应得只仅限更最比较约近多至少超余再又也才还曾已都皆尽前后上下内外克斤升杯次片粒瓶袋天周月年度元]/u.test(extra))return null;
          const v=samples[i].visualEvidence,inkLeft=v.ink.left/v.maskWidth*v.inputWidth,inkRight=v.ink.right/v.maskWidth*v.inputWidth;
          for(let p=0;p<others.length;p++)if(p<mapped.prefix.length||p>=mapped.prefix.length+chars.length){
            const b=mapped.fa.bands[views[i].positions[p]],left=p<mapped.prefix.length;
            if(b.confidence>=60||(left?b.right>=v.box.left||b.right>inkLeft-mapped.height*.5:b.left<=v.box.right||b.left<inkRight+mapped.height*.5))return null;
          }
          // Every clean frame must also bind the same actual core to this crop.
          if(samples.some((o,j)=>!mappedCore(o,views[j],crops[j],key)))return null;
          edgeFrames++;
        }
      }
      const actual=new Map();
      for(let i=0;i<samples.length;i++){
        const readings=[{reading:full[i],comparable:views[i]},...(crops[i]?[crops[i]]:[])],seen=new Set();
        for(const item of readings){
          if(item.comparable.key!==key||seen.has(item.reading.text))continue;seen.add(item.reading.text);
          // Do not let a high-scored crop override an unresolved core mismatch.
          if(item.reading.mode==='spatial_candidate'&&views[i].key!==key&&othersDifferInside(views[i].key,key))continue;
          const row=actual.get(item.reading.text)||{text:item.reading.text,count:0,omitted:item.comparable.omitted.length,first:i};row.count++;actual.set(row.text,row);
        }
      }
      const chosen=[...actual.values()].sort((a,b)=>b.count-a.count||a.omitted-b.omitted||a.first-b.first)[0];
      if(!chosen)return null;
      return {text:chosen.text,votes:anchors.length,variantFrames,edgeFrames,reasonCode:edgeFrames?'main_line_original_anchors_with_outside_crop_evidence':'main_line_comparison_with_original_glyph_evidence'};
    }
    function othersDifferInside(value,key){return !value.includes(key);}
    function candidates(samples) {
      const values = new Map();
      for (const o of samples) {
        const texts = new Map();
        for (const r of [o, ...(o.alternatives || [])]) {
          if (typeof r?.text !== "string" || !r.text) continue;
          // One actual frame contributes at most one count per candidate string.
          if (!texts.has(r.text)) texts.set(r.text, r);
        }
        for (const [text, r] of texts) {
          const v = values.get(text) || { text, frames: 0, confidence: 0, firstObserved: o.time, lastObserved: o.time };
          v.frames++; v.confidence += score(r.confidence) ? r.confidence : 0; v.lastObserved = o.time; values.set(text, v);
        }
      }
      return [...values.values()].map(v => ({ ...v, confidence: v.confidence/v.frames }));
    }
    const output = [], decisions = [];
    for (let i = 0; i < descriptors.length;) {
      const first = descriptors[i];
      if (!first.valid || first.segment.finalizeBarrier === true) { output.push(copy(first.segment)); i++; continue; }
      let samples = [], best = null;
      for (let j = i; j < descriptors.length; j++) {
        const d = descriptors[j], previous = samples.at(-1), head = d.samples[0];
        if (!d.valid || d.segment.finalizeBarrier === true || d.scope !== first.scope
          || (previous && (head.index !== previous.index+1 || head.time <= previous.time || head.time-previous.time > maxGap
            || scope(head) !== scope(previous) || !sameEvidence(previous.visualEvidence, head.visualEvidence)))) break;
        samples = [...samples, ...d.samples];
        if (samples.length > maxSamples || samples.at(-1).time-samples[0].time > MAX_EVENT_SECONDS) break;
        const proposed = lineProposal(samples) || proposal(samples);
        if (proposed && (j > i || d.segment.text !== proposed.text)) best = { end: j, samples: [...samples], proposed };
      }
      if (!best) { output.push(copy(first.segment)); i++; continue; }
      const parts = segments.slice(i, best.end+1), indices = best.samples.map(o => o.index);
      const id = `caption-event-v188-${indices[0]}-${indices.at(-1)}`;
      const reason = best.proposed.reasonCode ? "同一主字幕行的连续原色画面支持完整候选，比较时忽略边缘杂点与汉字间横向空白；差异仍经原图字形或实际裁切位置核对，原记录保留" : "连续画面的字幕位置与差异字形相符，采用至少两帧实际原图支持的完整句；原读数和分段保留";
      const merged = { ...copy(parts[0]), text: best.proposed.text, observedText: best.proposed.text, edgeSymbolsCleaned: false,
        firstObserved: best.samples[0].time, lastObserved: best.samples.at(-1).time,
        observationIndices: indices, eventObservationIndices: indices, confidence: Math.min(...best.samples.map(o => score(o.confidence) ? o.confidence : 0)),
        candidateGroup: true, finalizedEvent: true, eventId: id, finalizationSchema: SCHEMA, finalizationPolicy: POLICY_VERSION,
        originalFrameVotes: best.proposed.votes, retainedSegments: copy(parts), candidates: candidates(best.samples),
        reviewOptions: [...new Set(best.samples.flatMap(o => [o.text, ...(o.alternatives || []).map(r => r.text)]).filter(v => typeof v === "string" && v))],
        needsReview: true, variation: best.proposed.variantFrames > 0 || parts.some(s => s.variation), reviewReason: reason };
      output.push(merged);
      decisions.push({ eventId: id, reasonCode: best.proposed.reasonCode || "continuous_original_majority_with_glyph_evidence", reason,
        observationIndices: [...indices], baselineSegmentIndices: Array.from({ length: parts.length }, (_, k) => i+k),
        representative: merged.text, originalFrameVotes: best.proposed.votes, variantFrames: best.proposed.variantFrames });
      i = best.end+1;
    }
    return { segments: output, decisions, reason: decisions.length ? "consolidated" : "no_supported_changes" };
  }
  function finalizeSegments(segments, observations, interval = .5) { return compute(segments, observations, interval).segments; }
  function finalize(result, options = {}) {
    if (!result || typeof result !== "object" || Array.isArray(result)) return copy(result);
    const out = copy(result);
    if (!COMPLETE_STATES.has(result.state)) return out;
    if (result.finalization) {
      const f=result.finalization;
      // Only migrate a known old no-op, never a consolidated or user-retained
      // view. Exact baseline equality prevents treating edited prose as raw OCR.
      const migratable=f.schema===SCHEMA&&f.policyVersion==='0.11.187.1'&&f.status==='no_supported_changes'
        &&f.mergedEvents===0&&dense(f.decisions)&&!f.decisions.length&&dense(f.baselineSegments)
        &&JSON.stringify(canonical(f.baselineSegments))===JSON.stringify(canonical(result.segments))
        &&!result.retainedCandidateGroups&&!(options.retainedGroups?.length)&&!(options.barrierObservationIndices?.length);
      if(!migratable)return out;
      const base=restore(result),next=finalize(base,options);
      // Audit the superseded no-op without nesting/copying another full ledger.
      if(next.finalization)next.finalization.previousPolicyVersion=f.policyVersion;
      return next;
    }
    const baseline = copy(result.segments), barrier = options.barrierObservationIndices;
    // A restored historical group's start alone cannot describe its entire
    // extent. With no explicit full index boundary, preserve the whole view.
    if (Array.isArray(options.retainedGroups) && options.retainedGroups.length && !Array.isArray(barrier)) return out;
    if (barrier !== undefined && (!dense(barrier) || barrier.some(i => !Number.isSafeInteger(i) || i < 0))) return out;
    const blocked = new Set(barrier || []), input = (Array.isArray(result.segments) ? result.segments : []).map(s =>
      s?.observationIndices?.some(i => blocked.has(i)) ? { ...s, finalizeBarrier: true } : s);
    const computed = compute(Array.isArray(result.segments) ? input : result.segments, result.observations, result.interval ?? .5);
    // The barrier is a view option, not a new fact to stamp onto old segments.
    computed.segments?.forEach((s,i) => { if (s?.finalizeBarrier && !result.segments?.some(old => old.finalizeBarrier && old.observationIndices?.[0] === s.observationIndices?.[0])) delete s.finalizeBarrier; });
    out.segments = computed.segments;
    out.finalization = { schema: SCHEMA, policyVersion: POLICY_VERSION, status: computed.reason,
      baselineSegments: baseline, baselineCounters: COUNTERS.map(key => ({ key, present: Object.hasOwn(result, key), value: copy(result[key]) })),
      decisions: computed.decisions, mergedEvents: computed.decisions.length,
      beforeSegments: Array.isArray(baseline) ? baseline.length : 0, afterSegments: Array.isArray(out.segments) ? out.segments.length : 0 };
    if (Array.isArray(out.segments)) {
      out.reviewSegments = out.segments.filter(s => s?.needsReview).length;
      out.variationSegments = out.segments.filter(s => s?.variation).length;
      out.variationFrames = out.segments.filter(s => s?.variation).reduce((n,s) => n+(s.observationIndices?.length || 0), 0);
      out.candidateGroups = out.segments.filter(s => s?.candidateGroup).length;
      out.consolidatedSegments = out.segments.filter(s => s?.candidateGroup || s?.consensusBridge).length;
    }
    return out;
  }
  function restore(result) {
    const out = copy(result);
    if (!out?.finalization || out.finalization.schema !== SCHEMA || !dense(out.finalization.baselineSegments)) return out;
    out.segments = copy(out.finalization.baselineSegments);
    delete out.finalization;
    // Restore exact baseline counters, not a second heuristic interpretation.
    for (const entry of Array.isArray(result.finalization.baselineCounters) ? result.finalization.baselineCounters : []) {
      if (!entry || !COUNTERS.includes(entry.key)) continue;
      if (entry.present) out[entry.key] = copy(entry.value); else delete out[entry.key];
    }
    return out;
  }
  return { SCHEMA, POLICY_VERSION, SPATIAL_PROPOSAL_SCHEMA, spatialCandidateProposal, spatialOnlyCandidateProposal, finalize, finalizeSegments, restore };
});
