(() => {
  const image = document.querySelector("#imageHistoryLargeImage");
  const link = document.querySelector("#historySaveImage");
  if (!image || !link) return;

  function update(image, link) {
    link.hidden = true;
    link.removeAttribute("href");
    link.removeAttribute("download");
    if (image.hidden || !image.getAttribute("src")) return;
    try {
      const url = new URL(image.getAttribute("src"), window.location.href);
      if (url.origin !== window.location.origin || url.username || url.password) return;
      let name;
      if (url.pathname === "/api/history-image") {
        name = url.searchParams.get("id")?.replace(/^(configured|default):/, "");
      } else if (url.pathname === "/api/comfy-view"
          && (url.searchParams.get("type") || "output") === "output") {
        name = url.searchParams.get("filename");
      }
      if (!name) return;
      name = name.replaceAll("\\", "/").split("/").pop();
      if (!name) return;
      url.searchParams.set("download", "1");
      link.href = url.href;
      link.download = name;
      link.title = "원본 이미지를 기기에 다운로드합니다. 사진 앱 저장은 브라우저 메뉴를 이용해 주세요.";
      link.hidden = false;
    } catch (_) {
      // Empty, transient, and non-media URLs are not downloadable results.
    }
  }

  new MutationObserver(() => update(image, link)).observe(image, {
    attributes: true, attributeFilter: ["src", "hidden"],
  });
  update(image, link);
})();
