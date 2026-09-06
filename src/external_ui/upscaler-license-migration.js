(() => {
  const modal = document.getElementById("upscalerMigration");
  const confirm = document.getElementById("upscalerMigrationConfirm");
  const acknowledgement = document.getElementById("animeSharpAcknowledgement");
  const ack = document.getElementById("animeSharpAck");
  const error = document.getElementById("upscalerMigrationError");
  const choices = [...document.querySelectorAll('input[name="upscalerChoice"]')];
  if (!modal || !confirm || !ack || choices.length !== 2) return;

  const selected = () => choices.find((item) => item.checked)?.value || "realesrgan";
  const refresh = () => {
    const animeSharp = selected() === "animesharp";
    acknowledgement.hidden = !animeSharp;
    choices.forEach((item) => item.closest(".upscaler-choice")?.classList.toggle("selected", item.checked));
    confirm.disabled = animeSharp && !ack.checked;
  };
  choices.forEach((item) => item.addEventListener("change", refresh));
  ack.addEventListener("change", refresh);

  confirm.addEventListener("click", async () => {
    const originalLabel = confirm.textContent;
    confirm.disabled = true;
    confirm.textContent = selected() === "realesrgan" ? "다운로드 및 적용 중…" : "선택 적용 중…";
    error.hidden = true;
    try {
      const response = await fetch("/api/upscaler-license-choice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ choice: selected(), acknowledged: ack.checked }),
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || "선택을 저장하지 못했습니다.");
      modal.hidden = true;
    } catch (failure) {
      error.textContent = failure.message || "선택을 저장하지 못했습니다.";
      error.hidden = false;
      refresh();
    } finally {
      confirm.textContent = originalLabel;
    }
  });

  window.addEventListener("DOMContentLoaded", async () => {
    try {
      const response = await fetch("/api/upscaler-license-choice", { cache: "no-store" });
      const result = await response.json();
      if (response.ok && result.required) {
        modal.hidden = false;
        refresh();
      }
    } catch (_) {
      // A failed bridge request must not block LAKIS startup.
    }
  });
})();
