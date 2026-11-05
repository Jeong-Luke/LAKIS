(() => {
  "use strict";

  const storageKey = "lakis.prototype.ui-theme.v1";
  const root = document.documentElement;
  root.dataset.synapseTheme = String(localStorage.getItem(storageKey) !== "lakis");

  document.addEventListener("DOMContentLoaded", () => {
    const button = document.querySelector("#uiThemeToggle");
    const label = button.querySelector(".theme-toggle-label");

    function syncThemeButton() {
      const synapse = root.dataset.synapseTheme === "true";
      const current = synapse ? "뉴테마" : "LAKIS 테마";
      const next = synapse ? "LAKIS 테마" : "뉴테마";
      button.setAttribute("aria-label", `현재 ${current} · ${next}로 전환`);
      button.setAttribute("aria-pressed", String(synapse));
      button.title = `${next}로 전환`;
      label.textContent = `${next}로 전환`;
    }

    button.addEventListener("click", () => {
      const synapse = root.dataset.synapseTheme !== "true";
      root.dataset.synapseTheme = String(synapse);
      localStorage.setItem(storageKey, synapse ? "synapse" : "lakis");
      syncThemeButton();
    });

    syncThemeButton();
  });
})();
