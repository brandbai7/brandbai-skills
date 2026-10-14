/* V2 changes only near-integer scoring scan bounds; it never moves a quad.
 * Bounded detector-map geometry only. This is NOT official polygon unclip,
 * a physical single-line certificate, caption-role selection, or OCR text.
 * All points use continuous pixel-edge coordinates, x right / y down. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.BrandbaiDBTextLinesV2 = api;
})(globalThis, function () {
  "use strict";
  const POLICY = "same_frame_db_connected_component_rectangle_candidate_not_line_or_text_certificate_v2";
  const LIMITS = Object.freeze({ maxPixels: 1280 * 1280, maxCandidates: 512, maxLines: 128,
    maxGeometryChecks: 5000000, maxScorePixels: 8000000 });
  const EPS = 1e-9, ROUNDING_TOLERANCE = 1e-6;
  const SCAN_INTEGER_SNAP_TOLERANCE = 1e-9;
  const SCAN_BOUNDARY_POLICY = "scan_bbox_snap_near_integer_1e-9_only_quads_and_scoring_membership_unchanged";
  function scanInteger(n) {
    const rounded = Math.round(n);
    return Math.abs(n - rounded) <= SCAN_INTEGER_SNAP_TOLERANCE ? rounded : n;
  }
  const integer = (n, lo, hi) => Number.isSafeInteger(n) && n >= lo && n <= hi;
  const copyPoints = q => q.map(p => ({ x: p.x, y: p.y }));
  const cross = (a, b, c) => (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
  function bounds(q) {
    return { left: Math.min(...q.map(p => p.x)), top: Math.min(...q.map(p => p.y)),
      right: Math.max(...q.map(p => p.x)), bottom: Math.max(...q.map(p => p.y)) };
  }
  function rotate(q, n) { return q.slice(n).concat(q.slice(0, n)); }
  function topLeftIndex(q) {
    let n = 0;
    for (let i = 1; i < q.length; i++) {
      const d = q[i].x + q[i].y - q[n].x - q[n].y;
      if (d < -EPS || (Math.abs(d) <= EPS && (q[i].y < q[n].y - EPS ||
        (Math.abs(q[i].y - q[n].y) <= EPS && q[i].x < q[n].x)))) n = i;
    }
    return n;
  }
  function hull(points) {
    points.sort((a, b) => a.x - b.x || a.y - b.y);
    const unique = points.filter((p, i) => !i || p.x !== points[i - 1].x || p.y !== points[i - 1].y);
    const lower = [], upper = [];
    for (const p of unique) { while (lower.length > 1 && cross(lower.at(-2), lower.at(-1), p) <= 0) lower.pop(); lower.push(p); }
    for (let i = unique.length - 1; i >= 0; i--) {
      const p = unique[i]; while (upper.length > 1 && cross(upper.at(-2), upper.at(-1), p) <= 0) upper.pop(); upper.push(p);
    }
    return lower.slice(0, -1).concat(upper.slice(0, -1));
  }
  function minRectangle(points, budget) {
    let best = null;
    for (let i = 0; i < points.length; i++) {
      const a = points[i], b = points[(i + 1) % points.length];
      let angle = Math.atan2(b.y - a.y, b.x - a.x);
      while (angle < -Math.PI / 4) angle += Math.PI / 2;
      while (angle >= Math.PI / 4) angle -= Math.PI / 2;
      const ux = Math.cos(angle), uy = Math.sin(angle), vx = -uy, vy = ux;
      let minU = Infinity, maxU = -Infinity, minV = Infinity, maxV = -Infinity;
      for (const p of points) {
        if (budget.geometryChecks >= budget.limits.maxGeometryChecks) return null;
        budget.geometryChecks++;
        const u = p.x * ux + p.y * uy, v = p.x * vx + p.y * vy;
        minU = Math.min(minU, u); maxU = Math.max(maxU, u); minV = Math.min(minV, v); maxV = Math.max(maxV, v);
      }
      const area = (maxU - minU) * (maxV - minV);
      const tolerance = Math.max(1, area, best ? best.area : 0) * 1e-10;
      if (!best || area < best.area - tolerance || (Math.abs(area - best.area) <= tolerance &&
        (Math.abs(angle) < Math.abs(best.angle) - EPS || (Math.abs(Math.abs(angle) - Math.abs(best.angle)) <= EPS && angle < best.angle)))) {
        best = { angle, ux, uy, vx, vy, minU, maxU, minV, maxV, area };
      }
    }
    return best;
  }
  function rectangleQuad(r, distance = 0) {
    return [[r.minU - distance, r.minV - distance], [r.maxU + distance, r.minV - distance],
      [r.maxU + distance, r.maxV + distance], [r.minU - distance, r.maxV + distance]]
      .map(([u, v]) => ({ x: u * r.ux + v * r.vx, y: u * r.uy + v * r.vy }));
  }
  function boxMean(data, width, height, r, budget) {
    const b = bounds(rectangleQuad(r));
    // Near-integer projection round-off can add an entirely empty scan column/row.
    // Its nearest pixel center is >= .5 - 1e-9 away from the true bbox, so it
    // cannot satisfy the existing 1e-9 rectangle membership test. Snap only
    // these loop bounds; original rectangle/quad and included-pixel test stay raw.
    const left = Math.max(0, Math.floor(scanInteger(b.left))), right = Math.min(width, Math.ceil(scanInteger(b.right))),
      top = Math.max(0, Math.floor(scanInteger(b.top))), bottom = Math.min(height, Math.ceil(scanInteger(b.bottom)));
    let sum = 0, count = 0;
    for (let y = top; y < bottom; y++) for (let x = left; x < right; x++) {
      if (budget.scorePixels >= budget.limits.maxScorePixels) return null;
      budget.scorePixels++;
      const u = (x + .5) * r.ux + (y + .5) * r.uy, v = (x + .5) * r.vx + (y + .5) * r.vy;
      if (u >= r.minU - EPS && u <= r.maxU + EPS && v >= r.minV - EPS && v <= r.maxV + EPS) { sum += data[y * width + x]; count++; }
    }
    return count ? { mean: sum / count, pixels: count } : null;
  }
  // Intersection is diagnostic only; it does not replace the original four-point sampling quad.
  function clipPolygon(q, width, height) {
    let out = copyPoints(q);
    const edges = [
      [p => p.x >= 0, (a, b) => ({ x: 0, y: a.y + (b.y - a.y) * -a.x / (b.x - a.x) })],
      [p => p.x <= width, (a, b) => ({ x: width, y: a.y + (b.y - a.y) * (width - a.x) / (b.x - a.x) })],
      [p => p.y >= 0, (a, b) => ({ x: a.x + (b.x - a.x) * -a.y / (b.y - a.y), y: 0 })],
      [p => p.y <= height, (a, b) => ({ x: a.x + (b.x - a.x) * (height - a.y) / (b.y - a.y), y: height })]
    ];
    for (const [inside, intersect] of edges) {
      const next = [];
      for (let i = 0; i < out.length; i++) {
        const a = out[i], b = out[(i + 1) % out.length], ai = inside(a), bi = inside(b);
        if (ai && bi) next.push(b); else if (ai && !bi) next.push(intersect(a, b)); else if (!ai && bi) next.push(intersect(a, b), b);
      }
      out = next;
    }
    return out;
  }
  function detect(input) {
    const candidates = [], rejectedCandidates = [], warnings = [];
    const overflow = { maxPixels: false, maxCandidates: false, maxLines: false, maxGeometryChecks: false, maxScorePixels: false };
    const diagnostics = { mapValidated: false, mapProcessed: false, componentsExamined: 0, foregroundPixels: null,
      processedForegroundPixels: 0, remainingForegroundPixels: null, remainingComponentsUnknown: false,
      geometryChecks: 0, scorePixels: 0, thresholdComparator: "strict_gt_float32_threshold",
      scorePolicy: "mean_at_pixel_centers_inside_unexpanded_rectangle_including_below_threshold_pixels",
      scoreScanBoundaryPolicy: SCAN_BOUNDARY_POLICY, scoreScanIntegerSnapTolerance: SCAN_INTEGER_SNAP_TOLERANCE,
      contourPolicy: "convex_hull_of_foreground_pixel_cell_edges_8_connected_no_dilation",
      completeTextExtentKnown: false, singleLineCertified: false, subtitleRoleConfirmed: false };
    let status = "complete";
    const output = () => ({ schemaVersion: 2, status, candidates, lines: candidates, rejectedCandidates, overflow, warnings,
      policy: POLICY, limits: { ...limits }, diagnostics });
    let limits = { ...LIMITS };
    const invalid = reason => { status = "invalid"; warnings.push({ reason }); return output(); };
    if (!input || typeof input !== "object") return invalid("invalid_input");
    const { data, width, height, sourceWidth, sourceHeight, frameId, time, sourceSha256 } = input;
    if (!integer(width, 1, 1280) || !integer(height, 1, 1280) || !integer(sourceWidth, 1, 4096) || !integer(sourceHeight, 1, 4096)) return invalid("invalid_dimensions");
    if (!ArrayBuffer.isView(data) || Object.prototype.toString.call(data) !== "[object Float32Array]" || data.length !== width * height) return invalid("invalid_float_map_shape");
    if (typeof frameId !== "string" || !frameId.length || frameId.length > 256 || !Number.isFinite(time) || time < 0 || time > 180 ||
      typeof sourceSha256 !== "string" || !/^[a-fA-F0-9]{64}$/.test(sourceSha256)) return invalid("invalid_own_frame_provenance");
    const threshold = input.threshold === undefined ? .3 : input.threshold,
      boxThreshold = input.boxThreshold === undefined ? .5 : input.boxThreshold,
      unclipRatio = input.unclipRatio === undefined ? 1.5 : input.unclipRatio;
    if (![threshold, boxThreshold].every(n => Number.isFinite(n) && n >= 0 && n <= 1) ||
      !Number.isFinite(unclipRatio) || unclipRatio < 0 || unclipRatio > 3) return invalid("invalid_detector_parameters");
    if (input.limits !== undefined) {
      if (!input.limits || typeof input.limits !== "object" || Array.isArray(input.limits) ||
        Object.keys(input.limits).some(k => !(k in LIMITS) || !integer(input.limits[k], 1, LIMITS[k]))) return invalid("invalid_or_raised_limits");
      limits = { ...limits, ...input.limits };
    }
    diagnostics.threshold = threshold; diagnostics.effectiveThreshold = Math.fround(threshold);
    diagnostics.boxThreshold = boxThreshold; diagnostics.unclipRatio = unclipRatio;
    if (data.length > limits.maxPixels) {
      status = "partial"; overflow.maxPixels = true; diagnostics.remainingComponentsUnknown = true;
      warnings.push({ reason: "map_pixel_budget", mapPixels: data.length, limit: limits.maxPixels, mapNotScanned: true }); return output();
    }
    let foreground = 0, roundingOutsideUnitInterval = 0;
    for (let i = 0; i < data.length; i++) {
      const n = data[i];
      if (!Number.isFinite(n) || n < -ROUNDING_TOLERANCE || n > 1 + ROUNDING_TOLERANCE) {
        diagnostics.invalidProbabilityIndex = i; return invalid("invalid_probability_value");
      }
      if (n < 0 || n > 1) roundingOutsideUnitInterval++;
      if (n > diagnostics.effectiveThreshold) foreground++;
    }
    if (roundingOutsideUnitInterval) warnings.push({ reason: "rounding_probability_outside_unit_interval", count: roundingOutsideUnitInterval,
      roundingTolerance: ROUNDING_TOLERANCE, mapClamped: false });
    diagnostics.mapValidated = true; diagnostics.foregroundPixels = foreground;
    const visited = new Uint8Array(data.length), queue = new Int32Array(data.length),
      rowMin = new Int32Array(height), rowMax = new Int32Array(height);
    rowMin.fill(width); rowMax.fill(-1);
    const budget = { limits, geometryChecks: 0, scorePixels: 0 };
    let stop = false;
    function exhaust(key, reason, metadata) {
      status = "partial"; overflow[key] = true; warnings.push({ reason, ...metadata });
    }
    for (let seed = 0; seed < data.length; seed++) {
      if (visited[seed] || data[seed] <= diagnostics.effectiveThreshold) continue;
      if (diagnostics.componentsExamined >= limits.maxCandidates) {
        exhaust("maxCandidates", "component_candidate_budget", { nextSeedIndex: seed, limit: limits.maxCandidates }); stop = true; break;
      }
      const id = `${frameId}:db:${seed}`, touched = [];
      let head = 0, tail = 1, minX = width, minY = height, maxX = -1, maxY = -1;
      queue[0] = seed; visited[seed] = 1;
      while (head < tail) {
        const p = queue[head++], y = Math.floor(p / width), x = p - y * width;
        if (rowMax[y] === -1) touched.push(y);
        rowMin[y] = Math.min(rowMin[y], x); rowMax[y] = Math.max(rowMax[y], x);
        minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y);
        for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
          const xx = x + dx, yy = y + dy;
          if ((!dx && !dy) || xx < 0 || xx >= width || yy < 0 || yy >= height) continue;
          const n = yy * width + xx;
          if (!visited[n] && data[n] > diagnostics.effectiveThreshold) { visited[n] = 1; queue[tail++] = n; }
        }
      }
      diagnostics.componentsExamined++; diagnostics.processedForegroundPixels += tail;
      const component = { id, seedIndex: seed, pixels: tail, mapBounds: { left: minX, top: minY, right: maxX + 1, bottom: maxY + 1 } };
      const points = [];
      for (const y of touched) {
        const left = rowMin[y], right = rowMax[y] + 1;
        points.push({ x: left, y }, { x: right, y }, { x: right, y: y + 1 }, { x: left, y: y + 1 });
        rowMin[y] = width; rowMax[y] = -1;
      }
      const convexHull = hull(points), r = minRectangle(convexHull, budget);
      if (!r) {
        rejectedCandidates.push({ ...component, reason: "geometry_work_budget", evidenceState: "geometry_uncompleted" });
        exhaust("maxGeometryChecks", "geometry_work_budget", { candidateId: id, limit: limits.maxGeometryChecks }); stop = true; break;
      }
      const score = boxMean(data, width, height, r, budget);
      if (!score) {
        rejectedCandidates.push({ ...component, reason: "score_pixel_budget", evidenceState: "box_score_uncompleted" });
        exhaust("maxScorePixels", "score_pixel_budget", { candidateId: id, limit: limits.maxScorePixels }); stop = true; break;
      }
      if (score.mean < boxThreshold) {
        rejectedCandidates.push({ ...component, reason: "box_mean_below_threshold", score: score.mean, scorePixels: score.pixels }); continue;
      }
      const w = r.maxU - r.minU, h = r.maxV - r.minV, perimeter = 2 * (w + h), distance = r.area * unclipRatio / perimeter;
      const sx = sourceWidth / width, sy = sourceHeight / height, scale = q => q.map(p => ({ x: p.x * sx, y: p.y * sy }));
      let mapOriginQuad = rectangleQuad(r), mapCropQuad = rectangleQuad(r, distance),
        originQuad = scale(mapOriginQuad), sourceQuad = scale(mapCropQuad);
      const first = topLeftIndex(sourceQuad);
      mapOriginQuad = rotate(mapOriginQuad, first); mapCropQuad = rotate(mapCropQuad, first);
      originQuad = rotate(originQuad, first); sourceQuad = rotate(sourceQuad, first);
      const unclippedBBox = bounds(sourceQuad), sourceBBox = {
        left: Math.max(0, unclippedBBox.left), top: Math.max(0, unclippedBBox.top),
        right: Math.min(sourceWidth, unclippedBBox.right), bottom: Math.min(sourceHeight, unclippedBBox.bottom) };
      const outsideSource = sourceQuad.some(p => p.x < -EPS || p.y < -EPS || p.x > sourceWidth + EPS || p.y > sourceHeight + EPS);
      const edgeLength = (a, b) => Math.hypot(b.x - a.x, b.y - a.y);
      const candidate = { ...component, frameId, sourceFrameId: frameId, time, sourceSha256,
        sourceWidth, sourceHeight, mapWidth: width, mapHeight: height, mapOriginQuad, mapCropQuad, originQuad,
        sourceQuad, cropQuad: copyPoints(sourceQuad), sourceBBox, unclippedSourceBBox: unclippedBBox,
        region: { left: sourceBBox.left / sourceWidth, top: sourceBBox.top / sourceHeight,
          right: sourceBBox.right / sourceWidth, bottom: sourceBBox.bottom / sourceHeight },
        score: score.mean, scorePixels: score.pixels, minSide: Math.min(w, h),
        sourceMinSide: Math.min(edgeLength(originQuad[0], originQuad[1]), edgeLength(originQuad[1], originQuad[2])),
        angleRadians: Math.atan2(sourceQuad[1].y - sourceQuad[0].y, sourceQuad[1].x - sourceQuad[0].x),
        hullVertices: convexHull.length, outsideSource, clipped: outsideSource,
        clippedPolygon: outsideSource ? clipPolygon(sourceQuad, sourceWidth, sourceHeight) : copyPoints(sourceQuad),
        clippedScope: "diagnostic_polygon_and_bbox_only_source_quad_unchanged", cropQuadClipped: false,
        cropQuadPolicy: "unclipped_affine_parallelogram_white_outside", pointOrder: "tl_tr_br_bl_clockwise",
        coordinateSystem: "continuous_source_pixel_edges_x_right_y_down",
        mappingPolicy: "independent_x_y_map_to_source_scale_no_refit_no_vertex_clamp",
        expansion: { method: "rectangle_area_ratio_over_perimeter_approximation", ratio: unclipRatio, distance,
          area: r.area, perimeter, officialPolygonUnclip: false },
        rangeKind: "connected_component_rectangle_candidate", policy: POLICY, proposalOnly: true,
        textConfirmed: false, singleLineCertified: false, physicalOwnershipCertified: false, subtitleRoleConfirmed: false,
        warnings: outsideSource ? [{ reason: "source_quad_outside_image_sample_with_white_background" }] : [] };
      if (candidates.length >= limits.maxLines) {
        rejectedCandidates.push({ ...candidate, reason: "line_output_budget", evidenceState: "geometry_complete_ocr_unplanned" });
        if (!overflow.maxLines) exhaust("maxLines", "line_output_budget", { limit: limits.maxLines });
      } else candidates.push(candidate);
    }
    diagnostics.geometryChecks = budget.geometryChecks; diagnostics.scorePixels = budget.scorePixels;
    diagnostics.remainingForegroundPixels = foreground - diagnostics.processedForegroundPixels;
    diagnostics.remainingComponentsUnknown = stop && diagnostics.remainingForegroundPixels > 0;
    diagnostics.mapProcessed = !stop;
    diagnostics.acceptedLines = candidates.length; diagnostics.rejectedCandidates = rejectedCandidates.length;
    return output();
  }
  return { POLICY, LIMITS, SCAN_BOUNDARY_POLICY, SCAN_INTEGER_SNAP_TOLERANCE, detect };
});


