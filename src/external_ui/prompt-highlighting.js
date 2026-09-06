const CLASSIFY_URL = "/api/classify-prompt";
const TARGET_IDS = [
  "fixedPromptInput", "generalPromptInput", "qualityPromptInput",
  "artistPromptInput", "triggerPromptInput", "negativePrompt",
  "negativeFixedPromptInput", "negativeQualityPromptInput", "negativeArtistPromptInput"
];
const COMMON_TAGS = [
  ["girl", "소녀"], ["1girl", "한 명의 소녀"], ["boy", "소년"], ["1boy", "한 명의 소년"],
  ["solo", "단독"], ["looking_at_viewer", "정면 응시"], ["smile", "미소"], ["long_hair", "긴 머리"],
  ["short_hair", "짧은 머리"], ["blue_eyes", "파란 눈"], ["full_body", "전신"], ["upper_body", "상반신"],
  ["close-up", "클로즈업"], ["from_above", "위에서"], ["from_below", "아래에서"], ["standing", "서 있는 자세"],
  ["sitting", "앉은 자세"], ["dynamic_pose", "역동적인 자세"], ["detailed_background", "상세한 배경"],
  ["masterpiece", "최고 품질"], ["best_quality", "최상 품질"], ["blurry", "흐림"], ["bad_hands", "잘못된 손"]
].map(([tag, ko]) => ({ tag, ko, category: "common" }));

const SECTION_STYLES = {
  quality: ["#fb7a2a", "rgba(234,88,12,.20)"],
  safety: ["#38bdf8", "rgba(2,132,199,.18)"],
  year: ["#2dd4bf", "rgba(13,148,136,.18)"],
  count: ["#60a5fa", "rgba(37,99,235,.18)"],
  character: ["#f472b6", "rgba(219,39,119,.18)"],
  artist: ["#a78bfa", "rgba(124,58,237,.18)"],
  copyright: ["#fb923c", "rgba(234,88,12,.18)"],
  meta: ["#94a3b8", "rgba(100,116,139,.18)"],
  general: ["#4ade80", "rgba(22,163,74,.16)"],
  natural: ["#cbd5e1", "rgba(71,85,105,.16)"],
  korean: ["#fbbf24", "rgba(245,158,11,.22)"],
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

function containsKorean(text) {
  return /[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]/u.test(String(text || ""));
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
    if (containsKorean(body)) {
      return escapeHtml(match[1]) + tokenSpan(body, {
        section: "korean",
        label: "자동 번역 대상"
      }) + escapeHtml(match[3]);
    }
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
  textarea.spellcheck = false;
  textarea.setAttribute("spellcheck", "false");
  const host = document.createElement("div");
  host.className = "prompt-highlight-host";
  const overlay = document.createElement("pre");
  overlay.className = "prompt-highlight-layer";
  overlay.setAttribute("aria-hidden", "true");
  textarea.parentNode.insertBefore(host, textarea);
  host.append(overlay, textarea);
  const suggestions = document.createElement("div");
  suggestions.className = "prompt-autocomplete";
  suggestions.hidden = true;
  host.append(suggestions);
  const resizeHandle = document.createElement("div");
  resizeHandle.className = "prompt-resize-handle";
  resizeHandle.setAttribute("aria-hidden", "true");
  host.append(resizeHandle);

  let sequence = 0;
  let timer = 0;
  let lastTokens = [];
  let suggestionTimer = 0;
  let suggestionSequence = 0;
  let activeSuggestion = 0;
  let currentRange = null;
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
    scheduleSuggestions();
  };
  const refreshWithoutSuggestions = () => {
    clearTimeout(timer);
    clearTimeout(suggestionTimer);
    suggestionSequence += 1;
    closeSuggestions();
    paint();
    timer = setTimeout(classify, 180);
  };
  const currentFragment = () => {
    const end = textarea.selectionStart ?? textarea.value.length;
    const start = Math.max(textarea.value.lastIndexOf(",", end - 1), textarea.value.lastIndexOf("\n", end - 1)) + 1;
    return { start, end, query: textarea.value.slice(start, end).trim().replace(/_/g, " ").toLowerCase() };
  };
  const closeSuggestions = () => { suggestions.hidden = true; suggestions.replaceChildren(); currentRange = null; };
  const caretPosition = () => {
    const style = getComputedStyle(textarea);
    const mirror = document.createElement("div");
    mirror.style.position = "fixed";
    mirror.style.left = "-10000px";
    mirror.style.top = "0";
    mirror.style.visibility = "hidden";
    mirror.style.whiteSpace = "pre-wrap";
    mirror.style.overflowWrap = "break-word";
    mirror.style.boxSizing = style.boxSizing;
    mirror.style.width = `${textarea.clientWidth}px`;
    for (const property of [
      "fontFamily", "fontSize", "fontStyle", "fontWeight", "letterSpacing", "lineHeight",
      "paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "textAlign", "tabSize",
      "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth"
    ]) mirror.style[property] = style[property];
    mirror.textContent = textarea.value.slice(0, textarea.selectionStart ?? textarea.value.length);
    const marker = document.createElement("span");
    marker.textContent = textarea.value.slice(textarea.selectionStart ?? textarea.value.length, (textarea.selectionStart ?? textarea.value.length) + 1) || "\u200b";
    mirror.append(marker);
    document.body.append(mirror);
    const position = {
      x: marker.offsetLeft - textarea.scrollLeft,
      y: marker.offsetTop - textarea.scrollTop,
      lineHeight: Number.parseFloat(style.lineHeight) || Number.parseFloat(style.fontSize) * 1.35,
    };
    mirror.remove();
    return position;
  };
  const positionSuggestions = () => {
    const caret = caretPosition();
    const popupWidth = Math.min(270, Math.max(160, textarea.clientWidth - 14));
    const rightSide = caret.x + 10;
    const left = rightSide + popupWidth <= textarea.clientWidth - 7
      ? rightSide
      : Math.max(7, caret.x - popupWidth - 8);
    suggestions.style.left = `${left}px`;
    suggestions.style.top = `${Math.max(7, caret.y + caret.lineHeight + 4)}px`;
  };
  const chooseSuggestion = item => {
    if (!currentRange) return;
    const before = textarea.value.slice(0, currentRange.start);
    const after = textarea.value.slice(currentRange.end);
    const prefix = before && !/[\s\n]$/.test(before) ? " " : "";
    textarea.value = before + prefix + item.tag.replace(/_/g, " ") + after;
    const caret = (before + prefix + item.tag.replace(/_/g, " ")).length;
    textarea.setSelectionRange(caret, caret);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    closeSuggestions(); textarea.focus();
  };
  const renderSuggestions = items => {
    suggestions.replaceChildren(...items.map((item, index) => {
      const button = document.createElement("button");
      button.type = "button"; button.className = index === activeSuggestion ? "active" : "";
      button.innerHTML = `<strong>${escapeHtml(item.tag.replace(/_/g, " "))}</strong><span>${escapeHtml(item.ko || item.description || item.category || "태그")}</span>`;
      button.addEventListener("mousedown", event => { event.preventDefault(); chooseSuggestion(item); });
      return button;
    }));
    suggestions.hidden = items.length === 0;
    if (items.length) positionSuggestions();
  };
  const scheduleSuggestions = () => {
    clearTimeout(suggestionTimer);
    const fragment = currentFragment();
    if (fragment.query.length < 2 || containsKorean(fragment.query)) { closeSuggestions(); return; }
    currentRange = fragment;
    suggestionTimer = setTimeout(async () => {
      const requestSequence = ++suggestionSequence;
      const local = COMMON_TAGS.filter(item => item.tag.replace(/_/g, " ").startsWith(fragment.query));
      let remote = [];
      try {
        const response = await fetch(`/api/tag-suggestions?q=${encodeURIComponent(fragment.query)}`, { cache: "no-store" });
        const result = await response.json();
        remote = Array.isArray(result.suggestions) ? result.suggestions : [];
      } catch {}
      if (requestSequence !== suggestionSequence || currentFragment().query !== fragment.query) return;
      const merged = [...local, ...remote].filter((item, index, all) => item?.tag && all.findIndex(other => other?.tag === item.tag) === index).slice(0, 3);
      activeSuggestion = 0; renderSuggestions(merged);
    }, 120);
  };
  textarea.addEventListener("keydown", event => {
    if (suggestions.hidden) return;
    const items = [...suggestions.querySelectorAll("button")];
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault(); activeSuggestion = (activeSuggestion + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      items.forEach((item, index) => item.classList.toggle("active", index === activeSuggestion));
    } else if (event.key === "Tab" || event.key === "Enter") {
      event.preventDefault(); items[activeSuggestion]?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    } else if (event.key === "Escape") closeSuggestions();
  });
  textarea.addEventListener("blur", () => setTimeout(closeSuggestions, 120));
  textarea.addEventListener("input", schedule);
  textarea.addEventListener("change", refreshWithoutSuggestions);
  textarea.addEventListener("scroll", syncScroll, { passive: true });
  let resizeStartY = 0;
  let resizeStartHeight = 0;
  let resizeMaxHeight = 0;
  let resizePanel = null;
  let resizePanelChrome = 0;
  resizeHandle.addEventListener("pointerdown", event => {
    event.preventDefault();
    const categoryPanel = host.closest(".fixed-prompt-panel");
    const promptField = host.closest(".prompt-field-title");
    const hostRect = host.getBoundingClientRect();
    const categoryRect = categoryPanel?.getBoundingClientRect();
    const fieldRect = promptField?.getBoundingClientRect();
    const bottomPadding = Number.parseFloat(getComputedStyle(categoryPanel).paddingBottom) || 12;
    resizeStartY = event.clientY;
    resizeStartHeight = hostRect.height;
    resizePanel = categoryPanel;
    resizePanelChrome = Math.max(0, (hostRect.top - (categoryRect?.top ?? hostRect.top)) + bottomPadding);
    resizeMaxHeight = Math.max(80, Math.floor((fieldRect?.bottom ?? hostRect.bottom) - hostRect.top - bottomPadding));
    resizeHandle.setPointerCapture?.(event.pointerId);
    document.body.classList.add("prompt-resizing");
  });
  resizeHandle.addEventListener("pointermove", event => {
    if (!resizeHandle.hasPointerCapture?.(event.pointerId)) return;
    const height = Math.max(80, Math.min(resizeMaxHeight, Math.round(resizeStartHeight + event.clientY - resizeStartY)));
    host.style.flex = "0 0 auto";
    host.style.height = `${height}px`;
    if (resizePanel) {
      resizePanel.style.flex = "0 0 auto";
      resizePanel.style.height = `${Math.round(height + resizePanelChrome)}px`;
    }
    paint();
  });
  const finishResize = event => {
    if (resizeHandle.hasPointerCapture?.(event.pointerId)) resizeHandle.releasePointerCapture(event.pointerId);
    document.body.classList.remove("prompt-resizing");
    resizePanel = null;
    paint();
  };
  resizeHandle.addEventListener("pointerup", finishResize);
  resizeHandle.addEventListener("pointercancel", finishResize);
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

document.addEventListener("keydown", event => {
  if (event.key !== "PageUp" && event.key !== "PageDown") return;
  requestAnimationFrame(() => {
    window.scrollTo(0, window.scrollY);
    document.documentElement.scrollLeft = 0;
    document.body.scrollLeft = 0;
    for (const element of document.querySelectorAll(".workspace, .model-column, .control-column, .prompt-column, .prompt-panel")) {
      element.scrollLeft = 0;
    }
    if (event.target instanceof HTMLTextAreaElement) event.target.scrollLeft = 0;
  });
});
