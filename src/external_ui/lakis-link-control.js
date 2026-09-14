(() => {
  const overlay = document.querySelector("#lakisLinkOverlay");
  const open = document.querySelector("#lakisLinkButton");
  const close = document.querySelector("#lakisLinkClose");
  const toggle = document.querySelector("#lakisLinkToggle");
  const copy = document.querySelector("#lakisLinkCopy");
  const background = document.querySelector("#lakisLinkBackground");
  const status = document.querySelector("#lakisLinkStatus");
  const url = document.querySelector("#lakisLinkUrl");
  const pin = document.querySelector("#lakisLinkPin");
  let enabled = false;

  async function refresh() {
    const response = await fetch("/api/lakis-link-info", { cache: "no-store" });
    if (!response.ok) throw new Error("status request failed");
    const data = await response.json();
    enabled = data.enabled === true;
    status.textContent = enabled
      ? "LAKIS Link가 준비되었습니다. PC와 휴대폰을 같은 Tailscale 네트워크에 연결해 주세요."
      : "LAKIS Link가 꺼져 있습니다.";
    url.textContent = data.url || "—";
    pin.textContent = data.pin || "—";
    toggle.textContent = enabled ? "Link 끄기" : "Link 시작";
    toggle.classList.toggle("primary", !enabled);
    copy.disabled = !data.url;
  }

  open?.addEventListener("click", async () => {
    overlay.hidden = false;
    try { await refresh(); }
    catch { status.textContent = "LAKIS Link 상태를 확인하지 못했습니다."; }
  });
  close?.addEventListener("click", () => { overlay.hidden = true; });
  overlay?.addEventListener("click", event => { if (event.target === overlay) overlay.hidden = true; });
  toggle?.addEventListener("click", async () => {
    toggle.disabled = true;
    status.textContent = enabled ? "LAKIS Link를 끄는 중…" : "LAKIS Link를 시작하는 중…";
    try {
      const response = await fetch("/api/lakis-link-control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: enabled ? "stop" : "start" })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "control request failed");
      await refresh();
    } catch (error) {
      status.textContent = error.message || "LAKIS Link 상태를 변경하지 못했습니다.";
    } finally { toggle.disabled = false; }
  });
  copy?.addEventListener("click", async () => {
    const value = url.textContent.trim();
    if (!value || value === "—") return;
    try { await navigator.clipboard.writeText(value); status.textContent = "접속 주소를 복사했습니다."; }
    catch { status.textContent = "주소를 복사하지 못했습니다. 주소를 길게 눌러 복사해 주세요."; }
  });
  background?.addEventListener("click", () => {
    if (window.chrome?.webview) window.chrome.webview.postMessage("lakis-background");
    else status.textContent = "데스크톱 앱에서만 백그라운드로 보낼 수 있습니다.";
  });
})();
