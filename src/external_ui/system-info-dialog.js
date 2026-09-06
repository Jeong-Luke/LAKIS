(() => {
  const dialog = document.getElementById("systemInfoDialog");
  const open = document.getElementById("systemInfoButton");
  const close = document.getElementById("systemInfoClose");
  const error = document.getElementById("systemInfoLegalError");
  if (!dialog || !open || !close) return;

  open.addEventListener("click", () => {
    document.getElementById("systemInfoVersion").textContent = document.getElementById("workflowVersion").textContent;
    document.getElementById("systemInfoComfy").textContent = document.getElementById("comfyStatusText").textContent;
    document.getElementById("systemInfoVram").textContent = document.getElementById("vramText").textContent;
    document.getElementById("systemInfoRam").textContent = document.getElementById("ramText").textContent;
    document.getElementById("systemInfoCpu").textContent = document.getElementById("cpuText").textContent;
    error.hidden = true;
    dialog.hidden = false;
  });
  close.addEventListener("click", () => { dialog.hidden = true; });
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.hidden = true; });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !dialog.hidden) dialog.hidden = true; });

  dialog.querySelectorAll("[data-legal-document]").forEach((button) => {
    button.addEventListener("click", async () => {
      error.hidden = true;
      try {
        const response = await fetch("/api/open-legal-document", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ document: button.dataset.legalDocument }),
        });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || "문서를 열지 못했습니다.");
      } catch (failure) {
        error.textContent = failure.message || "문서를 열지 못했습니다.";
        error.hidden = false;
      }
    });
  });
})();
