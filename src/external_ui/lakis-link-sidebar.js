(() => {
  const sidebar = document.querySelector(".sidebar");
  const toggle = document.querySelector("#mobileSidebarToggle");
  if (!sidebar || !toggle) return;
  const setOpen = open => {
    sidebar.classList.toggle("mobile-menu-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "빠른 메뉴 닫기" : "빠른 메뉴 열기");
  };
  toggle.addEventListener("click", event => { event.stopPropagation(); setOpen(!sidebar.classList.contains("mobile-menu-open")); });
  document.addEventListener("click", event => { if (matchMedia("(max-width:800px)").matches && !sidebar.contains(event.target)) setOpen(false); });
  addEventListener("keydown", event => { if (event.key === "Escape") setOpen(false); });
})();
