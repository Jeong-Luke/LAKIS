const CLASSIFY_URL = "/api/classify-prompt";
const TARGET_IDS = [
  "fixedPromptInput", "generalPromptInput", "qualityPromptInput",
  "artistPromptInput", "triggerPromptInput", "negativePrompt",
  "negativeFixedPromptInput", "negativeQualityPromptInput", "negativeArtistPromptInput"
];

const SECTION_STYLES = {
  quality: ["#facc15", "rgba(202,138,4,.18)"],
  safety: ["#38bdf8", "rgba(2,132,199,.18)"],
  year: ["#2dd4bf", "rgba(13,148,136,.18)"],
  count: ["#60a5fa", "rgba(37,99,235,.18)"],
  character: ["#f472b6", "rgba(219,39,119,.18)"],
  artist: ["#a78bfa", "rgba(124,58,237,.18)"],
  copyright: ["#fb923c", "rgba(234,88,12,.18)"],
  meta: ["#94a3b8", "rgba(100,116,139,.18)"],
  general: ["#4ade80", "rgba(22,163,74,.16)"],
  natural: ["#cbd5e1", "rgba(71,85,105,.16)"],
  translation: ["#22d3ee", "rgba(8,145,178,.22)"],
  wildcard: ["#c084fc", "rgba(126,34,206,.24)"],
  lora: ["#e879f9", "rgba(192,38,211,.22)"],
  comment: ["#9ca3af", "rgba(156,163,175,.14)"],
  syntax: ["#f87171", "transparent"],
  artist_unknown: ["#f87171", "transparent"],
  unknown: ["#cbd5e1", "transparent"]
};

const escapeHtml = value => String(value).replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
})[char]);

function normalized(value) {
  return String(value || "")
    .trim()
    .replace(/^\((.*):[+-]?(?:\d+(?:\.\d*)?|\.\d+)\)$/s, "$1")
    .replace(/^@/, "")
    .replace(/\\(.)/g, "$1")
    .replace(/\s+/g, " ")
    .toLocaleLowerCase();
}

function tokenSpan(text, token) {
  const section = String(token?.section || "unknown");
  const [color, background] = SECTION_STYLES[section] || SECTION_STYLES.unknown;
  const unverified = section === "unknown" || section === "artist_unknown" || section === "syntax";
  const title = token?.label || section;
  return `<span class="prompt-highlight-token${unverified ? " is-unverified" : ""}" title="${escapeHtml(title)}" style="color:${color};background:${background}">${escapeHtml(text)}</span>`;
}

function render(text, tokens) {
  const queues = new Map();
  for (const token of tokens || []) {
    const key = normalized(token.base || token.token);
    if (!key) continue;
    if (!queues.has(key)) queues.set(key, []);
    queues.get(key).push(token);
  }
  const parts = String(text).split(/([,\n])/);
  return parts.map(part => {
    if (part === "," || part === "\n") return escapeHtml(part);
    const match = /^(\s*)([\s\S]*?)(\s*)$/.exec(part);
    const body = match?.[2] || "";
    if (!body) return escapeHtml(part);
    const key = normalized(body);
    const token = queues.get(key)?.shift();
    if (!token) return escapeHtml(part);
    return escapeHtml(match[1]) + tokenSpan(body, token) + escapeHtml(match[3]);
  }).join("") || " ";
}

function copyTextMetrics(textarea, overlay) {
  const style = getComputedStyle(textarea);
  for (const property of [
    "fontFamily", "fontSize", "fontStyle", "fontWeight", "letterSpacing", "lineHeight",
    "paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "textAlign", "tabSize"
  ]) overlay.style[property] = style[property];
}

function install(textarea) {
  if (!textarea || textarea.dataset.promptHighlight === "true") return;
  textarea.dataset.promptHighlight = "true";
  const host = document.createElement("div");
  host.className = "prompt-highlight-host";
  const overlay = document.createElement("pre");
  overlay.className = "prompt-highlight-layer";
  overlay.setAttribute("aria-hidden", "true");
  textarea.parentNode.insertBefore(host, textarea);
  host.append(overlay, textarea);

  let sequence = 0;
  let timer = 0;
  let lastTokens = [];
  const syncScroll = () => {
    overlay.scrollTop = textarea.scrollTop;
    overlay.scrollLeft = textarea.scrollLeft;
  };
  const paint = () => {
    copyTextMetrics(textarea, overlay);
    overlay.innerHTML = render(textarea.value, lastTokens);
    syncScroll();
  };
  const classify = async () => {
    const requestSequence = ++sequence;
    const requestedText = textarea.value;
    paint();
    if (!requestedText.trim()) {
      lastTokens = [];
      paint();
      return;
    }
    try {
      const response = await fetch(CLASSIFY_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: requestedText })
      });
      const result = await response.json();
      if (requestSequence !== sequence || textarea.value !== requestedText) return;
      lastTokens = Array.isArray(result.tokens) ? result.tokens : [];
      paint();
    } catch {
      if (requestSequence === sequence) {
        lastTokens = [];
        paint();
      }
    }
  };
  const schedule = () => {
    clearTimeout(timer);
    paint();
    timer = setTimeout(classify, 180);
  };
  textarea.addEventListener("input", schedule);
  textarea.addEventListener("change", schedule);
  textarea.addEventListener("scroll", syncScroll, { passive: true });
  new ResizeObserver(paint).observe(textarea);
  paint();
  classify();
}

function installAll() {
  for (const id of TARGET_IDS) install(document.getElementById(id));
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", installAll, { once: true });
} else {
  installAll();
}

window.addEventListener("lakis-prompt-state-loaded", () => {
  for (const id of TARGET_IDS) document.getElementById(id)?.dispatchEvent(new Event("change"));
});
