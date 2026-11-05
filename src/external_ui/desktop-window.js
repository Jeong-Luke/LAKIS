(() => {
  const host = window.chrome?.webview;
  const controls = document.querySelector("#desktopWindowControls");
  const header = document.querySelector(".brand-header");
  if (!host || !controls || !header) return;
  document.documentElement.dataset.desktopWindow = "true";
  controls.hidden = false;
  controls.addEventListener("click", event => {
    const button = event.target.closest("button[data-window-action]");
    if (button) host.postMessage("lakis-window-" + button.dataset.windowAction);
  });
  header.addEventListener("mousedown", event => {
    if (event.button !== 0 || event.target.closest("button, a, input, select, textarea")) return;
    event.preventDefault();
    host.postMessage(event.detail === 2 ? "lakis-window-maximize" : "lakis-window-drag");
  });
  host.addEventListener("message", event => {
    if (event.data?.type !== "lakis-window-state") return;
    const maximized = event.data.maximized === true;
    controls.dataset.maximized = String(maximized);
    const button = document.querySelector("#desktopWindowMaximize");
    button.title = maximized ? "이전 크기로" : "최대화";
    button.setAttribute("aria-label", button.title);
  });
  host.postMessage("lakis-window-ready");
})();
