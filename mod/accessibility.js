// Accessibility layer for the chart editor. Loaded after the main editor script.
// - Accessible names for icon-only buttons, canvas labels
// - Modal dialogs: focus moves in, Tab is trapped, focus returns on close
// - Screen-reader live region (play/pause, undo/redo, assistant results)
// - Keyboard shortcut reference dialog (? or F1)
// - Settings: text size, reduce motion, high-contrast theme; theme choice persists
(function(){
  const STORE = {
    enabled: 'chart_editor_a11y',
    scale: 'chart_editor_ui_scale',
    focus: 'chart_editor_a11y_focus',
    bigHelp: 'chart_editor_a11y_big_help',
    motion: 'chart_editor_reduce_motion',
    theme: 'chart_editor_theme'
  };
  const read = key => { try { return localStorage.getItem(key); } catch { return null; } };
  const write = (key, value) => { try { localStorage.setItem(key, value); } catch {} };
  const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
  const isVisible = node => !!(node.offsetWidth || node.offsetHeight || node.getClientRects().length) && getComputedStyle(node).visibility !== 'hidden';

  // ---------- Live region + toast ----------
  const live = document.createElement('div');
  live.id = 'editorPlusLive';
  live.className = 'sr-only';
  live.setAttribute('aria-live', 'polite');
  live.setAttribute('role', 'status');
  document.body.appendChild(live);
  const toast = document.createElement('div');
  toast.id = 'editorPlusToast';
  toast.setAttribute('aria-hidden', 'true'); // the live region already speaks it
  document.body.appendChild(toast);
  let toastTimer = 0;
  window.editorPlusAnnounce = function(message, options = {}){
    if(!message) return;
    live.textContent = '';
    setTimeout(() => { live.textContent = message; }, 30); // re-set so repeats are spoken
    if(options.toast){
      toast.textContent = message;
      toast.classList.add('show');
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => toast.classList.remove('show'), Math.max(3500, message.length * 70));
    }
  };

  // ---------- Accessible names ----------
  const LABELS = {
    memoryBtn: () => document.getElementById('memoryBtn')?.title,
    cameraFollowBtn: () => document.getElementById('cameraFollowBtn')?.title,
    loopBtn: () => `Loop (${document.getElementById('loopBtn')?.title || 'L'})`,
    trackPreviewMinimizeBtn: () => document.getElementById('trackPreviewMinimizeBtn')?.title,
    trackPreviewFullscreenBtn: () => document.getElementById('trackPreviewFullscreenBtn')?.title
  };
  function labelIconButtons(root = document){
    root.querySelectorAll('button').forEach(button => {
      if(button.hasAttribute('aria-label') && button.getAttribute('aria-label').trim()) return;
      const text = (button.textContent || '').trim();
      if(/\p{L}{2,}/u.test(text)) return; // has a readable text label already
      let label = LABELS[button.id]?.() || button.title || '';
      if(!label && button.classList.contains('track-del')) label = t('plus.removeTrack');
      if(label) button.setAttribute('aria-label', label);
    });
    root.querySelectorAll('input[type="range"]:not([aria-label]), input[type="number"]:not([aria-label]), select:not([aria-label])').forEach(input => {
      if(input.labels?.length) return;
      const previous = input.previousElementSibling;
      const label = input.title || (previous?.classList?.contains('tb-label') ? previous.textContent.replace(/:\s*$/, '').trim() : '');
      if(label) input.setAttribute('aria-label', label);
    });
    root.querySelectorAll('input:not([type]):not([aria-label]), input[type="text"]:not([aria-label]), input[type="search"]:not([aria-label])').forEach(input => {
      if(!input.labels?.length && input.placeholder) input.setAttribute('aria-label', input.placeholder);
    });
  }
  function labelCanvases(){
    const grid = document.getElementById('gridCanvas');
    if(grid){ grid.setAttribute('role', 'application'); grid.setAttribute('aria-label', t('plus.timelineLabel')); grid.setAttribute('aria-roledescription', 'timeline'); }
    document.getElementById('waveCanvas')?.setAttribute('aria-hidden', 'true');
    document.getElementById('trackPreviewCanvas')?.setAttribute('aria-hidden', 'true');
    document.getElementById('workshopToast')?.setAttribute('role', 'status');
  }

  // ---------- Modal focus management ----------
  const openStack = [];
  function dialogOf(overlay){ return overlay.querySelector('[role="dialog"]') || overlay.querySelector('.modal') || overlay; }
  function prepareDialog(overlay){
    const dialog = dialogOf(overlay);
    if(!dialog.getAttribute('role') && !overlay.getAttribute('role')) dialog.setAttribute('role', 'dialog');
    const dialogNode = overlay.getAttribute('role') === 'dialog' ? overlay : dialog;
    dialogNode.setAttribute('aria-modal', 'true');
    if(!dialogNode.hasAttribute('aria-labelledby') && !dialogNode.hasAttribute('aria-label')){
      const heading = dialog.querySelector('h1,h2,h3,h4');
      if(heading){ if(!heading.id) heading.id = (overlay.id || 'dialog') + 'Heading'; dialogNode.setAttribute('aria-labelledby', heading.id); }
    }
    return dialog;
  }
  function onOverlayShown(overlay){
    if(openStack.some(entry => entry.overlay === overlay)) return;
    const dialog = prepareDialog(overlay);
    openStack.push({overlay, returnFocus: document.activeElement});
    requestAnimationFrame(() => {
      if(overlay.contains(document.activeElement)) return; // the editor already focused something inside
      const target = [...dialog.querySelectorAll(FOCUSABLE)].find(isVisible);
      if(target) target.focus({preventScroll: true});
      else { dialog.setAttribute('tabindex', '-1'); dialog.focus({preventScroll: true}); }
    });
  }
  function onOverlayHidden(overlay){
    const index = openStack.findIndex(entry => entry.overlay === overlay);
    if(index < 0) return;
    const [entry] = openStack.splice(index, 1);
    const target = entry.returnFocus;
    if(target && document.contains(target) && isVisible(target) && !document.querySelector('.modal-overlay.show')) target.focus({preventScroll: true});
  }
  const overlayObserver = new MutationObserver(records => {
    for(const record of records){
      const node = record.target;
      if(!(node instanceof HTMLElement) || !node.classList.contains('modal-overlay')) continue;
      node.classList.contains('show') ? onOverlayShown(node) : onOverlayHidden(node);
    }
  });
  function watchOverlays(){
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
      if(overlay.dataset.a11yWatched) return;
      overlay.dataset.a11yWatched = '1';
      overlayObserver.observe(overlay, {attributes: true, attributeFilter: ['class']});
      if(overlay.classList.contains('show')) onOverlayShown(overlay);
    });
  }
  document.addEventListener('keydown', event => {
    if(event.key !== 'Tab' || !openStack.length) return;
    const {overlay} = openStack[openStack.length - 1];
    if(!overlay.classList.contains('show')) return;
    const items = [...dialogOf(overlay).querySelectorAll(FOCUSABLE)].filter(isVisible);
    if(!items.length){ event.preventDefault(); return; }
    const first = items[0], last = items[items.length - 1];
    if(!overlay.contains(document.activeElement)){ event.preventDefault(); first.focus(); }
    else if(event.shiftKey && document.activeElement === first){ event.preventDefault(); last.focus(); }
    else if(!event.shiftKey && document.activeElement === last){ event.preventDefault(); first.focus(); }
  }, true);

  // ---------- Shortcut reference dialog ----------
  function buildShortcutsModal(){
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.id = 'shortcutsModal';
    overlay.innerHTML = '<div class="modal shortcuts-dialog" role="dialog" aria-modal="true" aria-labelledby="shortcutsTitle"><h3 id="shortcutsTitle"></h3><p id="shortcutsHint" class="shortcuts-hint"></p><table class="shortcuts-table"><tbody id="shortcutsBody"></tbody></table><div class="modal-btns"><button type="button" class="btn-ok" id="shortcutsCloseBtn"></button></div></div>';
    document.body.appendChild(overlay);
    overlay.querySelector('#shortcutsCloseBtn').onclick = () => overlay.classList.remove('show');
    overlay.addEventListener('mousedown', event => { if(event.target === overlay) overlay.classList.remove('show'); });
    overlay.addEventListener('keydown', event => { if(event.key === 'Escape'){ event.stopPropagation(); overlay.classList.remove('show'); } });
    watchOverlays();
    return overlay;
  }
  function openShortcuts(){
    const overlay = document.getElementById('shortcutsModal') || buildShortcutsModal();
    overlay.querySelector('#shortcutsTitle').textContent = t('plus.shortcutsTitle');
    overlay.querySelector('#shortcutsHint').textContent = t('plus.shortcutsHint');
    overlay.querySelector('#shortcutsCloseBtn').textContent = t('plus.close');
    const body = overlay.querySelector('#shortcutsBody');
    body.replaceChildren();
    const tips = t('helpTips');
    (Array.isArray(tips) ? tips : []).forEach(tip => {
      const split = tip.indexOf('=');
      const row = document.createElement('tr');
      const keys = document.createElement('th'); keys.scope = 'row';
      tip.slice(0, split).split(/\s*\/\s*|\s+or\s+/).forEach((part, i) => {
        if(i) keys.append(' / ');
        const kbd = document.createElement('kbd'); kbd.textContent = part.trim(); keys.appendChild(kbd);
      });
      const desc = document.createElement('td'); desc.textContent = tip.slice(split + 1);
      row.append(keys, desc); body.appendChild(row);
    });
    overlay.classList.add('show');
  }
  window.addEventListener('keydown', event => {
    if(window.isLyricTapSyncActive?.()) return;
    const target = event.target;
    const typing = target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName));
    if(typing || event.ctrlKey || event.metaKey || event.altKey) return;
    const question = event.key === '?' || (event.code === 'Slash' && event.shiftKey);
    if(event.key === 'F1' || (question && !document.querySelector('.modal-overlay.show'))){
      event.preventDefault(); event.stopImmediatePropagation();
      openShortcuts();
    }
  }, true);

  // ---------- Announcements for playback / undo ----------
  const playBtn = document.getElementById('playBtn');
  if(playBtn){
    let wasPlaying = typeof isPlaying !== 'undefined' && isPlaying;
    new MutationObserver(() => {
      const playing = typeof isPlaying !== 'undefined' && isPlaying;
      if(playing !== wasPlaying){ wasPlaying = playing; window.editorPlusAnnounce(t(playing ? 'plus.playing' : 'plus.paused')); }
      playBtn.setAttribute('aria-pressed', String(playing));
    }).observe(playBtn, {childList: true, characterData: true, subtree: true});
  }
  // Wrap undo/redo by name: the keyboard handler and other callers resolve them through the global object.
  for(const [name, key] of [['undo', 'plus.undone'], ['redo', 'plus.redone']]){
    const original = window[name];
    if(typeof original !== 'function') continue;
    window[name] = function(...args){ const result = original.apply(this, args); window.editorPlusAnnounce(t(key)); return result; };
  }

  // ---------- Settings: text size, reduce motion, high contrast ----------
  if(typeof THEMES !== 'undefined' && !THEMES.highContrast){
    THEMES.highContrast = Object.assign({}, THEMES.neutral, {
      bg:'#000000', barBg:'#000000', typeBg:'#000000', gridBg:'#000000', gridAlt:'#0e0e0e', headerLine:'#ffffff', laneDivider:'#6a6a6a',
      barLine:'#e6e6e6', beatLine:'#8a8a8a', subLine:'#3c3c3c', labelBg:'#000000', waveformBg:'#000000', waveformBar:'#ffd400', waveformMid:'#9a9a9a',
      text:'#f0f0f0', textBright:'#ffffff', border:'#bdbdbd', loopFill:'rgba(0,255,170,0.20)', loopLine:'#00ffaa',
      btnBg:'#000000', btnText:'#ffffff', btnBorder:'#ffffff', btnHover:'#333333', helpBg:'#000000', helpText:'#f0f0f0', helpKeyBg:'#000000',
      helpKeyBorder:'#ffffff', helpKeyText:'#ffd400', annotBg:'#000000', annotBorder:'#ffffff', annotLabel:'#dddddd', modalBg:'#000000',
      modalText:'#ffffff', inputBg:'#000000', inputText:'#ffffff', accent:'#ffd400'
    });
  }
  const themeSelect = document.getElementById('themeSelect');
  function syncThemeOptionLabel(){
    const option = themeSelect?.querySelector('option[value="highContrast"]');
    if(option) option.textContent = t('plus.themeHighContrast');
  }
  if(themeSelect){
    if(!themeSelect.querySelector('option[value="highContrast"]')) themeSelect.appendChild(new Option('', 'highContrast'));
    syncThemeOptionLabel();
    themeSelect.addEventListener('change', () => {
      write(STORE.theme, themeSelect.value);
      document.documentElement.classList.toggle('a11y-high-contrast', themeSelect.value === 'highContrast');
    });
    const savedTheme = read(STORE.theme);
    if(savedTheme && THEMES[savedTheme] && themeSelect.value !== savedTheme){
      themeSelect.value = savedTheme;
      themeSelect.dispatchEvent(new Event('change'));
    }
    document.documentElement.classList.toggle('a11y-high-contrast', themeSelect.value === 'highContrast');
  }

  // Visual accessibility changes are opt-in behind one "Accessibility mode" switch (off by default,
  // so the editor looks stock). Each visual change then has its own toggle. Invisible improvements
  // (accessible names, dialog focus handling, screen-reader announcements) are always on.
  const html = document.documentElement;
  const flag = (key, fallback) => { const value = read(key); return value === null ? fallback : value === 'true'; };
  const systemReduce = !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  function a11yEnabled(){ return flag(STORE.enabled, false); }
  function applyA11y(){
    const on = a11yEnabled();
    html.classList.toggle('a11y-on', on);
    html.classList.toggle('a11y-focus', on && flag(STORE.focus, true));
    html.classList.toggle('a11y-big-help', on && flag(STORE.bigHelp, true));
    html.classList.toggle('a11y-reduce-motion', on && flag(STORE.motion, systemReduce));
    const options = document.getElementById('a11yOptions');
    if(options) options.hidden = !on;
    // Text size is read by updateEditorViewport() in chart_editor.html, which also checks the master switch.
    if(typeof updateEditorViewport === 'function') updateEditorViewport();
    window.dispatchEvent(new Event('resize'));
  }

  function buildSettingsGroup(){
    const panel = document.getElementById('settingsPanel');
    if(!panel || document.getElementById('a11ySettingsGroup')) return;
    const group = document.createElement('div');
    group.className = 'tb-group';
    group.id = 'a11ySettingsGroup';
    const check = (id) => `<label class="tb-label a11y-inline" for="${id}"><input type="checkbox" id="${id}"><span id="${id}Label"></span></label>`;
    group.innerHTML = check('a11yEnabled')
      + '<span id="a11yOptions" class="a11y-options">'
      + '<label class="tb-label a11y-inline" for="a11yTextSize"><span id="a11yTextSizeLabel"></span></label>'
      + '<select id="a11yTextSize"><option value="1">100%</option><option value="1.15">115%</option><option value="1.3">130%</option><option value="1.5">150%</option><option value="1.75">175%</option></select>'
      + check('a11yFocus') + check('a11yBigHelp') + check('a11yReduceMotion')
      + '</span>'
      + '<button type="button" id="a11yShortcutsBtn"></button>';
    panel.appendChild(group);
    const bind = (id, key, fallback) => {
      const box = group.querySelector('#' + id);
      box.checked = flag(key, fallback);
      box.addEventListener('change', () => { write(key, String(box.checked)); applyA11y(); });
    };
    bind('a11yEnabled', STORE.enabled, false);
    bind('a11yFocus', STORE.focus, true);
    bind('a11yBigHelp', STORE.bigHelp, true);
    bind('a11yReduceMotion', STORE.motion, systemReduce);
    const size = group.querySelector('#a11yTextSize');
    size.value = ['1','1.15','1.3','1.5','1.75'].includes(read(STORE.scale)) ? read(STORE.scale) : '1';
    size.addEventListener('change', () => { write(STORE.scale, size.value); applyA11y(); });
    group.querySelector('#a11yShortcutsBtn').addEventListener('click', openShortcuts);
    applyA11y();
  }
  function localizeSettingsGroup(){
    const set = (id, key) => { const node = document.getElementById(id); if(node) node.textContent = t(key); };
    set('a11yEnabledLabel', 'plus.a11yMode');
    set('a11yTextSizeLabel', 'plus.textSize');
    set('a11yFocusLabel', 'plus.focusOutlines');
    set('a11yBigHelpLabel', 'plus.largeHelp');
    set('a11yReduceMotionLabel', 'plus.reduceMotion');
    set('a11yShortcutsBtn', 'plus.shortcutsBtn');
    syncThemeOptionLabel();
    labelCanvases();
  }

  // ---------- Init + keep up with dynamic DOM / language changes ----------
  buildSettingsGroup();
  localizeSettingsGroup();
  labelIconButtons();
  watchOverlays();
  let pending = 0;
  const NOISY = '#timeDisplay,#zoomIndicator,#entityInfo,#editorPlusLive,#editorPlusToast,#trackPreviewMeter,#trackPreviewStatus,#lyricTapSyncPanel';
  new MutationObserver(records => {
    if(records.every(record => (record.target.nodeType === 1 ? record.target : record.target.parentElement)?.closest?.(NOISY))) return;
    if(pending) return;
    pending = requestAnimationFrame(() => { pending = 0; labelIconButtons(); watchOverlays(); });
  }).observe(document.body, {childList: true, subtree: true});
  document.getElementById('langSelect')?.addEventListener('change', () => setTimeout(localizeSettingsGroup, 0));
})();
