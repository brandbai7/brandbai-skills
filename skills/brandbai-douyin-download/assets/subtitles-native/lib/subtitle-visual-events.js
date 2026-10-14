/* Local pixel evidence for outlined caption rows. Abstain on ambiguous geometry.
 * This module never reads text, translates characters, or observes scene images. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.BrandbaiSubtitleVisualEvents = api;
})(globalThis, function () {
  "use strict";
  const SCHEMA = "outlined-caption-pixels-v1";
  const median = values => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)] || 0;
  function analyze(image) {
    if (!image || !Number.isSafeInteger(image.width) || !Number.isSafeInteger(image.height) || image.width < 32 || image.height < 12
      || image.width > 2560 || image.height > 512 || image.data?.length !== image.width * image.height * 4) return null;
    const factor = Math.min(1, 40 / image.height), w = Math.round(image.width * factor), h = Math.round(image.height * factor);
    const pixels = new Uint8ClampedArray(w * h * 4);
    // Geometry is estimated at a fixed physical glyph scale. This is only a
    // mask; recognition still receives the unchanged source ROI pixels.
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const l = Math.floor(x * image.width / w), r = Math.max(l + 1, Math.floor((x + 1) * image.width / w));
      const t = Math.floor(y * image.height / h), b = Math.max(t + 1, Math.floor((y + 1) * image.height / h));
      for (let c = 0; c < 3; c++) {
        let sum = 0; for (let yy = t; yy < b; yy++) for (let xx = l; xx < r; xx++) sum += image.data[(yy * image.width + xx) * 4 + c];
        pixels[(y * w + x) * 4 + c] = sum / ((r - l) * (b - t));
      }
      pixels[(y * w + x) * 4 + 3] = 255;
    }
    const value = analyzeMask({ width: w, height: h, data: pixels });
    if (!value) return null;
    return { ...value, inputWidth: image.width, inputHeight: image.height,
      box: { left: Math.floor(value.box.left * image.width / w), right: Math.ceil(value.box.right * image.width / w), top: 0, bottom: image.height } };
  }
  function analyzeMask(image) {
    const { width: w, height: h, data } = image || {};
    if (!Number.isSafeInteger(w) || !Number.isSafeInteger(h) || w < 32 || h < 12 || w > 2560 || h > 512 || data?.length !== w * h * 4) return null;
    const n = w * h, light = new Uint8Array(n), dark = new Uint8Array(n), mask = new Uint8Array(n);
    for (let i = 0; i < n; i++) {
      const p = i * 4, r = data[p], g = data[p + 1], b = data[p + 2];
      light[i] = Math.min(r, g, b) >= 180 && Math.max(r, g, b) >= 215 ? 1 : 0;
      dark[i] = Math.max(r, g, b) <= 95 ? 1 : 0;
    }
    const radius = Math.max(2, Math.min(6, Math.round(h * .075)));
    for (let y = radius; y < h - radius; y++) for (let x = radius; x < w - radius; x++) {
      const i = y * w + x;
      if (!light[i]) continue;
      for (let d = 1; d <= radius; d++) if (dark[i - d] || dark[i + d] || dark[i - d * w] || dark[i + d * w]) { mask[i] = 1; break; }
    }
    const seen = new Uint8Array(n), queue = new Int32Array(n), components = [], allComponents = [];
    for (let i = 0; i < n; i++) {
      if (!mask[i] || seen[i]) continue;
      let head = 0, count = 1, left = w, right = 0, top = h, bottom = 0;
      queue[0] = i; seen[i] = 1;
      while (head < count) {
        const p = queue[head++], y = Math.floor(p / w), x = p % w;
        left = Math.min(left, x); right = Math.max(right, x + 1); top = Math.min(top, y); bottom = Math.max(bottom, y + 1);
        for (let yy = Math.max(0, y - 1); yy < Math.min(h, y + 2); yy++) for (let xx = Math.max(0, x - 1); xx < Math.min(w, x + 2); xx++) {
          const next = yy * w + xx; if (mask[next] && !seen[next]) { seen[next] = 1; queue[count++] = next; }
        }
      }
      const height = bottom - top, width = right - left;
      if (count >= 3 && height <= h * .94 && width <= h * 1.6) allComponents.push({ left, right, top, bottom, height, pixels: count });
      if (height >= h * .25 && height <= h * .94 && width >= 2 && width <= h * 1.6 && count >= h * .35)
        components.push({ left, right, top, bottom, height, pixels: count });
    }
    const rows = [];
    for (const c of components.sort((a, b) => a.top - b.top)) {
      const center = (c.top + c.bottom) / 2;
      let row = rows.find(r => Math.abs(r.center - center) <= h * .15 && c.height / r.height > .45 && c.height / r.height < 2.2);
      if (!row) { row = { center, height: c.height, members: [] }; rows.push(row); }
      row.members.push(c); row.center = median(row.members.map(m => (m.top + m.bottom) / 2)); row.height = median(row.members.map(m => m.height));
    }
    const groups = [];
    for (const row of rows) {
      let group = [];
      const finish = () => {
        if (group.length < 4) return;
        const left = Math.min(...group.map(c => c.left)), right = Math.max(...group.map(c => c.right));
        const top = Math.min(...group.map(c => c.top)), bottom = Math.max(...group.map(c => c.bottom));
        if (right - left < (bottom - top) * 3 || right - left < w * .18) return;
        groups.push({ left, right, top, bottom, members: group.length, pixels: group.reduce((s, c) => s + c.pixels, 0) });
      };
      for (const c of row.members.sort((a, b) => a.left - b.left)) {
        if (group.length && c.left - Math.max(...group.map(m => m.right)) > row.height * 1.7) { finish(); group = []; }
        group.push(c);
      }
      finish();
    }
    groups.sort((a, b) => b.pixels - a.pixels);
    const main = groups[0];
    if (!main || groups[1]?.pixels > main.pixels * .65) return null;
    // Disconnected strokes (e.g. a short horizontal stroke of the first glyph)
    // are not whole-character components. Extend through nearby strokes in the
    // SAME established text band instead of mistaking them for absent letters.
    const glyphHeight = main.bottom - main.top;
    for (let pass = 0; pass < 32; pass++) {
      const left = main.left, right = main.right;
      for (const c of allComponents) if (c.top >= main.top - 2 && c.bottom <= main.bottom + 2
        && c.right >= main.left - glyphHeight * .7 && c.left <= main.right + glyphHeight * .7) {
        main.left = Math.min(main.left, c.left); main.right = Math.max(main.right, c.right);
      }
      if (left === main.left && right === main.right) break;
    }
    // An entire glyph of padding retains disconnected first/last glyph strokes.
    // A proposed box is not permission to shorten recognized text.
    const pad = Math.max(3, Math.ceil(main.bottom - main.top));
    const box = { left: Math.max(0, main.left - pad), right: Math.min(w, main.right + pad), top: 0, bottom: h };
    // Native selected-ROI pixels are retained. Only horizontal empty/background
    // margins are removed, never a second resize or a tighter vertical crop.
    const bits = [];
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) bits.push(x >= box.left && x < box.right && y >= main.top && y < main.bottom ? mask[y * w + x] : 0);
    return { schema: SCHEMA, inputWidth: w, inputHeight: h, box, ink: { left: main.left, right: main.right, top: main.top, bottom: main.bottom },
      members: main.members, pixels: main.pixels, maskWidth: w, maskHeight: h, maskEncoding: "hex4",
      mask: bits.join("").match(/.{1,4}/g).map(chunk=>parseInt(chunk.padEnd(4,'0'),2).toString(16)).join("") };
  }
  function crop(canvas, evidence) {
    if (!evidence || evidence.inputWidth !== canvas.width || evidence.inputHeight !== canvas.height) return canvas;
    const box = evidence.box, output = canvas.ownerDocument?.createElement("canvas") || globalThis.document.createElement("canvas");
    output.width = box.right - box.left; output.height = canvas.height;
    output.getContext("2d").drawImage(canvas, box.left, 0, output.width, output.height, 0, 0, output.width, output.height);
    return output;
  }
  function valid(e) {
    return e?.schema === SCHEMA && Number.isSafeInteger(e.maskWidth) && e.maskWidth >= 16 && e.maskWidth <= 2560
      && Number.isSafeInteger(e.maskHeight) && e.maskHeight >= 12 && e.maskHeight <= 40
      && Number.isSafeInteger(e.inputWidth) && e.inputWidth >= 32 && e.inputWidth <= 2560
      && Number.isSafeInteger(e.inputHeight) && e.inputHeight >= 12 && e.inputHeight <= 512
      && typeof e.mask === 'string' && (e.maskEncoding === 'hex4' ? e.mask.length === Math.ceil(e.maskWidth * e.maskHeight / 4) && /^[0-9a-f]+$/.test(e.mask)
        : !e.maskEncoding && e.mask.length === e.maskWidth * e.maskHeight && /^[01]+$/.test(e.mask))
      && e.ink && ['left','right','top','bottom'].every(k => Number.isSafeInteger(e.ink[k]))
      && e.ink.left >= 0 && e.ink.right <= e.maskWidth && e.ink.right > e.ink.left
      && e.ink.top >= 0 && e.ink.bottom <= e.maskHeight && e.ink.bottom > e.ink.top
      && e.box && ['left','right','top','bottom'].every(k => Number.isSafeInteger(e.box[k]))
      && e.box.left >= 0 && e.box.right <= e.inputWidth && e.box.right > e.box.left && e.box.top === 0 && e.box.bottom === e.inputHeight;
  }
  const decoded = new WeakMap();
  function bits(e) {
    let data=decoded.get(e); if(data) return data;
    data=new Uint8Array(e.maskWidth*e.maskHeight);
    for(let i=0;i<data.length;i++) data[i]=e.maskEncoding==='hex4' ? (parseInt(e.mask[Math.floor(i/4)],16)>>(3-i%4))&1 : Number(e.mask[i]);
    decoded.set(e,data);return data;
  }
  function same(a, b) {
    if (!valid(a) || !valid(b) || a.maskWidth !== b.maskWidth || a.maskHeight !== b.maskHeight
      || a.inputWidth !== b.inputWidth || a.inputHeight !== b.inputHeight
      || Math.abs(a.ink.top - b.ink.top) > 2 || Math.abs(a.ink.bottom - b.ink.bottom) > 2) return false;
    let union = 0, different = 0;
    const aa=bits(a),bb=bits(b);
    for (let i = 0; i < aa.length; i++) { if (aa[i] || bb[i]) union++; if (aa[i] !== bb[i]) different++; }
    // This is corroborating evidence, NEVER a text-equivalence rule on its own.
    return union >= 100 && different / union <= .085;
  }
  function sameGlyph(a, b, position, length) {
    if (!same(a,b) || !Number.isInteger(position) || !Number.isInteger(length) || position < 0 || position >= length) return false;
    const left = Math.max(a.ink.left,b.ink.left), right = Math.min(a.ink.right,b.ink.right);
    const l = Math.floor(left + (right-left)*position/length), r = Math.ceil(left + (right-left)*(position+1)/length);
    let union=0, diff=0;
    const aa=bits(a),bb=bits(b);
    for (let y=0;y<a.maskHeight;y++) for(let x=l;x<r;x++){const i=y*a.maskWidth+x;if(aa[i]||bb[i])union++;if(aa[i]!==bb[i])diff++;}
    // A dot/bar can distinguish a real Han glyph (大/太, 已/己, 牛/午).
    // Whole-line similarity cannot suppress that small but meaningful change.
    // This tight local bound intentionally leaves ambiguous compressed pixels
    // unmerged; recovering fewer events is safer than deleting a true caption.
    return union >= 20 && diff / union <= .02;
  }
  return { SCHEMA, analyze, crop, valid, same, sameGlyph };
});
