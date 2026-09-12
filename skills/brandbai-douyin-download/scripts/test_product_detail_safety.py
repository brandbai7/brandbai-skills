"""Offline regressions for current-work product identity, privacy and image integrity.

The browser extraction expression runs in Node against synthetic DOM elements.
No Chrome, platform request, credential, real comment or personal record is used.
"""

from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import download_creator_works as downloader


SCRIPTS = Path(__file__).resolve().parent
PRODUCT_SCRIPT = SCRIPTS / "collect_product_detail.js"
NODE = os.environ.get("NODE_BINARY") or shutil.which("node")
WORK_ID = "7654321098765432101"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@contextmanager
def workspace_temp():
    # Avoid Python 3.14 Windows temporary-directory ACLs in restricted hosts.
    root = SCRIPTS / ".test-product-detail"
    root.mkdir(exist_ok=True)
    temporary = root / ("case-" + uuid.uuid4().hex)
    temporary.mkdir()
    try:
        yield temporary
    finally:
        shutil.rmtree(temporary)
        try:
            root.rmdir()
        except OSError:
            pass


DOM_HARNESS = r"""
const options = JSON.parse(process.argv[1]);
globalThis.innerWidth = 1400;
globalThis.innerHeight = 900;
globalThis.location = {href: 'https://www.douyin.com/video/7654321098765432101'};
globalThis.window = globalThis;
globalThis.getComputedStyle = node => Object.assign({
  display: 'block', visibility: 'visible', opacity: '1',
  fontSize: '16px', fontWeight: '400', zIndex: '1'
}, node.style || {});

function splitSelectors(value) {
  const result = []; let start = 0; let depth = 0;
  for (let i = 0; i < value.length; i++) {
    if (value[i] === '[' || value[i] === '(') depth++;
    if (value[i] === ']' || value[i] === ')') depth--;
    if (value[i] === ',' && depth === 0) { result.push(value.slice(start, i)); start = i + 1; }
  }
  result.push(value.slice(start));
  return result.map(part => part.trim()).filter(Boolean);
}

function simpleMatch(node, selector) {
  let value = selector.trim();
  const negatives = [...value.matchAll(/:not\(([^()]*)\)/g)].map(match => match[1]);
  if (negatives.some(part => node.matches(part))) return false;
  value = value.replace(/:not\([^()]*\)/g, '').replace(/:scope/g, '').trim();
  const attributes = [...value.matchAll(/\[([^\]]+)\]/g)];
  for (const match of attributes) {
    const expression = match[1].trim();
    const parsed = expression.match(/^([^\s~|^$*=]+)\s*(?:(\*=|\^=|\$=|~=|=)\s*["']?([^"']*?)["']?\s*(i)?)?$/);
    if (!parsed) throw new Error('Synthetic DOM cannot parse attribute selector: ' + expression);
    const actualValue = node.getAttribute(parsed[1]);
    if (actualValue === null) return false;
    if (parsed[2]) {
      let actual = String(actualValue); let expected = (parsed[3] || '').trim();
      if (parsed[4]) { actual = actual.toLowerCase(); expected = expected.toLowerCase(); }
      if (parsed[2] === '=' && actual !== expected) return false;
      if (parsed[2] === '*=' && !actual.includes(expected)) return false;
      if (parsed[2] === '^=' && !actual.startsWith(expected)) return false;
      if (parsed[2] === '$=' && !actual.endsWith(expected)) return false;
      if (parsed[2] === '~=' && !actual.split(/\s+/).includes(expected)) return false;
    }
  }
  value = value.replace(/\[[^\]]+\]/g, '');
  const id = value.match(/#([\w-]+)/);
  if (id && node.id !== id[1]) return false;
  for (const match of value.matchAll(/\.([\w-]+)/g)) {
    if (!node.className.split(/\s+/).includes(match[1])) return false;
  }
  const tag = value.match(/^[a-zA-Z][\w-]*/);
  if (tag && node.tagName.toLowerCase() !== tag[0].toLowerCase()) return false;
  return true;
}

class SyntheticElement {
  constructor(tag, text = '', attrs = {}, rect = {}) {
    this.tagName = tag.toUpperCase(); this.nodeName = this.tagName; this.nodeType = 1;
    this.ownText = text; this.attrs = {...attrs}; this.children = [];
    this.parentElement = null; this.style = {};
    this.rect = Object.assign({width: 160, height: 28, top: 180, left: 600}, rect);
  }
  get id() { return this.attrs.id || ''; }
  get className() { return this.attrs.class || ''; }
  get parentNode() { return this.parentElement; }
  get childNodes() { return this.children; }
  get nextElementSibling() { const siblings = this.parentElement?.children || []; return siblings[siblings.indexOf(this) + 1] || null; }
  get isConnected() { return this === body || Boolean(this.parentElement?.isConnected); }
  get innerText() { return [this.ownText, ...this.children.map(child => child.innerText)].filter(Boolean).join('\n'); }
  get textContent() { return this.innerText; }
  set textContent(value) { this.ownText = String(value); this.children = []; }
  get offsetWidth() { return this.rect.width; }
  get offsetHeight() { return this.rect.height; }
  get offsetParent() { return this.parentElement; }
  get dataset() { return Object.fromEntries(Object.entries(this.attrs).filter(([key]) => key.startsWith('data-')).map(([key, value]) => [key.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase()), value])); }
  getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null; }
  hasAttribute(name) { return this.getAttribute(name) !== null; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getBoundingClientRect() { return Object.assign({}, this.rect, {right: this.rect.left + this.rect.width, bottom: this.rect.top + this.rect.height}); }
  matches(selector) { return splitSelectors(selector).some(part => simpleMatch(this, part)); }
  closest(selector) { for (let node = this; node; node = node.parentElement) if (node.matches(selector)) return node; return null; }
  contains(node) { return node === this || this.children.some(child => child.contains(node)); }
  querySelectorAll(selector) {
    const descendants = [];
    const visit = node => { for (const child of node.children) { descendants.push(child); visit(child); } };
    visit(this);
    return descendants.filter(node => node.matches(selector));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  appendChild(child) { child.parentElement = this; this.children.push(child); return child; }
  remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this); this.parentElement = null; }
  cloneNode(deep) {
    const copy = new SyntheticElement(this.tagName, this.ownText, this.attrs, this.rect);
    Object.assign(copy, {style: {...this.style}, naturalWidth: this.naturalWidth, naturalHeight: this.naturalHeight, src: this.src, currentSrc: this.currentSrc});
    if (deep) for (const child of this.children) copy.appendChild(child.cloneNode(true));
    return copy;
  }
}
globalThis.Element = SyntheticElement;
globalThis.HTMLElement = SyntheticElement;
globalThis.HTMLImageElement = SyntheticElement;
const body = new SyntheticElement('body', '', {}, {width: 1400, height: 900, top: 0, left: 0});
const active = body.appendChild(new SyntheticElement('main', '', {'data-e2e': 'feed-active-video', 'data-aweme-id': '7654321098765432101'}));
const video = active.appendChild(new SyntheticElement('video'));
video.paused = false; video.pause = () => { video.paused = true; };
const trigger = active.appendChild(new SyntheticElement('div', '购物 目标作品的测试商品', {class: 'xgplayer-shop-anchor', 'data-e2e': 'commerce-anchor'}, {top: 400}));
let clicks = 0;

function makePanel(oldProduct) {
  const panel = new SyntheticElement('aside', '', {role: 'dialog', 'data-e2e': 'product-detail', class: 'product-detail-panel'}, {width: 400, height: 600, top: 100, left: 850});
  panel.appendChild(new SyntheticElement('div', '商品详情'));
  const title = panel.appendChild(new SyntheticElement('h1', oldProduct ? '此前其他作品的测试商品完整标题' : '目标作品的测试商品完整标题', {'data-role': 'product-title'}));
  title.style = {fontSize: '24px', fontWeight: '700'};
  panel.appendChild(new SyntheticElement('div', '￥39.90'));
  const sku = panel.appendChild(new SyntheticElement('section', '', {'data-e2e': 'sku-selector', 'data-role': 'sku-group', class: 'sku-specification'}));
  sku.appendChild(new SyntheticElement('span', '选择规格'));
  sku.appendChild(new SyntheticElement('button', '测试规格A', {class: 'sku-item', role: 'radio'}));
  sku.appendChild(new SyntheticElement('button', '测试规格B', {class: 'sku-item', role: 'radio'}));
  const address = panel.appendChild(new SyntheticElement('section', '', {'data-e2e': 'shipping-address', class: 'shipping-address', 'aria-label': '收货地址'}));
  address.appendChild(new SyntheticElement('span', '收货地址'));
  address.appendChild(new SyntheticElement('span', '测试收件人 13800000000'));
  address.appendChild(new SyntheticElement('span', '测试省测试市测试路88号'));
  address.appendChild(new SyntheticElement('span', '48小时发货，送达测试省测试市测试路88号'));
  panel.appendChild(new SyntheticElement('div', '物流'));
  panel.appendChild(new SyntheticElement('div', '付款后48小时内发货', {'data-e2e': 'delivery-service', class: 'logistics-service'}));
  panel.appendChild(new SyntheticElement('div', '商品评价(0)'));
  panel.appendChild(new SyntheticElement('div', '立即购买'));
  const image = panel.appendChild(new SyntheticElement('img', '', {src: 'https://p.example.ecombdimg.com/synthetic.jpg'}));
  Object.assign(image, {src: image.attrs.src, currentSrc: image.attrs.src, naturalWidth: 600, naturalHeight: 600});
  return panel;
}
trigger.click = () => { clicks++; body.appendChild(makePanel(false)); };
if (options.preexistingPanel) body.appendChild(makePanel(true));
globalThis.document = {
  body, documentElement: body,
  querySelectorAll: selector => body.querySelectorAll(selector),
  querySelector: selector => body.querySelector(selector),
  elementFromPoint: () => trigger,
  elementsFromPoint: () => [trigger],
  createElement: tag => new SyntheticElement(tag)
};
"""


@unittest.skipUnless(NODE, "Node.js is required for the synthetic product-panel DOM tests")
class ProductDetailDomSafetyTests(unittest.TestCase):
    def collect(self, *, preexisting_panel=False):
        self.assertTrue(PRODUCT_SCRIPT.is_file(), "The portable product collector JS must be packaged beside the Python runner")
        collector = PRODUCT_SCRIPT.read_text(encoding="utf-8")
        program = DOM_HARNESS + "\nconst collect = (\n" + collector.rstrip().rstrip(";") + "\n);\n" + r"""
Promise.resolve().then(() => collect({expectedAwemeId: '7654321098765432101', timeoutMs: 1000}))
  .then(result => console.log(JSON.stringify({ok: true, clicks, result})))
  .catch(error => console.log(JSON.stringify({ok: false, clicks, error: String(error && error.message || error)})));
"""
        result = subprocess.run(
            [NODE, "-e", program, json.dumps({"preexistingPanel": preexisting_panel})],
            capture_output=True, text=True, encoding="utf-8", timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip(), result.stderr)
        return json.loads(result.stdout.strip())

    def test_rejects_preexisting_unattributed_product_panel(self):
        result = self.collect(preexisting_panel=True)
        self.assertFalse(result["ok"], "An unchanged work URL does not prove a preexisting panel belongs to the work")
        self.assertEqual(result["clicks"], 0, "Reject the stale panel before attempting another product navigation")
        self.assertNotIn("Synthetic DOM", result.get("error", ""))
        self.assertNotRegex(result.get("error", ""), r"(?:not a function|not defined|Cannot read)")

    def test_private_address_does_not_become_sku_or_delivery_data(self):
        result = self.collect()
        self.assertTrue(result["ok"], result.get("error", ""))
        self.assertEqual(result["clicks"], 1)
        self.assertEqual(result["result"]["source_work_id"], WORK_ID)
        product = result["result"]["products"][0]
        public_fields = json.dumps({
            "sku_groups": product.get("sku_groups", []),
            "delivery_texts": product.get("delivery_texts", []),
        }, ensure_ascii=False)
        for private_text in ("13800000000", "测试收件人", "测试省测试市测试路"):
            self.assertNotIn(private_text, public_fields)
        self.assertIn("测试规格A", public_fields, "Public SKU choices should remain usable after private address removal")
        self.assertIn("48小时内发货", public_fields, "The public delivery promise should remain after personalized address removal")


class ProductImageSafetyTests(unittest.TestCase):
    def test_rejects_nonempty_html_response(self):
        with workspace_temp() as temporary:
            with patch.object(downloader.urllib.request, "urlopen", return_value=io.BytesIO(b"<!doctype html><html>synthetic access page</html>")):
                result = downloader.download_product_image(
                    ["https://p.example.ecombdimg.com/synthetic.jpg"],
                    temporary / "product", "https://www.douyin.com/video/" + WORK_ID, 1,
                )
        self.assertEqual(result["status"], "failed", "Nonempty access/error HTML must not be counted as a downloaded product image")

    def test_does_not_trust_existing_nonimage_file(self):
        with workspace_temp() as temporary:
            (temporary / "product.jpg").write_bytes(b"<html>synthetic stale error page</html>")
            with patch.object(downloader.urllib.request, "urlopen", side_effect=OSError("synthetic network unavailable")):
                result = downloader.download_product_image(
                    ["https://p.example.ecombdimg.com/synthetic.jpg"],
                    temporary / "product", "https://www.douyin.com/video/" + WORK_ID, 1,
                )
        self.assertEqual(result["status"], "failed", "A previous corrupt file must not turn a failed retry into skipped_existing success")

    def test_preserves_valid_product_image_and_actual_extension(self):
        with workspace_temp() as temporary:
            with patch.object(downloader.urllib.request, "urlopen", return_value=io.BytesIO(PNG_1X1)):
                result = downloader.download_product_image(
                    ["https://p.example.ecombdimg.com/synthetic.jpg"],
                    temporary / "product", "https://www.douyin.com/video/" + WORK_ID, 1,
                )
            self.assertEqual(result["status"], "downloaded")
            self.assertEqual(Path(result["file"]).suffix, ".png")
            self.assertEqual((temporary / result["file"]).read_bytes(), PNG_1X1)


if __name__ == "__main__":
    unittest.main()
