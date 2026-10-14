/* R5 selector baseline plus v195 lanes and v199 substantive-language anchor competition. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.BrandbaiCaptionRoleV7=factory();})(typeof globalThis!=='undefined'?globalThis:this,function(){
'use strict';const definitions={"associate-text-lines-v2.cjs":function(require,module,exports){
'use strict';
const numeric=require('./deterministic-geometry.js');

// V2 resource-only fork of frozen V1. Closed history never consumes active matching slots.
// Candidate association only: no OCR, text comparison, caption-role decision,
// physical ownership, deletion, or interpolation across missing/uncertain frames.
const LIMITS = Object.freeze({ frames: 6000, rows: 6000, rowsPerFrame: 128, tracks: 6000,
  pairChecks: 100000, readsPerRow: 4, textCodePoints: 512, jsonNodes: 250000,
  jsonSlots: 1000000, jsonCharacters: 12000000, depth: 64 });
const POLICY = Object.freeze({ verticalHeightUnits: .65, heightRatio: 1.45,
  anchorWidthFraction: .035, minimumAnchorPixels: 6, angleRadians: .12,
  ambiguityCostMargin: .12, maximumTimeGapIntervals: 1.16, profilePoints: 3,
  matching: 'mutual_unique_best_geometry_candidates_not_greedy',
  sameFrameRowsPerTrack: 1, textUsedForAssociation: false,
  activeMatchTrackLimit: 128, lifetimeTrackLimit: 6000, closedTracksConsumeActiveBudget: false,
  uncertainFrameBreaks: true, geometryProxyNotFont: true,
  sourcePixelsVerifiedHere: false,
  physicalOwnershipClaim: false, captionRoleConfirmed: false, textCorrectnessClaim: false,
  fullVideoCoverageClaim: false, defaultMainTrack: null });
function fail(code, message) { const e = new TypeError(message); e.code = code; throw e; }
function check(v, code, message) { if (!v) fail(code, message); }
const finite = v => typeof v === 'number' && Number.isFinite(v);
const id = v => typeof v === 'string' && v.length > 0 && v.length <= 256;
const sha = v => typeof v === 'string' && /^[a-f0-9]{64}$/i.test(v);
const integer = (v, lo, hi) => Number.isSafeInteger(v) && v >= lo && v <= hi;
const median = values => { const a = values.slice().sort((x, y) => x - y); return (a[Math.floor((a.length - 1) / 2)] + a[Math.floor(a.length / 2)]) / 2; };
function clone(input) {
  let nodes = 0, slots = 0, chars = 0; const seen = new Map(), active = new Set();
  function copy(v, depth) {
    check(depth <= LIMITS.depth, 'depth_budget', 'Plain evidence exceeds depth budget');
    if (typeof v === 'string') { chars += v.length; check(chars <= LIMITS.jsonCharacters, 'character_budget', 'Plain evidence exceeds character budget'); return v; }
    if (finite(v) || v === null || v === undefined || typeof v === 'boolean') return v;
    check(v && typeof v === 'object', 'invalid_plain_value', 'Only finite plain JSON-like evidence is supported');
    check(!active.has(v), 'cyclic_input', 'Cyclic evidence'); if (seen.has(v)) return seen.get(v);
    const array = Array.isArray(v), proto = Object.getPrototypeOf(v);
    check(proto === Object.prototype || proto === null || array && proto === Array.prototype, 'invalid_plain_prototype', 'Plain evidence required');
    check(++nodes <= LIMITS.jsonNodes, 'node_budget', 'Plain evidence exceeds node budget');
    check(!array || v.length <= LIMITS.jsonSlots, 'array_budget', 'Plain evidence exceeds array budget');
    const out = array ? new Array(v.length) : Object.create(proto); seen.set(v, out); active.add(v);
    for (const key of Reflect.ownKeys(v)) {
      if (array && key === 'length') continue;
      const d = Object.getOwnPropertyDescriptor(v, key);
      check(typeof key === 'string' && d && 'value' in d && d.enumerable, 'invalid_plain_descriptor', 'No accessors, symbols, or hidden evidence fields');
      check(++slots <= LIMITS.jsonSlots, 'slot_budget', 'Plain evidence exceeds slot budget'); chars += key.length;
      check(chars <= LIMITS.jsonCharacters, 'character_budget', 'Plain evidence exceeds character budget');
      Object.defineProperty(out, key, { value: copy(d.value, depth + 1), enumerable: true, writable: true, configurable: true });
    }
    active.delete(v); return out;
  }
  return copy(input, 0);
}
function regionValid(r) { return r && !Array.isArray(r) && ['left', 'top', 'right', 'bottom'].every(k => finite(r[k]) && r[k] >= 0 && r[k] <= 1) && r.right > r.left && r.bottom > r.top; }
function binding(v, f, source, required = false) {
  for (const [key, expected] of [['sourceSha256', source], ['sourceFrameId', f.sourceFrameId], ['time', f.time]]) {
    check(!required && v[key] === undefined || v[key] === expected, 'foreign_source_frame_or_time', `Incorrect ${key} binding`);
  }
  if (v.frameId !== undefined) check(v.frameId === f.sourceFrameId, 'foreign_source_frame_or_time', 'Incorrect frameId binding');
  if (v.sourceWidth !== undefined) check(v.sourceWidth === f.width, 'source_grid_mismatch', 'Incorrect source width');
  if (v.sourceHeight !== undefined) check(v.sourceHeight === f.height, 'source_grid_mismatch', 'Incorrect source height');
}
function quadValid(q, f) {
  return Array.isArray(q) && q.length === 4 && q.every(p => p && finite(p.x) && finite(p.y) &&
    Math.abs(p.x) <= f.width * 2 && Math.abs(p.y) <= f.height * 2) &&
    Math.abs(q[0].x + q[2].x - q[1].x - q[3].x) <= 1e-5 &&
    Math.abs(q[0].y + q[2].y - q[1].y - q[3].y) <= 1e-5 &&
    (q[1].x - q[0].x) * (q[3].y - q[0].y) - (q[1].y - q[0].y) * (q[3].x - q[0].x) > 1e-6;
}
function geometry(candidate, f) {
  const q = candidate.sourceRectQuad;
  check(quadValid(q, f) && quadValid(candidate.sourceRectReadQuad, f), 'invalid_own_quad', 'Ordered native parallelogram quads required');
  check(finite(candidate.sourceMinSide) && candidate.sourceMinSide > 0 && finite(candidate.angleRadians) && Math.abs(candidate.angleRadians) <= Math.PI,
    'invalid_geometry_proxy', 'Positive native minimum side and measured angle required');
  const native=numeric.nativeRectangle(q)&&numeric.nativeRectangle(candidate.sourceRectReadQuad)&&q.every((p,i)=>p.x===candidate.sourceRectReadQuad[i].x&&p.y===candidate.sourceRectReadQuad[i].y);
  const measuredSide = native?Math.min(q[1].x-q[0].x,q[3].y-q[0].y):Math.min(Math.hypot(q[1].x - q[0].x, q[1].y - q[0].y), Math.hypot(q[2].x - q[1].x, q[2].y - q[1].y));
  check(Math.abs(candidate.sourceMinSide - measuredSide) <= 1e-5, 'geometry_proxy_mismatch', 'Minimum side must match its own original quad');
  const measuredAngle = native?0:Math.atan2(candidate.sourceRectReadQuad[1].y - candidate.sourceRectReadQuad[0].y, candidate.sourceRectReadQuad[1].x - candidate.sourceRectReadQuad[0].x);
  check(Math.abs(candidate.angleRadians - measuredAngle) <= 1e-5, 'geometry_proxy_mismatch', 'Angle must match its own source quad');
  const bbox = { left: Math.max(0, Math.min(...candidate.sourceRectReadQuad.map(p => p.x))) / f.width,
    right: Math.min(f.width, Math.max(...candidate.sourceRectReadQuad.map(p => p.x))) / f.width,
    top: Math.max(0, Math.min(...candidate.sourceRectReadQuad.map(p => p.y))) / f.height,
    bottom: Math.min(f.height, Math.max(...candidate.sourceRectReadQuad.map(p => p.y))) / f.height };
  check(Object.keys(bbox).every(k => Math.abs(candidate.region[k] - bbox[k]) <= 1e-8), 'geometry_region_mismatch', 'ROI must match its own quad bounded bbox');
  const left = Math.min(...q.map(p => p.x)), right = Math.max(...q.map(p => p.x));
  let angle = candidate.angleRadians;
  while (angle < -Math.PI / 2) angle += Math.PI;
  while (angle >= Math.PI / 2) angle -= Math.PI;
  return { centerY: q.reduce((s, p) => s + p.y, 0) / 4 / f.height,
    height: (native?q[3].y-q[0].y:Math.hypot(q[3].x - q[0].x, q[3].y - q[0].y)) / f.height,
    ...(native?{nativeHeightTwice:2*(q[3].y-q[0].y),nativeSourceHeight:f.height}:{}),
    minimumSide: candidate.sourceMinSide / f.height, left: left / f.width,
    centerX: (left + right) / 2 / f.width, right: right / f.width, angle,
    kind: 'native_rectangle_geometry_proxy_not_font_or_single_line', physicalOwnershipCertified: false };
}
function profile(points) {
  const tail = points.slice(-POLICY.profilePoints);
  const out = Object.fromEntries(['centerY', 'height', 'left', 'centerX', 'right'].map(k => [k, median(tail.map(p => p[k]))]));
  const base = tail.at(-1).angle;
  out.angle = median(tail.map(p => { let a = p.angle; while (a - base < -Math.PI / 2) a += Math.PI; while (a - base >= Math.PI / 2) a -= Math.PI; return a; }));
  while (out.angle < -Math.PI / 2) out.angle += Math.PI;
  while (out.angle >= Math.PI / 2) out.angle -= Math.PI;
  if(tail.every(p=>Number.isSafeInteger(p.nativeHeightTwice)&&p.nativeSourceHeight===tail[0].nativeSourceHeight))Object.assign(out,{nativeHeightTwice:median(tail.map(p=>p.nativeHeightTwice)),nativeSourceHeight:tail[0].nativeSourceHeight});
  return out;
}
function compareGeometry(current, previous, sourceWidth) {
  check(integer(sourceWidth, 1, 4096) && [current, previous].every(p => p && ['centerY', 'height', 'left', 'centerX', 'right', 'angle'].every(k => finite(p[k])) &&
    p.height > 0 && Math.abs(p.angle) <= Math.PI / 2 && p.left <= p.centerX && p.centerX <= p.right),
    'invalid_geometry_proxy', 'Finite positive geometry proxies and native width required');
  const dy = Math.abs(current.centerY - previous.centerY) / Math.max(current.height, previous.height),
    heightLog = Math.abs(numeric.logarithm(current.height / previous.height)),
    anchors = ['left', 'centerX', 'right'].map(kind => ({ kind, distance: Math.abs(current[kind] - previous[kind]) })),
    anchor = anchors.sort((a, b) => a.distance - b.distance || numeric.compareIds(a.kind,b.kind))[0],
    anchorGate = Math.max(POLICY.anchorWidthFraction, POLICY.minimumAnchorPixels / sourceWidth),
    rawAngle = Math.abs(current.angle - previous.angle), angle = Math.min(rawAngle, Math.PI - rawAngle),
    reasons = [];
  if (dy > POLICY.verticalHeightUnits) reasons.push('vertical_position');
  if (!numeric.ratioWithin(current, previous, 29, 20)) reasons.push('height_proxy');
  if (anchor.distance > anchorGate) reasons.push('horizontal_anchor');
  if (angle > POLICY.angleRadians) reasons.push('angle_proxy');
  return { eligible: !reasons.length, cost: numeric.finiteCost(dy / POLICY.verticalHeightUnits * .45 + heightLog / numeric.logarithm(POLICY.heightRatio) * .2 +
      anchor.distance / anchorGate * .25 + angle / POLICY.angleRadians * .1),
    verticalHeightUnits: dy, heightLogRatio: heightLog, anchor: anchor.kind, anchorDistance: anchor.distance,
    anchorGate, angleDifference: angle, reasons };
}
function associate(input) {
  let own = null, rawResults = null;
  try {
    own = clone(input); rawResults = own?.results;
    check(own && !Array.isArray(own) && sha(own.sourceSha256), 'invalid_source_sha', 'Exact source SHA required');
    check(finite(own.duration) && own.duration > 0 && own.duration <= 180 && finite(own.samplingInterval) && own.samplingInterval > 0 && own.samplingInterval <= 2,
      'invalid_sampling_metadata', 'Bounded duration and sampling interval required');
    check(['continuous_sampled', 'sparse_focus'].includes(own.samplingScope), 'invalid_sampling_scope', 'Explicit sampling scope required');
    check(Array.isArray(rawResults) && rawResults.length <= LIMITS.frames, 'frame_budget_or_type', 'Bounded result array required');
    const limits = { tracks: LIMITS.tracks, pairChecks: LIMITS.pairChecks };
    if (own.limits !== undefined) {
      check(own.limits && !Array.isArray(own.limits) && Object.keys(own.limits).every(k => k in limits && integer(own.limits[k], 1, limits[k])),
        'invalid_or_raised_limits', 'Only lower track/pair-check budgets are allowed'); Object.assign(limits, own.limits);
    }
    if (own.expectedFrameTimes !== undefined) {
      check(Array.isArray(own.expectedFrameTimes) && own.expectedFrameTimes.length <= LIMITS.frames, 'invalid_sampling_plan', 'Bounded expected actual times required');
      let last = -Infinity;
      for (const time of own.expectedFrameTimes) { check(finite(time) && time >= 0 && time < own.duration && time > last, 'invalid_sampling_plan', 'Expected times must strictly increase within source'); last = time; }
    }
    const frames = [], frameIds = new Set(); let lastTime = -Infinity, nativeGrid = null, rowTotal = 0;
    for (const [resultIndex, result] of rawResults.entries()) {
      check(result && id(result.sourceFrameId) && !frameIds.has(result.sourceFrameId), 'duplicate_or_invalid_frame', 'Unique exact sourceFrameId required; include actual PTS in saved-image identity');
      check(finite(result.time) && result.time >= 0 && result.time < own.duration && result.time > lastTime,
        'frame_time_order', 'Actual times must strictly increase within source duration');
      const saved = /^native-rgba-([a-f0-9]{64})(?:-pts-(.+))?$/i.exec(result.sourceFrameId);
      check(saved && sha(result.sourcePixelSha256) && saved[1] === result.sourcePixelSha256 &&
        (saved[2] === undefined || /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(saved[2]) && Number(saved[2]) === result.time),
        'saved_image_identity_mismatch', 'Native RGBA SHA and optional exact PTS must match own ledger fields');
      check(integer(result.width, 1, 4096) && integer(result.height, 1, 4096), 'invalid_native_grid', 'Bounded native dimensions required');
      check(!nativeGrid || result.width === nativeGrid.width && result.height === nativeGrid.height, 'native_grid_changed', 'Source grid must stay unchanged');
      binding(result, result, own.sourceSha256, true);
      const det = result.detection, status = det?.status ?? result.detectionStatus;
      check(['complete', 'partial', 'invalid', 'failed', 'not_attempted'].includes(status), 'invalid_detection_status', 'Explicit detection state required');
      const detRows = det?.candidates || [];
      check(Array.isArray(detRows) && detRows.length <= LIMITS.rowsPerFrame && Array.isArray(result.rows) && result.rows.length <= LIMITS.rowsPerFrame,
        'per_frame_row_budget', 'Detector/readout arrays must remain within native per-frame budget');
      const candidateIds = new Set(), readouts = new Map();
      for (const [rowIndex, raw] of result.rows.entries()) {
        check(raw && id(raw.candidateId) && !readouts.has(raw.candidateId), 'duplicate_or_invalid_readout', 'Readout must reference one unique own candidate');
        binding(raw, result, own.sourceSha256); readouts.set(raw.candidateId, { raw, rowIndex });
      }
      const frame = { sourceFrameId: result.sourceFrameId, sourceSha256: own.sourceSha256, time: result.time, width: result.width, height: result.height,
        detectionStatus: status === 'complete' ? 'completed' : status === 'invalid' ? 'failed' : status,
        inputImageSha256: result.sourcePixelSha256, originalRef: { resultIndex, sourceFrameId: result.sourceFrameId, time: result.time,
          sourceSha256: own.sourceSha256, sourcePixelSha256: result.sourcePixelSha256, id: result.id }, rows: [] };
      for (const [candidateIndex, candidate] of detRows.entries()) {
        check(candidate && id(candidate.id) && !candidateIds.has(candidate.id), 'duplicate_or_invalid_candidate', 'Unique own geometry candidate required');
        binding(candidate, result, own.sourceSha256, true);
        check(regionValid(candidate.region) && (candidate.region.right - candidate.region.left) * result.width >= 1 - 1e-9 &&
          (candidate.region.bottom - candidate.region.top) * result.height >= 1 - 1e-9, 'invalid_own_region', 'Positive representable own native region required');
        const proxy = geometry(candidate, result), match = readouts.get(candidate.id), raw = match?.raw,
          readStatus = raw ? raw.readStatus : 'unread', reads = raw ? clone(raw.reads) : [];
        if (raw?.sourceRectGeometry?.sourceRectReadQuad !== undefined) check(JSON.stringify(raw.sourceRectGeometry.sourceRectReadQuad) === JSON.stringify(candidate.sourceRectReadQuad),
          'readout_geometry_mismatch', 'Actual readout quad must match its own detector candidate');
        if (raw?.region !== undefined) check(JSON.stringify(raw.region) === JSON.stringify(candidate.region),
          'readout_geometry_mismatch', 'Actual readout ROI must match its own detector candidate');
        check(['read', 'empty', 'unread', 'failed'].includes(readStatus) && Array.isArray(reads) && reads.length <= LIMITS.readsPerRow,
          'invalid_read_status_or_budget', 'Explicit bounded raw read state required');
        const modes = new Set(); let nonempty = 0;
        for (const read of reads) {
          check(read && id(read.mode) && !modes.has(read.mode), 'duplicate_or_invalid_mode', 'Unique actual mode required');
          const data = read.rawData;
          check(data && typeof data.text === 'string' && [...data.text].length <= LIMITS.textCodePoints && finite(data.confidence) && data.confidence >= 0 && data.confidence <= 100,
            'invalid_raw_reading', 'Literal bounded text and legal confidence required');
          binding(read, result, own.sourceSha256); binding(data, result, own.sourceSha256);
          check(data.mode === undefined || data.mode === read.mode, 'raw_mode_mismatch', 'Raw mode label mismatch');
          nonempty += data.text.trim() ? 1 : 0; modes.add(read.mode);
        }
        check(readStatus !== 'read' || nonempty > 0, 'read_without_text', 'Read state cannot invent text');
        check(readStatus !== 'empty' || reads.length > 0 && !nonempty, 'empty_without_returned_empty', 'Empty needs an actual empty OCR return');
        check(readStatus !== 'unread' || reads.length === 0, 'unread_with_returned_pass', 'Unattempted is not empty or returned text');
        check(++rowTotal <= LIMITS.rows, 'total_row_budget', 'Total raw rows exceed downstream budget; do not truncate');
        frame.rows.push({ id: candidate.id, candidateId: candidate.id, region: clone(candidate.region), sourceRectReadQuad: clone(candidate.sourceRectReadQuad),
          sourceRectQuad: clone(candidate.sourceRectQuad), angleRadians: candidate.angleRadians, geometryProxy: proxy,
          sourceFrameId: result.sourceFrameId, sourceSha256: own.sourceSha256, time: result.time, readStatus, reads,
          reason: raw?.error ?? (raw ? undefined : 'no_own_readout'),
          originalRef: { resultIndex, candidateIndex, rowIndex: match?.rowIndex ?? null, candidateId: candidate.id,
            sourceFrameId: result.sourceFrameId, sourceSha256: own.sourceSha256, time: result.time,
            imagePath: raw?.imagePath, sourcePixelSha256: raw?.sourcePixelSha256, sourceRectGeometry: clone(raw?.sourceRectGeometry) } });
        candidateIds.add(candidate.id);
      }
      for (const candidateId of readouts.keys()) check(candidateIds.has(candidateId), 'orphan_readout', 'Readout has no own-frame detector candidate');
      frames.push(frame); frameIds.add(result.sourceFrameId); lastTime = result.time; nativeGrid = result;
    }
    const tracks = [], associations = [], trackBreaks = [], unassignedRows = [], warnings = [], active = new Map();
    let pairChecks = 0, maximumActiveTracksObserved = 0, associationBudgetExhausted = false, partial = frames.some(f => f.detectionStatus !== 'completed');
    const ref = (f, r) => ({ sourceSha256: own.sourceSha256, sourceFrameId: f.sourceFrameId, time: f.time, rowId: r.id });
    const breakTrack = (track, beforeFrame, reason) => {
      track.state = 'ended'; trackBreaks.push({ trackId: track.id, after: track.rowRefs.at(-1), beforeFrame: beforeFrame?.originalRef ?? null, reason });
    };
    for (let frameIndex = 0; frameIndex < frames.length; frameIndex++) {
      const frame = frames[frameIndex], previous = frames[frameIndex - 1], gap = previous ? frame.time - previous.time : null;
      const boundary = !previous ? 'first_frame' : gap > own.samplingInterval * POLICY.maximumTimeGapIntervals + 1e-9 ? 'actual_time_gap' :
        previous.detectionStatus !== 'completed' || frame.detectionStatus !== 'completed' ? 'uncertain_detection_boundary' : !previous.rows.length ? 'previous_frame_no_geometry' : null;
      const prior = boundary ? [] : [...active.values()], matches = frame.rows.map(() => []), rejectedCounts = frame.rows.map(() => ({}));
      let frameBudgetUnresolved = associationBudgetExhausted;
      outer: for (let rowIndex = 0; rowIndex < frame.rows.length; rowIndex++) for (const track of prior) {
        if (pairChecks >= limits.pairChecks) { associationBudgetExhausted = true; frameBudgetUnresolved = true; partial = true; break outer; }
        pairChecks++; const metric = compareGeometry(frame.rows[rowIndex].geometryProxy, profile(track._profiles), frame.width);
        if (metric.eligible) matches[rowIndex].push({ trackId: track.id, predecessorRef: track.rowRefs.at(-1), ...metric });
        else for (const reason of metric.reasons) rejectedCounts[rowIndex][reason] = (rejectedCounts[rowIndex][reason] || 0) + 1;
      }
      matches.forEach(list => list.sort((a, b) => a.cost - b.cost || numeric.compareIds(a.trackId,b.trackId)));
      const trackMatches = new Map();
      matches.forEach((list, rowIndex) => list.forEach(m => {
        if (!trackMatches.has(m.trackId)) trackMatches.set(m.trackId, []); trackMatches.get(m.trackId).push({ rowIndex, cost: m.cost });
      }));
      trackMatches.forEach(list => list.sort((a, b) => a.cost - b.cost || a.rowIndex - b.rowIndex));
      const next = new Map();
      check(prior.length <= LIMITS.rowsPerFrame, 'active_track_budget', 'Active match candidates exceed native per-frame row budget');
      maximumActiveTracksObserved = Math.max(maximumActiveTracksObserved, active.size);
      for (const [rowIndex, row] of frame.rows.entries()) {
        const rowRef = ref(frame, row), list = matches[rowIndex], best = list[0], contest = best && trackMatches.get(best.trackId);
        let decision = 'new_track', reason = boundary || 'no_eligible_geometric_predecessor', chosen = null;
        if (frameBudgetUnresolved) { reason = 'association_budget_unchecked'; decision = 'ambiguous_new_track'; }
        else if (best) {
          if (list.length > 1 && list[1].cost - best.cost <= POLICY.ambiguityCostMargin + 1e-9) { decision = 'ambiguous_new_track'; reason = 'multiple_close_predecessor_tracks'; }
          else if (contest.length > 1 && contest[1].cost - contest[0].cost <= POLICY.ambiguityCostMargin + 1e-9) { decision = 'ambiguous_new_track'; reason = 'multiple_close_current_rows'; }
          else if (contest[0].rowIndex !== rowIndex) { decision = 'ambiguous_new_track'; reason = 'not_mutual_unique_best'; }
          else { decision = 'associated_geometry_candidate'; reason = 'mutual_unique_best'; chosen = active.get(best.trackId); }
        }
        if (chosen) { chosen.rowRefs.push(rowRef); chosen._profiles.push(row.geometryProxy); chosen._profiles = chosen._profiles.slice(-POLICY.profilePoints); }
        else if (tracks.length < limits.tracks) {
          chosen = { id: 'geometry-track-' + String(tracks.length + 1).padStart(4, '0'), rowRefs: [rowRef],
            state: 'open_at_end', associationOnly: true, style: 'geometry_proxy_only_not_font_or_caption_role',
            physicalOwnershipCertified: false, captionRoleConfirmed: false, _profiles: [row.geometryProxy] }; tracks.push(chosen);
        } else {
          partial = true; decision = 'unassigned'; reason = 'lifetime_track_budget';
          unassignedRows.push({ rowRef, reason, predecessorCandidates: list });
        }
        if (chosen) next.set(chosen.id, chosen);
        associations.push({ rowRef, frameIndex, rowIndex, decision, reason, trackId: chosen?.id ?? null,
          geometryProxy: row.geometryProxy, predecessorCandidates: list,
          consideredTrackIds: prior.map(t => t.id), rejectedByGate: rejectedCounts[rowIndex],
          comparisonComplete: !frameBudgetUnresolved, frameBoundary: boundary,
          policy: POLICY.matching, ownershipConfirmed: false, textUsed: false });
      }
      for (const track of active.values()) if (!next.has(track.id)) breakTrack(track, frame,
        boundary || (frameBudgetUnresolved ? 'association_budget_unchecked' : frame.rows.length ? 'no_mutual_current_row' : 'current_frame_no_geometry'));
      check(next.size <= LIMITS.rowsPerFrame, 'active_track_budget', 'New active tracks exceed native per-frame row budget');
      maximumActiveTracksObserved = Math.max(maximumActiveTracksObserved, next.size);
      active.clear(); next.forEach((track, key) => active.set(key, track));
    }
    tracks.forEach(track => { delete track._profiles; });
    if (associationBudgetExhausted) warnings.push({ reason: 'association_pair_budget', limit: limits.pairChecks, rawRowsRetained: true });
    if (unassignedRows.length) warnings.push({ reason: 'lifetime_track_budget', limit: limits.tracks, rawRowsRetained: true, count: unassignedRows.length });
    const roleInput = { sourceSha256: own.sourceSha256, duration: own.duration, samplingInterval: own.samplingInterval,
      samplingScope: own.samplingScope, ...(own.expectedFrameTimes === undefined ? {} : { expectedFrameTimes: own.expectedFrameTimes }),
      frames, tracks, links: [] };
    return { schemaVersion: 2, status: partial ? 'partial' : 'complete', ...roleInput, roleInput, associations, trackBreaks, unassignedRows,
      rawResults, rawResultsRetained: true, inputWasTruncated: false, defaultMainTrack: null, policy: POLICY,
      warnings, limits: { ...LIMITS, ...limits },
      resourceBudget: { activeMatchTracks: LIMITS.rowsPerFrame, lifetimeTracks: limits.tracks, totalRows: LIMITS.rows,
        maximumActiveTracksObserved, closedTracksConsumeActiveBudget: false, historicalTracksRetained: true },
      roleSummaryCompatibility: { legacyRoleModule: 'caption-role-evidence-v1.cjs', legacyTrackLimit: 240,
        actualTracks: tracks.length, compatible: tracks.length <= 240, status: tracks.length > 240 ? 'over_budget' : 'not_run',
        reason: tracks.length > 240 ? 'legacy_role_track_budget' : null, summaryPerformed: false,
        rawRowsRetained: true, inputWasTruncated: false },
      diagnostics: { frames: frames.length, rows: rowTotal, tracks: tracks.length,
        associatedRows: associations.filter(a => a.decision === 'associated_geometry_candidate').length,
        ambiguousRows: associations.filter(a => a.decision === 'ambiguous_new_track').length,
        unassignedRows: unassignedRows.length, pairChecks, associationBudgetExhausted, maximumActiveTracksObserved,
        styleMeaning: 'measured_geometry_proxy_not_font', expectedTextUsed: false, textCorrectnessClaim: false,
        captionRoleConfirmed: false, fullVideoCoverageClaim: false } };
  } catch (error) {
    return { schemaVersion: 2, status: 'invalid_input', error: { code: error.code || 'invalid_input', message: String(error.message || error) },
      frames: [], tracks: [], links: [], roleInput: null, rawResults, rawResultsRetained: Array.isArray(rawResults), inputWasTruncated: false,
      originalInputRetainedByCaller: true, defaultMainTrack: null, policy: POLICY, associationPerformed: false };
  }
}
module.exports = Object.freeze({ schemaVersion: 2, LIMITS, POLICY, compareGeometry, associate });



},
"main-caption-selector-v4.cjs":function(require,module,exports){
'use strict';
const numeric=require('./deterministic-geometry.js');
// Experimental region proposals, NOT an OCR correction or destructive text filter.
// Neither video names, expected sentences, evaluation labels nor a bottom-screen prior are inputs.
const { associate } = require('./associate-text-lines-v2.cjs');
const POLICY = Object.freeze({
  version: 4, verticalHeightUnits: .7, seedVerticalHeightUnits: 1,
  heightRatio: 1.65, anchorFraction: .04, angleRadians: .14,
  minimumObservedFrames: 6, minimumFrameFraction: .10,
  minimumStableEvents: 3, minimumSubstantialTransitions: 2,
  minimumTimelineBins: 2, timelineBins: 8,
  eventSimilarity: .22, eventMaximumGapIntervals: 1.18,
  stableEventDistinctFrames: 2, minimumReadConfidence: 55,
  maximumFamilies: 6000, maximumGeometryChecks: 3000000,
  primaryDominanceRatio: 1.3, secondaryRelativeScore: .4,
  geometryAmbiguityMargin: .10, maximumTextCodePoints: 512,
  allRowsRetained: true, changesText: false, globalDeduplication: false,
  usesFilenameOrExpectedText: false, bottomRegionPrior: false,
});
const median = a => { const x = a.slice().sort((p,q)=>p-q); return x.length ? (x[(x.length-1)>>1]+x[x.length>>1])/2 : 0; };
const key = s => s.normalize('NFKC').replace(/[\p{P}\p{Z}\s]/gu,'');
function distance(a,b) {
  const x=[...a],y=[...b]; let v=Array.from({length:y.length+1},(_,i)=>i);
  for(let i=0;i<x.length;i++){const n=[i+1];for(let j=0;j<y.length;j++)n[j+1]=Math.min(n[j]+1,v[j+1]+1,v[j]+(x[i]===y[j]?0:1));v=n;}return v[y.length];
}
function similar(a,b) {
  const x=key(a),y=key(b); if(x===y)return true;
  if(Math.min([...x].length,[...y].length)<4)return false;
  return distance(x,y)/Math.max([...x].length,[...y].length)<=POLICY.eventSimilarity;
}
function reading(row) {
  if(row.readStatus!=='read')return {selected:null,modeConflict:false};
  const candidates=row.reads.map((r,i)=>({text:r.rawData.text,confidence:r.rawData.confidence,mode:r.mode,readIndex:i}))
    .filter(r=>key(r.text)&&r.confidence>=POLICY.minimumReadConfidence);
  // Original pixels are not destroyed for colored subtitles; disagreement remains visible.
  const selected=candidates.find(r=>r.mode==='original')||candidates.slice().sort((a,b)=>b.confidence-a.confidence)[0]||null;
  return {selected,modeConflict:candidates.some(r=>selected&&key(r.text)!==key(selected.text))};
}
function profile(rows) { const out=Object.fromEntries(['centerY','height','left','centerX','right','angle'].map(k=>[k,median(rows.map(r=>r.geometryProxy[k]))]));const p=rows[0].geometryProxy;if(rows.every(r=>Number.isSafeInteger(r.geometryProxy.nativeHeightTwice)&&r.geometryProxy.nativeSourceHeight===p.nativeSourceHeight))Object.assign(out,{nativeHeightTwice:median(rows.map(r=>r.geometryProxy.nativeHeightTwice)),nativeSourceHeight:p.nativeSourceHeight});return out; }
function geometry(a,b,width,anchors=['left','centerX','right'],seed=b) {
  const dy=Math.abs(a.centerY-b.centerY)/Math.max(a.height,b.height),dh=Math.abs(numeric.logarithm(a.height/b.height));
  const da=Math.abs(a.angle-b.angle),gate=Math.max(POLICY.anchorFraction,6/width);
  const compatibleAnchors=anchors.filter(k=>Math.abs(a[k]-b[k])<=gate&&Math.abs(a[k]-seed[k])<=gate*1.5);
  const dx=Math.min(...compatibleAnchors.map(k=>Math.abs(a[k]-b[k])));
  return {eligible:dy<=POLICY.verticalHeightUnits&&numeric.ratioWithin(a,b,33,20)&&dx<=gate&&da<=POLICY.angleRadians,
    compatibleAnchors,cost:numeric.finiteCost(dy/POLICY.verticalHeightUnits*.5+dh/numeric.logarithm(POLICY.heightRatio)*.2+dx/gate*.2+da/POLICY.angleRadians*.1)};
}
function ref(row) {return {sourceSha256:row.sourceSha256,sourceFrameId:row.sourceFrameId,time:row.time,rowId:row.id};}
function parallelBlock(a,b) {
  const p=a.profile,q=b.profile,h=Math.max(p.height,q.height),dy=Math.abs(p.centerY-q.centerY);
  const minWidth=Math.min(p.right-p.left,q.right-q.left);
  const overlap=Math.max(0,Math.min(p.right,q.right)-Math.max(p.left,q.left));
  // Similar y is NOT a multi-line block: horizontally separate labels/columns compete.
  return dy>=h*.8&&dy<=h*3&&minWidth>0&&overlap/minWidth>=.35&&
    Math.min(...['left','centerX','right'].map(k=>Math.abs(p[k]-q[k])))<=.05;
}
function eventEvidence(rows,interval) {
  const events=[]; let active=null;
  for(const r of rows){const read=reading(r);
    if(!read.selected){active=null;continue;}
    if(!active||r.time-active.lastObserved>interval*POLICY.eventMaximumGapIntervals||!similar(active.representative.text,read.selected.text)){
      active={firstObserved:r.time,lastObserved:r.time,representative:{...read.selected,ref:ref(r)},refs:[],variants:[]};events.push(active);
    }
    active.lastObserved=r.time;active.refs.push(ref(r));
    if(!active.variants.some(v=>v.text===read.selected.text))active.variants.push({...read.selected,ref:ref(r)});
  }
  // Text is compared only to measure replacement evidence, never to erase/change output rows.
  const stable=events.filter(e=>e.refs.length>=POLICY.stableEventDistinctFrames);
  let transitions=0;const states=[];
  for(let i=0;i<stable.length;i++){
    if(!states.some(e=>similar(e.representative.text,stable[i].representative.text)))states.push(stable[i]);
    if(i&&stable[i].firstObserved-stable[i-1].lastObserved<=interval*3&&
      !similar(stable[i-1].representative.text,stable[i].representative.text))transitions++;
  }
  const largestStateFrames=Math.max(0,...states.map(s=>stable.filter(e=>similar(e.representative.text,s.representative.text)).reduce((n,e)=>n+e.refs.length,0)));
  return {events,stableEvents:stable.length,stableStates:states.length,substantialTransitions:transitions,
    dominantStateFraction:largestStateFrames/Math.max(1,rows.length)};
}
function select(input) {
  const association=associate(input);
  if(association.status==='invalid_input'||!association.roleInput)return {status:'invalid',error:association.error,policy:POLICY,
    allRowsRetained:false,originalInputRetainedByCaller:true,decisions:[],families:[]};
  const frames=association.frames,rows=frames.flatMap(f=>f.rows),families=[],ambiguous=new Set();let checks=0,exhausted=false;
  const adjacent=new Map(association.associations.filter(a=>a.decision==='associated_geometry_candidate')
    .map(a=>[a.rowRef.rowId,a.predecessorCandidates[0].predecessorRef.rowId]));
  const assigned=new Map();let continuityResolutions=0;
  // Fixed first-row anchor prevents single-linkage drift from joining moving package text into a screen band.
  for(const frame of frames)for(const row of frame.rows){
    const matches=[];
    for(const f of families){
      if(++checks>POLICY.maximumGeometryChecks){exhausted=true;break;}
      if(f.frameIds.has(row.sourceFrameId))continue;
      if(Math.abs(row.geometryProxy.centerY-f.seed.centerY)>Math.max(row.geometryProxy.height,f.seed.height)*POLICY.seedVerticalHeightUnits)continue;
      const m=geometry(row.geometryProxy,f.profile,frame.width,f.anchors,f.seed);if(m.eligible)matches.push({f,...m});
    }
    matches.sort((a,b)=>a.cost-b.cost||numeric.compareIds(a.f.id,b.f.id));
    let family=null;
    const priorFamily=assigned.get(adjacent.get(row.id)),continuousMatch=matches.find(m=>m.f===priorFamily);
    if(continuousMatch){family=continuousMatch.f;family.anchors=continuousMatch.compatibleAnchors;continuityResolutions++;}
    else if(matches.length&&!(matches[1]&&matches[1].cost-matches[0].cost<POLICY.geometryAmbiguityMargin)){family=matches[0].f;family.anchors=matches[0].compatibleAnchors;}
    else if(matches.length>1)ambiguous.add(row.id);
    if(!family){family={id:`region-${String(families.length+1).padStart(4,'0')}`,rows:[],frameIds:new Set(),seed:row.geometryProxy,profile:row.geometryProxy,anchors:['left','centerX','right']};families.push(family);}
    family.rows.push(row);family.frameIds.add(row.sourceFrameId);family.profile=profile(family.rows);
    assigned.set(row.id,family);
  }
  const expected=input.expectedFrameTimes,planMatches=Array.isArray(expected)&&expected.length===frames.length&&frames.every((f,i)=>f.time===expected[i]);
  const continuous=planMatches&&frames.length>1&&frames[0].time<=input.samplingInterval*1.18&&
    input.duration-frames.at(-1).time<=input.samplingInterval*1.18&&
    frames.every((f,i)=>f.detectionStatus==='completed'&&(!i||f.time-frames[i-1].time<=input.samplingInterval*1.18));
  const eligibleTimeline=association.status==='complete'&&input.samplingScope==='continuous_sampled'&&continuous&&!exhausted;
  const measured=families.map(f=>{
    const evidence=eventEvidence(f.rows,input.samplingInterval),bins=new Set(f.rows.map(r=>Math.min(7,Math.floor(r.time/input.duration*8))));
    const count=f.rows.length,coverage=count/Math.max(1,frames.length),modeConflicts=f.rows.filter(r=>reading(r).modeConflict).length;
    const reasons=[];
    if(count<Math.max(POLICY.minimumObservedFrames,Math.ceil(frames.length*POLICY.minimumFrameFraction)))reasons.push('too_few_observed_frames');
    if(bins.size<POLICY.minimumTimelineBins)reasons.push('too_short_temporal_distribution');
    if(evidence.stableStates<POLICY.minimumStableEvents)reasons.push('too_few_distinct_stable_text_states');
    if(evidence.substantialTransitions<POLICY.minimumSubstantialTransitions)reasons.push('too_few_supported_text_changes');
    if(evidence.dominantStateFraction>.8)reasons.push('predominantly_fixed_text');
    if(!eligibleTimeline)reasons.push('sampling_or_detection_not_complete');
    const score=coverage*(.5+.5*bins.size/8)*Math.min(12,evidence.substantialTransitions);
    return {id:f.id,profile:f.profile,compatibleAlignmentAnchors:f.anchors,rowRefs:f.rows.map(ref),observedFrames:count,frameFraction:coverage,timelineBins:bins.size,
      modeConflictFrames:modeConflicts,stableStates:evidence.stableStates,stableEvents:evidence.stableEvents,
      substantialTransitions:evidence.substantialTransitions,dominantStateFraction:evidence.dominantStateFraction,
      events:evidence.events,eligible:!reasons.length,reasons,score,proposal:'other_screen_text_retained'};
  });
  const rank=measured.filter(f=>f.eligible).sort((a,b)=>b.score-a.score||numeric.compareIds(a.id,b.id));
  let primary=null;
  if(rank[0]){
    const first=rank[0],second=rank[1];
    const overlap=second?first.rowRefs.filter(r=>second.rowRefs.some(s=>s.sourceFrameId===r.sourceFrameId)).length/Math.min(first.observedFrames,second.observedFrames):0;
    const adjacent=second&&parallelBlock(first,second);
    // Two close parallel recurring lines may be a multi-line block, not competing roles.
    if(!second||first.score>=second.score*POLICY.primaryDominanceRatio||overlap<.2||adjacent){primary=first;first.proposal='main_caption_region';}
    else {first.proposal='ambiguous_main_region';second.proposal='ambiguous_main_region';}
    if(primary)for(const f of rank.slice(1)){
      const co=primary.rowRefs.filter(r=>f.rowRefs.some(s=>s.sourceFrameId===r.sourceFrameId)).length/Math.min(primary.observedFrames,f.observedFrames);
      const near=parallelBlock(primary,f);
      // A short video phase must not compete with whole-video duration. It already passed
      // recurrence + multiple real changes, and the primary is absent on >=80% of its rows.
      if(co<.2||f.score>=primary.score*POLICY.secondaryRelativeScore&&near)f.proposal=near&&co>=.2?'parallel_caption_region':'alternate_caption_region';
      else f.proposal='other_changing_text_retained';
    }
  }
  const chosenFamilies=measured.filter(f=>['main_caption_region','parallel_caption_region','alternate_caption_region'].includes(f.proposal));
  const byRow=new Map(measured.flatMap(f=>f.rowRefs.map(r=>[r.rowId,f]))),decisions=rows.map(r=>{
    const f=byRow.get(r.id),chosen=['main_caption_region','parallel_caption_region','alternate_caption_region'].includes(f.proposal);
    const read=reading(r);let recovery=null;
    if(!chosen&&primary&&read.selected){
      // A short or restyled replacement is visible in the result, not buried in debug/raw logs.
      // A simultaneous line is not proof this row is irrelevant: multi-line captions and
      // competing overlays can coexist. Retain as visible, NOT automatically confirmed text.
      const nearby=chosenFamilies.some(c=>Math.abs(r.geometryProxy.centerY-c.profile.centerY)<=Math.max(r.geometryProxy.height,c.profile.height)*4&&
        Math.abs(r.geometryProxy.centerX-c.profile.centerX)<=.2);
      const ownEvent=f.events.find(e=>e.refs.some(s=>s.rowId===r.id));
      const brief=ownEvent&&ownEvent.lastObserved-ownEvent.firstObserved<=Math.min(6,input.duration*.2);
      const surrounds=chosenFamilies.flatMap(c=>c.rowRefs).some(s=>Math.abs(s.time-r.time)<=input.samplingInterval*5);
      if(nearby&&brief&&surrounds)recovery='short_or_restyled_caption_candidate';
    }
    return {ref:ref(r),familyId:f.id,decision:chosen?'proposed_caption':recovery?'visible_recovery_candidate':'retained_other_or_uncertain',
      reason:recovery||f.proposal,geometryAmbiguous:ambiguous.has(r.id),read,readStatus:r.readStatus};
  });
  return {schemaVersion:4,status:!eligibleTimeline?'unresolved_sampling':primary?'caption_regions_proposed':'no_unique_caption_region',
    policy:POLICY,sourceSha256:input.sourceSha256,sourceDuration:input.duration,primaryFamilyId:primary?.id??null,
    families:measured,decisions,statistics:{frames:frames.length,rows:rows.length,families:families.length,
      proposedRows:decisions.filter(r=>r.decision==='proposed_caption').length,
      visibleRecoveryRows:decisions.filter(r=>r.decision==='visible_recovery_candidate').length,retainedRows:rows.length,
      geometryAmbiguousRows:ambiguous.size,geometryChecks:checks,adjacentContinuityResolutions:continuityResolutions},
    samplingPlanComplete:continuous,allRowsRetained:true,rawTextModified:false,captionTextCorrectnessVerified:false,
    fullVideoSubtitleRecallVerified:false,productionChanged:false};
}
module.exports={POLICY,select,similar,eventEvidence};

},
"main-caption-selector-v6.cjs":function(require,module,exports){
'use strict';
const numeric=require('./deterministic-geometry.js');
// V6 keeps short time/date index blocks separate from caption body proposals.
// It is a role proposal, not transcription correction, semantic truth or export acceptance.
const base = require('./main-caption-selector-v4.cjs');
const { associate } = require('./associate-text-lines-v2.cjs');
const POLICY = Object.freeze({
  ...base.POLICY, version:6, baseVersion:4,
  phaseMinimumRows:6, phaseMinimumStableStates:3, phaseMinimumChanges:2,
  pairedMinimumFrames:2, phaseMaximumGapIntervals:1.18,
  selectedContextIntervals:6, maximumSelectedCooccurrence:.2,
  localRegionHeightUnits:4, localRegionAnchorFraction:.08,
  blockMinimumHeightUnits:.8, blockMaximumHeightUnits:3,
  blockMinimumHorizontalOverlap:.35, blockAnchorFraction:.05,
  blockMaximumHeightRatio:1.8, blockMaximumAngleDifference:.14,
  maximumPhaseChecks:3000000, maximumLinkedBlockLines:2,
  minimumIndexFrameFraction:.6, minimumIndexFrames:2,
  indexClassifierScope:'complete_clock_or_calendar_date_line_only',
  blockOwnershipUsesFrozenRawRows:true,
  existingBaseCaptionRowsNeverDemoted:true,
  promotesEntireFamily:false, promotionUsesOwnFrameGeometry:true,
  labelsAreProposals:true, textCorrectionPerformed:false,
});
const literal=s=>s.normalize('NFKC').replace(/[\p{P}\p{Z}\s]/gu,'');
const byTime=(a,b)=>a.time-b.time||numeric.compareIds(a.id,b.id);
const chosen=d=>d.decision==='proposed_caption';
function indexOnlyKind(text) {
  if(typeof text!=='string')return null;
  const value=text.normalize('NFKC').replace(/\s/gu,'');
  const clock=/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(value);
  if(clock&&Number(clock[2])<60&&(clock[3]===undefined||Number(clock[3])<60))return 'clock_or_timer';
  const month='(?:0?[1-9]|1[0-2])',day='(?:0?[1-9]|[12]\\d|3[01])';
  if(new RegExp(`^(?:\\d{4}[-/.]${month}[-/.]${day}|(?:\\d{4}年)?${month}月${day}日)$`,'u').test(value))return 'calendar_date';
  return null;
}
function block(a,b) {
  const p=a.geometryProxy,q=b.geometryProxy,h=Math.max(p.height,q.height),dy=Math.abs(p.centerY-q.centerY);
  const minWidth=Math.min(p.right-p.left,q.right-q.left);
  const overlap=Math.max(0,Math.min(p.right,q.right)-Math.max(p.left,q.left));
  const aligned=Math.min(...['left','centerX','right'].map(k=>Math.abs(p[k]-q[k])))<=POLICY.blockAnchorFraction;
  if(dy<h*POLICY.blockMinimumHeightUnits||dy>h*POLICY.blockMaximumHeightUnits||minWidth<=0||
    overlap/minWidth<POLICY.blockMinimumHorizontalOverlap||!aligned||
    Math.max(p.height,q.height)/Math.min(p.height,q.height)>POLICY.blockMaximumHeightRatio||
    Math.abs(p.angle-q.angle)>POLICY.blockMaximumAngleDifference)return null;
  return {centerY:(p.centerY+q.centerY)/2,height:h,left:Math.min(p.left,q.left),right:Math.max(p.right,q.right),
    centerX:(p.centerX+q.centerX)/2,angle:(p.angle+q.angle)/2};
}
function near(p,q,heightUnits=POLICY.localRegionHeightUnits) {
  return Math.abs(p.centerY-q.centerY)<=Math.max(p.height,q.height)*heightUnits&&
    Math.min(...['left','centerX','right'].map(k=>Math.abs(p[k]-q[k])))<=POLICY.localRegionAnchorFraction&&
    Math.max(p.height,q.height)/Math.min(p.height,q.height)<=2&&
    Math.abs(p.angle-q.angle)<=POLICY.blockMaximumAngleDifference;
}
function splitRuns(rows,interval) {
  const runs=[];let run=null;
  for(const row of rows.slice().sort(byTime)){
    if(!run||row.time-run.at(-1).time>interval*POLICY.phaseMaximumGapIntervals){run=[];runs.push(run);}
    run.push(row);
  }
  return runs;
}
function select(input) {
  const initial=base.select(input);
  if(initial.status==='invalid')return {...initial,policy:POLICY,schemaVersion:6};
  const result={...initial,policy:POLICY,schemaVersion:6,
    families:initial.families.map(f=>({...f,phaseProposalIds:[]})),
    decisions:initial.decisions.map(d=>({...d,baseDecision:d.decision,phaseEvidenceIds:[],screenInfoEvidenceIds:[]})),
    statistics:{...initial.statistics,phasePromotedRows:0,phasePromotedRowObservations:0,screenInfoRowObservations:0,phaseProposals:0,screenInfoProposals:0},
    phaseProposals:[],screenInfoProposals:[],phaseAnalysisComplete:false,phaseAnalysisReasons:[]};
  if(initial.status!=='caption_regions_proposed'){
    result.phaseAnalysisReasons.push('no_complete_unique_base_region');
    return result;
  }
  const association=associate(input);
  if(association.status!=='complete'){
    result.phaseAnalysisReasons.push('own_geometry_not_complete');return result;
  }
  const rows=association.frames.flatMap(f=>f.rows),ownRows=new Map(rows.map(r=>[r.id,r]));
  const decisionMap=new Map(result.decisions.map(d=>[d.ref.rowId,d]));
  const familyMap=new Map(result.families.map(f=>[f.id,f]));
  const selected=result.decisions.filter(chosen),selectedRows=selected.map(d=>ownRows.get(d.ref.rowId));
  const baseSelectedIds=new Set(selected.map(d=>d.ref.rowId));
  const byFrame=new Map(association.frames.map(f=>[f.sourceFrameId,f.rows]));
  const selectedByFrame=new Map(association.frames.map(f=>[f.sourceFrameId,f.rows.filter(r=>chosen(decisionMap.get(r.id)))]));
  // All links use the frozen base-selected rows. Promoted rows never bootstrap further promotion.
  const selectedByFamily=new Map();
  for(const d of selected){if(!selectedByFamily.has(d.familyId))selectedByFamily.set(d.familyId,[]);selectedByFamily.get(d.familyId).push(ownRows.get(d.ref.rowId));}
  let checks=0,exhausted=false;
  const check=()=>{if(++checks>POLICY.maximumPhaseChecks){exhausted=true;return false;}return true;};
  const promotable=r=>!chosen(decisionMap.get(r.id))&&decisionMap.get(r.id).decision!=='screen_information_candidate';
  function submit(kind,targetRows,supportRows,extra={}) {
    const unique=[...new Map(targetRows.map(r=>[r.id,r])).values()].filter(promotable);
    if(!unique.length)return;
    const proposal={id:`phase-${String(result.phaseProposals.length+1).padStart(4,'0')}`,kind,
      affectedRefs:unique.map(r=>decisionMap.get(r.id).ref),supportRefs:[...new Map(supportRows.map(r=>[r.id,r])).values()].map(r=>decisionMap.get(r.id).ref),
      firstObserved:Math.min(...unique.map(r=>r.time)),lastObserved:Math.max(...unique.map(r=>r.time)),
      meaning:'machine_role_proposal_only',textCorrectnessVerified:false,semanticRoleVerified:false,
      wholeFamilyPromoted:false,usesExpectedText:false,...extra};
    result.phaseProposals.push(proposal);
    for(const row of unique){const d=decisionMap.get(row.id);d.phaseEvidenceIds.push(proposal.id);
      d.decision='proposed_caption';d.reason=kind;d.proposalTier='temporally_linked_role_proposal';
      const f=familyMap.get(d.familyId);if(!f.phaseProposalIds.includes(proposal.id))f.phaseProposalIds.push(proposal.id);}
  }
  const selectedRef=(rows,time,direction)=>rows.filter(r=>direction==='before'?r.time<time:r.time>time)
    .sort((a,b)=>Math.abs(a.time-time)-Math.abs(b.time-time))[0];
  const contextLimit=input.samplingInterval*POLICY.selectedContextIntervals;
  function screenInfo(run,supportRows,indexEvidence,extra) {
    const affected=[...new Map(run.flatMap(p=>[p.a,p.b]).map(r=>[r.id,r])).values()].filter(r=>!baseSelectedIds.has(r.id));
    const info={id:`screen-info-${String(result.screenInfoProposals.length+1).padStart(4,'0')}`,
      kind:'index_label_block_candidate',affectedRefs:affected.map(r=>decisionMap.get(r.id).ref),
      supportRefs:supportRows.map(r=>decisionMap.get(r.id).ref),
      firstObserved:run[0].time,lastObserved:run.at(-1).time,
      indexStructure:indexEvidence.kind,indexObservedFrameCount:indexEvidence.count,
      indexObservedFrameFraction:indexEvidence.count/run.length,indexRowFamilyId:indexEvidence.familyId,
      meaning:'screen_information_candidate_not_main_caption_truth',semanticRoleVerified:false,
      textCorrectnessVerified:false,wholeFamilyPromoted:false,usesExpectedText:false,...extra};
    result.screenInfoProposals.push(info);
    for(const r of affected){const d=decisionMap.get(r.id);d.decision='screen_information_candidate';
      d.reason='index_label_block_not_automatically_main_caption';d.screenInfoEvidenceIds.push(info.id);
      d.proposalTier='visible_screen_information_candidate';}
  }
  // Detect complete temporary blocks from frozen base + own raw geometry before any additions.
  // Later promotions cannot remove a third row and manufacture a false two-line block.
  const linkedBlocks=temporaryBlocks();

  // Strong local changing phases should not fail solely because a long video dilutes frame coverage.
  for(const f of initial.families){
    const candidate=f.rowRefs.map(r=>ownRows.get(r.rowId)).filter(r=>promotable(r)&&decisionMap.get(r.id).read.selected);
    for(const run of splitRuns(candidate,input.samplingInterval)){
      if(run.length<POLICY.phaseMinimumRows)continue;
      const evidence=base.eventEvidence(run,input.samplingInterval);
      if(evidence.stableStates<POLICY.phaseMinimumStableStates||evidence.substantialTransitions<POLICY.phaseMinimumChanges||evidence.dominantStateFraction>.8)continue;
      for(const [familyId,context] of selectedByFamily){
        if(!check())break;
        const selectedFamily=familyMap.get(familyId);
        if(!near(f.profile,selectedFamily.profile))continue;
        const present=run.filter(r=>context.some(c=>c.sourceFrameId===r.sourceFrameId)).length/run.length;
        const before=selectedRef(context,run[0].time,'before'),after=selectedRef(context,run.at(-1).time,'after');
        const beforeOK=before&&run[0].time-before.time<=contextLimit;
        const afterOK=after&&after.time-run.at(-1).time<=contextLimit;
        const edgeBefore=run[0].time<=input.samplingInterval*POLICY.phaseMaximumGapIntervals;
        const edgeAfter=input.duration-run.at(-1).time<=input.samplingInterval*POLICY.phaseMaximumGapIntervals;
        if(present<=POLICY.maximumSelectedCooccurrence&&(beforeOK||edgeBefore)&&(afterOK||edgeAfter)){
          submit('local_changing_caption_phase',run,[beforeOK?before:null,afterOK?after:null].filter(Boolean),
            {contextFamilyId:familyId,localStableStates:evidence.stableStates,localChanges:evidence.substantialTransitions});break;
        }
      }
    }
  }

  // Subtitle line reflow: one companion event is linked to an adjacent selected occurrence
  // of the same literal, not all other texts that ever used this geometry family.
  for(const f of initial.families)for(const event of f.events){
    if(exhausted)break;
    const eventRows=event.refs.map(r=>ownRows.get(r.rowId)).filter(r=>promotable(r)&&decisionMap.get(r.id).read.selected);
    if(!eventRows.length)continue;
    const paired=eventRows.map(r=>({r,siblings:selectedByFrame.get(r.sourceFrameId).filter(s=>block(r,s))})).filter(x=>x.siblings.length===1);
    if(paired.length!==eventRows.length)continue;
    const identity=literal(event.representative.text);
    const context=selectedRows.filter(r=>{
      if(!check())return false;
      const d=decisionMap.get(r.id),gap=r.time<event.firstObserved?event.firstObserved-r.time:r.time>event.lastObserved?r.time-event.lastObserved:Infinity;
      return gap<=input.samplingInterval*POLICY.phaseMaximumGapIntervals&&literal(d.read.selected?.text||'')===identity&&near(r.geometryProxy,eventRows[0].geometryProxy);
    });
    if(context.length)submit('multiline_reflow_continuity',eventRows,[...context,...paired.flatMap(p=>p.siblings)],
      {exactNormalizedLiteralContinuity:true,ownFrameCompanionCount:paired.length});
  }

  // A temporary two-line block can replace the normal one-line lane, provided actual paired
  // frames are bracketed by the same selected lane. This does not promote unrelated clock/label
  // events belonging to those region families elsewhere in the video.
  function temporaryBlocks() {
  const pairedRuns=new Map(),accepted=[];
  for(const frame of association.frames){
    const candidates=byFrame.get(frame.sourceFrameId).filter(r=>!baseSelectedIds.has(r.id)&&decisionMap.get(r.id).read.selected);
    for(let i=0;i<candidates.length;i++)for(let j=i+1;j<candidates.length;j++){
      if(!check())break;
      const a=candidates[i],b=candidates[j],g=block(a,b);if(!g)continue;
      const ids=[decisionMap.get(a.id).familyId,decisionMap.get(b.id).familyId].sort(),k=ids.join('|');
      if(ids[0]===ids[1])continue;
      if(!pairedRuns.has(k))pairedRuns.set(k,[]);
      pairedRuns.get(k).push({id:`pair:${a.id}|${b.id}`,time:frame.time,sourceFrameId:frame.sourceFrameId,a,b,geometryProxy:g});
    }
  }
  for(const pairs of pairedRuns.values())for(const run of splitRuns(pairs,input.samplingInterval)){
    if(exhausted)break;
    if(run.length<POLICY.pairedMinimumFrames||new Set(run.map(p=>p.sourceFrameId)).size!==run.length)continue;
    for(const [familyId,context] of selectedByFamily){
      if(!check())break;
      const selectedFamily=familyMap.get(familyId);
      if(!run.every(p=>near(p.geometryProxy,selectedFamily.profile,1.5)))continue;
      const present=run.filter(p=>context.some(c=>c.sourceFrameId===p.sourceFrameId)).length/run.length;
      if(present>POLICY.maximumSelectedCooccurrence)continue;
      const before=selectedRef(context,run[0].time,'before'),after=selectedRef(context,run.at(-1).time,'after');
      if(!before||!after||run[0].time-before.time>contextLimit||after.time-run.at(-1).time>contextLimit)continue;
      // More than one geometrically plausible partner in a frame means a block ownership ambiguity.
      const unambiguous=run.every(p=>{
        // Failed/unread OCR does not erase its own detected geometry. A plausible third
        // row is still ambiguous; its inability to yield text cannot certify a two-line block.
        const peers=byFrame.get(p.sourceFrameId);
        return peers.filter(r=>r.id!==p.a.id&&block(p.a,r)).length===1&&peers.filter(r=>r.id!==p.b.id&&block(p.b,r)).length===1;
      });
      if(!unambiguous)continue;
      const extra={contextFamilyId:familyId,ownFramePairCount:run.length,oneSelectedLaneBeforeAndAfter:true};
      const indexCounts=new Map();
      for(const p of run)for(const row of [p.a,p.b]){
        const d=decisionMap.get(row.id),kind=indexOnlyKind(d.read.selected.text);if(!kind)continue;
        const key=d.familyId+'|'+kind;
        if(!indexCounts.has(key))indexCounts.set(key,{kind,familyId:d.familyId,count:0});
        indexCounts.get(key).count++;
      }
      const indexEvidence=[...indexCounts.values()].find(e=>e.count>=POLICY.minimumIndexFrames&&e.count/run.length>=POLICY.minimumIndexFrameFraction);
      if(indexEvidence)screenInfo(run,[before,after],indexEvidence,extra);
      else accepted.push({rows:run.flatMap(p=>[p.a,p.b]),support:[before,after],extra});
      break;
    }
  }
  return accepted;
  }
  for(const linked of linkedBlocks)submit('bracketed_multiline_caption_phase',linked.rows,linked.support,linked.extra);
  if(exhausted){
    // No partly-checked promotion is exposed as a successful pass.
    result.decisions=initial.decisions.map(d=>({...d,baseDecision:d.decision,phaseEvidenceIds:[],screenInfoEvidenceIds:[]}));
    result.families=initial.families.map(f=>({...f,phaseProposalIds:[]}));result.phaseProposals=[];result.screenInfoProposals=[];
    result.phaseAnalysisReasons.push('phase_resource_budget_exceeded');
  }
  result.phaseAnalysisComplete=!exhausted;
  result.statistics={...initial.statistics,
    proposedRows:result.decisions.filter(chosen).length,
    visibleRecoveryRows:result.decisions.filter(d=>d.decision==='visible_recovery_candidate').length,
    phasePromotedRows:result.decisions.filter(d=>d.phaseEvidenceIds.length).length,
    phasePromotedRowObservations:result.decisions.filter(d=>d.phaseEvidenceIds.length).length,
    screenInfoRowObservations:result.decisions.filter(d=>d.screenInfoEvidenceIds.length).length,
    phaseProposals:result.phaseProposals.length,screenInfoProposals:result.screenInfoProposals.length,phaseChecks:checks};
  result.promotionBoundary='Each linked row is a machine role proposal; original OCR and all other rows are retained. Not whole-video truth.';
  return result;
}
module.exports={POLICY,select,indexOnlyKind,similar:base.similar,eventEvidence:base.eventEvidence};

},
"main-caption-selector-v7.cjs":function(require,module,exports){
'use strict';
// Development-only role hypotheses. No OCR, text rewriting, event merging or destructive filtering.
const base=require('./main-caption-selector-v6.cjs');
const {associate}=require('./associate-text-lines-v2.cjs');
const POLICY=Object.freeze({version:7,baseVersion:6,labelsAreProposals:true,
  globalCompletenessGateUnchanged:true,usesFilenameOrExpectedText:false,changesText:false,
  localHeightUnits:4,anchorFraction:.08,heightRatio:1.8,angleDifference:.14,
  pairMaximumOverlapFraction:.35,pairMaximumEdgeGapHeightUnits:.8,
  pairMinimumCenterHeightUnits:.6,pairMinimumHorizontalOverlap:.6,pairAnchorFraction:.05,
  companionMinimumFrames:2,companionMinimumFamilyStableStates:2,
  phaseMinimumFrames:4,phaseMinimumStableStates:2,phaseMinimumChanges:1,
  phaseMaximumSeconds:12,phaseMaximumGapIntervals:2.18,phaseStepHeightUnits:1.5,
  anchorContextIntervals:6,maximumChecks:3000000,
  roleMayBridgeOneObservedEmptyFrame:true,eventMergingPerformed:false,
  allRawRowsRetained:true,farAlternateRequiresIndependentReview:true,
  anchorMinimumLanguageCodePoints:4,anchorMinimumLetterCodePoints:2,anchorMinimumLanguageStates:3,
  languageAnchorGateIsNotPerRowDeletion:true,anchorMaximumEmptyVerticalGapHeightUnits:4,
  digitsDoNotCreateIndependentLanguageAnchorStates:true});
const clone=x=>JSON.parse(JSON.stringify(x));
const isBody=d=>d.decision==='proposed_caption';
const COMPETITION_POLICY=Object.freeze({id:'substantive-language-anchor-competition-v199',
  nearStateMaximumEditFraction:.45,minimumEditedCodePoints:3,minimumStableFrames:2,
  minimumLanguageStates:3,minimumSubstantiveTransitions:2,maximumDominantStateFraction:.8,
  minimumWinnerScoreRatio:1.3,maximumPairChecks:500000,maximumEditCells:8000000,
  geometryProxyIsNotFont:true,usesPositionPrior:false,usesExpectedText:false,
  changesRawText:false,changesEventBoundaries:false,semanticRoleVerified:false});
function substantiveLanguageEvidence(f,budget){
  // These broader equivalence classes measure ROLE evidence only. They never
  // merge OCR events or choose/correct a displayed reading. Fixed small print
  // with several OCR spellings must not acquire a new sentence for each spelling.
  const signature=text=>text.normalize('NFKC').replace(/\p{N}+/gu,'').replace(/[\p{P}\p{Z}\s]/gu,'');
  const stable=f.events.map((e,i)=>({event:e,index:i,text:signature(e.representative.text)}))
    .filter(e=>e.event.refs.length>=COMPETITION_POLICY.minimumStableFrames&&
      [...e.text].length>=POLICY.anchorMinimumLanguageCodePoints&&
      (e.text.match(/\p{L}/gu)||[]).length>=POLICY.anchorMinimumLetterCodePoints&&
      !base.indexOnlyKind(e.event.representative.text));
  const nearState=(a,b)=>{
    if(++budget.pairs>COMPETITION_POLICY.maximumPairChecks)throw Error('competition_budget');
    const x=[...a],y=[...b];if(a===b)return true;
    budget.cells+=x.length*y.length;if(budget.cells>COMPETITION_POLICY.maximumEditCells)throw Error('competition_budget');
    let v=Array.from({length:y.length+1},(_,i)=>i);
    for(let i=0;i<x.length;i++){const n=[i+1];for(let j=0;j<y.length;j++)n[j+1]=Math.min(n[j]+1,v[j+1]+1,v[j]+(x[i]===y[j]?0:1));v=n;}
    const edits=v[y.length];return edits<COMPETITION_POLICY.minimumEditedCodePoints||
      edits/Math.max(x.length,y.length)<=COMPETITION_POLICY.nearStateMaximumEditFraction;
  };
  const states=[],stateByEvent=new Map();
  // Complete-link classes prevent a chain of small OCR edits from bridging
  // two truly different sentences. A frequent state is a deterministic seed.
  for(const e of stable.slice().sort((a,b)=>b.event.refs.length-a.event.refs.length||a.index-b.index)){
    let state=states.find(s=>s.members.every(p=>nearState(p.text,e.text)));
    if(!state){state={id:states.length,members:[],frames:0};states.push(state);}
    state.members.push(e);state.frames+=e.event.refs.length;stateByEvent.set(e.index,state.id);
  }
  let transitions=0;
  for(let i=1;i<stable.length;i++)if(stateByEvent.get(stable[i-1].index)!==stateByEvent.get(stable[i].index)&&
    stable[i].event.firstObserved-stable[i-1].event.lastObserved<=1.5)transitions++;
  const support=stable.reduce((n,e)=>n+e.event.refs.length,0),dominant=Math.max(0,...states.map(s=>s.frames))/Math.max(1,support);
  const qualified=f.eligible&&states.length>=COMPETITION_POLICY.minimumLanguageStates&&
    transitions>=COMPETITION_POLICY.minimumSubstantiveTransitions&&dominant<=COMPETITION_POLICY.maximumDominantStateFraction;
  return {familyId:f.id,substantiveLanguageStates:states.length,substantiveTransitions:transitions,
    stableLanguageFrames:support,dominantLanguageStateFraction:dominant,
    roleScore:f.frameFraction*(.5+.5*f.timelineBins/8)*Math.min(12,transitions),qualified,
    stateWitnesses:states.map(s=>({frames:s.frames,eventIndices:s.members.map(e=>e.index),
      supportRefs:s.members.flatMap(e=>e.event.refs)})),rawTextModified:false,semanticRoleVerified:false};
}
function competingAnchor(initial){
  const budget={pairs:0,cells:0};
  try{
    const evidence=initial.families.map(f=>substantiveLanguageEvidence(f,budget)),byId=new Map(evidence.map(e=>[e.familyId,e]));
    const old=initial.families.filter(f=>f.proposal==='main_caption_region');
    const weak=old.length?old.every(f=>!byId.get(f.id).qualified):
      initial.samplingPlanComplete===true&&initial.status==='no_unique_caption_region';
    const rank=evidence.filter(e=>e.qualified).sort((a,b)=>b.roleScore-a.roleScore||(a.familyId<b.familyId?-1:a.familyId>b.familyId?1:0));
    const winner=weak&&rank[0]&&(!rank[1]||rank[0].roleScore>=rank[1].roleScore*COMPETITION_POLICY.minimumWinnerScoreRatio)?rank[0]:null;
    return {schema:'caption-anchor-competition-evidence-v199',policy:COMPETITION_POLICY,analysisComplete:true,
      previousPrimaryFamilyIds:old.map(f=>f.id),replacementPrimaryFamilyIds:winner?[winner.familyId]:[],
      evidence,resourceUse:budget,semanticRoleVerified:false,rawTextModified:false};
  }catch(e){if(e.message!=='competition_budget')throw e;
    return {schema:'caption-anchor-competition-evidence-v199',policy:COMPETITION_POLICY,analysisComplete:false,
      previousPrimaryFamilyIds:[],replacementPrimaryFamilyIds:[],evidence:[],resourceUse:budget,
      reason:'competition_resource_budget_no_partial_replacement',semanticRoleVerified:false,rawTextModified:false};}
}
function near(a,b,units=POLICY.localHeightUnits){
  return Math.abs(a.centerY-b.centerY)<=Math.max(a.height,b.height)*units&&
    Math.max(a.height,b.height)/Math.min(a.height,b.height)<=POLICY.heightRatio&&
    Math.min(...['left','centerX','right'].map(k=>Math.abs(a[k]-b[k])))<=POLICY.anchorFraction&&
    Math.abs(a.angle-b.angle)<=POLICY.angleDifference;
}
function pair(a,b){
  const p=a.geometryProxy,q=b.geometryProxy,h=Math.max(p.height,q.height),small=Math.min(p.height,q.height);
  const dy=Math.abs(p.centerY-q.centerY),overlapY=Math.max(0,(p.height+q.height)/2-dy),gap=Math.max(0,dy-(p.height+q.height)/2);
  const width=Math.min(p.right-p.left,q.right-q.left),overlapX=Math.max(0,Math.min(p.right,q.right)-Math.max(p.left,q.left));
  // Native axis-aligned crops include padding. Test actual overlap/edge separation,
  // not a minimum line-center distance calibrated to unpadded quadrilaterals.
  return small>0&&h/small<=POLICY.heightRatio&&dy>=h*POLICY.pairMinimumCenterHeightUnits&&
    overlapY<=small*POLICY.pairMaximumOverlapFraction&&gap<=h*POLICY.pairMaximumEdgeGapHeightUnits&&
    width>0&&overlapX/width>=POLICY.pairMinimumHorizontalOverlap&&
    Math.min(...['left','centerX','right'].map(k=>Math.abs(p[k]-q[k])))<=POLICY.pairAnchorFraction&&
    Math.abs(p.angle-q.angle)<=POLICY.angleDifference;
}
function anchorNeighborhood(a,b){
  // Compare the empty gap between observed bands, not just their centers.
  // This is bounded to one direct primary neighborhood, never transitive drift.
  const gap=Math.max(0,Math.abs(a.centerY-b.centerY)-(a.height+b.height)/2);
  return gap<=Math.max(a.height,b.height)*POLICY.anchorMaximumEmptyVerticalGapHeightUnits&&
    near({...a,centerY:b.centerY},b);
}
function groupGeometry(rows){
  return {centerY:rows.reduce((s,r)=>s+r.geometryProxy.centerY,0)/rows.length,
    height:Math.max(...rows.map(r=>r.geometryProxy.height)),
    left:Math.min(...rows.map(r=>r.geometryProxy.left)),right:Math.max(...rows.map(r=>r.geometryProxy.right)),
    centerX:rows.reduce((s,r)=>s+r.geometryProxy.centerX,0)/rows.length,
    angle:rows.reduce((s,r)=>s+r.geometryProxy.angle,0)/rows.length};
}
function anchorEvidence(f){
  const states=[];let supportingFrames=0;
  for(const e of f.events){
    const text=e.representative.text.normalize('NFKC').replace(/[\p{P}\p{Z}\s]/gu,'');
    if(e.refs.length<2||base.indexOnlyKind(e.representative.text)||[...text].length<POLICY.anchorMinimumLanguageCodePoints||
      (text.match(/\p{L}/gu)||[]).length<POLICY.anchorMinimumLetterCodePoints)continue;
    supportingFrames+=e.refs.length;
    // Role-only signature: a changing counter cannot manufacture changing language.
    // Output text, numbers and caption-event boundaries are never normalized here.
    const signature=e.representative.text.normalize('NFKC').replace(/\p{N}+/gu,'#');
    if(!states.some(s=>base.similar(s,signature)))states.push(signature);
  }
  return {languageStates:states.length,supportingFrames,qualified:f.eligible&&states.length>=POLICY.anchorMinimumLanguageStates};
}
function unresolved(initial,reasons){
  const out=clone(initial);
  out.policy=POLICY;out.schemaVersion=7;
  out.status=initial.status==='caption_regions_proposed'?'role_analysis_unresolved':initial.status;
  out.roleGraphAnalysisComplete=false;out.roleGraphAnalysisReasons=reasons;
  out.roleGraphProposals=[];out.roleGraphDemotions=[];out.roleGraphRecoveries=[];
  out.rolePresentation='retained_screen_text_and_unresolved_role_candidates';out.claimsNoText=false;
  for(const d of out.decisions){if(d.decision==='proposed_caption'){
    d.previousV6Decision=d.decision;d.decision='retained_other_or_uncertain';d.reason='role_analysis_unresolved_not_automatic_body';
  }}
  for(const f of out.families){if(f.proposal.includes('caption_region')){f.previousV6Proposal=f.proposal;f.proposal='unresolved_role_retained';}}
  out.baselinePhaseProposals=out.phaseProposals||[];out.phaseProposals=[];
  out.statistics={...out.statistics,proposedRows:0};return out;
}
function select(input,options={}){
  const initial=base.select(input),out=clone(initial);
  out.policy=POLICY;out.schemaVersion=7;out.roleGraphProposals=[];out.roleGraphDemotions=[];
  out.roleGraphRecoveries=[];
  out.roleGraphAnalysisComplete=false;out.roleGraphAnalysisReasons=[];
  const competition=options.captionAnchorCompetition;
  const independentPrimary=initial.status==='no_unique_caption_region'&&initial.samplingPlanComplete===true&&
    competition?.analysisComplete===true&&competition.replacementPrimaryFamilyIds.length>0;
  if(initial.status!=='caption_regions_proposed'&&!independentPrimary){
    return unresolved(initial,['unchanged_base_completeness_or_unique_primary_gate']);
  }
  if(independentPrimary)out.status='caption_regions_proposed';
  const a=associate(input);
  if(a.status!=='complete')return unresolved(initial,['own_geometry_not_complete']);
  const families=new Map(out.families.map(f=>[f.id,f])),ds=new Map(out.decisions.map(d=>[d.ref.rowId,d]));
  const originalPrimary=out.families.filter(f=>f.proposal==='main_caption_region');
  const evidence=new Map(out.families.map(f=>[f.id,anchorEvidence(f)]));
  out.anchorLanguageEvidence=out.families.map(f=>({familyId:f.id,...evidence.get(f.id)}));
  let primary=originalPrimary.filter(f=>evidence.get(f.id).qualified);
  const replacement=competition?.analysisComplete===true&&competition.replacementPrimaryFamilyIds.length?
    out.families.filter(f=>competition.replacementPrimaryFamilyIds.includes(f.id)):[];
  if(replacement.length){primary=replacement;out.anchorCompetition=clone(competition);
    out.primaryFamilyId=primary[0].id;out.roleGraphAnalysisReasons.push(independentPrimary?
      'complete_native_scan_unique_substantive_language_anchor':'weak_ocr_variant_anchor_replaced_by_substantive_language_track');}
  if(!primary.length){
    const ranked=out.families.filter(f=>evidence.get(f.id).qualified).sort((x,y)=>y.score-x.score);
    if(ranked.length&&(!ranked[1]||ranked[0].score>=ranked[1].score*1.3)){
      primary=[ranked[0]];out.roleGraphAnalysisReasons.push('nonlanguage_anchor_replaced_by_unique_language_evidence');
    }
  }
  if(!primary.length){
    // No global gate is relaxed. A short/status-like winner is an unresolved role,
    // not a license to choose the next arbitrary screen text.
    return unresolved(initial,['no_supported_language_anchor']);
  }
  const maximumChecks=Number.isSafeInteger(options.maximumChecks)&&options.maximumChecks>0?Math.min(options.maximumChecks,POLICY.maximumChecks):POLICY.maximumChecks;
  let checks=0;const tick=()=>{if(++checks>maximumChecks)throw new Error('role_budget');};
  const rows=a.frames.flatMap(f=>f.rows),rowMap=new Map(rows.map(r=>[r.id,r]));
  const competitionEvidence=new Map((competition?.evidence||[]).map(e=>[e.familyId,e]));
  const seeds=out.families.filter(f=>(primary.includes(f)||f.proposal.includes('caption_region')||replacement.length&&competitionEvidence.get(f.id)?.qualified)&&
    evidence.get(f.id).qualified&&primary.some(p=>anchorNeighborhood(f.profile,p.profile)));
  out.roleGraphAnchors={primaryFamilyIds:primary.map(f=>f.id),connectedFamilyIds:seeds.map(f=>f.id)};
  const seedIds=new Set(seeds.map(f=>f.id));
  if(replacement.length)for(const f of out.families){
    if(seedIds.has(f.id)){f.previousV6Proposal=f.proposal;f.proposal=primary.includes(f)?'main_caption_region':'alternate_caption_region';}
    else if(f.proposal.includes('caption_region')){f.previousV6Proposal=f.proposal;f.proposal='screen_information_retained_after_anchor_competition';}
  }
  const references=rs=>rs.map(r=>clone(ds.get(r.id).ref));
  function demote(kind,affected){
    if(!affected.length)return;
    const entry={id:`role-demotion-${out.roleGraphDemotions.length+1}`,kind,affectedRefs:references(affected),
      semanticRoleVerified:false,rawRetained:true};out.roleGraphDemotions.push(entry);
    for(const r of affected){const d=ds.get(r.id);d.previousV6Decision=d.decision;d.decision='screen_information_candidate';
      d.reason=kind;d.proposalTier='visible_screen_information_candidate';d.roleGraphEvidenceId=entry.id;}
  }
  // Non-co-occurrence alone cannot prove that a distant, separately styled block is dialogue.
  // It remains visible, but is not silently concatenated into the main caption body.
  demote('spatially_disconnected_alternate_requires_role_review',rows.filter(r=>{
    const d=ds.get(r.id),f=families.get(d.familyId);
    return isBody(d)&&(replacement.length||f.proposal.includes('caption_region'))&&!seedIds.has(d.familyId);
  }));
  const primaryIds=new Set((replacement.length?seeds:primary).map(f=>f.id));
  for(const r of rows){const d=ds.get(r.id);if(primaryIds.has(d.familyId)&&d.read.selected&&d.decision!=='proposed_caption'){
    d.previousV6Decision=d.decision;d.decision='proposed_caption';d.reason='unique_language_supported_primary_region';
  }}
  const readable=r=>!!ds.get(r.id)?.read.selected;
  // Exact clock/calendar whole-line categories only; prose that mentions time is unchanged.
  demote('whole_line_clock_or_calendar_screen_information',rows.filter(r=>isBody(ds.get(r.id))&&base.indexOnlyKind(ds.get(r.id).read.selected?.text)));
  const frozenBody=new Set(out.decisions.filter(isBody).map(d=>d.ref.rowId));
  const seedRows=rows.filter(r=>frozenBody.has(r.id));
  const allowed=r=>readable(r)&&ds.get(r.id).decision!=='screen_information_candidate'&&
    !base.indexOnlyKind(ds.get(r.id).read.selected.text)&&seeds.some(f=>near(r.geometryProxy,f.profile));
  const groupsByFrame=[];
  try{
    for(let fi=0;fi<a.frames.length;fi++){
      const frame=a.frames[fi],available=frame.rows.filter(allowed),groups=[],seen=new Set();
      const peerMap=new Map();
      // Failed/unread third-row geometry still creates ownership ambiguity.
      for(const r of available){peerMap.set(r.id,frame.rows.filter(o=>{tick();return o.id!==r.id&&pair(r,o);}));}
      for(const r of available){
        if(seen.has(r.id))continue;
        const peers=peerMap.get(r.id);let members;
        if(!peers.length)members=[r];
        else if(peers.length===1&&allowed(peers[0])&&peerMap.get(peers[0].id)?.length===1)members=[r,peers[0]];
        else continue;
        members.forEach(x=>seen.add(x.id));members.sort((x,y)=>x.geometryProxy.centerY-y.geometryProxy.centerY);
        const indexBlock=members.some(x=>base.indexOnlyKind(ds.get(x.id).read.selected?.text));
        if(indexBlock)continue;
        groups.push({id:`block-${fi}-${groups.length}`,frameIndex:fi,sourceFrameId:frame.sourceFrameId,time:frame.time,
          rows:members,geometryProxy:groupGeometry(members),hasBody:members.some(x=>frozenBody.has(x.id))});
      }
      groupsByFrame.push(groups);
    }
    function submit(kind,target,support,extra={}){
      const affected=[...new Map(target.map(r=>[r.id,r])).values()].filter(r=>!isBody(ds.get(r.id))&&ds.get(r.id).decision!=='screen_information_candidate');
      if(!affected.length)return;
      const entry={id:`role-graph-${out.roleGraphProposals.length+1}`,kind,affectedRefs:references(affected),
        supportRefs:references([...new Map(support.map(r=>[r.id,r])).values()]),
        firstObserved:Math.min(...affected.map(r=>r.time)),lastObserved:Math.max(...affected.map(r=>r.time)),
        textCorrectnessVerified:false,semanticRoleVerified:false,wholeFamilyPromoted:false,...extra};
      out.roleGraphProposals.push(entry);
      for(const r of affected){const d=ds.get(r.id);d.previousV6Decision??=d.decision;d.decision='proposed_caption';
        d.reason=kind;d.proposalTier='temporally_linked_role_proposal';d.roleGraphEvidenceId=entry.id;}
    }
    // Same-frame companion ownership is independent of whether its literal previously
    // appeared alone. It needs repeat evidence and a changing companion family.
    const companionRuns=[];let active=new Map();
    for(const groups of groupsByFrame){const next=new Map();
      for(const g of groups.filter(g=>g.hasBody&&g.rows.length===2)){
        const extra=g.rows.find(r=>!frozenBody.has(r.id));if(!extra)continue;
        const f=families.get(ds.get(extra.id).familyId);
        if(f.stableStates<POLICY.companionMinimumFamilyStableStates||evidence.get(f.id).supportingFrames<2)continue;
        const k=g.rows.map(r=>ds.get(r.id).familyId).sort().join('|'),previous=active.get(k);
        const run=previous&&g.time-previous.at(-1).time<=input.samplingInterval*1.18?previous:[];
        if(!run.length)companionRuns.push(run);run.push(g);next.set(k,run);
      }active=next;
    }
    for(const run of companionRuns)if(run.length>=POLICY.companionMinimumFrames){
      submit('unique_same_frame_multiline_companion',run.flatMap(g=>g.rows),run.flatMap(g=>g.rows.filter(r=>frozenBody.has(r.id))),
        {ownPairedFrames:run.length,changingCompanionFamilyRequired:true});
    }
    // A short/single-frame companion cannot establish a new role family, but is
    // not hidden just because it cannot pass the anchor's language-state gate.
    for(const groups of groupsByFrame)for(const g of groups.filter(g=>g.hasBody&&g.rows.length===2)){
      const target=g.rows.filter(r=>!isBody(ds.get(r.id))&&[...ds.get(r.id).read.selected.text.trim()].length<=3);
      if(!target.length)continue;
      const entry={id:`role-recovery-${out.roleGraphRecoveries.length+1}`,kind:'short_same_frame_companion_needs_review',
        affectedRefs:references(target),supportRefs:references(g.rows.filter(r=>frozenBody.has(r.id))),
        singleFrameAllowed:true,semanticRoleVerified:false,doesNotEstablishNewAnchor:true};
      out.roleGraphRecoveries.push(entry);
      for(const r of target){const d=ds.get(r.id);d.previousV6Decision??=d.decision;
        d.decision='visible_recovery_candidate';d.reason=entry.kind;d.roleGraphRecoveryId=entry.id;}
    }
    // Time-local phases: same typography, mutually unique continuity, no other
    // simultaneous main block. One observed empty frame may separate role evidence;
    // this NEVER joins subtitle text events across that empty observation.
    const paths=[];let open=[];
    for(let fi=0;fi<groupsByFrame.length;fi++){
      const groups=groupsByFrame[fi],hasMain=groups.some(g=>g.hasBody);
      const candidates=hasMain?[]:groups.filter(g=>!g.hasBody);
      open=open.filter(p=>a.frames[fi].time-p.at(-1).time<=input.samplingInterval*POLICY.phaseMaximumGapIntervals);
      const matches=candidates.map(g=>open.filter(p=>{tick();return near(g.geometryProxy,p.at(-1).geometryProxy,POLICY.phaseStepHeightUnits);}));
      const next=[];
      for(let i=0;i<candidates.length;i++){
        const g=candidates[i],possible=matches[i];
        if(candidates.length>1){continue;} // unresolved competing local blocks are not selected by score
        let p=possible.length===1&&matches.filter(m=>m.includes(possible[0])).length===1?possible[0]:null;
        if(!p){p=[];paths.push(p);}p.push(g);next.push(p);
      }
      // Actual competing/main rows break a phase; genuinely empty observations may bridge once.
      open=next.length?next:(a.frames[fi].rows.length===0?open:[]);
    }
    const limit=input.samplingInterval*POLICY.anchorContextIntervals;
    for(const path of paths){
      for(let start=0;start<path.length;start++){
        const run=[];for(let j=start;j<path.length&&path[j].time-path[start].time<=POLICY.phaseMaximumSeconds;j++)run.push(path[j]);
        if(run.length<POLICY.phaseMinimumFrames)continue;
        const pseudo=run.map(g=>({...g,id:g.id,sourceSha256:input.sourceSha256,readStatus:'read',
          reads:[{mode:'original',rawData:{text:g.rows.map(r=>ds.get(r.id).read.selected.text).join('\n'),confidence:100}}]}));
        const ev=base.eventEvidence(pseudo,input.samplingInterval);
        if(ev.stableStates<POLICY.phaseMinimumStableStates||ev.substantialTransitions<POLICY.phaseMinimumChanges)continue;
        const before=seedRows.filter(r=>r.time<run[0].time&&run[0].time-r.time<=limit&&near(r.geometryProxy,run[0].geometryProxy));
        const after=seedRows.filter(r=>r.time>run.at(-1).time&&r.time-run.at(-1).time<=limit&&near(r.geometryProxy,run.at(-1).geometryProxy));
        if(!before.length&&!after.length)continue;
        submit('anchored_time_local_changing_phase',run.flatMap(g=>g.rows),[...before,...after],
          {stableBlockStates:ev.stableStates,blockChanges:ev.substantialTransitions,ownObservedFrames:run.length,
            observedGapCount:run.slice(1).filter((g,i)=>g.frameIndex-run[i].frameIndex>1).length,
            eventMergingPerformed:false,anchorSides:[before.length?'before':null,after.length?'after':null].filter(Boolean)});
        // Later windows are useful only for unsupported tails; they cannot bootstrap new anchors.
      }
    }
    out.roleGraphAnalysisComplete=true;
  }catch(error){
    if(error.message!=='role_budget')throw error;
    return unresolved(initial,['resource_budget_exceeded_no_automatic_body_fallback']);
  }
  out.statistics={...out.statistics,proposedRows:out.decisions.filter(isBody).length,
    visibleRecoveryRows:out.decisions.filter(d=>d.decision==='visible_recovery_candidate').length,
    screenInfoRowObservations:out.decisions.filter(d=>d.decision==='screen_information_candidate').length,
    roleGraphPromotedRowObservations:out.decisions.filter(d=>d.roleGraphEvidenceId?.startsWith('role-graph-')).length,
    roleGraphDemotedRowObservations:out.decisions.filter(d=>d.roleGraphEvidenceId?.startsWith('role-demotion-')).length,
    roleGraphChecks:checks};
  out.roleGraphBoundary='Spatial/temporal candidate role only. Every original row remains; no corrected text, subtitle-event merge, or semantic role certification.';
  return out;
}
module.exports={POLICY,COMPETITION_POLICY,select,pair,near,anchorEvidence,competingAnchor,substantiveLanguageEvidence};

},
"native-role-adapter.js":function(require,module,exports){
'use strict';
// Pure input adapter. Receipts are validated for binding/shape; this function does
// not hash pixels, confirm a full line, or certify the semantic role of text.
const GEOMETRY_CONTRACT=Object.freeze({schema:'adapter-sourceRectGeometry-v1',
  coordinateSystem:'actual_source_pixel_edges_x_right_y_down',quadOrigin:'axis_aligned_actual_drawImage_sourceRect',
  detectorOriginalQuad:false,textExtentConfirmed:false,singleLineCertified:false,subtitleRoleConfirmed:false,
  actualSourcePixelsSHA256Kind:'uncompressed_parent_source_RGBA_bytes',
  aliases:{sourceRectQuad:'actual sourceRect corners tl,tr,br,bl',sourceRectReadQuad:'same actual sourceRect corners; not an oriented detector quad',
    sourcePixelSha256:'actualSourcePixelsSHA256; native parent RGBA hash, not PNG/JPEG file bytes'}});
const check=(test,code)=>{if(!test){const e=new Error(code);e.code=code;throw e;}};
const hash=s=>typeof s==='string'&&/^[a-f0-9]{64}$/.test(s);
const sameRect=(a,b)=>a&&b&&['left','top','right','bottom'].every(k=>a[k]===b[k]);
function adapt(raw){
  check(raw&&hash(raw.sourceSha256),'invalid_source_sha256');
  check(Array.isArray(raw.frames)&&Array.isArray(raw.rows),'invalid_raw_collections');
  check(Number.isFinite(raw.videoDuration)&&raw.videoDuration>0&&raw.videoDuration<=180,'invalid_video_duration');
  check(raw.frames.length===raw.total&&raw.processed===raw.total,'incomplete_frozen_sampling');
  const sourceSha256=raw.sourceSha256,byFrame=new Map(),byId=new Map();
  for(const row of raw.rows){check(row&&Number.isSafeInteger(row.index)&&!byId.has(row.index),'duplicate_or_invalid_raw_row_id');byId.set(row.index,row);
    const a=byFrame.get(row.frameIndex)||[];a.push(row);byFrame.set(row.frameIndex,a);}
  let expectedDimensions=null;const mapping=[];
  const results=raw.frames.map((f,resultIndex)=>{
    check(f&&hash(f.sourcePixelSha256),'invalid_parent_rgba_sha256');check(Number.isSafeInteger(f.frameIndex),'invalid_frame_index');
    const rows=byFrame.get(f.frameIndex)||[],width=raw.sourceVideoWidth,height=raw.sourceVideoHeight;
    check(Number.isSafeInteger(width)&&Number.isSafeInteger(height),'invalid_source_dimensions');
    check(!expectedDimensions||width===expectedDimensions.width&&height===expectedDimensions.height,'source_grid_changed');expectedDimensions={width,height};
    const sourceFrameId=`native-rgba-${f.sourcePixelSha256}-pts-${f.time}`,candidates=[],readouts=[];
    for(const row of rows){
      check(row.frameId===f.frameId&&row.time===f.time&&row.frameTime===f.time&&row.sourceWidth===width&&row.sourceHeight===height,'row_frame_binding_mismatch');
      const b=row.sourceRect,receipt=row.cropReceipt;
      check(receipt?.schema==='source-rect-native-crop-v190'&&receipt.frameId===f.frameId&&receipt.time===f.time&&sameRect(receipt.sourceRect,b),'invalid_actual_crop_receipt');
      check(receipt.interpolation==='none_integer_1_to_1'&&row.inputWidth===b.right-b.left&&row.inputHeight===b.bottom-b.top&&receipt.inputWidth===row.inputWidth&&receipt.inputHeight===row.inputHeight,'resampled_or_mismatched_crop');
      check(['left','top','right','bottom'].every(k=>Number.isSafeInteger(b[k]))&&b.left>=0&&b.top>=0&&b.right<=width&&b.bottom<=height&&b.right>b.left&&b.bottom>b.top,'invalid_native_source_rect');
      const id=`source-rect-row-${row.index}`,q=[{x:b.left,y:b.top},{x:b.right,y:b.top},{x:b.right,y:b.bottom},{x:b.left,y:b.bottom}],region={left:b.left/width,top:b.top/height,right:b.right/width,bottom:b.bottom/height};
      candidates.push({id,sourceSha256,sourceFrameId,time:f.time,sourceWidth:width,sourceHeight:height,sourceRectQuad:q,sourceRectReadQuad:q,
        actualSourcePixelsSHA256:f.sourcePixelSha256,actualSourceRect:{...b},sourceMinSide:Math.min(row.inputWidth,row.inputHeight),angleRadians:0,region,
        geometryKind:'adapter_sourceRectGeometry_axis_aligned_actual_drawImage_not_detector_quad',textExtentConfirmed:false,singleLineCertified:false,subtitleRoleConfirmed:false});
      check(typeof row.text==='string'&&Number.isFinite(row.confidence)&&row.confidence>=0&&row.confidence<=100,'invalid_actual_reading');
      readouts.push({candidateId:id,sourceSha256,sourceFrameId,time:f.time,region,readStatus:row.text.trim()?'read':'empty',reads:[{mode:'original',rawData:{text:row.text,confidence:row.confidence}}],
        sourceRectGeometry:{schema:'adapter_sourceRectGeometry',sourceRectReadQuad:q,sourceRect:{...b},actualReceipt:{...receipt,sourceRect:{...receipt.sourceRect}}}});
      mapping.push({adapterRowId:id,rawRowIndex:row.index,resultIndex,frameIndex:f.frameIndex,originalFrameId:f.frameId,adapterFrameId:sourceFrameId,time:f.time,
        detectorCandidateId:row.detectorCandidateId,actualSourcePixelsSHA256:f.sourcePixelSha256,actualSourceRect:{...b}});
    }
    check(['complete','partial','invalid','failed','not_attempted'].includes(f.detectorStatus),'invalid_detection_state');
    return {sourceSha256,sourceFrameId,time:f.time,width,height,sourcePixelSha256:f.sourcePixelSha256,actualSourcePixelsSHA256:f.sourcePixelSha256,
      sourceHashKind:'uncompressed_source_RGBA_bytes',detection:{status:f.detectorStatus,candidates},rows:readouts};
  });
  check(mapping.length===raw.rows.length&&new Set(mapping.map(m=>m.rawRowIndex)).size===raw.rows.length,'orphan_or_duplicate_raw_rows');
  return {input:{sourceSha256,duration:raw.videoDuration,samplingInterval:.5,samplingScope:'continuous_sampled',expectedFrameTimes:raw.frames.map(f=>f.time),results},mapping};
}
module.exports={adapt,GEOMETRY_CONTRACT};

},
"deterministic-geometry.js":function(require,module,exports){
'use strict';
// R5 numeric contract. Native half-pixel medians stay exact; no epsilon expands
// a qualification gate. This module never receives or interprets OCR text.
const POLICY=Object.freeze({id:'role-native-arithmetic-v1',nativeHeightUnit:'half_source_pixel',
  nativeGate:'integer_cross_product',legacyGate:'positive_float64_cross_product_not_native_certificate',
  logKernel:'range_reduced_atanh_32_terms',costDecimalPlaces:12,idOrder:'unicode_codepoint'});
const LN2=0.6931471805599453,PRECISION=1e12;
function finiteCost(n){return Number.isFinite(n)?Math.round(n*PRECISION)/PRECISION:n;}
function logarithm(x){
  if(typeof x!=='number'||!Number.isFinite(x)||x<=0)throw new TypeError('positive finite logarithm argument required');
  let exponent=0;
  while(x>=2){x/=2;exponent++;}while(x<1){x*=2;exponent--;}
  const z=(x-1)/(x+1),z2=z*z;let term=z,sum=0;
  for(let n=1;n<=63;n+=2){sum+=term/n;term*=z2;}
  return finiteCost(2*sum+exponent*LN2);
}
function ratioWithin(a,b,numerator,denominator){
  if(!a||!b||![a.height,b.height].every(v=>typeof v==='number'&&Number.isFinite(v)&&v>0)
    ||!Number.isSafeInteger(numerator)||!Number.isSafeInteger(denominator)||numerator<denominator||denominator<=0)return false;
  const native=Number.isSafeInteger(a.nativeHeightTwice)&&a.nativeHeightTwice>0&&Number.isSafeInteger(b.nativeHeightTwice)&&b.nativeHeightTwice>0
    &&Number.isSafeInteger(a.nativeSourceHeight)&&a.nativeSourceHeight>0&&a.nativeSourceHeight===b.nativeSourceHeight;
  if(native){const left=Math.max(a.nativeHeightTwice,b.nativeHeightTwice)*denominator,right=Math.min(a.nativeHeightTwice,b.nativeHeightTwice)*numerator;
    return Number.isSafeInteger(left)&&Number.isSafeInteger(right)&&left<=right;}
  // Legacy non-native geometry: compare the supplied Float64 values directly.
  // No rounding to integer pixels and no claim that an oblique quad is native.
  return Math.max(a.height,b.height)*denominator<=Math.min(a.height,b.height)*numerator;
}
function compareIds(a,b){const x=Array.from(String(a)),y=Array.from(String(b));for(let i=0;i<Math.min(x.length,y.length);i++){const d=x[i].codePointAt(0)-y[i].codePointAt(0);if(d)return d<0?-1:1;}return x.length<y.length?-1:x.length>y.length?1:0;}
function nativeRectangle(q){return Array.isArray(q)&&q.length===4&&q.every(p=>p&&Number.isSafeInteger(p.x)&&Number.isSafeInteger(p.y))
  &&q[0].y===q[1].y&&q[1].x===q[2].x&&q[2].y===q[3].y&&q[3].x===q[0].x&&q[1].x>q[0].x&&q[3].y>q[0].y;}
module.exports={POLICY,finiteCost,logarithm,ratioWithin,compareIds,nativeRectangle};

}},cache=Object.create(null);
function load(name){if(cache[name])return cache[name].exports;if(!Object.prototype.hasOwnProperty.call(definitions,name))throw Error('Unknown bundled dependency');const module={exports:{}};cache[name]=module;definitions[name](s=>load(s.replace(/^\.\//,'')),module,module.exports);return module.exports;}
const selector=load('main-caption-selector-v7.cjs'),adapter=load('native-role-adapter.js'),numeric=load('deterministic-geometry.js'),provenance=Object.freeze({"schema":"caption-role-v7-r5-provenance-v1","roleStrategyR4Sha256":"e04c249c7c6579eaf2eb6df31b398bb3de6b0abb053e184b33947a530395c292","numericRevision":"r5-deterministic-native-arithmetic","modules":[{"name":"associate-text-lines-v2.cjs","sourceSha256":"844782c20e2594fa6f2351a4d66af8732509259cb34a8fc00f3c24a62761eb13","runtimeSha256":"12cde11a81debfda69036fb8f6a5ab823ac0ad90d84f9fe15729db49de7c5e34","roleThresholdsChanged":false,"numericPolicyChanged":true},{"name":"main-caption-selector-v4.cjs","sourceSha256":"66f1099315cb2c68f9fb323a161044ceaef74a95d5d834edad112c7ec08629a1","runtimeSha256":"288eaebd5bf266b923e4daddc0d471e3cfcbff9cfb0caa7d99c58d4a545a12f3","roleThresholdsChanged":false,"numericPolicyChanged":true},{"name":"main-caption-selector-v6.cjs","sourceSha256":"bce3c8dedddc0b12665dedbec70bca258142af8c26f0cca14f85efb9111e5615","runtimeSha256":"1f5aab9f5fd090df935d47ce3439ff8a1b8cdf3502f5c3352c32d15185407705","roleThresholdsChanged":false,"numericPolicyChanged":true},{"name":"main-caption-selector-v7.cjs","sourceSha256":"e04c249c7c6579eaf2eb6df31b398bb3de6b0abb053e184b33947a530395c292","runtimeSha256":"e04c249c7c6579eaf2eb6df31b398bb3de6b0abb053e184b33947a530395c292","roleThresholdsChanged":false,"numericPolicyChanged":false},{"name":"native-role-adapter.js","sourceSha256":"054142994c1cd0f727a07f6a614e05b35337c0644a8004318cfbefc36d18c33e","runtimeSha256":"054142994c1cd0f727a07f6a614e05b35337c0644a8004318cfbefc36d18c33e"},{"name":"deterministic-geometry.js","sourceSha256":"19a9512b7f52803bf78e34d140185a3d98b8f2804a4cb7e17567989ea6918574","runtimeSha256":"19a9512b7f52803bf78e34d140185a3d98b8f2804a4cb7e17567989ea6918574"}],"noNodeRuntimeDependencies":true,"productionActivated":false});
const CAPTION_LANE_POLICY=Object.freeze({id:'scene-local-caption-lane-source-continuity-v199',baselineId:'scene-local-caption-lane-v195',maximumContextSeconds:8,
  maximumPrimaryCenterHeightUnits:.9,minimumHeightRatio:.6,maximumHeightRatio:4,
  minimumHorizontalOverlap:.35,maximumCenterXDifference:.22,maximumCropHeightFraction:.15,
  persistentMinimumFrames:12,persistentFrameFraction:.2,persistentDominantStateFraction:.8,
  companionMaximumGapHeightUnits:.8,companionMinimumHorizontalOverlap:.25,
  companionMinimumHeightRatio:.6,companionMaximumHeightRatio:1.8,
  companionMinimumObservedFrames:2,clockLabelTransitionMaximumSeconds:.55,
  companionRepeatMaximumSeconds:1.05,
  clockLabelChainMaximumSeconds:1.05,clockLabelChainMaximumWidthRatio:1.25,
  sameLineCenterHeightUnits:.55,maximumChecks:500000,
  separateClockLabelBlockNeverInherited:true,unconfirmedLatinLabelNeverInherited:true,
  globalAnchorGateUnchanged:false,qualifiedNativeLanguageAnchorRequired:true,inheritedRowsEstablishAnchors:false,wholeFamilyPromoted:false,
  usesExpectedText:false,changesText:false,semanticRoleVerified:false,
  sourceContinuousAlternateQualifiedSeed:true,alternateSeedNeverUsesInheritedRows:true,
  alternateSeedRequiresUniquePerFrameGeometry:true,alternateSeedDriftMeasuredAgainstFixedRoot:true,
  independentAnchorInheritanceRequiresOwnStrongLanguageFamily:true,
  independentAnchorGeometryAloneDoesNotCertifyAdjacentScreenText:true,
  recurringFixedLanguageOverlayVeto:true,recurringFixedMinimumFrames:4,recurringFixedMinimumCodePoints:4,
  sameLiteralBracketUsesSharedFrozenRoot:true,bracketRowsNeverEstablishNewAnchors:true});
const COMPANION_PERSISTENCE_POLICY=Object.freeze({id:'same-literal-companion-over-native-caption-changes-v199-r10',
  minimumIndependentPrimaryStates:3,minimumPrimaryChanges:2,minimumStablePrimaryFrames:2,
  sameLiteralEquivalenceIsRoleEvidenceOnly:true,qualifiedPrimaryRowsNeverDemoted:true,usesExpectedText:false,semanticRoleVerified:false});
function inheritCaptionLanes(raw,initial,options={}){
  const out=JSON.parse(JSON.stringify(initial));out.captionLanePolicy=CAPTION_LANE_POLICY;
  out.captionLaneEvidence=[];out.captionLaneAnalysisComplete=false;out.captionLaneAnalysisReasons=[];
  for(const d of out.decisions)d.captionLaneId=null;
  if(out.roleGraphAnalysisComplete!==true||out.samplingPlanComplete!==true||out.status!=='caption_regions_proposed'){
    out.captionLaneAnalysisReasons.push('complete_qualified_primary_anchor_required');return out;
  }
  const byId=new Map(out.decisions.map(d=>[d.ref.rowId,d])),families=new Map(out.families.map(f=>[f.id,f]));
  const primaryIds=out.roleGraphAnchors?.primaryFamilyIds||[];
  if(!primaryIds.length){out.captionLaneAnalysisReasons.push('no_existing_language_primary_lane');return out;}
  const independentAnchor=out.anchorCompetition?.previousPrimaryFamilyIds?.length===0;
  const independentFamilies=new Set((out.anchorCompetition?.evidence||[]).filter(e=>e.qualified).map(e=>e.familyId));
  const frameRows=new Map(raw.frames.map(f=>[f.frameIndex,[]])),rawByIndex=new Map(raw.rows.map(r=>[r.index,r])),frozenBody=[];
  const rowId=r=>'source-rect-row-'+r.index,decision=r=>byId.get(rowId(r));
  const nearbyRows=(r,seconds)=>raw.frames.filter(f=>Math.abs(f.time-r.time)<=seconds)
    .flatMap(f=>frameRows.get(f.frameIndex)||[]);
  const geometry=r=>({left:r.sourceRect.left/raw.sourceVideoWidth,right:r.sourceRect.right/raw.sourceVideoWidth,
    centerX:(r.sourceRect.left+r.sourceRect.right)/2/raw.sourceVideoWidth,
    centerY:(r.sourceRect.top+r.sourceRect.bottom)/2/raw.sourceVideoHeight,height:(r.sourceRect.bottom-r.sourceRect.top)/raw.sourceVideoHeight});
  const laneFor=r=>{const g=geometry(r);return primaryIds.map((id,index)=>({id,index,
      cost:Math.abs(g.centerY-families.get(id).profile.centerY)/families.get(id).profile.height}))
    .sort((a,b)=>a.cost-b.cost||a.index-b.index)[0];};
  const laneId=i=>'caption-lane-'+raw.sourceSha256.slice(0,12)+'-'+String(i+1).padStart(3,'0');
  for(const r of raw.rows){frameRows.get(r.frameIndex)?.push(r);const d=decision(r);if(d?.decision==='proposed_caption'){
    const lane=laneFor(r);d.captionLaneId=laneId(lane.index);frozenBody.push(r);
    d.roleEvidence={schema:'caption-lane-row-evidence-v195',kind:'existing_qualified_caption_observation',captionLaneId:d.captionLaneId,
      primaryFamilyId:lane.id,rowRef:d.ref,supportRefs:[d.ref],sourceFrameId:r.frameId,time:r.time,
      sceneLocal:true,wholeFamilyPromoted:false,semanticRoleVerified:false};
  }}
  const frozenBodyIds=new Set(frozenBody.map(r=>r.index)),seedByLane=new Map(primaryIds.map((id,i)=>[laneId(i),frozenBody.filter(r=>decision(r).captionLaneId===laneId(i)).sort((a,b)=>a.time-b.time||a.index-b.index)]));
  const requestedChecks=options.captionLaneMaximumChecks??options.maximumChecks;
  let checks=0;const limit=Number.isSafeInteger(requestedChecks)&&requestedChecks>0?Math.min(requestedChecks,CAPTION_LANE_POLICY.maximumChecks):CAPTION_LANE_POLICY.maximumChecks;
  const tick=()=>{if(++checks>limit)throw Error('caption_lane_resource_budget');};
  const base=load('main-caption-selector-v6.cjs');
  const readable=r=>{const d=decision(r),text=d?.read.selected?.text;
    // An already qualified English caption is retained. An unqualified Latin
    // label alone is not proof a nearby package/costume belongs to narration.
    return typeof text==='string'&&/\p{L}/u.test(text)&&!base.indexOnlyKind(text)
      &&!(/^[\x00-\x7f\s]+$/u.test(text)&&Array.from(text.trim()).length<=12);};
  const persistent=r=>{const f=families.get(decision(r).familyId);return f&&f.observedFrames>=Math.max(CAPTION_LANE_POLICY.persistentMinimumFrames,Math.ceil(raw.frames.length*CAPTION_LANE_POLICY.persistentFrameFraction))
    &&f.dominantStateFraction>=CAPTION_LANE_POLICY.persistentDominantStateFraction;};
  const promotable=r=>{const d=decision(r);return d&&d.decision!=='proposed_caption'&&readable(r)&&!persistent(r)
    &&d.decision!=='screen_information_candidate'&&(!independentAnchor||independentFamilies.has(d.familyId));};
  const clockLike=r=>{const text=decision(r)?.read.selected?.text||r.text;if(typeof text!=='string')return false;
    return !!base.indexOnlyKind(text)||/^(?:[A-Za-z]{0,5}\s*)?\d{1,2}:\d{2}(?::\d{2})?$/u.test(text.normalize('NFKC').trim());};
  const separateIndexBlock=r=>{const a=geometry(r);return frameRows.get(r.frameIndex).some(s=>{if(s.index===r.index||!clockLike(s))return false;const b=geometry(s);
    return Math.abs(a.centerY-b.centerY)<=Math.max(a.height,b.height)*3&&(overlap(a,b)>=.2||Math.abs(a.centerX-b.centerX)<=.15);});};
  const overlap=(a,b)=>Math.max(0,Math.min(a.right,b.right)-Math.max(a.left,b.left))/Math.min(a.right-a.left,b.right-b.left);
  if(options.baselineRoleRevision!==true){
    const fixed=out.families.filter(f=>f.events&&f.events.length>1&&f.observedFrames>=CAPTION_LANE_POLICY.recurringFixedMinimumFrames&&
      !frozenBody.some(r=>decision(r).familyId===f.id)&&f.stableStates<=1).filter(f=>{
      const events=f.events.filter(e=>[...e.representative.text.trim()].length>=CAPTION_LANE_POLICY.recurringFixedMinimumCodePoints);
      return events.some((e,i)=>events.slice(i+1).some(s=>s.firstObserved-e.lastObserved>CAPTION_LANE_POLICY.maximumContextSeconds&&
        e.refs.length>=2&&s.refs.length>=2&&base.similar(e.representative.text,s.representative.text)));
    });
    out.captionLaneFixedScreenEvidence=[];
    for(const r of raw.rows){const d=decision(r);if(!d||d.decision==='proposed_caption'||!d.read.selected)continue;
      const text=d.read.selected.text;if([...text.trim()].length<CAPTION_LANE_POLICY.recurringFixedMinimumCodePoints)continue;
      const a=geometry(r),witness=fixed.find(f=>{const b=f.profile;
        return base.similar(text,f.events[0].representative.text)&&Math.abs(a.centerY-b.centerY)<=b.height*.9&&
          a.height/b.height>=.6&&a.height/b.height<=4&&overlap(a,b)>=.35;});
      if(!witness)continue;
      const entry={schema:'recurring-fixed-screen-line-evidence-v199',kind:'repeated_fixed_language_overlay',rowRef:d.ref,
        witnessFamilyId:witness.id,supportRefs:witness.rowRefs,sceneGapSeconds:CAPTION_LANE_POLICY.maximumContextSeconds,
        rawRetained:true,semanticRoleVerified:false};
      d.previousFixedScreenDecision=JSON.parse(JSON.stringify(d));d.decision='screen_information_candidate';
      d.reason='recurring_fixed_language_overlay_requires_own_role_evidence';d.roleEvidence=entry;
      out.captionLaneFixedScreenEvidence.push(entry);
    }
  }
  function relation(r,seed,countCheck=true){
    if(countCheck)tick();const a=geometry(r),b=geometry(seed),ratio=a.height/b.height;
    return {eligible:ratio>=CAPTION_LANE_POLICY.minimumHeightRatio&&ratio<=CAPTION_LANE_POLICY.maximumHeightRatio
      &&a.height<=CAPTION_LANE_POLICY.maximumCropHeightFraction
      &&Math.abs(a.centerY-b.centerY)<=b.height*CAPTION_LANE_POLICY.maximumPrimaryCenterHeightUnits
      &&(overlap(a,b)>=CAPTION_LANE_POLICY.minimumHorizontalOverlap||Math.abs(a.centerX-b.centerX)<=CAPTION_LANE_POLICY.maximumCenterXDifference),
      centerHeightUnits:Math.abs(a.centerY-b.centerY)/b.height,heightRatio:ratio,horizontalOverlap:overlap(a,b),
      candidateGeometry:a,supportGeometry:b};
  }
  function localSupports(r){
    const matches=[];
    for(const [id,seeds]of seedByLane){
      const before=seeds.filter(s=>s.time<r.time).at(-1),after=seeds.find(s=>s.time>r.time),same=seeds.filter(s=>s.frameIndex===r.frameIndex);
      // A future primary observation cannot turn a preceding opening title into
      // narration. The lane must already exist, or be present in this own frame.
      if(!before&&!same.length)continue;
      const supports=[...same,...[before,after].filter(s=>s&&Math.abs(s.time-r.time)<=CAPTION_LANE_POLICY.maximumContextSeconds)];
      let accepted=supports.map(s=>({r:s,relation:relation(r,s)})).filter(x=>x.relation.eligible),continuity=null;
      if(!accepted.length&&options.baselineRoleRevision!==true){
        // A closer styled/big crop may be incompatible with this observation.
        // Find another actual frozen seed, never an inherited point, and require
        // every intervening source frame to own one compatible observed line.
        const previous=seeds.filter(s=>s.time<r.time&&r.time-s.time<=CAPTION_LANE_POLICY.maximumContextSeconds)
          .slice().sort((a,b)=>b.time-a.time||a.index-b.index);
        for(const seed of previous){const edge=relation(r,seed);if(!edge.eligible)continue;
          const path=sourceContinuousPath(seed,r);if(!path)continue;
          accepted=[{r:seed,relation:edge}];continuity=path;break;
        }
      }
      if(accepted.length)matches.push({laneId:id,support:accepted,primaryFamilyId:primaryIds[[...seedByLane.keys()].indexOf(id)],
        ...(continuity?{sourceContinuousSupport:continuity}:{} )});
    }
    return matches.length===1?matches[0]:null;
  }
  function sourceContinuousPath(seed,r){
    const frames=raw.frames.filter(f=>f.frameIndex>=seed.frameIndex&&f.frameIndex<=r.frameIndex),path=[];
    if(frames.length!==r.frameIndex-seed.frameIndex+1)return null;
    for(let i=0;i<frames.length;i++){const f=frames[i];tick();
      if(f.detectorStatus!=='complete'||f.status!==undefined&&f.status!=='observed'||
        i&&(f.frameIndex!==frames[i-1].frameIndex+1||f.time-frames[i-1].time>.59))return null;
      // An unread/failed compatible crop still creates physical-line ambiguity;
      // weak recognition cannot erase its geometry to certify a unique witness.
      const possible=(frameRows.get(f.frameIndex)||[]).filter(s=>relation(s,seed).eligible);
      if(possible.length!==1||!readable(possible[0])||persistent(possible[0])||separateIndexBlock(possible[0]))return null;
      path.push(possible[0]);
    }
    if(path[0].index!==seed.index||path.at(-1).index!==r.index)return null;
    if(path.every(s=>base.similar(decision(s).read.selected.text,decision(seed).read.selected.text)))return null;
    return {schema:'fixed-root-source-continuity-v199',rootRef:decision(seed).ref,observationRefs:path.map(s=>decision(s).ref),
      perFrameUnique:true,rootGeometryFixed:true,inheritedRowsEstablishAnchors:false,semanticRoleVerified:false};
  }
  const rectangleOverlap=(r,s)=>{const a=r.sourceRect,b=s.sourceRect,area=Math.max(0,Math.min(a.right,b.right)-Math.max(a.left,b.left))*Math.max(0,Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top));
    return area/Math.min((a.right-a.left)*(a.bottom-a.top),(b.right-b.left)*(b.bottom-b.top));};
  const proposals=[];
  const persistenceCache=new Map();out.captionLaneCompanionPersistenceEvidence=[];
  function persistentCompanionConflict(r,primaryFamilyId){
    if(options.baselineRoleRevision===true)return null;const d=decision(r),family=families.get(d.familyId),primary=families.get(primaryFamilyId);
    if(!family||!primary||frozenBodyIds.has(r.index))return null;
    const ownIndex=family.events.findIndex(e=>e.refs.some(ref=>ref.rowId===d.ref.rowId));if(ownIndex<0)return null;
    const key=JSON.stringify([family.id,primary.id]);if(!persistenceCache.has(key)){
      const languageBudget={pairs:0,cells:0},classes=selector.substantiveLanguageEvidence({...family,eligible:true},languageBudget).stateWitnesses,proofs=[];
      for(const state of classes){let witness=null;for(const index of state.eventIndices){const fixed=family.events[index],frameIds=new Set(fixed.refs.map(ref=>ref.sourceFrameId)),events=[];
        for(const e of primary.events){tick();const refs=e.refs.filter(ref=>frameIds.has(ref.sourceFrameId)&&frozenBody.some(s=>rowId(s)===ref.rowId));
          if(refs.length<COMPANION_PERSISTENCE_POLICY.minimumStablePrimaryFrames)continue;
          events.push({...e,refs,firstObserved:refs[0].time,lastObserved:refs.at(-1).time});}
        const strong=selector.substantiveLanguageEvidence({...primary,events,eligible:true},languageBudget);
        if(strong.qualified&&strong.substantiveLanguageStates>=COMPANION_PERSISTENCE_POLICY.minimumIndependentPrimaryStates&&strong.substantiveTransitions>=COMPANION_PERSISTENCE_POLICY.minimumPrimaryChanges){
          witness={fixedEventIndex:index,fixedSupportRefs:fixed.refs,primaryStateEvidence:strong};break;}}
        if(witness)proofs.push({eventIndices:state.eventIndices,...witness});}
      persistenceCache.set(key,proofs);
    }
    const proof=persistenceCache.get(key).find(p=>p.eventIndices.includes(ownIndex));if(!proof)return null;
    return{schema:'caption-companion-persistence-conflict-v199-r10',kind:'same_literal_companion_over_changing_primary',policy:COMPANION_PERSISTENCE_POLICY,
      rowRef:d.ref,primaryFamilyId,ownEventIndex:ownIndex,sameLiteralClassEventIndices:proof.eventIndices,
      fixedWitnessSupportRefs:proof.fixedSupportRefs,primaryStateEvidence:proof.primaryStateEvidence,
      candidateStillRequiresItsOwnCompanionGeometry:true,rawRetained:true,wholeFamilyDemoted:false,semanticRoleVerified:false};
  }
  function queue(r,support,kind,id=support.laneId,extra={}){
    proposals.push({r,id,kind,primaryFamilyId:support.primaryFamilyId,supportRefs:support.support.map(x=>decision(x.r).ref),
      spatialRelation:support.support.map(x=>({supportRowIndex:x.r.index,supportTime:x.r.time,...relation(r,x.r,false)})),
      ...(support.sourceContinuousSupport?{sourceContinuousSupport:support.sourceContinuousSupport}:{}),...extra});
  }
  try{
    // A clock can animate into its scene label on the following sampled frame.
    // Track that observed block, not its geometry family: a later wider caption
    // on the same baseline may still inherit. This is an ambiguity veto only;
    // it does not claim the literal is a semantically verified screen label.
    const clockRows=raw.rows.filter(clockLike),indexBlocks=new Map(),ordered=raw.rows.slice().sort((a,b)=>a.time-b.time||a.index-b.index);
    for(const r of ordered){if(!promotable(r))continue;const a=geometry(r);
      const nearbyClock=clockRows.find(s=>{tick();const dt=r.time-s.time,b=geometry(s);return dt>=0&&dt<=CAPTION_LANE_POLICY.clockLabelTransitionMaximumSeconds
        &&Math.abs(a.centerY-b.centerY)<=Math.max(a.height,b.height)*3&&(overlap(a,b)>=.2||Math.abs(a.centerX-b.centerX)<=.15);});
      if(nearbyClock){indexBlocks.set(r.index,{rootRef:decision(nearbyClock).ref,rootWidth:a.right-a.left});continue;}
      const prior=nearbyRows(r,CAPTION_LANE_POLICY.clockLabelChainMaximumSeconds)
        .filter(s=>s.time<r.time&&indexBlocks.has(s.index));
      for(const s of prior){tick();const b=geometry(s),block=indexBlocks.get(s.index),ratio=a.height/b.height;
        if(ratio>=.7&&ratio<=1.5&&a.right-a.left<=block.rootWidth*CAPTION_LANE_POLICY.clockLabelChainMaximumWidthRatio
          &&Math.abs(a.centerY-b.centerY)<=Math.max(a.height,b.height)*CAPTION_LANE_POLICY.sameLineCenterHeightUnits
          &&(overlap(a,b)>=.5||Math.abs(a.centerX-b.centerX)<=.08)){indexBlocks.set(r.index,block);break;}}
    }
    out.captionLaneIndexAmbiguities=[...indexBlocks].map(([index,block])=>({rowRef:decision(rawByIndex.get(index)).ref,
      clockWitnessRef:block.rootRef,kind:'scene_local_clock_to_label_block',inheritanceVeto:true,semanticRoleVerified:false}));
    // No whole-family promotion: each observed row needs its own source-local
    // replacement evidence, and inherits only an already established lane.
    for(const r of raw.rows){if(!promotable(r)||separateIndexBlock(r)||indexBlocks.has(r.index))continue;const support=localSupports(r);if(!support)continue;
      const currentBody=frameRows.get(r.frameIndex).filter(s=>frozenBodyIds.has(s.index));
      // A nested duplicate crop or an extra same-line label beside an existing
      // main caption does not become new body text merely because it is close.
      if(currentBody.some(s=>rectangleOverlap(r,s)>.35||Math.abs(geometry(r).centerY-geometry(s).centerY)<=Math.max(geometry(r).height,geometry(s).height)*CAPTION_LANE_POLICY.sameLineCenterHeightUnits))continue;
      queue(r,support,'scene_local_caption_lane_replacement');
    }
    const direct=new Map(proposals.map(p=>[p.r.index,p]));
    if(options.baselineRoleRevision!==true){
      // Exact-literal bracketing is an observation-local proof, not a new anchor.
      // Both neighbours must already point directly to the same frozen source
      // root; the middle row also matches that qualified family's fixed geometry.
      for(const r of raw.rows){if(!promotable(r)||direct.has(r.index)||indexBlocks.has(r.index)||separateIndexBlock(r))continue;
        const text=decision(r).read.selected.text.normalize('NFKC').replace(/\p{White_Space}/gu,'');
        const neighbours=[r.frameIndex-1,r.frameIndex+1].map(fi=>[...direct.values()].filter(p=>p.r.frameIndex===fi&&
          Math.abs(p.r.time-r.time)<=.59&&decision(p.r).read.selected.text.normalize('NFKC').replace(/\p{White_Space}/gu,'')===text));
        if(neighbours.some(a=>a.length!==1))continue;
        const [before,after]=neighbours.map(a=>a[0]);if(before.id!==after.id||before.primaryFamilyId!==after.primaryFamilyId)continue;
        const shared=before.supportRefs.filter(a=>after.supportRefs.some(b=>a.rowId===b.rowId&&a.sourceSha256===b.sourceSha256));
        if(!shared.length||shared.some(s=>!frozenBody.some(q=>rowId(q)===s.rowId)))continue;
        const profile=families.get(before.primaryFamilyId)?.profile,a=geometry(r);if(!profile)continue;
        const ratio=a.height/profile.height;
        if(ratio<.6||ratio>4||Math.abs(a.centerY-profile.centerY)>profile.height*.9||overlap(a,profile)<.35)continue;
        const peers=(frameRows.get(r.frameIndex)||[]).filter(s=>{const b=geometry(s);return Math.abs(a.centerY-b.centerY)<=Math.max(a.height,b.height)*.55&&overlap(a,b)>=.35;});
        if(peers.length!==1||peers[0].index!==r.index)continue;
        const support={laneId:before.id,primaryFamilyId:before.primaryFamilyId,support:shared.map(s=>({r:rawByIndex.get(Number(s.rowId.slice(16)))}))};
        queue(r,support,'scene_local_caption_lane_replacement',before.id,{sameLiteralBracket:{schema:'source-bound-same-literal-bracket-v199',
          neighbourRefs:[decision(before.r).ref,decision(after.r).ref],sharedQualifiedRootRefs:shared,qualifiedFamilyProfile:{...profile},
          perFrameUnique:true,interpolationAcrossMissingFrames:false,neighboursEstablishAnchors:false,semanticRoleVerified:false}});
      }
    }
    // At a reflow frame, an observed companion may use the directly anchored
    // primary row as a geometric witness, never as a newly established anchor.
    for(const r of raw.rows){if(!promotable(r)||separateIndexBlock(r)||indexBlocks.has(r.index)||direct.has(r.index)
      ||families.get(decision(r).familyId)?.observedFrames<CAPTION_LANE_POLICY.companionMinimumObservedFrames)continue;const a=geometry(r);
      const literal=decision(r).read.selected.text.normalize('NFKC').replace(/\p{White_Space}/gu,'');
      const repeated=nearbyRows(r,CAPTION_LANE_POLICY.companionRepeatMaximumSeconds).some(s=>{tick();if(s.frameIndex===r.frameIndex||!readable(s))return false;
        const b=geometry(s);return decision(s).read.selected.text.normalize('NFKC').replace(/\p{White_Space}/gu,'')===literal
          &&Math.abs(a.centerY-b.centerY)<=Math.max(a.height,b.height)*.5&&overlap(a,b)>=.5;});
      if(!repeated)continue;
      const peers=frameRows.get(r.frameIndex).filter(s=>s.index!==r.index&&(frozenBodyIds.has(s.index)||direct.has(s.index)));
      const possible=[];
      for(const s of peers){tick();const b=geometry(s),ratio=a.height/b.height,dy=Math.abs(a.centerY-b.centerY),gap=Math.max(0,dy-(a.height+b.height)/2);
        if(ratio<CAPTION_LANE_POLICY.companionMinimumHeightRatio||ratio>CAPTION_LANE_POLICY.companionMaximumHeightRatio
          ||dy<Math.max(a.height,b.height)*.6||gap>Math.max(a.height,b.height)*CAPTION_LANE_POLICY.companionMaximumGapHeightUnits
          ||overlap(a,b)<CAPTION_LANE_POLICY.companionMinimumHorizontalOverlap)continue;
        possible.push(s);
      }
      if(possible.length!==1)continue;const s=possible[0],p=direct.get(s.index),support=p?{laneId:p.id,primaryFamilyId:p.primaryFamilyId,
        support:p.spatialRelation.map(v=>({r:rawByIndex.get(v.supportRowIndex),relation:v}))}:localSupports(s);
      if(!support)continue;
      const persistence=persistentCompanionConflict(r,support.primaryFamilyId);if(persistence){const d=decision(r);
        d.previousCompanionCandidateDecision=JSON.parse(JSON.stringify(d));d.decision='screen_information_candidate';
        d.reason='same_literal_companion_outlasts_independent_primary_caption_changes';d.captionLaneId=null;d.roleEvidence=persistence;
        out.captionLaneCompanionPersistenceEvidence.push(persistence);continue;}
      const side=a.centerY>geometry(s).centerY?'below':'above';
      queue(r,support,'scene_local_caption_lane_companion',support.laneId+':'+side,
        {parentCaptionLaneId:support.laneId,companionWitnessRef:decision(s).ref,companionWitnessEstablishesAnchor:false});
    }
    // Two disjoint spans on one actual line retain separate slots, so a
    // simultaneous right-hand phrase cannot consume a left-hand timeline.
    const originalLaneIds=new Map(proposals.map(p=>[p,p.id]));
    for(const p of proposals){const sameLine=proposals.filter(q=>q!==p&&q.r.frameIndex===p.r.frameIndex&&originalLaneIds.get(q)===originalLaneIds.get(p)
      &&Math.abs(geometry(q.r).centerY-geometry(p.r).centerY)<=Math.max(geometry(q.r).height,geometry(p.r).height)*CAPTION_LANE_POLICY.sameLineCenterHeightUnits
      &&rectangleOverlap(q.r,p.r)<.1);
      if(sameLine.length){p.parentCaptionLaneId=p.id;p.id+=':span-'+(geometry(p.r).centerX<.5?'left':'right');}}
    for(const p of proposals){const d=decision(p.r);d.previousLaneDecision=d.decision;d.decision='proposed_caption';d.reason=p.kind;d.captionLaneId=p.id;
      const entry={schema:'caption-lane-row-evidence-v195',id:'caption-lane-evidence-'+(out.captionLaneEvidence.length+1),kind:p.kind,
        captionLaneId:p.id,primaryFamilyId:p.primaryFamilyId,rowRef:d.ref,supportRefs:p.supportRefs,
        sourceFrameId:p.r.frameId,time:p.r.time,spatialRelation:p.spatialRelation,
        ...(p.parentCaptionLaneId?{parentCaptionLaneId:p.parentCaptionLaneId}:{}),
        ...(p.companionWitnessRef?{companionWitnessRef:p.companionWitnessRef,companionWitnessEstablishesAnchor:false}:{}),
        ...(p.sourceContinuousSupport?{sourceContinuousSupport:p.sourceContinuousSupport}:{}),
        ...(p.sameLiteralBracket?{sameLiteralBracket:p.sameLiteralBracket}:{}),
        sceneLocal:true,wholeFamilyPromoted:false,textCorrectnessVerified:false,semanticRoleVerified:false};
      d.roleEvidence=entry;out.captionLaneEvidence.push(entry);
    }
    out.captionLaneAnalysisComplete=true;
  }catch(e){if(!['caption_lane_resource_budget','competition_budget'].includes(e.message))throw e;
    const failed=JSON.parse(JSON.stringify(initial));failed.captionLanePolicy=CAPTION_LANE_POLICY;failed.captionLaneAnalysisComplete=false;
    failed.captionLaneAnalysisReasons=['caption_lane_resource_budget_no_partial_promotions'];failed.captionLaneEvidence=[];
    for(const d of failed.decisions)d.captionLaneId=null;
    failed.roleGraphAnalysisComplete=false;return failed;
  }
  out.statistics={...out.statistics,proposedRows:out.decisions.filter(d=>d.decision==='proposed_caption').length,
    visibleRecoveryRows:out.decisions.filter(d=>d.decision==='visible_recovery_candidate').length,
    screenInfoRowObservations:out.decisions.filter(d=>d.decision==='screen_information_candidate').length,
    captionLaneInheritedRows:out.captionLaneEvidence.length,captionLaneChecks:checks};
  return out;
}
const LOCAL_PARTIAL_POLICY=Object.freeze({id:'complete-native-frame-language-roles-v199-r9',
  minimumCompleteObservedFrames:6,minimumStableLanguageStates:3,minimumSupportedChanges:2,
  maximumAnchorDominantFraction:.8,uniqueScoreRatio:1.3,maximumSimultaneousFraction:.2,
  maximumContextSeconds:8,maximumCenterHeightUnits:.9,minimumHeightRatio:.6,maximumHeightRatio:1.8,
  minimumHorizontalOverlap:.35,maximumChecks:500000,
  partialFramesEstablishAnchors:false,partialFramesContributeLanguageEvidence:false,
  rawFrameStatusChanged:false,rawRowsRemoved:false,wholeVideoComplete:false,
  geometryProxyIsNotFont:true,usesExpectedText:false,semanticRoleVerified:false});
function proposeLocalPartialRoles(raw,input,initial,options={}){
  const out=JSON.parse(JSON.stringify(initial)),association=load('associate-text-lines-v2.cjs').associate(input),base=load('main-caption-selector-v4.cjs');
  const completeFrames=association.frames.filter(f=>f.detectionStatus==='completed'),completeIds=new Set(completeFrames.map(f=>f.sourceFrameId));
  const byFrame=new Map(association.frames.map(f=>[f.sourceFrameId,f])),rows=association.frames.flatMap(f=>f.rows),rowById=new Map(rows.map(r=>[r.id,r]));
  const ds=new Map(out.decisions.map(d=>[d.ref.rowId,d])),rawById=new Map(raw.rows.map(r=>['source-rect-row-'+r.index,r]));
  out.localRolePolicy=LOCAL_PARTIAL_POLICY;out.localRoleDecisionUsable=false;out.localRoleGraphAnalysisComplete=false;
  out.localRoleAnalysis={schema:'source-local-partial-role-analysis-v199-r9',sourceSha256:raw.sourceSha256,
    sourceBinding:localSourceBinding(raw),
    completeFrameIndices:completeFrames.map(f=>f.originalRef.resultIndex),
    excludedAnchorFrameIndices:association.frames.filter(f=>!completeIds.has(f.sourceFrameId)).map(f=>f.originalRef.resultIndex),
    samplingComplete:false,wholeVideoComplete:false,partialFramesEstablishAnchors:false,semanticRoleVerified:false,
    anchorEvidence:[],anchors:[],rowEvidence:[],rejectedRows:[],analysisReasons:[],allRawRowsRetained:true};
  const evidence=out.localRoleAnalysis,budget={pairs:0,cells:0};let checks=0;
  const requested=options.localRoleMaximumChecks??options.maximumChecks;
  const limit=Number.isSafeInteger(requested)&&requested>0?Math.min(requested,LOCAL_PARTIAL_POLICY.maximumChecks):LOCAL_PARTIAL_POLICY.maximumChecks;
  const tick=()=>{if(++checks>limit)throw Error('local_role_budget');};
  const median=values=>{const a=values.slice().sort((x,y)=>x-y);return(a[(a.length-1)>>1]+a[a.length>>1])/2;};
  const profile=rs=>Object.fromEntries(['centerY','height','left','centerX','right','angle'].map(k=>[k,median(rs.map(r=>r.geometryProxy[k]))]));
  const overlap=(a,b)=>Math.max(0,Math.min(a.right,b.right)-Math.max(a.left,b.left))/Math.min(a.right-a.left,b.right-b.left);
  function relation(a,b){tick();const ratio=a.height/b.height;
    return ratio>=LOCAL_PARTIAL_POLICY.minimumHeightRatio&&ratio<=LOCAL_PARTIAL_POLICY.maximumHeightRatio&&
      Math.abs(a.centerY-b.centerY)<=b.height*LOCAL_PARTIAL_POLICY.maximumCenterHeightUnits&&
      overlap(a,b)>=LOCAL_PARTIAL_POLICY.minimumHorizontalOverlap&&Math.abs(a.angle-b.angle)<=.14;}
  const readable=r=>{const d=ds.get(r.id),text=d?.read.selected?.text;
    return typeof text==='string'&&/\p{L}/u.test(text)&&!load('main-caption-selector-v6.cjs').indexOnlyKind(text);};
  const reference=r=>JSON.parse(JSON.stringify(ds.get(r.id).ref));
  try{
    const measuredFamilies=out.families.map(f=>{
      const own=f.rowRefs.filter(ref=>completeIds.has(ref.sourceFrameId)).map(ref=>rowById.get(ref.rowId));
      if(!own.length)return null;
      const events=base.eventEvidence(own,input.samplingInterval),bins=new Set(own.map(r=>Math.min(7,Math.floor(r.time/input.duration*8))));
      const measured={...f,...events,profile:profile(own),rowRefs:own.map(reference),observedFrames:own.length,
        frameFraction:own.length/raw.frames.length,timelineBins:bins.size,
        eligible:own.length>=LOCAL_PARTIAL_POLICY.minimumCompleteObservedFrames&&events.stableStates>=3&&
          events.substantialTransitions>=2&&events.dominantStateFraction<=LOCAL_PARTIAL_POLICY.maximumAnchorDominantFraction};
      const strong=selector.substantiveLanguageEvidence(measured,budget);
      return {...measured,strong,completeRows:own};
    }).filter(Boolean);
    const groups=[];
    // Width/reflow changes may fragment a line into several geometry families.
    // Join only temporally exclusive families against the first fixed profile,
    // never transitively; simultaneous columns remain competing observations.
    for(const f of measuredFamilies.filter(f=>f.completeRows.length>=2&&f.events.some(e=>e.refs.length>=2))){
      const matching=groups.filter(g=>relation(f.profile,g.seedProfile)&&relation(g.seedProfile,f.profile)&&
        !f.completeRows.some(r=>g.rows.some(s=>s.sourceFrameId===r.sourceFrameId)));
      let group=matching.length===1?matching[0]:null;
      if(!group){group={id:f.id,seedProfile:f.profile,members:[],rows:[]};groups.push(group);}
      group.members.push(f);group.rows.push(...f.completeRows);
    }
    const local=groups.map(g=>{const own=g.rows.slice().sort((a,b)=>a.time-b.time||numeric.compareIds(a.id,b.id)),events=base.eventEvidence(own,input.samplingInterval);
      const bins=new Set(own.map(r=>Math.min(7,Math.floor(r.time/input.duration*8))));
      const measured={...g.members[0],...events,profile:profile(own),rowRefs:own.map(reference),completeRows:own,
        contributingFamilyIds:g.members.map(f=>f.id),observedFrames:own.length,frameFraction:own.length/raw.frames.length,timelineBins:bins.size,
        eligible:own.length>=LOCAL_PARTIAL_POLICY.minimumCompleteObservedFrames&&events.stableStates>=3&&
          events.substantialTransitions>=2&&events.dominantStateFraction<=LOCAL_PARTIAL_POLICY.maximumAnchorDominantFraction};
      return {...measured,strong:selector.substantiveLanguageEvidence(measured,budget)};});
    evidence.anchorEvidence=local.map(f=>({...f.strong,completeObservedFrames:f.observedFrames,
      sourceProfile:f.profile,partialFramesIncluded:false}));
    const rank=local.filter(f=>f.strong.qualified).sort((a,b)=>b.strong.roleScore-a.strong.roleScore||numeric.compareIds(a.id,b.id));
    if(!rank.length){evidence.analysisReasons.push('no_complete_frame_substantive_language_anchor');out.localRoleGraphAnalysisComplete=true;return out;}
    const co=(a,b)=>a.completeRows.filter(r=>b.completeRows.some(s=>s.sourceFrameId===r.sourceFrameId)).length/
      Math.min(a.completeRows.length,b.completeRows.length);
    const parallel=(a,b)=>{const p=a.profile,q=b.profile,h=Math.max(p.height,q.height),dy=Math.abs(p.centerY-q.centerY);
      return dy>=h*.8&&dy<=h*3&&overlap(p,q)>=.35&&Math.min(...['left','centerX','right'].map(k=>Math.abs(p[k]-q[k])))<=.05;};
    const first=rank[0],contest=rank.slice(1).find(f=>co(first,f)>=LOCAL_PARTIAL_POLICY.maximumSimultaneousFraction&&!parallel(first,f));
    if(contest&&first.strong.roleScore<contest.strong.roleScore*LOCAL_PARTIAL_POLICY.uniqueScoreRatio){
      evidence.analysisReasons.push('competing_complete_frame_language_tracks_no_unique_local_anchor');out.localRoleGraphAnalysisComplete=true;return out;
    }
    const anchors=rank.filter(f=>f===first||co(first,f)<LOCAL_PARTIAL_POLICY.maximumSimultaneousFraction||parallel(first,f));
    evidence.anchors=anchors.map((f,i)=>({familyId:f.id,contributingFamilyIds:f.contributingFamilyIds,captionLaneId:'caption-lane-'+raw.sourceSha256.slice(0,12)+'-'+String(i+1).padStart(3,'0'),
      sourceProfile:f.profile,completeSourceSupportRefs:f.rowRefs,substantiveLanguageStates:f.strong.substantiveLanguageStates,
      substantiveTransitions:f.strong.substantiveTransitions,partialFramesEstablishAnchors:false,semanticRoleVerified:false}));
    const chosen=new Map(),assign=(r,anchor,kind,support)=>{
      const d=ds.get(r.id),source=rawById.get(r.id),frame=byFrame.get(r.sourceFrameId);
      const entry={schema:'source-local-caption-row-evidence-v199-r9',kind,captionLaneId:anchor.captionLaneId,
        primaryFamilyId:anchor.familyId,rowRef:reference(r),supportRefs:support.map(reference),
        sourceFrameId:source.frameId,time:r.time,sourceDetectionStatus:frame.detectionStatus==='completed'?'complete':frame.detectionStatus,
        fixedQualifiedProfile:{...anchor.sourceProfile},partialSource:true,wholeVideoComplete:false,wholeFamilyPromoted:false,
        partialFramesEstablishAnchors:false,textCorrectnessVerified:false,semanticRoleVerified:false};
      d.previousLocalRoleDecision=JSON.parse(JSON.stringify(d));d.decision='proposed_caption';d.reason=kind;
      d.captionLaneId=anchor.captionLaneId;d.roleEvidence=entry;chosen.set(r.id,anchor);evidence.rowEvidence.push(entry);
    };
    // Only independently changing complete-frame families establish anchors.
    for(let i=0;i<anchors.length;i++)for(const r of anchors[i].completeRows){if(!readable(r)||!relation(r.geometryProxy,anchors[i].profile))continue;
      assign(r,evidence.anchors[i],'existing_qualified_caption_observation',[r]);}
    const frozen=new Set(chosen.keys());
    for(const r of rows){if(frozen.has(r.id)||!readable(r))continue;
      const frame=byFrame.get(r.sourceFrameId);if(!['completed','partial'].includes(frame.detectionStatus))continue;
      const matches=evidence.anchors.filter(anchor=>relation(r.geometryProxy,anchor.sourceProfile));
      if(matches.length!==1){if(matches.length)evidence.rejectedRows.push({rowRef:reference(r),reason:'multiple_fixed_local_profiles'});continue;}
      const anchor=matches[0],f=local.find(f=>f.id===anchor.familyId);
      const before=f.completeRows.filter(s=>frozen.has(s.id)&&s.time<r.time&&r.time-s.time<=LOCAL_PARTIAL_POLICY.maximumContextSeconds)
        .sort((a,b)=>b.time-a.time||numeric.compareIds(a.id,b.id))[0];
      const after=f.completeRows.filter(s=>frozen.has(s.id)&&s.time>r.time&&s.time-r.time<=LOCAL_PARTIAL_POLICY.maximumContextSeconds)
        .sort((a,b)=>a.time-b.time||numeric.compareIds(a.id,b.id))[0];
      const same=f.completeRows.filter(s=>frozen.has(s.id)&&s.sourceFrameId===r.sourceFrameId);
      if(!before&&!same.length)continue; // Later dialogue cannot classify an opening card.
      const repeatedTail=before&&r.time-before.time<=1.05&&raw.videoDuration-r.time<=1.05&&
        rows.some(s=>s.id!==r.id&&completeIds.has(s.sourceFrameId)&&Math.abs(s.time-r.time)<=.59&&relation(s.geometryProxy,anchor.sourceProfile)&&
          ds.get(s.id)?.read.selected?.text===ds.get(r.id).read.selected.text);
      if(frame.detectionStatus==='completed'&&!same.length&&!after&&!repeatedTail)continue;
      const peers=frame.rows.filter(s=>relation(s.geometryProxy,anchor.sourceProfile));
      if(peers.length!==1||peers[0].id!==r.id){evidence.rejectedRows.push({rowRef:reference(r),reason:'own_frame_line_geometry_not_unique'});continue;}
      const ownFamily=out.families.find(f=>f.id===ds.get(r.id).familyId),text=ds.get(r.id).read.selected.text;
      if(ownFamily&&ownFamily.observedFrames>=12&&ownFamily.dominantStateFraction>=.8||/^[\x00-\x7f\s]+$/u.test(text)&&[...text.trim()].length<=12)continue;
      assign(r,anchor,'scene_local_caption_lane_replacement',[...same,...(before?[before]:[]),...(after?[after]:[])]);
    }
    out.status='partial_caption_regions_proposed';out.localRoleDecisionUsable=chosen.size>0;out.localRoleGraphAnalysisComplete=true;
    out.localCaptionLaneAnalysisComplete=true;out.captionLaneAnalysisComplete=false;out.roleGraphAnalysisComplete=false;
    out.samplingPlanComplete=false;out.roleGraphAnchors={primaryFamilyIds:anchors.map(f=>f.id),connectedFamilyIds:anchors.map(f=>f.id)};
    out.primaryFamilyId=first.id;evidence.analysisReasons.push('local_complete_frame_language_anchors_full_source_stays_partial');
    evidence.resourceUse={...budget,geometryChecks:checks};
    out.statistics={...out.statistics,proposedRows:chosen.size,
      localCompleteFrameBodyRows:rows.filter(r=>chosen.has(r.id)&&completeIds.has(r.sourceFrameId)).length,
      localPartialFrameBodyRows:rows.filter(r=>chosen.has(r.id)&&!completeIds.has(r.sourceFrameId)).length,
      visibleRecoveryRows:out.decisions.filter(d=>d.decision==='visible_recovery_candidate').length,
      retainedRows:raw.rows.length,localRoleChecks:checks};
    out.fullVideoSubtitleRecallVerified=false;out.captionTextCorrectnessVerified=false;out.rawTextModified=false;return out;
  }catch(error){if(!['local_role_budget','competition_budget'].includes(error.message))throw error;
    const failed=JSON.parse(JSON.stringify(initial));failed.localRolePolicy=LOCAL_PARTIAL_POLICY;failed.localRoleDecisionUsable=false;
    failed.localRoleGraphAnalysisComplete=false;failed.localRoleAnalysis={...evidence,anchors:[],rowEvidence:[],
      analysisReasons:['local_role_resource_budget_no_partial_promotions']};return failed;}
}
const COMPLETE_PHASE_POLICY=Object.freeze({id:'independent-complete-source-caption-phases-v199-r10',
  preservesExistingQualifiedPrimary:true,requiresOwnSubstantiveLanguageAnchor:true,
  simultaneousPrimaryNeverOverridden:true,everyPointRequiresUniqueFixedSourceGeometry:true,
  wholeFamilyPromoted:false,samplingStatusChanged:false,usesExpectedText:false,semanticRoleVerified:false});
function proposeCompleteSourcePhases(raw,input,initial,options={}){
  const out=JSON.parse(JSON.stringify(initial));out.completeSourcePhaseRolePolicy=COMPLETE_PHASE_POLICY;
  const analysis={schema:'independent-complete-source-caption-phase-analysis-v199-r10',sourceSha256:raw.sourceSha256,
    sourceBinding:localSourceBinding(raw),samplingComplete:initial.samplingPlanComplete===true,
    roleGraphCompletenessPreserved:true,existingPrimaryPreserved:true,anchors:[],rowEvidence:[],rejectedRows:[],
    analysisComplete:false,allRawRowsRetained:true,wholeVideoSubtitleRecallVerified:false,semanticRoleVerified:false};
  out.completeSourcePhaseRoleAnalysis=analysis;
  if(initial.samplingPlanComplete!==true||initial.roleGraphAnalysisComplete!==true||initial.status!=='caption_regions_proposed')return out;
  // Reuse the native complete-frame evidence kernel. Its partial-source status
  // and local boolean are NOT imported into the complete-source caller.
  const checked=proposeLocalPartialRoles(raw,input,initial,options),e=checked.localRoleAnalysis;
  if(checked.localRoleGraphAnalysisComplete!==true){analysis.reasons=e?.analysisReasons||['independent_phase_evidence_incomplete'];return out;}
  const oldById=new Map(initial.decisions.map(d=>[d.ref.rowId,d])),byId=new Map(out.decisions.map(d=>[d.ref.rowId,d]));
  const newById=new Map(checked.decisions.map(d=>[d.ref.rowId,d])),rawById=new Map(raw.rows.map(r=>['source-rect-row-'+r.index,r]));
  const originalPrimaryIds=new Set(initial.roleGraphAnchors?.primaryFamilyIds||[]),originalPrimary=initial.decisions.filter(d=>d.decision==='proposed_caption'&&d.roleEvidence?.kind==='existing_qualified_caption_observation');
  const profileOf=r=>({left:r.sourceRect.left/raw.sourceVideoWidth,right:r.sourceRect.right/raw.sourceVideoWidth,
    centerY:(r.sourceRect.top+r.sourceRect.bottom)/2/raw.sourceVideoHeight,height:(r.sourceRect.bottom-r.sourceRect.top)/raw.sourceVideoHeight});
  const relation=(r,p)=>{const a=profileOf(r),ratio=a.height/p.height,overlap=Math.max(0,Math.min(a.right,p.right)-Math.max(a.left,p.left))/Math.min(a.right-a.left,p.right-p.left);
    return ratio>=LOCAL_PARTIAL_POLICY.minimumHeightRatio&&ratio<=LOCAL_PARTIAL_POLICY.maximumHeightRatio&&Math.abs(a.centerY-p.centerY)<=p.height*LOCAL_PARTIAL_POLICY.maximumCenterHeightUnits&&overlap>=LOCAL_PARTIAL_POLICY.minimumHorizontalOverlap;};
  for(const a of e?.anchors||[]){if(a.contributingFamilyIds.some(id=>originalPrimaryIds.has(id)))continue;
    // A simultaneous second line can be companion evidence, but does not
    // establish a new independent scene phase through this separate branch.
    const refs=a.completeSourceSupportRefs,cooccurring=refs.filter(ref=>originalPrimary.some(d=>d.ref.sourceFrameId===ref.sourceFrameId));
    if(cooccurring.length/refs.length>=LOCAL_PARTIAL_POLICY.maximumSimultaneousFraction){analysis.rejectedRows.push({familyId:a.familyId,reason:'independent_phase_overlaps_existing_qualified_primary'});continue;}
    const laneId='caption-phase-'+raw.sourceSha256.slice(0,12)+'-'+a.familyId,entry={...JSON.parse(JSON.stringify(a)),captionLaneId:laneId,proposedRowRefs:[]};
    for(const ref of refs){const old=oldById.get(ref.rowId),candidate=newById.get(ref.rowId),r=rawById.get(ref.rowId);if(!old||!candidate||!r||old.decision==='proposed_caption'||candidate.roleEvidence?.kind!=='existing_qualified_caption_observation')continue;
      if(originalPrimary.some(d=>d.ref.sourceFrameId===ref.sourceFrameId)||['repeated_fixed_language_overlay','same_literal_companion_over_changing_primary'].includes(old.roleEvidence?.kind))continue;
      const peers=raw.rows.filter(s=>s.frameIndex===r.frameIndex&&relation(s,a.sourceProfile));
      if(peers.length!==1||peers[0].index!==r.index){analysis.rejectedRows.push({rowRef:ref,reason:'independent_phase_fixed_source_geometry_not_unique'});continue;}
      const d=byId.get(ref.rowId);d.previousCompletePhaseDecision=JSON.parse(JSON.stringify(d));d.decision='proposed_caption';
      d.reason='independent_complete_source_language_phase';d.captionLaneId=laneId;
      d.roleEvidence={...JSON.parse(JSON.stringify(candidate.roleEvidence)),schema:'independent-complete-source-caption-row-evidence-v199-r10',
        kind:'existing_qualified_caption_observation',captionLaneId:laneId,supportRefs:JSON.parse(JSON.stringify(refs)),
        independentCompletePhase:true,partialSource:false,sourceSamplingComplete:true,wholeFamilyPromoted:false,semanticRoleVerified:false};
      entry.proposedRowRefs.push(ref);analysis.rowEvidence.push(d.roleEvidence);
    }
    if(entry.proposedRowRefs.length)analysis.anchors.push(entry);
  }
  analysis.analysisComplete=true;analysis.reasons=['independent_complete_frame_phases_checked_without_replacing_primary'];
  out.statistics={...out.statistics,proposedRows:out.decisions.filter(d=>d.decision==='proposed_caption').length,
    visibleRecoveryRows:out.decisions.filter(d=>d.decision==='visible_recovery_candidate').length,
    independentCompletePhaseBodyRows:analysis.rowEvidence.length};return out;
}
function localSourceBinding(raw){
  return {schema:'all-native-source-bindings-v199-r9',sourceSha256:raw.sourceSha256,videoDuration:raw.videoDuration,
    sourceVideoWidth:raw.sourceVideoWidth,sourceVideoHeight:raw.sourceVideoHeight,total:raw.total,processed:raw.processed,
    frames:raw.frames.map(f=>[f.frameIndex,f.frameId,f.time,f.status??null,f.detectorStatus,f.sourcePixelSha256]),
    rows:raw.rows.map(r=>{const c=r.cropReceipt,b=r.sourceRect,cb=c.sourceRect;
      return[r.index,r.frameIndex,r.frameId,r.time,r.frameTime,r.sourceWidth,r.sourceHeight,
        [b.left,b.top,b.right,b.bottom],r.inputWidth,r.inputHeight,r.cropPixelsSha256??null,r.text,r.confidence,
        [c.schema,c.frameId,c.time,[cb.left,cb.top,cb.right,cb.bottom],c.inputWidth,c.inputHeight,c.interpolation]];})};
}
function validateLocalRoleDecisionUsable(raw,selection){
  // The boolean is not authority. Reproduce the pure source-only decision and
  // require its complete frame/row/crop binding and local evidence to agree.
  try{
    adapter.adapt(raw);
    if(selection?.schemaVersion!==10||selection.sourceSha256!==raw.sourceSha256||selection.sourceDuration!==raw.videoDuration||
      selection.localRoleDecisionUsable!==true||selection.samplingPlanComplete!==false||
      selection.roleGraphAnalysisComplete!==false||selection.localRoleGraphAnalysisComplete!==true||
      selection.captionLaneAnalysisComplete!==false||selection.localCaptionLaneAnalysisComplete!==true||
      selection.status!=='partial_caption_regions_proposed'||selection.allRowsRetained!==true||
      selection.localRoleAnalysis?.schema!=='source-local-partial-role-analysis-v199-r9'||
      selection.localRoleAnalysis.sourceSha256!==raw.sourceSha256||selection.localRoleAnalysis.samplingComplete!==false||
      selection.localRoleAnalysis.wholeVideoComplete!==false||selection.localRoleAnalysis.semanticRoleVerified!==false||
      JSON.stringify(selection.localRoleAnalysis.sourceBinding)!==JSON.stringify(localSourceBinding(raw)))return {valid:false,reason:'local_source_receipt_missing_or_mismatched'};
    const expected=selectNative(raw);
    if(expected.localRoleDecisionUsable!==true||JSON.stringify(expected.localRoleAnalysis)!==JSON.stringify(selection.localRoleAnalysis)||
      JSON.stringify(expected.policy)!==JSON.stringify(selection.policy)||
      JSON.stringify(expected.decisions)!==JSON.stringify(selection.decisions))return {valid:false,reason:'source_only_local_role_replay_mismatch'};
    return {valid:true,schema:'validated-source-local-role-receipt-v199-r9',wholeVideoComplete:false,samplingComplete:false,
      completeAnchorFramesOnly:true,semanticRoleVerified:false};
  }catch(error){return {valid:false,reason:error.code||'invalid_local_source_role_receipt'};}
}
const REVISION_POLICY=Object.freeze({...selector.POLICY,version:10,baseVersion:9,
  revision:'r10-complete-source-phases-and-persistent-companion-v199',baseline:'r5-lanes-v195',
  globalCompletenessGateUnchanged:false,completeSamplingGateUnchanged:true,legacyUniquePrimaryRoleGateRevised:true,
  roleThresholdsChanged:true,anchorCompetitionPolicy:selector.COMPETITION_POLICY,
  oldDecisionsAudited:true,localPartialRolePolicy:LOCAL_PARTIAL_POLICY,completePhaseRolePolicy:COMPLETE_PHASE_POLICY,
  companionPersistencePolicy:COMPANION_PERSISTENCE_POLICY,semanticRoleVerified:false});
const REVISION_PROVENANCE=Object.freeze({schema:'caption-role-v10-r10-provenance-v199',
  revision:REVISION_POLICY.revision,baselineProvenance:provenance,
  roleThresholdsChanged:true,numericPolicyChanged:false,noNodeRuntimeDependencies:true,
  productionActivated:false,semanticRoleVerified:false});
function selectNative(raw,options={}){
  let p;try{p=adapter.adapt(raw);}catch(e){return {schemaVersion:10,status:'invalid_native_input',policy:REVISION_POLICY,
    arithmeticPolicy:numeric.POLICY,decisions:[],families:[],allRowsRetained:false,originalInputRetainedByCaller:true,
    roleGraphAnalysisComplete:false,roleGraphAnalysisReasons:[e.code||'invalid_native_input'],roleGraphProposals:[],
    roleGraphDemotions:[],roleGraphRecoveries:[],claimsNoText:false,rawTextModified:false,productionChanged:false,
    fullVideoSubtitleRecallVerified:false};}
  // Competition evidence is produced only from this call's bound raw input;
  // a caller cannot supply expected-role families through the options object.
  const nativeOptions={...options,captionAnchorCompetition:undefined,baselineRoleRevision:false};
  const initial=selector.select(p.input,nativeOptions),legacy=inheritCaptionLanes(raw,initial,{...nativeOptions,baselineRoleRevision:true});
  const competition=initial.samplingPlanComplete===true&&['caption_regions_proposed','no_unique_caption_region'].includes(initial.status)?
    selector.competingAnchor(initial):null;
  const replace=competition?.analysisComplete===true&&competition.replacementPrimaryFamilyIds.length;
  let out=inheritCaptionLanes(raw,replace?selector.select(p.input,{...nativeOptions,captionAnchorCompetition:competition}):initial,nativeOptions);
  if(initial.status==='unresolved_sampling'&&initial.samplingPlanComplete!==true)out=proposeLocalPartialRoles(raw,p.input,out,nativeOptions);
  else if(out.samplingPlanComplete===true&&out.roleGraphAnalysisComplete===true)out=proposeCompleteSourcePhases(raw,p.input,out,nativeOptions);
  out.schemaVersion=10;out.policy=REVISION_POLICY;out.roleRevision=REVISION_POLICY.revision;
  out.arithmeticPolicy=numeric.POLICY;out.anchorCompetition=competition;
  out.roleRevisionAudit={schema:'caption-role-revision-audit-v199',baselineSchema:'caption-role-v7-native-umd-r5-lanes-v195',
    previousPrimaryFamilyId:legacy.primaryFamilyId??null,previousAnchors:legacy.roleGraphAnchors??null,
    previousStatistics:legacy.statistics??null,changedRowRefs:[],allRawRowsRetained:true,semanticRoleVerified:false};
  const oldById=new Map(legacy.decisions.map(d=>[d.ref.rowId,d]));
  for(const d of out.decisions){const previous=oldById.get(d.ref.rowId);
    if(previous&&(previous.decision!==d.decision||previous.captionLaneId!==d.captionLaneId)){
      d.previousRoleRevisionDecision=JSON.parse(JSON.stringify(previous));out.roleRevisionAudit.changedRowRefs.push(d.ref);
    }
  }
  return out;
}
return Object.freeze({schema:'caption-role-v10-native-umd-r10-complete-phase-competition-v199',policy:REVISION_POLICY,
  arithmeticPolicy:numeric.POLICY,captionLanePolicy:CAPTION_LANE_POLICY,anchorCompetitionPolicy:selector.COMPETITION_POLICY,
  provenance:REVISION_PROVENANCE,geometryContract:adapter.GEOMETRY_CONTRACT,selectNative,
  validateLocalRoleDecisionUsable,adaptNative:adapter.adapt});});
