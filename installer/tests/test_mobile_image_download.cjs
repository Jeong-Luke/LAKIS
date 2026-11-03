const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../src/external_ui/lakis-link-download.js"), "utf8");
const callbacks = new Map();
const element = () => ({
  hidden: true,
  attributes: {},
  getAttribute(name) { return this.attributes[name] || null; },
  removeAttribute(name) { delete this.attributes[name]; delete this[name]; },
});
const image = element(), link = element(), history = element(), historyLink = element();
const nodes = { "#previewImage": image, "#previewSaveImage": link,
  "#imageHistoryLargeImage": history, "#historySaveImage": historyLink };
const origin = "http://100.64.0.10:8767";
vm.runInNewContext(source, {
  URL,
  window: { location: { href: origin + "/", origin } },
  document: { querySelector: selector => nodes[selector] },
  MutationObserver: class {
    constructor(callback) { this.callback = callback; }
    observe(target) { callbacks.set(target, this.callback); }
  },
});
function display(target, url, hidden = false) {
  target.attributes.src = url; target.hidden = hidden; callbacks.get(target)();
}
assert.equal(link.hidden, true);
display(image, "/api/comfy-view?filename=final.png&subfolder=2026&type=output");
assert.equal(link.hidden, false);
assert.equal(link.download, "final.png");
assert.equal(new URL(link.href).searchParams.get("download"), "1");
assert.equal(new URL(link.href).origin, origin);
assert.equal(new URL(link.href).searchParams.get("subfolder"), "2026");
for (const url of ["blob:temporary", "/api/generation-preview", "/api/thumbnail?id=x",
  "https://foreign.example/api/history-image?id=x.png",
  "/api/comfy-view?filename=input.png&type=input",
  "/api/comfy-view?filename=preview.png&type=temp",
  "/api/comfy-view?type=output", "/api/history-image", ""]) {
  display(image, url);
  assert.equal(link.hidden, true, url);
  assert.equal(link.href, undefined, url);
}
display(history, "/api/history-image?id=" + encodeURIComponent("default:2026/한글 이미지.webp"));
assert.equal(historyLink.hidden, false);
assert.equal(historyLink.download, "한글 이미지.webp");
assert.equal(new URL(historyLink.href).searchParams.get("id"), "default:2026/한글 이미지.webp");
display(image, "/api/history-image?id=old.png", true);
assert.equal(link.hidden, true);
display(history, "/api/history-image?id=new.png");
assert.equal(historyLink.download, "new.png");
console.log("PASS original-image download links, mobile HTTP origin, library selection, preview exclusion and hidden-state updates");
