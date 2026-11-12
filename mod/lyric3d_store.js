// 3D lyric signs ("lyric3d") - the data behind the 3D Lyric Designer, shown in game by the BFS Lyric3D mod.
// Stored on the chart beside the normal lyrics, which stay as the fallback for players without the mod.
//
// This file does not edit the editor's own lyrics.js. It wraps four of its functions from the outside
// (load from chart, undo snapshot, restore snapshot, export), so it keeps working when the editor updates.
// Load it right after lyrics.js.

let lyric3dDesign = {version: 1, panels: []};
var LYRIC3D_REVEALS = ['none', 'typewriter', 'karaoke'];
var LYRIC3D_ENTERS = ['rise', 'fade', 'pop', 'drop'];
var LYRIC3D_EXITS = ['fade', 'dissolve', 'shrink', 'rise'];

function clampNumber(value, min, max, fallback){
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(min, Math.min(max, number)) : fallback;
}

function isHexColor(value){ return /^#[0-9a-f]{6}$/i.test(String(value || '')); }

function normalizeLyric3dSign(raw){
  if(!raw || typeof raw !== 'object') return null;
  const lines = (Array.isArray(raw.lines) ? raw.lines : []).map(line => ({
    text: String(line?.text ?? '').slice(0, 200),
    size: clampNumber(line?.size, 0.2, 4, 1),
    color: isHexColor(line?.color) ? line.color : '#ffffff',
    bold: line?.bold !== false,
    italic: line?.italic === true,
  })).filter(line => line.text.trim());
  if(!lines.length || !Number.isFinite(Number(raw.beat))) return null;
  const sign = {
    beat: Number(raw.beat), duration: clampNumber(raw.duration, 0.05, 64, 2), lines,
    side: [-1, 0, 1].includes(Number(raw.side)) ? Number(raw.side) : 1,
    distance: clampNumber(raw.distance, 2, 80, 15), height: clampNumber(raw.height, 0, 40, 7),
    turn: clampNumber(raw.turn, 0, 90, 60), scale: clampNumber(raw.scale, 0.1, 5, 1),
    opacity: clampNumber(raw.opacity, 0, 1, 0.95), outline: clampNumber(raw.outline, 0, 0.5, 0.15),
    spacing: clampNumber(raw.spacing, -20, 60, 4),
    reveal: LYRIC3D_REVEALS.includes(raw.reveal) ? raw.reveal : 'karaoke',
    enter: LYRIC3D_ENTERS.includes(raw.enter) ? raw.enter : 'rise',
    exit: LYRIC3D_EXITS.includes(raw.exit) ? raw.exit : 'fade',
    pulse: raw.pulse !== false,
  };
  if(typeof raw.font === 'string' && raw.font.trim()) sign.font = raw.font.trim().slice(0, 80);
  // road signs: seconds to stand further along the road (+) or closer (-) than where you are while the
  // line is sung. Only the position changes; the karaoke still follows the singing.
  // optional reveal window (beats): when the typewriter types / the karaoke lights up, if not the sung time
  // each end is optional on its own: a missing start/end follows the sung start/end
  if(Number.isFinite(Number(raw.revealStart)) && raw.revealStart !== null && raw.revealStart !== '') sign.revealStart = Number(raw.revealStart);
  if(Number.isFinite(Number(raw.revealEnd)) && raw.revealEnd !== null && raw.revealEnd !== '') sign.revealEnd = Number(raw.revealEnd);
  // road signs placed by hand: the beat you drive past them. Absolute - the mod's TimeOffset does not apply.
  const passAt = Number(raw.passAt);
  if(raw.anchor !== 'world' && Number.isFinite(passAt)) sign.passAt = passAt;
  if(Array.isArray(raw.gradient) && raw.gradient.length === 2 && raw.gradient.every(isHexColor)) sign.gradient = [...raw.gradient];
  // "world" signs stand at a fixed spot in the scene with their own appear/disappear times;
  // "road" signs (default) are placed beside the road where the car is while the line is sung.
  const position = raw.position;
  if(raw.anchor === 'world' && position && ['x', 'y', 'z'].every(axis => Number.isFinite(Number(position[axis])))){
    sign.anchor = 'world';
    sign.position = {x: Number(position.x), y: Number(position.y), z: Number(position.z)};
    sign.yaw = clampNumber(raw.yaw, -360, 360, 0);
    sign.tilt = clampNumber(raw.tilt, -89, 89, 0);
    sign.appear = Number.isFinite(Number(raw.appear)) ? Number(raw.appear) : sign.beat - 8;
    sign.disappear = Number.isFinite(Number(raw.disappear)) ? Math.max(sign.appear + 0.05, Number(raw.disappear)) : sign.beat + sign.duration + 4;
  }
  return sign;
}

function normalizeLyric3d(raw, beatShift = 0){
  const panels = (Array.isArray(raw?.panels) ? raw.panels : []).map(normalizeLyric3dSign).filter(Boolean)
    .map(sign => {
      const shifted = {...sign, beat: sign.beat + beatShift};
      for(const key of ['appear', 'disappear', 'revealStart', 'revealEnd', 'passAt']){
        if(Number.isFinite(sign[key])) shifted[key] = sign[key] + beatShift;
      }
      return shifted;
    })
    .sort((a, b) => a.beat - b.beat);
  return {version: 1, panels};
}

(function hookIntoLyrics(){
  const notifyDesigner = () => { if(typeof window.onLyric3dDesignReplaced === 'function') window.onLyric3dDesignReplaced(); };
  const wrap = (name, makeWrapper) => {
    const original = window[name];
    if(typeof original !== 'function'){
      console.warn(`[3D lyrics] the editor has no ${name}() any more - 3D lyric designs will not be saved`);
      return;
    }
    window[name] = makeWrapper(original);
  };

  // opening a chart: read its design (beats in the file include the global offset)
  wrap('restoreLyricsFromChart', original => function(chart, ...rest){
    const result = original.call(this, chart, ...rest);
    const offset = (Number(chart?.musicData?.offset) || 0) * (Number(chart?.musicData?.bpm) || 120) / 60;
    lyric3dDesign = normalizeLyric3d(chart?.lyric3d, -offset);
    notifyDesigner();
    return result;
  });

  // undo/redo and autosave snapshots carry the design too
  wrap('lyricSnapshot', original => function(...args){
    const snapshot = original.apply(this, args);
    try {
      const state = JSON.parse(snapshot);
      state.lyric3d = lyric3dDesign;
      return JSON.stringify(state);
    } catch {
      return snapshot;
    }
  });
  wrap('restoreLyricSnapshot', original => function(snapshot, ...rest){
    const result = original.call(this, snapshot, ...rest);
    if(snapshot){
      try { lyric3dDesign = normalizeLyric3d(JSON.parse(snapshot).lyric3d); } catch {}
      notifyDesigner();
    }
    return result;
  });

  // saving / exporting / importing to the game / Workshop upload
  wrap('exportLyrics', original => function(output, offset, ...rest){
    const result = original.call(this, output, offset, ...rest);
    const design = normalizeLyric3d(lyric3dDesign, Number(offset) || 0);
    const round4 = value => Number(Number(value).toFixed(4));
    if(design.panels.length){
      output.lyric3d = {version: 1, panels: design.panels.map(sign => sign.anchor === 'world'
        ? {...sign, beat: round4(sign.beat), appear: round4(sign.appear), disappear: round4(sign.disappear)}
        : {...sign, beat: round4(sign.beat)})
        .map(sign => ({...sign,
          ...(Number.isFinite(sign.revealStart) ? {revealStart: round4(sign.revealStart)} : {}),
          ...(Number.isFinite(sign.revealEnd) ? {revealEnd: round4(sign.revealEnd)} : {})}))
        .map(sign => Number.isFinite(sign.passAt) ? {...sign, passAt: round4(sign.passAt)} : sign)};
    } else {
      delete output.lyric3d;
    }
    return result;
  });
})();
