// Tap sync: keyboard-driven lyric timing. Play the song and press Enter/T as each
// line starts. Works without any AI model, is fully keyboard/screen-reader usable,
// and is usually more precise than recognition for sung vocals.
// Depends on editor globals: isPlaying, togglePlay, pausePlayback, getCurrentSec,
// seekTimelineToBeat, secToBeat, getMaxAudioDuration, applyAssistantLyrics,
// timedEntriesToLyrics, t, tFmt.
(function(){
  let session = null;

  function el(tag, attrs = {}, text){
    const node = document.createElement(tag);
    for(const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if(text !== undefined) node.textContent = text;
    return node;
  }

  function buildPanel(){
    const panel = el('div', {id:'lyricTapSyncPanel', role:'dialog', 'aria-modal':'false', 'aria-labelledby':'lyricTapSyncTitle'});
    panel.innerHTML = `
      <div class="tap-head"><strong id="lyricTapSyncTitle"></strong><span id="lyricTapSyncCount"></span></div>
      <div class="tap-line tap-prev"><span class="tap-tag" id="lyricTapPrevTag"></span><span id="lyricTapPrev"></span></div>
      <div class="tap-line tap-current" id="lyricTapCurrent" aria-live="assertive"></div>
      <div class="tap-line tap-next"><span class="tap-tag" id="lyricTapNextTag"></span><span id="lyricTapNext"></span></div>
      <div class="tap-progress"><span id="lyricTapProgressFill"></span></div>
      <p class="tap-keys" id="lyricTapKeys"></p>
      <div class="tap-actions"><button type="button" class="btn-cancel" id="lyricTapCancelBtn"></button><button type="button" class="btn-ok" id="lyricTapFinishBtn"></button></div>`;
    document.body.appendChild(panel);
    panel.querySelector('#lyricTapCancelBtn').onclick = () => endTapSync(false);
    panel.querySelector('#lyricTapFinishBtn').onclick = () => endTapSync(true);
    return panel;
  }

  function updatePanel(){
    if(!session) return;
    const {panel, lines, taps} = session;
    const index = taps.length;
    panel.querySelector('#lyricTapSyncTitle').textContent = t('plus.tapTitle');
    panel.querySelector('#lyricTapSyncCount').textContent = tFmt('plus.tapProgress', Math.min(index + 1, lines.length), lines.length);
    panel.querySelector('#lyricTapPrevTag').textContent = t('plus.tapPrev');
    panel.querySelector('#lyricTapNextTag').textContent = t('plus.tapNext');
    panel.querySelector('#lyricTapPrev').textContent = index > 0 ? lines[index - 1] : '—';
    panel.querySelector('#lyricTapCurrent').textContent = index < lines.length ? lines[index] : t('plus.tapAllDone');
    panel.querySelector('#lyricTapNext').textContent = index + 1 < lines.length ? lines[index + 1] : '—';
    panel.querySelector('#lyricTapKeys').textContent = (index === 0 ? t('plus.tapWaiting') + ' ' : '') + t('plus.tapKeys');
    panel.querySelector('#lyricTapCancelBtn').textContent = t('plus.tapCancel');
    panel.querySelector('#lyricTapFinishBtn').textContent = t('plus.tapFinish');
    panel.querySelector('#lyricTapProgressFill').style.width = `${(index / lines.length) * 100}%`;
    panel.classList.remove('tap-flash'); void panel.offsetWidth; if(session.flash) panel.classList.add('tap-flash');
    session.flash = false;
  }

  function nowSeconds(){
    return Math.max(0, getCurrentSec() - session.latency);
  }

  function tap(){
    if(!isPlaying){ togglePlay(); return; }
    if(session.taps.length >= session.lines.length) return;
    const start = nowSeconds();
    const previous = session.taps[session.taps.length - 1];
    if(previous && start <= previous.start + 0.05) return; // double-press guard
    session.taps.push({start, end:null});
    session.flash = true;
    updatePanel();
  }

  function markEnd(){
    const last = session.taps[session.taps.length - 1];
    if(!last || !isPlaying) return;
    const end = nowSeconds();
    if(end > last.start + 0.1) last.end = end;
  }

  function undoTap(){
    const removed = session.taps.pop();
    if(!removed) return;
    // Rewind ~2 s before the removed line so it can be re-tapped in context.
    seekTimelineToBeat(secToBeat(Math.max(0, removed.start - 2)), true);
    updatePanel();
  }

  function onKeyDown(event){
    if(!session) return;
    if(event.ctrlKey || event.metaKey || event.altKey) return;
    const key = event.key;
    if(key === ' ' || event.code === 'Space') return; // editor handles play/pause
    if(/^F\d+$/.test(key) || key === 'Tab') return;
    if(document.activeElement && session.panel.contains(document.activeElement) && key === 'Enter' && document.activeElement.tagName === 'BUTTON') return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if(event.repeat) return;
    if(key === 'Enter' || event.code === 'KeyT') tap();
    else if(event.code === 'KeyS') markEnd();
    else if(key === 'Backspace') undoTap();
    else if(key === 'Escape') endTapSync(true);
  }

  function buildEntries(){
    const {lines, taps} = session;
    const audioEnd = Math.max(1, getMaxAudioDuration?.() || 0);
    return taps.map((entry, index) => {
      const next = taps[index + 1];
      let end = entry.end;
      if(!Number.isFinite(end)) end = next ? Math.min(next.start - 0.08, entry.start + 8) : Math.min(audioEnd, entry.start + 4);
      return {start: entry.start, end: Math.max(entry.start + 0.15, end), text: lines[index], confidence: 'high'};
    });
  }

  function endTapSync(apply){
    if(!session) return;
    const current = session;
    window.removeEventListener('keydown', onKeyDown, true);
    if(isPlaying) pausePlayback();
    const entries = apply ? buildEntries() : [];
    current.panel.remove();
    session = null;
    current.returnFocus?.focus?.({preventScroll: true});
    if(entries.length){
      applyAssistantLyrics(timedEntriesToLyrics(entries, 'high', 1), 'tap sync lyrics');
      window.editorPlusAnnounce?.(tFmt('plus.tapDone', entries.length, current.lines.length), {toast: true});
    }else if(apply){
      window.editorPlusAnnounce?.(t('plus.tapNone'), {toast: true});
    }
  }

  window.startLyricTapSync = function(lines, latencyMs = 60){
    if(session) endTapSync(false);
    if(!Array.isArray(lines) || !lines.length) return;
    const panel = buildPanel();
    session = {lines, taps: [], panel, latency: Math.max(0, Number(latencyMs) || 0) / 1000, flash: false, returnFocus: document.getElementById('lyricsAssistantBtn')};
    window.addEventListener('keydown', onKeyDown, true);
    updatePanel();
    panel.querySelector('#lyricTapFinishBtn').blur();
    document.getElementById('gridCanvas')?.focus?.({preventScroll: true});
    if(!isPlaying) togglePlay();
  };
  window.isLyricTapSyncActive = () => !!session;
})();
