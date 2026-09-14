(() => {
  if (!window.matchMedia("(max-width: 800px)").matches) return;
  const promptColumn = document.querySelector(".prompt-column");
  const previewColumn = document.querySelector(".preview-column");
  const generationRow = document.querySelector(".generation-action-row");
  if (promptColumn && previewColumn && generationRow) promptColumn.insertBefore(previewColumn, generationRow);
  const version = "1";
  if (localStorage.getItem("lakis-link-layout-version") !== version) {
    Object.keys(localStorage).filter(key => key.startsWith("lakis-link-collapsed:"))
      .forEach(key => localStorage.removeItem(key));
    localStorage.setItem("lakis-link-layout-version", version);
  }
  const labelFor = panel => panel.querySelector(":scope > .panel-heading h2")?.textContent?.trim()
    || panel.querySelector(".prompt-section-heading")?.textContent?.trim()
    || (panel.classList.contains("mode-panel") ? "생성 모드" : "설정");
  document.querySelectorAll(".workspace .panel").forEach((panel, index) => {
    if (panel.closest(".preview-column") || panel.classList.contains("mode-panel") || panel.querySelector("#generateButton")) return;
    let heading = panel.querySelector(":scope > .panel-heading");
    if (!heading) {
      heading = document.createElement("div"); heading.className = "panel-heading mobile-generated-heading";
      const wrap = document.createElement("div"), title = document.createElement("h2");
      title.className = "section-title-accent"; title.textContent = labelFor(panel); wrap.append(title); heading.append(wrap); panel.prepend(heading);
    }
    const button = document.createElement("button"); button.type = "button"; button.className = "mobile-collapse-button";
    const label = labelFor(panel), key = `lakis-link-collapsed:${[...panel.classList].join(".")}:${index}`;
    const apply = collapsed => { panel.classList.toggle("mobile-panel-collapsed", collapsed); button.setAttribute("aria-expanded", String(!collapsed)); button.setAttribute("aria-label", `${label} ${collapsed ? "펼치기" : "접기"}`); };
    apply(localStorage.getItem(key) === "1");
    button.addEventListener("click", event => { event.stopPropagation(); const collapsed = !panel.classList.contains("mobile-panel-collapsed"); apply(collapsed); localStorage.setItem(key, collapsed ? "1" : "0"); });
    heading.append(button);
  });
})();
