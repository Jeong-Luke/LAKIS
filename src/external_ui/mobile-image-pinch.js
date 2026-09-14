(() => {
  if (!window.matchMedia('(max-width: 800px)').matches) return;

  const distance = touches => Math.hypot(
    touches[0].clientX - touches[1].clientX,
    touches[0].clientY - touches[1].clientY,
  );
  const center = touches => ({
    x: (touches[0].clientX + touches[1].clientX) / 2,
    y: (touches[0].clientY + touches[1].clientY) / 2,
  });

  const previewStage = document.querySelector('.preview-stage');
  let previewPinch = null;
  previewStage?.addEventListener('touchstart', event => {
    if (event.touches.length !== 2 || typeof window.setPreviewZoom !== 'function') return;
    previewPinch = {
      distance: distance(event.touches),
      zoom: Number.parseInt(document.querySelector('#previewZoomValue')?.textContent || '100', 10) || 100,
    };
    event.preventDefault();
  }, {passive: false});
  previewStage?.addEventListener('touchmove', event => {
    if (!previewPinch || event.touches.length !== 2 || typeof window.setPreviewZoom !== 'function') return;
    const rect = previewStage.getBoundingClientRect();
    const midpoint = center(event.touches);
    window.setPreviewZoom(previewPinch.zoom * distance(event.touches) / previewPinch.distance, {
      x: midpoint.x - rect.left,
      y: midpoint.y - rect.top,
    });
    event.preventDefault();
  }, {passive: false});
  previewStage?.addEventListener('touchend', event => {
    if (event.touches.length < 2) previewPinch = null;
  });
  previewStage?.addEventListener('touchcancel', () => { previewPinch = null; });

  const libraryImage = document.querySelector('#imageHistoryLargeImage');
  let libraryScale = 1, libraryX = 0, libraryY = 0, libraryPinch = null;
  const applyLibraryTransform = () => {
    libraryImage.style.transform = `translate(${libraryX}px, ${libraryY}px) scale(${libraryScale})`;
  };
  const resetLibraryTransform = () => {
    libraryScale = 1; libraryX = 0; libraryY = 0; libraryPinch = null;
    applyLibraryTransform();
  };
  libraryImage?.addEventListener('load', resetLibraryTransform);
  libraryImage?.addEventListener('touchstart', event => {
    if (event.touches.length !== 2) return;
    libraryPinch = {
      distance: distance(event.touches),
      center: center(event.touches),
      scale: libraryScale,
      x: libraryX,
      y: libraryY,
    };
    event.preventDefault();
  }, {passive: false});
  libraryImage?.addEventListener('touchmove', event => {
    if (!libraryPinch || event.touches.length !== 2) return;
    const midpoint = center(event.touches);
    libraryScale = Math.max(1, Math.min(4, libraryPinch.scale * distance(event.touches) / libraryPinch.distance));
    libraryX = libraryPinch.x + midpoint.x - libraryPinch.center.x;
    libraryY = libraryPinch.y + midpoint.y - libraryPinch.center.y;
    if (libraryScale === 1) { libraryX = 0; libraryY = 0; }
    applyLibraryTransform();
    event.preventDefault();
  }, {passive: false});
  libraryImage?.addEventListener('touchend', event => {
    if (event.touches.length < 2) libraryPinch = null;
  });
  libraryImage?.addEventListener('touchcancel', () => { libraryPinch = null; });
})();
