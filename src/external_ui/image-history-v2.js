(() => {
  const overlay = document.querySelector('#imageHistoryOverlay');
  const groups = document.querySelector('#imageHistoryGroups');
  const inspector = document.querySelector('#imageHistoryInspector');
  const deleteButton = document.querySelector('#imageHistoryDelete');
  const selectModeButton = document.querySelector('#imageHistorySelectMode');
  const selectionBar = document.querySelector('#imageHistorySelectionBar');
  const selectedCount = document.querySelector('#imageHistorySelectedCount');
  const batchDeleteButton = document.querySelector('#imageHistoryBatchDelete');
  const selectionCancel = document.querySelector('#imageHistorySelectionCancel');
  if (!overlay || !groups || !inspector || !deleteButton || !selectModeButton || !selectionBar || !selectedCount || !batchDeleteButton || !selectionCancel) return;
  let items = [], selected = null, selectionMode = false, batchDeleting = false;
  const selectedItems = new Set();
  const LIBRARY_RENDER_BATCH_SIZE = 20;
  let renderedCount = 0;
  const renderedDateGrids = new Map();
  const loadMoreSentinel = document.createElement('div');
  loadMoreSentinel.className = 'image-history-load-more-sentinel';
  loadMoreSentinel.setAttribute('aria-hidden', 'true');
  Object.assign(loadMoreSentinel.style, {height:'1px', width:'100%', pointerEvents:'none'});
  groups.after(loadMoreSentinel);
  let loadMoreObserver = null;
  const viewportLazyLoadEnabled = localStorage.getItem('lakis.libraryViewportLazyLoad') !== '0';
  const VIEWPORT_PRELOAD_MARGIN = '150% 0px';
  let imageObserver = null;
  const lazyStats = { domImages: 0, assignedSources: 0, loadedImages: 0 };
  const apiUrl = path => `${window.location.origin}${path.startsWith('/') ? path : `/${path}`}`;
  const notice = message => { const el = document.querySelector('#imageHistoryNotice'); el.textContent = message || ''; el.hidden = !message; };
  const publishLazyStats = () => {
    overlay.dataset.lazyDomImages = String(lazyStats.domImages);
    overlay.dataset.lazyAssignedSources = String(lazyStats.assignedSources);
    overlay.dataset.lazyLoadedImages = String(lazyStats.loadedImages);
  };
  const assignImageSource = image => {
    const source = image.dataset.src;
    if (!source || image.src) return;
    image.src = source;
    delete image.dataset.src;
    lazyStats.assignedSources += 1;
    publishLazyStats();
  };
  const resetImageObserver = () => {
    imageObserver?.disconnect();
    imageObserver = null;
    lazyStats.domImages = 0;
    lazyStats.assignedSources = 0;
    lazyStats.loadedImages = 0;
    publishLazyStats();
  };
  const observeImage = image => {
    lazyStats.domImages += 1;
    image.loading = 'lazy';
    image.decoding = 'async';
    image.addEventListener('load', () => {
      lazyStats.loadedImages += 1;
      publishLazyStats();
    }, {once: true});
    if (!viewportLazyLoadEnabled || !('IntersectionObserver' in window)) {
      assignImageSource(image);
      return;
    }
    if (!imageObserver) {
      imageObserver = new IntersectionObserver(entries => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          assignImageSource(entry.target);
          imageObserver?.unobserve(entry.target);
        }
      }, {root: null, rootMargin: VIEWPORT_PRELOAD_MARGIN, threshold: 0.01});
    }
    imageObserver.observe(image);
    publishLazyStats();
  };
  const stopLoadMoreObserver = () => {
    loadMoreObserver?.disconnect();
    loadMoreObserver = null;
  };
  const observeLoadMoreSentinel = () => {
    if (renderedCount >= items.length) {
      loadMoreSentinel.hidden = true;
      stopLoadMoreObserver();
      return;
    }
    loadMoreSentinel.hidden = false;
    if (!('IntersectionObserver' in window)) return;
    if (!loadMoreObserver) {
      loadMoreObserver = new IntersectionObserver(entries => {
        if (entries.some(entry => entry.isIntersecting)) renderNextBatch();
      }, {root:null, rootMargin:'600px 0px', threshold:0});
    }
    loadMoreObserver.observe(loadMoreSentinel);
  };
  const clearDetail = () => { selected = null; deleteButton.disabled = true; inspector.hidden = true; document.querySelectorAll('.image-history-card.selected').forEach(el => el.classList.remove('selected')); };
  const syncSelectionUi = () => {
    selectionBar.hidden = !selectionMode;
    selectModeButton.hidden = selectionMode;
    deleteButton.hidden = selectionMode;
    selectedCount.textContent = `${selectedItems.size}개 선택됨`;
    batchDeleteButton.disabled = selectedItems.size === 0 || batchDeleting;
    batchDeleteButton.textContent = batchDeleting ? '삭제 중…' : '선택 삭제';
  };
  const exitSelectionMode = () => { selectionMode = false; batchDeleting = false; selectedItems.clear(); syncSelectionUi(); render(); };
  const clear = () => { clearDetail(); selectionMode = false; batchDeleting = false; selectedItems.clear(); syncSelectionUi(); };
  const show = (item, card) => {
    selected = item; deleteButton.disabled = false;
    document.querySelectorAll('.image-history-card.selected').forEach(el => el.classList.remove('selected')); card.classList.add('selected');
    document.querySelector('#imageHistoryLargeImage').src = apiUrl(item.url);
    document.querySelector('#historyCheckpoint').textContent = item.checkpoint || '확인할 수 없음';
    document.querySelector('#historyLoras').textContent = (item.loras || []).map(value => typeof value === 'string' ? value : `${value.name || ''} · ${value.strength ?? 1}`).join('\n') || '사용하지 않음';
    document.querySelector('#historySeed').textContent = item.seed ?? '확인할 수 없음';
    document.querySelector('#historyPrompt').textContent = item.prompt || '이미지 메타데이터에 없음';
    document.querySelector('#historyNegative').textContent = item.negative_prompt || '이미지 메타데이터에 없음'; inspector.hidden = false;
  };
  const renderNextBatch = () => {
    if (renderedCount >= items.length) {
      observeLoadMoreSentinel();
      return;
    }
    const end = Math.min(items.length, renderedCount + LIBRARY_RENDER_BATCH_SIZE);
    for (let index = renderedCount; index < end; index += 1) {
      const item = items[index];
      const date = String(item.date || '날짜 미상');
      let grid = renderedDateGrids.get(date);
      if (!grid) {
        const section = document.createElement('section');
        const heading = document.createElement('h3');
        grid = document.createElement('div');
        section.className = 'image-history-date';
        heading.textContent = date;
        grid.className = 'image-history-grid';
        section.append(heading, grid);
        groups.append(section);
        renderedDateGrids.set(date, grid);
      }

      const button = document.createElement('button');
      const image = document.createElement('img');
      const name = document.createElement('span');
      button.type = 'button';
      button.className = 'image-history-card';
      button.setAttribute('data-history-index', String(index));
      image.dataset.src = apiUrl(item.thumbnail_url || item.url);
      image.alt = String(item.name || 'LAKIS 이미지');
      name.textContent = String(item.name || '이미지');
      if (selectionMode) button.classList.add('selection-mode');
      if (selectedItems.has(item.id)) button.classList.add('multi-selected');
      button.setAttribute('aria-pressed', selectionMode ? String(selectedItems.has(item.id)) : 'false');
      button.append(image, name);
      observeImage(image);
      button.addEventListener('click', () => {
        if (!selectionMode) { show(item, button); return; }
        if (selectedItems.has(item.id)) selectedItems.delete(item.id); else selectedItems.add(item.id);
        button.classList.toggle('multi-selected', selectedItems.has(item.id));
        button.setAttribute('aria-pressed', String(selectedItems.has(item.id)));
        syncSelectionUi();
      });
      grid.append(button);
    }
    renderedCount = end;
    overlay.dataset.libraryRenderedItems = String(renderedCount);
    observeLoadMoreSentinel();
  };
  const render = () => {
    resetImageObserver();
    stopLoadMoreObserver();
    groups.replaceChildren();
    renderedDateGrids.clear();
    renderedCount = 0;
    overlay.dataset.libraryRenderedItems = '0';
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'image-history-empty';
      empty.textContent = '저장된 이미지가 없습니다.';
      groups.append(empty);
      loadMoreSentinel.hidden = true;
      return;
    }
    renderNextBatch();
    if (!('IntersectionObserver' in window)) {
      while (renderedCount < items.length) renderNextBatch();
    }
  };
  const load = async () => {
    clear(); notice('이미지를 불러오는 중…');
    try {
      const response = await fetch(apiUrl('/api/image-history'), {cache: 'no-store', credentials: 'same-origin'});
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
      items = Array.isArray(data.items) ? data.items : [];
      document.querySelector('#imageHistoryPath').textContent = `${data.root || ''}${data.includes_default_root ? ' · 기본 출력 포함' : (data.custom ? ' · 사용자 지정 경로' : ' · 기본 저장 경로')}`;
      notice(''); render();
    } catch (error) { notice(`라키스 라이브러리를 불러오지 못했습니다: ${error?.message || String(error)}`); }
  };
  const close = () => { overlay.hidden = true; document.body.style.overflow = ''; resetImageObserver(); stopLoadMoreObserver(); loadMoreSentinel.hidden = true; clear(); };
  window.addEventListener('lakis:open-image-history', () => { overlay.hidden = false; document.body.style.overflow = 'hidden'; load(); });
  document.querySelector('#imageHistoryClose')?.addEventListener('click', close); overlay.addEventListener('click', event => { if (event.target === overlay) close(); });
  selectModeButton.addEventListener('click', () => { clearDetail(); selectedItems.clear(); selectionMode = true; syncSelectionUi(); render(); });
  selectionCancel.addEventListener('click', exitSelectionMode);
  document.querySelector('#imageHistoryInspectorClose')?.addEventListener('click', event => {
    event.stopPropagation();
    clearDetail();
  });
  document.querySelector('#imageHistoryOpenFolder')?.addEventListener('click', async () => {
    const response = await fetch(apiUrl('/api/open-output-folder'), {method:'POST', credentials:'same-origin'});
    if (!response.ok) notice('저장 폴더를 열지 못했습니다.');
  });
  document.querySelector('#imageHistoryChangePath')?.addEventListener('click', async () => {
    notice('Windows 폴더 선택창에서 새 저장 경로를 선택하세요.');
    try {
      const response = await fetch(apiUrl('/api/choose-output-folder'), {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:'{}'}), data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      if (data.ok) { notice(`저장 경로를 ${data.path}(으)로 변경했습니다. 다음 실행부터 적용됩니다.`); load(); }
      else if (data.cancelled) notice('저장 경로 변경을 취소했습니다.');
    } catch (error) { notice(error?.message || '저장 경로를 변경하지 못했습니다.'); }
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || overlay.hidden) return;
    if (selectionMode) exitSelectionMode();
    else if (!inspector.hidden) clearDetail();
    else close();
  });
  deleteButton.addEventListener('click', async () => {
    if (!selected || !confirm(`“${selected.name}” 이미지를 휴지통으로 보낼까요?`)) return; deleteButton.disabled = true;
    try { const response = await fetch(apiUrl('/api/delete-history-image'), {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify({id:selected.id})}), data = await response.json(); if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`); items = items.filter(item => item.id !== selected.id); clear(); notice('선택한 이미지를 휴지통으로 보냈습니다.'); render(); }
    catch (error) { deleteButton.disabled = false; notice(error?.message || '이미지를 삭제하지 못했습니다.'); }
  });
  batchDeleteButton.addEventListener('click', async () => {
    const requestedIds = [...selectedItems];
    if (!requestedIds.length || batchDeleting) return;
    if (!confirm(`선택한 ${requestedIds.length}개 이미지를 휴지통으로 이동할까요?`)) return;
    batchDeleting = true; syncSelectionUi();
    try {
      const response = await fetch(apiUrl('/api/delete-history-images-batch'), {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify({items:requestedIds})});
      const data = await response.json();
      if (!response.ok || !Array.isArray(data.deleted_items)) throw new Error(data.error || `HTTP ${response.status}`);
      const deletedIds = new Set(data.deleted_items);
      items = items.filter(item => !deletedIds.has(item.id));
      const deleted = Number(data.deleted || deletedIds.size), failed = Number(data.failed || 0);
      exitSelectionMode();
      notice(failed ? `${deleted}개를 휴지통으로 이동했습니다. ${failed}개는 삭제하지 못했습니다.` : `${deleted}개를 휴지통으로 이동했습니다.`);
    } catch (error) {
      batchDeleting = false; syncSelectionUi();
      notice(error?.message || '선택한 이미지를 삭제하지 못했습니다.');
    }
  });
  const sendTo = async kind => { if (!selected) return; const chosen = selected; const response = await fetch(apiUrl(chosen.url), {credentials:'same-origin'}); if (!response.ok) throw new Error(`HTTP ${response.status}`); const blob = await response.blob(), reader = new FileReader(); reader.onload = () => window.dispatchEvent(new CustomEvent(`lakis:history-to-${kind}`, {detail:{dataUrl:reader.result,name:chosen.name}})); reader.readAsDataURL(blob); close(); };
  document.querySelector('#historyUseInpaint')?.addEventListener('click', () => sendTo('inpaint').catch(error => notice(error.message)));
  document.querySelector('#historyUseI2i')?.addEventListener('click', () => sendTo('i2i').catch(error => notice(error.message)));
  syncSelectionUi();
})();
