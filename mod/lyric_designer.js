// Lyric Designer - design 3D lyric signs inside the chart editor's 3D track view.
//
// Signs are stored on the chart as "lyric3d" (see lyrics.js) and shown in game by the BFS Lyric3D
// mod. Two kinds of sign:
//   road  - placed beside the road where the rider is while the line is sung (side, distance, height, turn)
//   world - fixed anywhere in the scene, with its own appear / disappear times
// The 3D view reuses the editor's track preview (same world coordinates as the game), and draws
// each sign with its real font, colours, gradient and karaoke state at the playhead.
(function(){
  'use strict';

  // ------------------------------------------------------------------ text (English; other languages fall back)
  const TEXT = {
    open: '🪧 3D Lyrics', title: '3D Lyric Designer', close: 'Close',
    play: '▶ Play', pause: '⏸ Pause', scrub: 'Song position', riderHelp: 'Drag the bar - or the green time tag over the rider in the 3D view - to move through the song.', rideAlong: 'Ride along (chase camera)', showScenery: 'Show buildings',
    rideHelp: 'Play the song and the camera follows the rider; signs appear on their real timing. Drag the view to look around (stops riding along).',
    modLead: 'Mod "LeadSeconds" (s)',
    hint: 'Signs show in game with the BFS Lyric3D mod. Normal lyrics stay as the fallback.',
    passAt: 'Pass it at (s)',
    roadHelp: 'Drag the sign along the road in the 3D view, or type when you drive past it. Placed signs stay exactly there (the mod\'s time offset no longer moves them). Empty = automatic.',
    generate: 'Generate from lyrics', addRoad: '+ Road sign at playhead', addWorld: '+ Place in world…',
    placing: 'Click anywhere in the 3D view to place the sign (Esc cancels).',
    duplicate: 'Duplicate', remove: 'Delete', driverView: 'Driver view', jump: 'Play from here', copyLook: 'Copy look to all signs',
    none: 'No signs yet. Generate them from the lyrics, or add one.',
    sectionText: 'Text', sectionTiming: 'Timing', sectionPlace: 'Placement', sectionLook: 'Look', sectionPreview: 'Preview',
    revealStart: '{0} starts (s)', revealEnd: '{0} ends (s)', karaoke: 'Karaoke', typewriter: 'Typewriter',
    revealHelp: 'Empty = the {0} follows the singing (Sung from -> Sung until). Fill in to make it start or end at other times.',
    sungUntil: 'Sung until (s)', sungLength: 'Sung for {0} s. These are when the words are sung - to move the sign itself, drag it along the road or use "Pass it at" under Placement.',
    addLine: '+ Line', sungAt: 'Sung from (s)', duration: 'Length (s)', appear: 'Appears (s)', disappear: 'Disappears (s)',
    anchor: 'Anchor', anchorRoad: 'Follow the road', anchorWorld: 'Fixed in the world',
    side: 'Side', left: 'Left', right: 'Right', over: 'Over the road', distance: 'Distance from road (m)',
    height: 'Height (m)', turn: 'Angle (0 faces rider, 90 parallel)', facing: 'Facing (°)', tilt: 'Tilt (°)',
    faceCamera: 'Face the camera', moveHere: 'Move to view centre', worldHelp: 'Drag the sign in the 3D view. Shift+drag = height, Alt+drag = turn.',
    font: 'Font', scale: 'Size', opacity: 'Opacity', outline: 'Outline', spacing: 'Letter spacing', gradient: 'Gradient',
    reveal: 'Reveal', enter: 'Enter', exit: 'Exit', pulse: 'Pulse on beat',
    modScale: 'Mod "Scale" setting', modOffset: 'Mod "TimeOffset" (s)', previewHelp: 'Match these to your BFS Lyric3D settings so road signs preview where the mod puts them.',
    replaceConfirm: 'Replace the existing road signs?', generated: 'Generated {0} road signs from the lyrics.',
    needScene: 'Pick a scene in the 3D view first (City, Forest, Coast or Mountain).',
    noScenery: 'Buildings are not available for this track yet: drive it once in game with the BFS Lyric3D mod (v0.7+) and reopen the designer.',
    scenery: 'Showing {0} buildings and objects from the game. Click a wall while placing to stick a sign onto it.',
  };
  if(typeof EDITOR_LOCALES !== 'undefined'){
    EDITOR_LOCALES.en = EDITOR_LOCALES.en || {};
    for(const [key, value] of Object.entries(TEXT)) if(!EDITOR_LOCALES.en['l3d.' + key]) EDITOR_LOCALES.en['l3d.' + key] = value;
  }
  const say = (key, ...args) => {
    let text = typeof t === 'function' ? t('l3d.' + key) : TEXT[key];
    if(text === 'l3d.' + key) text = TEXT[key];
    args.forEach((arg, index) => { text = text.split('{' + index + '}').join(String(arg)); });
    return text;
  };

  // ------------------------------------------------------------------ constants matching the BFS Lyric3D mod
  const CANVAS_PIXEL_METRES = 0.02;   // the mod's canvas units -> metres
  const BASE_FONT_PIXELS = 150;       // the mod's font size
  const PASS_POINT = 0.4;             // where in a sung line the rider passes a road sign
  const KARAOKE_DIM_ALPHA = 0x6e / 255;
  const COMMON_FONTS = ['Impact', 'Arial Black', 'Bebas Neue', 'Montserrat', 'Segoe UI Black', 'Bahnschrift', 'Franklin Gothic Heavy', 'Georgia', 'Trebuchet MS', 'Verdana'];

  const PREFS_KEY = 'chart_editor_lyric3d_prefs_v1';
  const prefs = {modScale: 0.7, modOffset: 4.5, modLead: 8, version: 4, showScenery: true};
  try {
    const saved = JSON.parse(localStorage.getItem(PREFS_KEY)) || {};
    // v4: settled on the mod's TimeOffset of 4.5 s after trying 8 and 5
    if((saved.version || 1) < 4 && [5, 8].includes(Number(saved.modOffset))) saved.modOffset = 4.5;
    Object.assign(prefs, saved, {version: 4});
  } catch {}
  const savePrefs = () => { try { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch {} };

  const state = {open: false, selected: -1, placing: false, drag: null, undoArmed: true, previousAutoFollow: true, wasFullscreen: false,
    scenery: {trackId: '', boxes: [], status: ''}, rideAlong: false};
  const measureContext = document.createElement('canvas').getContext('2d');

  // ------------------------------------------------------------------ small vector helpers (editor's vec* are reused)
  const up = {x: 0, y: 1, z: 0};
  const flat = vector => normalizeVec({x: vector.x, y: 0, z: vector.z}, {x: 0, y: 0, z: 1});
  const rotateAroundUp = (vector, degrees) => {      // same direction as Unity's AngleAxis(degrees, up)
    const radians = degrees * Math.PI / 180, cos = Math.cos(radians), sin = Math.sin(radians);
    return {x: vector.x * cos + vector.z * sin, y: vector.y, z: -vector.x * sin + vector.z * cos};
  };
  const yawToForward = yawDegrees => ({x: Math.sin(yawDegrees * Math.PI / 180), y: 0, z: Math.cos(yawDegrees * Math.PI / 180)});
  const forwardToYaw = forward => Math.atan2(forward.x, forward.z) * 180 / Math.PI;

  const signs = () => lyric3dDesign.panels;
  const selectedSign = () => signs()[state.selected] || null;
  const secondsOf = beat => beatToSec(beat);
  const beatOf = seconds => secToBeat(seconds);

  // ------------------------------------------------------------------ where a sign stands (mirrors the mod)

  /** World centre, the direction the rider reads it along (canvas forward), and its basis vectors. */
  function signPose(sign){
    if(sign.anchor === 'world'){
      const yaw = sign.yaw || 0, tilt = (sign.tilt || 0) * Math.PI / 180;
      const level = yawToForward(yaw);
      const forward = normalizeVec({x: level.x * Math.cos(tilt), y: -Math.sin(tilt), z: level.z * Math.cos(tilt)}, level);
      return poseFrom({...sign.position}, forward);
    }
    if(!trackPreviewData) return null;
    const roadDistance = beatToPreviewRuntimeDistance(beatOf(roadSignPassSeconds(sign))) + pathStartOffsetDistance;
    const sample = sampleTrackAtDistance(roadDistance);
    if(!sample) return null;
    const along = flat(sample.direction);
    const roadRight = normalizeVec(crossVec(up, along), {x: 1, y: 0, z: 0});
    const earlier = sampleTrackAtDistance(roadDistance - 40);
    const approach = earlier ? flat(vecSub(sample.position, earlier.position)) : along;
    if(sign.side === 0) return poseFrom(vecAdd(sample.position, vecScale(up, sign.height + 3)), approach, roadDistance);
    let forward = rotateAroundUp(along, sign.side * sign.turn);
    if(dotVec(forward, approach) < 0) forward = vecScale(forward, -1);
    const centre = vecAdd(vecAdd(sample.position, vecScale(roadRight, sign.side * sign.distance)), vecScale(up, sign.height));
    return poseFrom(centre, forward, roadDistance);
  }

  /** The reader looks along `forward`; text runs along `right` and up along `textUp`. */
  function poseFrom(centre, forward, roadDistance){
    const right = normalizeVec(crossVec(up, forward), {x: 1, y: 0, z: 0});
    const textUp = normalizeVec(crossVec(forward, right), up);
    return {centre, forward, right, textUp, roadDistance};
  }

  // ------------------------------------------------------------------ text layout (same proportions as the mod)

  function cssFont(sign, line, pixels){
    const family = sign.font ? `"${sign.font}", ` : '';
    return `${line.italic ? 'italic ' : ''}${line.bold ? '800' : '400'} ${pixels}px ${family}"Liberation Sans", Arial, sans-serif`;
  }

  function layoutSign(sign){
    const pixelScale = CANVAS_PIXEL_METRES * Number(prefs.modScale || 0.7) * (sign.scale || 1);
    const lines = sign.lines.map(line => {
      const pixels = BASE_FONT_PIXELS * line.size;
      measureContext.font = cssFont(sign, line, pixels);
      measureContext.letterSpacing = `${sign.spacing || 0}px`;
      return {line, pixels, width: measureContext.measureText(line.text).width, height: pixels * 0.88};
    });
    const widthPixels = Math.max(10, ...lines.map(entry => entry.width));
    const heightPixels = Math.max(10, lines.reduce((sum, entry) => sum + entry.height, 0));
    return {lines, widthPixels, heightPixels, metresPerPixel: pixelScale};
  }

  // ------------------------------------------------------------------ scenery exported by the BFS Lyric3D mod
  // Tools/chart_editor/scene_context/<track>.json: buildings near the road as rotated boxes
  // (centre + three half-extent vectors), recorded the first time the mod drives that track.

  async function loadScenery(){
    const trackId = String(trackPreviewData?.id || '').toLowerCase();
    if(!trackId || state.scenery.trackId === trackId) return;
    state.scenery = {trackId, boxes: [], status: ''};
    try {
      const response = await fetch(`scene_context/${encodeURIComponent(trackId)}.json`, {cache: 'no-store'});
      if(!response.ok) throw new Error(String(response.status));
      const data = await response.json();
      const toVector = array => ({x: Number(array[0]), y: Number(array[1]), z: Number(array[2])});
      state.scenery.boxes = (data.boxes || []).map(box => {
        const halfX = toVector(box.halfX), halfY = toVector(box.halfY), halfZ = toVector(box.halfZ);
        return {center: toVector(box.center), halves: [halfX, halfY, halfZ],
          axes: [halfX, halfY, halfZ].map(half => normalizeVec(half, {x: 1, y: 0, z: 0})),
          extents: [halfX, halfY, halfZ].map(half => Math.hypot(half.x, half.y, half.z))};
      });
      state.scenery.status = say('scenery', state.scenery.boxes.length);
    } catch {
      state.scenery.status = say('noScenery');
    }
    if(state.open){ setStatus(state.scenery.status); renderTrackPreview(true); }
  }

  const BOX_CORNERS = [[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]];
  const BOX_FACES = [   // corner indices, and which axis/sign is the face's outward normal
    {corners: [0, 3, 7, 4], axis: 0, sign: -1}, {corners: [1, 5, 6, 2], axis: 0, sign: 1},
    {corners: [0, 4, 5, 1], axis: 1, sign: -1}, {corners: [3, 2, 6, 7], axis: 1, sign: 1},
    {corners: [0, 1, 2, 3], axis: 2, sign: -1}, {corners: [4, 7, 6, 5], axis: 2, sign: 1},
  ];

  function drawScenery(context, camera, width, height){
    const boxes = state.scenery.boxes;
    if(!state.open || !boxes.length || !prefs.showScenery) return;
    const basis = getTrackPreviewCameraBasis(camera);
    const visible = [];
    for(const box of boxes){
      const depth = dotVec(vecSub(box.center, camera.position), basis.forward);
      // while riding along, skip buildings right around the camera so they do not wall off the view
      const nearest = state.rideAlong ? 35 : 2;
      if(depth > nearest && depth < 1600) visible.push({box, depth});
    }
    visible.sort((a, b) => b.depth - a.depth);
    context.save();
    context.lineWidth = 1;
    for(const {box} of visible){
      const corners = BOX_CORNERS.map(([sx, sy, sz]) => projectTrackPoint(
        vecAdd(vecAdd(vecAdd(box.center, vecScale(box.halves[0], sx)), vecScale(box.halves[1], sy)), vecScale(box.halves[2], sz)),
        camera, width, height, 2));
      if(corners.some(corner => !corner)) continue;
      for(const face of BOX_FACES){
        const normal = vecScale(box.axes[face.axis], face.sign);
        const faceCentre = vecAdd(box.center, vecScale(box.halves[face.axis], face.sign));
        if(dotVec(normal, vecSub(camera.position, faceCentre)) <= 0) continue;   // facing away
        context.beginPath();
        face.corners.forEach((cornerIndex, index) => index
          ? context.lineTo(corners[cornerIndex].x, corners[cornerIndex].y)
          : context.moveTo(corners[cornerIndex].x, corners[cornerIndex].y));
        context.closePath();
        const shade = face.axis === 1 ? 0.16 : 0.09;   // roofs a little lighter
        context.fillStyle = `rgba(150,165,200,${shade})`;
        context.strokeStyle = 'rgba(170,185,220,0.28)';
        context.fill();
        context.stroke();
      }
    }
    context.restore();
  }

  /** Nearest box face hit by a ray: {point, normal} or null. */
  function hitScenery(ray){
    if(!prefs.showScenery) return null;   // hidden buildings can't be clicked
    let best = null;
    for(const box of state.scenery.boxes){
      const offset = vecSub(ray.origin, box.center);
      let enter = -Infinity, exit = Infinity, enterAxis = -1, enterSign = 1;
      let missed = false;
      for(let axis = 0; axis < 3; axis++){
        const origin = dotVec(offset, box.axes[axis]);
        const direction = dotVec(ray.direction, box.axes[axis]);
        const extent = box.extents[axis];
        if(Math.abs(direction) < 1e-8){
          if(Math.abs(origin) > extent){ missed = true; break; }
          continue;
        }
        let near = (-extent - origin) / direction, far = (extent - origin) / direction;
        let sign = -1;
        if(near > far){ [near, far] = [far, near]; sign = 1; }
        if(near > enter){ enter = near; enterAxis = axis; enterSign = sign; }
        exit = Math.min(exit, far);
        if(enter > exit){ missed = true; break; }
      }
      if(missed || enter <= 0 || enterAxis < 0) continue;
      if(!best || enter < best.distance){
        best = {distance: enter, point: vecAdd(ray.origin, vecScale(ray.direction, enter)),
          normal: vecScale(box.axes[enterAxis], enterSign)};
      }
    }
    return best;
  }

  // ------------------------------------------------------------------ time markers along the road

  function clockText(totalSeconds){
    const sign = totalSeconds < 0 ? '-' : '';
    const value = Math.abs(totalSeconds);
    const minutes = Math.floor(value / 60), seconds = value - minutes * 60;
    return `${sign}${minutes}:${seconds.toFixed(1).padStart(4, '0')}`;
  }

  function songLengthSeconds(){
    const buffer = (typeof audioTracks !== 'undefined' && audioTracks[0]?.buffer) || null;
    return buffer?.duration || 300;
  }

  /** Where the rider is at a song time, in preview coordinates. */
  function roadPointAtSeconds(songSeconds){
    return sampleTrackAtDistance(beatToPreviewRuntimeDistance(beatOf(songSeconds)) + pathStartOffsetDistance);
  }

  function drawTimeMarks(context, camera, width, height){
    if(!state.open || !trackPreviewData) return;
    // spacing grows as the camera moves out, so labels never pile up
    const step = camera.distance < 120 ? 2 : camera.distance < 300 ? 5 : camera.distance < 700 ? 10 : 20;
    context.save();
    context.font = '600 11px "Segoe UI", system-ui, sans-serif';
    context.textAlign = 'center';
    context.textBaseline = 'bottom';
    const end = songLengthSeconds();
    for(let time = 0; time <= end; time += step){
      const sample = roadPointAtSeconds(time);
      if(!sample) continue;
      const point = projectTrackPoint(vecAdd(sample.position, vecScale(up, 1.5)), camera, width, height, 2);
      if(!point || point.x < -40 || point.x > width + 40 || point.y < -20 || point.y > height + 20) continue;
      const major = time % (step * 5) === 0;
      context.fillStyle = major ? 'rgba(255,214,102,0.95)' : 'rgba(200,210,235,0.8)';
      context.fillRect(point.x - 1, point.y - 6, 2, 6);
      context.fillText(clockText(time), point.x, point.y - 7);
    }
    // the playhead: where the rider is right now
    const now = secondsOf(getCurrentPlayheadBeat());
    const rider = roadPointAtSeconds(now);
    const riderPoint = rider && projectTrackPoint(vecAdd(rider.position, vecScale(up, 4)), camera, width, height, 2);
    context.font = '700 14px "Segoe UI", system-ui, sans-serif';
    state.riderTag = riderPoint ? {x: riderPoint.x, y: riderPoint.y - 16, height: rider.position.y} : null;
    if(riderPoint){
      const label = `▶ ${clockText(now)}`;
      const labelWidth = context.measureText(label).width + 12;
      context.fillStyle = 'rgba(20,24,40,0.85)';
      context.fillRect(riderPoint.x - labelWidth / 2, riderPoint.y - 26, labelWidth, 20);
      context.fillStyle = '#7cf0a8';
      context.fillText(label, riderPoint.x, riderPoint.y - 9);
    }
    // corner readout, always visible
    context.textAlign = 'right';
    context.textBaseline = 'top';
    context.font = '700 16px "Segoe UI", system-ui, sans-serif';
    context.fillStyle = 'rgba(20,24,40,0.8)';
    context.fillRect(width - 128, 36, 118, 26);
    context.fillStyle = '#7cf0a8';
    context.fillText(clockText(now), width - 18, 40);
    // while sliding a road sign: when you will pass it
    const selected = selectedSign();
    if(state.drag?.mode === 'road' && selected){
      const pose = signPose(selected);
      const point = pose && projectTrackPoint(vecAdd(pose.centre, vecScale(up, 4)), camera, width, height, 2);
      if(point){
        context.textAlign = 'center';
        context.textBaseline = 'bottom';
        const label = `pass at ${clockText(roadSignPassSeconds(selected))}`;
        const labelWidth = context.measureText(label).width + 12;
        context.fillStyle = 'rgba(20,24,40,0.85)';
        context.fillRect(point.x - labelWidth / 2, point.y - 24, labelWidth, 22);
        context.fillStyle = '#ffd666';
        context.fillText(label, point.x, point.y - 4);
      }
    }
    context.restore();
  }

  // ------------------------------------------------------------------ drawing in the 3D view

  function drawSigns(){
    if(!lyric3dDesign?.panels?.length || !trackPreviewCanvas || !trackPreviewCtx) return;
    const width = trackPreviewCanvas.clientWidth || 1, height = trackPreviewCanvas.clientHeight || 1;
    if(!trackPreviewData && !signs().some(sign => sign.anchor === 'world')) return;
    const camera = getTrackPreviewCamera(width, height);
    const basis = getTrackPreviewCameraBasis(camera);
    const playheadBeat = getCurrentPlayheadBeat();
    const round = trackPreviewData ? getActivePreviewRound() : 0;
    const length = trackPreviewData?.totalLength || 0;

    const drawable = [];
    signs().forEach((sign, index) => {
      const pose = signPose(sign);
      if(!pose) return;
      if(sign.anchor !== 'world' && length > 0 && !state.open && Math.floor(pose.roadDistance / length) !== round) return;
      const depth = dotVec(vecSub(pose.centre, camera.position), basis.forward);
      if(depth <= 1) return;
      drawable.push({sign, index, pose, depth});
    });
    drawable.sort((a, b) => b.depth - a.depth);   // far to near
    for(const item of drawable) drawSign(trackPreviewCtx, camera, width, height, item, playheadBeat);
  }

  /** The song time a road sign is passed: where it was placed by hand, otherwise automatic
   *  (part-way through the sung line plus the mod's TimeOffset). */
  function roadSignPassSeconds(sign){
    if(Number.isFinite(sign.passAt)) return secondsOf(sign.passAt);
    return secondsOf(sign.beat) + PASS_POINT * (secondsOf(sign.beat + sign.duration) - secondsOf(sign.beat))
      + Number(prefs.modOffset || 0);
  }

  /** Road distance (preview metres) nearest to a world point, searched within ~400 m of a starting distance. */
  function nearestRoadDistance(point, aroundDistance){
    let best = aroundDistance, bestSquared = Infinity;
    for(let distance = aroundDistance - 400; distance <= aroundDistance + 400; distance += 2){
      const sample = sampleTrackAtDistance(distance);
      if(!sample) continue;
      const dx = sample.position.x - point.x, dz = sample.position.z - point.z;
      const squared = dx * dx + dz * dz;
      if(squared < bestSquared){ bestSquared = squared; best = distance; }
    }
    return best;
  }

  /** Is the sign in the world at this playhead position? (same timing as the BFS Lyric3D mod) */
  function signActiveAt(sign, beat){
    if(sign.anchor === 'world') return beat >= sign.appear && beat <= sign.disappear;
    const now = secondsOf(beat), pass = roadSignPassSeconds(sign);
    return now >= pass - Number(prefs.modLead || 8) && now <= pass + 0.6;
  }

  function drawSign(context, camera, width, height, item, playheadBeat){
    const {sign, index, pose} = item;
    const layout = layoutSign(sign);
    const halfWidth = layout.widthPixels * layout.metresPerPixel / 2;
    const halfHeight = layout.heightPixels * layout.metresPerPixel / 2;
    const corner = (horizontal, vertical) => projectTrackPoint(
      vecAdd(vecAdd(pose.centre, vecScale(pose.right, horizontal * halfWidth)), vecScale(pose.textUp, vertical * halfHeight)),
      camera, width, height, 1);
    const topLeft = corner(-1, 1), topRight = corner(1, 1), bottomLeft = corner(-1, -1), bottomRight = corner(1, -1);
    if(!topLeft || !topRight || !bottomLeft || !bottomRight) return;
    item.quad = [topLeft, topRight, bottomRight, bottomLeft];

    const selected = index === state.selected && state.open;
    const active = signActiveAt(sign, playheadBeat);
    // while riding along, only signs that are really in the world right now are shown (like in game)
    const inactiveAlpha = state.rideAlong ? 0 : state.open ? 0.4 : 0;
    const alpha = (active ? 1 : inactiveAlpha) * (sign.opacity ?? 1);
    if(alpha <= 0 && !selected) return;

    const deviceScale = trackPreviewCanvas.width / (trackPreviewCanvas.clientWidth || 1);
    context.save();
    // outline of the sign area (selection / anchor colour)
    context.beginPath();
    item.quad.forEach((point, pointIndex) => pointIndex ? context.lineTo(point.x, point.y) : context.moveTo(point.x, point.y));
    context.closePath();
    if(selected){ context.fillStyle = 'rgba(124,148,255,0.14)'; context.fill(); }
    context.lineWidth = selected ? 2 : 1;
    context.strokeStyle = selected ? '#9fb0ff' : sign.anchor === 'world' ? 'rgba(255,200,87,0.35)' : 'rgba(255,255,255,0.15)';
    context.setLineDash(sign.anchor === 'world' ? [] : [4, 4]);
    context.stroke();

    // text, drawn in the sign's own pixel space mapped onto the projected rectangle
    const scaleX = 1 / layout.widthPixels, scaleY = 1 / layout.heightPixels;
    context.setTransform(
      (topRight.x - topLeft.x) * scaleX * deviceScale, (topRight.y - topLeft.y) * scaleX * deviceScale,
      (bottomLeft.x - topLeft.x) * scaleY * deviceScale, (bottomLeft.y - topLeft.y) * scaleY * deviceScale,
      topLeft.x * deviceScale, topLeft.y * deviceScale);
    context.globalAlpha = Math.max(alpha, selected ? (state.rideAlong ? 0.25 : 0.75) : 0);
    context.textBaseline = 'middle';
    context.textAlign = 'left';

    // the reveal follows the singing unless the sign has its own reveal window
    const revealFrom = Number.isFinite(sign.revealStart) ? sign.revealStart : sign.beat;
    const revealTo = Number.isFinite(sign.revealEnd) ? sign.revealEnd : sign.beat + sign.duration;
    const sungFraction = Math.max(0, Math.min(1, (secondsOf(playheadBeat) - secondsOf(revealFrom)) / Math.max(0.2, secondsOf(revealTo) - secondsOf(revealFrom))));
    const totalCharacters = sign.lines.reduce((sum, line) => sum + line.text.length, 0);
    const sungCharacters = Math.round(sungFraction * totalCharacters);
    let characterIndex = 0, lineTop = 0;
    for(const entry of layout.lines){
      const {line} = entry;
      context.font = cssFont(sign, line, entry.pixels);
      context.letterSpacing = `${sign.spacing || 0}px`;
      let x = (layout.widthPixels - entry.width) / 2;
      const y = lineTop + entry.height / 2;
      let fill = line.color;
      if(sign.gradient){
        const gradient = context.createLinearGradient(0, lineTop, 0, lineTop + entry.height);
        gradient.addColorStop(0, sign.gradient[0]); gradient.addColorStop(1, sign.gradient[1]);
        fill = gradient;
      }
      for(const character of line.text){
        const visible = sign.reveal !== 'typewriter' || characterIndex < Math.max(1, sungCharacters) || !active;
        const dimmed = sign.reveal === 'karaoke' && active && characterIndex >= sungCharacters;
        if(visible){
          context.save();
          context.globalAlpha *= dimmed ? KARAOKE_DIM_ALPHA : 1;
          if(sign.outline > 0){
            context.lineWidth = sign.outline * 40;
            context.strokeStyle = 'rgba(0,0,0,0.8)';
            context.strokeText(character, x, y);
          }
          context.fillStyle = fill;
          context.fillText(character, x, y);
          context.restore();
        }
        x += context.measureText(character).width + (sign.spacing || 0);
        characterIndex++;
      }
      lineTop += entry.height;
    }
    context.restore();
  }

  // ------------------------------------------------------------------ ride along: chase camera behind the rider

  function lerpAngle(from, to, amount){
    let difference = to - from;
    while(difference > Math.PI) difference -= Math.PI * 2;
    while(difference < -Math.PI) difference += Math.PI * 2;
    return from + difference * amount;
  }

  /** Move the 3D camera behind the rider at the playhead (called before every preview frame). */
  function updateRideCamera(){
    if(!state.open || !state.rideAlong || !trackPreviewData) return;
    const riderDistance = beatToPreviewRuntimeDistance(getCurrentPlayheadBeat()) + pathStartOffsetDistance;
    const rider = sampleTrackAtDistance(riderDistance);
    const ahead = sampleTrackAtDistance(riderDistance + 25);
    if(!rider) return;
    const heading = flat(ahead ? vecSub(ahead.position, rider.position) : rider.direction);
    // look at a point a little ahead of the rider; the camera sits behind and above (like the game's chase cam)
    const lookAt = vecAdd(vecAdd(rider.position, vecScale(heading, 18)), vecScale(up, 3));
    const smoothing = isPlaying ? 0.35 : 1;
    trackPreviewCamera.target = lerpVec(trackPreviewCamera.target, lookAt, smoothing);
    trackPreviewCamera.yaw = lerpAngle(trackPreviewCamera.yaw, Math.atan2(-heading.x, -heading.z), isPlaying ? 0.25 : 1);
    trackPreviewCamera.pitch = 0.14;
    trackPreviewCamera.distance = 30;
  }

  function setRideAlong(enabled){
    state.rideAlong = enabled;
    const toggle = panel?.querySelector('[data-ride]');
    if(toggle) toggle.checked = enabled;
    renderTrackPreview(true);
  }

  /** Move the playhead to a song time (seconds) and redraw the 3D view. */
  function seekToSeconds(songSeconds){
    const clamped = Math.max(0, Math.min(songLengthSeconds(), songSeconds));
    seekTimelineToBeat(beatOf(clamped), false);
    renderTrackPreview(true);
    updateScrubber(true);
  }

  /** Keep the scrubber bar and its time readout in step with the playhead (skipped while it is being dragged). */
  function updateScrubber(force){
    const bar = panel?.querySelector('[data-scrub]');
    if(!bar) return;
    const now = secondsOf(getCurrentPlayheadBeat());
    const length = Math.round(songLengthSeconds() * 20) / 20;
    if(String(bar.max) !== String(length)) bar.max = length;
    if(force || document.activeElement !== bar) bar.value = now;
    const readout = panel.querySelector('[data-readout="scrubTime"]');
    if(readout) readout.textContent = clockText(now);
  }

  function updatePlayButton(){
    syncPlacingHighlight();
    updateScrubber(false);
    const button = panel?.querySelector('[data-action="play"]');
    if(!button) return;
    const label = isPlaying ? say('pause') : say('play');
    if(button.textContent !== label) button.textContent = label;
  }

  // ------------------------------------------------------------------ picking + world placement with the mouse

  function canvasPoint(event){
    const rect = getEditorRect(trackPreviewCanvas);
    return {x: editorClientX(event) - rect.left, y: editorClientY(event) - rect.top};
  }

  function rayFromCanvas(point){
    const width = trackPreviewCanvas.clientWidth || 1, height = trackPreviewCanvas.clientHeight || 1;
    const camera = getTrackPreviewCamera(width, height);
    const basis = getTrackPreviewCameraBasis(camera);
    const focal = Math.min(width, height) * 0.95;   // must match projectTrackPoint
    const direction = normalizeVec(vecAdd(vecAdd(basis.forward,
      vecScale(basis.right, (point.x - width * 0.5) / focal)),
      vecScale(basis.up, (height * 0.52 - point.y) / focal)), basis.forward);
    return {origin: camera.position, direction, camera};
  }

  function hitHorizontalPlane(ray, planeHeight){
    if(Math.abs(ray.direction.y) < 1e-4) return null;
    const along = (planeHeight - ray.origin.y) / ray.direction.y;
    return along > 0 ? vecAdd(ray.origin, vecScale(ray.direction, along)) : null;
  }

  function nearestRoadHeight(position){
    const samples = trackPreviewData?.samples;
    if(!samples?.length) return position.y;
    let best = samples[0], bestDistance = Infinity;
    for(const sample of samples){
      const dx = sample.position.x - position.x, dz = sample.position.z - position.z;
      const distance = dx * dx + dz * dz;
      if(distance < bestDistance){ bestDistance = distance; best = sample; }
    }
    return best.position.y;
  }

  function insideQuad(point, quad){
    let inside = false;
    for(let i = 0, j = quad.length - 1; i < quad.length; j = i++){
      const a = quad[i], b = quad[j];
      if(((a.y > point.y) !== (b.y > point.y)) && point.x < (b.x - a.x) * (point.y - a.y) / (b.y - a.y) + a.x) inside = !inside;
    }
    return inside;
  }

  function signAtCanvasPoint(point){
    const width = trackPreviewCanvas.clientWidth || 1, height = trackPreviewCanvas.clientHeight || 1;
    const camera = getTrackPreviewCamera(width, height);
    let found = -1, nearestDepth = Infinity;
    signs().forEach((sign, index) => {
      const pose = signPose(sign);
      if(!pose) return;
      const layout = layoutSign(sign);
      const halfWidth = layout.widthPixels * layout.metresPerPixel / 2, halfHeight = layout.heightPixels * layout.metresPerPixel / 2;
      const quad = [[-1, 1], [1, 1], [1, -1], [-1, -1]].map(([horizontal, vertical]) => projectTrackPoint(
        vecAdd(vecAdd(pose.centre, vecScale(pose.right, horizontal * halfWidth)), vecScale(pose.textUp, vertical * halfHeight)), camera, width, height, 1));
      if(quad.some(corner => !corner) || !insideQuad(point, quad)) return;
      const depth = quad.reduce((sum, corner) => sum + corner.z, 0) / 4;
      if(depth < nearestDepth){ nearestDepth = depth; found = index; }
    });
    return found;
  }

  function onCanvasMouseDown(event){
    if(!state.open || event.button !== 0) return;
    const point = canvasPoint(event);
    if(state.placing){
      const ray = rayFromCanvas(point);
      const sign = makeSign({beat: cursorBeat, anchor: 'world'});
      const wall = hitScenery(ray);
      if(wall && Math.abs(wall.normal.y) < 0.5){
        // stick it onto the wall, readable from the street side
        sign.position = vecAdd(wall.point, vecScale(wall.normal, 0.4));
        sign.yaw = forwardToYaw(flat(vecScale(wall.normal, -1)));
      } else {
        const ground = wall ? wall.point : hitHorizontalPlane(ray, trackPreviewCamera.target.y);
        if(!ground) return;
        const baseHeight = wall ? ground.y : nearestRoadHeight(ground);
        sign.position = {x: ground.x, y: baseHeight + 6, z: ground.z};
        sign.yaw = forwardToYaw(flat(vecSub(ground, ray.origin)));   // face back toward the camera
      }
      sign.yaw = Math.round(sign.yaw);
      checkpoint('place 3D lyric');
      lyric3dDesign.panels.push(sign);
      sortSigns(sign);
      state.placing = false;
      setStatus('');
      refresh();
      swallow(event);
      return;
    }
    const tag = state.riderTag;
    if(tag && Math.abs(point.x - tag.x) < 40 && Math.abs(point.y - tag.y) < 16){
      if(isPlaying) pausePlayback();
      if(state.rideAlong) setRideAlong(false);   // the camera stays put while you drag the rider
      state.drag = {mode: 'rider', height: tag.height,
        roadDistance: beatToPreviewRuntimeDistance(getCurrentPlayheadBeat()) + pathStartOffsetDistance};
      swallow(event);
      return;
    }
    const index = signAtCanvasPoint(point);
    if(index < 0){
      if(state.rideAlong) setRideAlong(false);   // the user wants to look around
      return;
    }
    selectSign(index);
    const sign = selectedSign();
    if(sign.anchor !== 'world'){
      const pose = signPose(sign);
      if(pose){
        checkpoint('slide 3D lyric along the road');
        state.drag = {mode: 'road', start: point, startRoadDistance: pose.roadDistance,
          roadHeight: pose.centre.y - (sign.side === 0 ? sign.height + 3 : sign.height)};
      }
    } else {
      checkpoint('move 3D lyric');
      const ray = rayFromCanvas(point);
      const grab = hitHorizontalPlane(ray, sign.position.y);
      state.drag = {start: point, startPosition: {...sign.position}, startYaw: sign.yaw || 0,
        grabOffset: grab ? vecSub(sign.position, grab) : {x: 0, y: 0, z: 0},
        mode: event.altKey ? 'turn' : event.shiftKey ? 'height' : 'move'};
    }
    swallow(event);
  }

  function onWindowMouseMove(event){
    if(!state.drag) return;
    if(state.drag.mode === 'rider'){
      // drag the rider along the road: the road spot under the mouse becomes the playhead
      const ground = hitHorizontalPlane(rayFromCanvas(canvasPoint(event)), state.drag.height);
      if(ground){
        state.drag.roadDistance = nearestRoadDistance(ground, state.drag.roadDistance);
        seekToSeconds(secondsOf(previewRuntimeDistanceToBeat(state.drag.roadDistance - pathStartOffsetDistance)));
      }
      swallow(event);
      return;
    }
    const sign = selectedSign();
    if(!sign){ state.drag = null; return; }
    const point = canvasPoint(event);
    const drag = state.drag;
    if(drag.mode === 'road'){
      // slide along the road: the road spot under the mouse becomes the new pass time
      const ground = hitHorizontalPlane(rayFromCanvas(point), drag.roadHeight);
      if(ground){
        const targetDistance = nearestRoadDistance(ground, drag.startRoadDistance);
        const targetSeconds = secondsOf(previewRuntimeDistanceToBeat(targetDistance - pathStartOffsetDistance));
        sign.passAt = beatOf(Math.max(0, Math.round(targetSeconds * 20) / 20));
      }
    } else if(sign.anchor !== 'world'){
      state.drag = null; return;
    } else if(drag.mode === 'turn'){
      sign.yaw = Math.round((drag.startYaw + (point.x - drag.start.x) * 0.5) * 10) / 10;
    } else if(drag.mode === 'height'){
      const metresPerPixel = Math.max(0.02, trackPreviewCamera.distance / Math.max(1, trackPreviewCanvas.clientHeight)) * 1.1;
      sign.position.y = drag.startPosition.y + (drag.start.y - point.y) * metresPerPixel;
    } else {
      const ground = hitHorizontalPlane(rayFromCanvas(point), drag.startPosition.y);
      if(ground){ sign.position.x = ground.x + drag.grabOffset.x; sign.position.z = ground.z + drag.grabOffset.z; }
    }
    renderTrackPreview(true);
    renderFields();
    swallow(event);
  }

  function onWindowMouseUp(event){
    if(!state.drag) return;
    state.drag = null;
    swallow(event);
  }

  // keep the editor's own orbit / seek handlers from also reacting
  function swallow(event){ event.preventDefault(); event.stopImmediatePropagation(); }

  // ------------------------------------------------------------------ data helpers

  function makeSign(overrides = {}){
    const base = {
      beat: cursorBeat, duration: 2,
      lines: [{text: 'NEW LYRIC', size: 1.25, color: lyricSettings?.color || '#ffffff', bold: true, italic: false}],
      side: 1, distance: 15, height: 7, turn: 60, scale: 1, opacity: 0.95, outline: 0.15, spacing: 4,
      reveal: 'karaoke', enter: 'rise', exit: 'fade', pulse: true,
    };
    const sign = {...base, ...overrides};
    if(sign.anchor === 'world'){
      sign.appear = sign.appear ?? sign.beat - 8;
      sign.disappear = sign.disappear ?? sign.beat + sign.duration + 4;
      sign.yaw = sign.yaw ?? 0; sign.tilt = sign.tilt ?? 0;
    }
    return sign;
  }

  function stackLines(text, color){
    const words = text.split(/\s+/).filter(Boolean);
    if(words.length < 3 || text.length < 12) return [{text, size: 1.25, color, bold: true, italic: false}];
    const split = Math.floor(words.length / 2);
    const first = words.slice(0, split).join(' '), second = words.slice(split).join(' ');
    const firstBigger = first.length <= second.length;
    return [
      {text: first, size: firstBigger ? 1.35 : 0.85, color, bold: true, italic: false},
      {text: second, size: firstBigger ? 0.85 : 1.35, color, bold: true, italic: false},
    ];
  }

  function generateFromLyrics(){
    const visible = (typeof lyrics !== 'undefined' ? lyrics : []).filter(line => !isLyricRowHidden(line.row) && line.text.trim())
      .sort((a, b) => a.beat - b.beat);
    if(!visible.length) return;
    const existingRoad = signs().filter(sign => sign.anchor !== 'world');
    if(existingRoad.length && !window.confirm(say('replaceConfirm'))) return;
    checkpoint('generate 3D lyrics');
    const kept = signs().filter(sign => sign.anchor === 'world');
    let side = 1;
    const generated = visible.map(line => {
      const color = line.color || lyricSettings?.color || '#ffffff';
      const sign = makeSign({beat: line.beat, duration: line.duration, side, lines: stackLines(line.text.toUpperCase(), color)});
      side = -side;
      return sign;
    });
    lyric3dDesign.panels = [...kept, ...generated];
    sortSigns();
    state.selected = signs().length ? 0 : -1;
    setStatus(say('generated', generated.length));
    refresh();
  }

  function sortSigns(keepSelected){
    const selected = keepSelected || selectedSign();
    lyric3dDesign.panels.sort((a, b) => a.beat - b.beat);
    state.selected = selected ? signs().indexOf(selected) : -1;
  }

  /** Record an undo step once per editing gesture. */
  function checkpoint(description){
    if(!state.undoArmed) return;
    pushUndo(description);
    state.undoArmed = false;
  }
  function rearmUndo(){ state.undoArmed = true; }

  // ------------------------------------------------------------------ panel UI

  let panel, listElement, fieldsElement, statusElement;

  function buildPanel(){
    panel = document.createElement('aside');
    panel.id = 'lyric3dPanel';
    panel.setAttribute('aria-label', say('title'));
    panel.innerHTML = `
      <header><h2>${say('title')}</h2><button type="button" data-action="close">${say('close')}</button></header>
      <p class="l3d-hint">${say('hint')}</p>
      <div class="l3d-ride">
        <button type="button" data-action="play">${say('play')}</button>
        <div class="l3d-scrub">
          <button type="button" data-step="-5" title="-5 s">⏪</button><button type="button" data-step="-1" title="-1 s">◀</button>
          <input type="range" data-scrub min="0" max="300" step="0.05" value="0" aria-label="${say('scrub')}">
          <button type="button" data-step="1" title="+1 s">▶</button><button type="button" data-step="5" title="+5 s">⏩</button>
          <span class="l3d-scrub-time" data-readout="scrubTime">0:00.0</span>
        </div>
        <p class="l3d-hint">${say('riderHelp')}</p>
        <label class="l3d-check"><input type="checkbox" data-ride> ${say('rideAlong')}</label>
        <label class="l3d-check"><input type="checkbox" data-scenery> ${say('showScenery')}</label>
      </div>
      <p class="l3d-hint">${say('rideHelp')}</p>
      <div class="l3d-actions">
        <button type="button" data-action="generate">${say('generate')}</button>
        <button type="button" data-action="add-road">${say('addRoad')}</button>
        <button type="button" data-action="add-world">${say('addWorld')}</button>
      </div>
      <p class="l3d-status" role="status" aria-live="polite"></p>
      <ol class="l3d-list"></ol>
      <div class="l3d-fields"></div>
      <details class="l3d-preview-settings"><summary>${say('sectionPreview')}</summary>
        <p class="l3d-hint">${say('previewHelp')}</p>
        <label>${say('modScale')} <input type="number" step="0.05" min="0.1" max="3" data-pref="modScale"></label>
        <label>${say('modOffset')} <input type="number" step="0.5" min="-10" max="20" data-pref="modOffset"></label>
        <label>${say('modLead')} <input type="number" step="0.5" min="1" max="20" data-pref="modLead"></label>
      </details>
      <datalist id="l3dFonts">${COMMON_FONTS.map(font => `<option value="${font}">`).join('')}</datalist>`;
    document.body.appendChild(panel);
    listElement = panel.querySelector('.l3d-list');
    fieldsElement = panel.querySelector('.l3d-fields');
    statusElement = panel.querySelector('.l3d-status');

    panel.addEventListener('click', onPanelClick);
    panel.addEventListener('input', onPanelInput);
    panel.addEventListener('change', rearmUndo);
    panel.addEventListener('keydown', event => {
      event.stopPropagation();   // typing here must not trigger editor shortcuts
      if(event.key === 'Escape'){ if(state.placing){ state.placing = false; setStatus(''); } else closeDesigner(); }
    });
    panel.querySelectorAll('[data-pref]').forEach(input => { input.value = prefs[input.dataset.pref]; });
    panel.querySelector('[data-scenery]').checked = prefs.showScenery !== false;
  }

  function setStatus(message){
    if(statusElement) statusElement.textContent = message;
    syncPlacingHighlight();
  }

  /** Light up "Place in world" while the next click in the 3D view will place a sign. */
  function syncPlacingHighlight(){
    const placing = state.open && state.placing;
    document.documentElement.classList.toggle('l3d-placing', placing);
    const button = panel?.querySelector('[data-action="add-world"]');
    if(button && button.getAttribute('aria-pressed') !== String(placing)) button.setAttribute('aria-pressed', String(placing));
  }

  function timeLabel(beat){
    const seconds = Math.max(0, secondsOf(beat));
    return `${Math.floor(seconds / 60)}:${(seconds % 60).toFixed(1).padStart(4, '0')}`;
  }

  function renderList(){
    if(!listElement) return;
    listElement.replaceChildren();
    if(!signs().length){
      const empty = document.createElement('li');
      empty.className = 'l3d-empty';
      empty.textContent = say('none');
      listElement.appendChild(empty);
      return;
    }
    signs().forEach((sign, index) => {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.select = index;
      button.className = index === state.selected ? 'selected' : '';
      button.setAttribute('aria-pressed', String(index === state.selected));
      button.innerHTML = `<span class="l3d-time">${timeLabel(sign.beat)}</span><span class="l3d-kind">${sign.anchor === 'world' ? '📍' : '🛣'}</span>`;
      const label = document.createElement('span');
      label.className = 'l3d-text';
      label.textContent = sign.lines.map(line => line.text).join(' / ');
      button.appendChild(label);
      item.appendChild(button);
      listElement.appendChild(item);
    });
    listElement.querySelector('.selected')?.scrollIntoView({block: 'nearest'});
  }

  const number = (field, value, attributes = '') =>
    `<input type="number" data-field="${field}" value="${Number(value).toFixed(2).replace(/\.?0+$/, '')}" ${attributes}>`;
  const select = (field, value, options) =>
    `<select data-field="${field}">${options.map(([optionValue, label]) => `<option value="${optionValue}"${String(optionValue) === String(value) ? ' selected' : ''}>${label}</option>`).join('')}</select>`;
  const escapeAttribute = text => String(text).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');

  function renderFields(){
    if(!fieldsElement) return;
    const sign = selectedSign();
    if(!sign){ fieldsElement.innerHTML = ''; return; }
    const world = sign.anchor === 'world';
    const seconds = beat => (Math.round(secondsOf(beat) * 100) / 100);
    fieldsElement.innerHTML = `
      <div class="l3d-buttons">
        <button type="button" data-action="driver">${say('driverView')}</button>
        <button type="button" data-action="jump">${say('jump')}</button>
        <button type="button" data-action="duplicate">${say('duplicate')}</button>
        <button type="button" data-action="delete" class="l3d-danger">${say('remove')}</button>
      </div>
      <fieldset><legend>${say('sectionText')}</legend>
        ${sign.lines.map((line, index) => `
          <div class="l3d-line">
            <input type="text" data-line="${index}" data-key="text" value="${escapeAttribute(line.text)}" aria-label="${say('sectionText')} ${index + 1}">
            <input type="number" data-line="${index}" data-key="size" value="${line.size}" step="0.05" min="0.2" max="4" title="${say('scale')}" aria-label="${say('scale')}">
            <input type="color" data-line="${index}" data-key="color" value="${line.color}" aria-label="Colour">
            <label title="Bold"><input type="checkbox" data-line="${index}" data-key="bold" ${line.bold ? 'checked' : ''}>B</label>
            <label title="Italic"><input type="checkbox" data-line="${index}" data-key="italic" ${line.italic ? 'checked' : ''}><i>I</i></label>
            <button type="button" data-action="remove-line" data-line="${index}" aria-label="Remove line" ${sign.lines.length < 2 ? 'disabled' : ''}>✕</button>
          </div>`).join('')}
        <button type="button" data-action="add-line">${say('addLine')}</button>
      </fieldset>
      <fieldset><legend>${say('sectionTiming')}</legend>
        <label>${say('sungAt')} <input type="number" data-field="sungSeconds" value="${seconds(sign.beat)}" step="0.05"></label>
        <label>${say('sungUntil')} <input type="number" data-field="sungEndSeconds" value="${seconds(sign.beat + sign.duration)}" step="0.05"></label>
        <p class="l3d-hint" data-readout="sungLength">${say('sungLength', Math.round((secondsOf(sign.beat + sign.duration) - secondsOf(sign.beat)) * 100) / 100)}</p>
        ${sign.reveal !== 'none' ? `
        <label>${say('revealStart', say(sign.reveal))} <input type="number" data-field="revealStartSeconds" value="${Number.isFinite(sign.revealStart) ? seconds(sign.revealStart) : ''}" placeholder="${seconds(sign.beat)}" step="0.05"></label>
        <label>${say('revealEnd', say(sign.reveal))} <input type="number" data-field="revealEndSeconds" value="${Number.isFinite(sign.revealEnd) ? seconds(sign.revealEnd) : ''}" placeholder="${seconds(sign.beat + sign.duration)}" step="0.05"></label>
        <p class="l3d-hint">${say('revealHelp', say(sign.reveal).toLowerCase())}</p>` : ''}
        ${world ? `
        <label>${say('appear')} <input type="number" data-field="appearSeconds" value="${seconds(sign.appear)}" step="0.1"></label>
        <label>${say('disappear')} <input type="number" data-field="disappearSeconds" value="${seconds(sign.disappear)}" step="0.1"></label>` : ''}
      </fieldset>
      <fieldset><legend>${say('sectionPlace')}</legend>
        <label>${say('anchor')} ${select('anchor', world ? 'world' : 'road', [['road', say('anchorRoad')], ['world', say('anchorWorld')]])}</label>
        ${world ? `
          <p class="l3d-hint">${say('worldHelp')}</p>
          <div class="l3d-xyz"><label>X ${number('x', sign.position.x, 'step="0.5"')}</label><label>Y ${number('y', sign.position.y, 'step="0.5"')}</label><label>Z ${number('z', sign.position.z, 'step="0.5"')}</label></div>
          <label>${say('facing')} ${number('yaw', sign.yaw, 'step="1"')}</label>
          <label>${say('tilt')} ${number('tilt', sign.tilt, 'step="1" min="-89" max="89"')}</label>
          <div class="l3d-buttons"><button type="button" data-action="face-camera">${say('faceCamera')}</button><button type="button" data-action="move-here">${say('moveHere')}</button></div>`
        : `
          <label>${say('side')} ${select('side', sign.side, [[-1, say('left')], [1, say('right')], [0, say('over')]])}</label>
          <label>${say('distance')} ${number('distance', sign.distance, 'step="0.5" min="2" max="80"')}</label>
          <label>${say('height')} ${number('height', sign.height, 'step="0.5" min="0" max="40"')}</label>
          <label>${say('turn')} ${number('turn', sign.turn, 'step="5" min="0" max="90"')}</label>
          <label>${say('passAt')} <input type="number" data-field="passAtSeconds" value="${Number.isFinite(sign.passAt) ? seconds(sign.passAt) : ''}" placeholder="auto ${Math.round(roadSignPassSeconds({...sign, passAt: undefined}) * 100) / 100}" step="0.05" min="0"></label>
          <p class="l3d-hint">${say('roadHelp')}</p>`}
      </fieldset>
      <fieldset><legend>${say('sectionLook')}</legend>
        <label>${say('font')} <input type="text" data-field="font" list="l3dFonts" value="${escapeAttribute(sign.font || '')}" placeholder="(game font)"></label>
        <label>${say('scale')} ${number('scale', sign.scale, 'step="0.05" min="0.1" max="5"')}</label>
        <label>${say('opacity')} ${number('opacity', sign.opacity, 'step="0.05" min="0" max="1"')}</label>
        <label>${say('outline')} ${number('outline', sign.outline, 'step="0.05" min="0" max="0.5"')}</label>
        <label>${say('spacing')} ${number('spacing', sign.spacing, 'step="1" min="-20" max="60"')}</label>
        <label class="l3d-check"><input type="checkbox" data-field="gradientOn" ${sign.gradient ? 'checked' : ''}> ${say('gradient')}</label>
        ${sign.gradient ? `<div class="l3d-gradient"><input type="color" data-field="gradientTop" value="${sign.gradient[0]}" aria-label="Top colour"><input type="color" data-field="gradientBottom" value="${sign.gradient[1]}" aria-label="Bottom colour"></div>` : ''}
        <label>${say('reveal')} ${select('reveal', sign.reveal, [['none', 'none'], ['karaoke', 'karaoke'], ['typewriter', 'typewriter']])}</label>
        <label>${say('enter')} ${select('enter', sign.enter, LYRIC3D_ENTERS.map(value => [value, value]))}</label>
        <label>${say('exit')} ${select('exit', sign.exit, LYRIC3D_EXITS.map(value => [value, value]))}</label>
        <label class="l3d-check"><input type="checkbox" data-field="pulse" ${sign.pulse ? 'checked' : ''}> ${say('pulse')}</label>
        <button type="button" data-action="copy-look">${say('copyLook')}</button>
      </fieldset>`;
  }

  function onPanelInput(event){
    const target = event.target;
    if(target.dataset.scrub !== undefined){
      if(isPlaying) pausePlayback();   // scrubbing pauses; press Play to carry on from the new spot
      seekToSeconds(Number(target.value));
      return;
    }
    if(target.dataset.ride !== undefined){ setRideAlong(target.checked); return; }
    if(target.dataset.scenery !== undefined){
      prefs.showScenery = target.checked;
      savePrefs();
      renderTrackPreview(true);
      return;
    }
    if(target.dataset.pref){
      prefs[target.dataset.pref] = Number(target.value);
      savePrefs();
      renderTrackPreview(true);
      return;
    }
    const sign = selectedSign();
    if(!sign) return;
    checkpoint('edit 3D lyric');

    if(target.dataset.line !== undefined && target.dataset.key){
      const line = sign.lines[Number(target.dataset.line)];
      const key = target.dataset.key;
      if(key === 'text') line.text = target.value;
      else if(key === 'size') line.size = clampNumber(target.value, 0.2, 4, line.size);
      else if(key === 'color') line.color = target.value;
      else line[key] = target.checked;
      renderList();
      renderTrackPreview(true);
      return;
    }

    const field = target.dataset.field;
    const value = target.type === 'checkbox' ? target.checked : target.value;
    switch(field){
      case 'sungSeconds': {
        const length = secondsOf(sign.beat + sign.duration) - secondsOf(sign.beat);
        const shift = beatOf(Number(value)) - sign.beat;
        sign.beat += shift;
        if(sign.anchor === 'world'){ sign.appear += shift; sign.disappear += shift; }
        if(Number.isFinite(sign.revealStart)){ sign.revealStart += shift; sign.revealEnd += shift; }
        sign.duration = Math.max(0.05, beatOf(Number(value) + length) - sign.beat);
        break;
      }
      case 'revealStartSeconds': case 'revealEndSeconds': {
        // each box stands alone: emptying one (e.g. to retype it) leaves the other untouched
        const key = field === 'revealStartSeconds' ? 'revealStart' : 'revealEnd';
        const raw = String(value).trim();
        if(raw === '' || !Number.isFinite(Number(raw))) delete sign[key];
        else sign[key] = beatOf(Number(raw));
        break;
      }
      case 'durationSeconds': sign.duration = Math.max(0.05, beatOf(secondsOf(sign.beat) + Math.max(0.05, Number(value))) - sign.beat); break;
      case 'sungEndSeconds': sign.duration = Math.max(beatOf(secondsOf(sign.beat) + 0.05) - sign.beat, beatOf(Number(value)) - sign.beat); break;
      case 'appearSeconds': sign.appear = beatOf(Number(value)); break;
      case 'disappearSeconds': sign.disappear = Math.max(sign.appear + 0.05, beatOf(Number(value))); break;
      case 'anchor': convertAnchor(sign, value); renderFields(); break;
      case 'side': sign.side = Number(value); break;
      case 'passAtSeconds':
        if(String(value).trim() === '') delete sign.passAt;
        else sign.passAt = beatOf(Math.max(0, Number(value)));
        break;
      case 'x': case 'y': case 'z': sign.position[field] = Number(value); break;
      case 'gradientOn':
        if(value) sign.gradient = [sign.lines[0]?.color || '#ffffff', '#ff4fa3'];
        else delete sign.gradient;
        renderFields();
        break;
      case 'gradientTop': sign.gradient[0] = value; break;
      case 'gradientBottom': sign.gradient[1] = value; break;
      case 'font': if(String(value).trim()) sign.font = String(value).trim(); else delete sign.font; break;
      case 'reveal': sign.reveal = value; renderFields(); break;   // shows/hides the reveal timing fields
      case 'enter': case 'exit': sign[field] = value; break;
      case 'pulse': sign.pulse = Boolean(value); break;
      default:
        if(['distance', 'height', 'turn', 'scale', 'opacity', 'outline', 'spacing', 'yaw', 'tilt'].includes(field)) sign[field] = Number(value);
    }
    if(field === 'sungSeconds'){ sortSigns(sign); renderList(); }
    if(field === 'sungSeconds' || field === 'sungEndSeconds') updateTimingReadouts(sign, field);
    renderTrackPreview(true);
  }

  /** Switching anchors keeps the sign where it currently stands. */
  /** Keep "Sung until" and the duration note in step while typing in the other timing box (no full redraw,
   *  which would move the cursor out of the box being typed in). */
  function updateTimingReadouts(sign, editedField){
    const end = panel?.querySelector('[data-field="sungEndSeconds"]');
    if(end && editedField !== 'sungEndSeconds') end.value = Math.round(secondsOf(sign.beat + sign.duration) * 100) / 100;
    const note = panel?.querySelector('[data-readout="sungLength"]');
    if(note) note.textContent = say('sungLength', Math.round((secondsOf(sign.beat + sign.duration) - secondsOf(sign.beat)) * 100) / 100);
  }

  function convertAnchor(sign, anchor){
    if(anchor === 'world' && sign.anchor !== 'world'){
      const pose = signPose(sign);
      sign.anchor = 'world';
      sign.position = pose ? {...pose.centre} : {...trackPreviewCamera.target};
      sign.yaw = pose ? Math.round(forwardToYaw(pose.forward)) : 0;
      sign.tilt = 0;
      sign.appear = sign.beat - 8;
      sign.disappear = sign.beat + sign.duration + 4;
    } else if(anchor === 'road'){
      delete sign.anchor; delete sign.position; delete sign.yaw; delete sign.tilt; delete sign.appear; delete sign.disappear;
      delete sign.passAt;
    }
  }

  function onPanelClick(event){
    const stepButton = event.target.closest?.('[data-step]');
    if(stepButton){
      seekToSeconds(secondsOf(getCurrentPlayheadBeat()) + Number(stepButton.dataset.step));
      return;
    }
    const selectButton = event.target.closest('[data-select]');
    if(selectButton){ selectSign(Number(selectButton.dataset.select)); return; }
    const button = event.target.closest('[data-action]');
    if(!button) return;
    const sign = selectedSign();
    switch(button.dataset.action){
      case 'close': closeDesigner(); break;
      case 'play':
        if(!isPlaying && !state.rideAlong) setRideAlong(true);
        togglePlay();
        setTimeout(updatePlayButton, 50);
        break;
      case 'generate': generateFromLyrics(); break;
      case 'add-road': {
        rearmUndo(); checkpoint('add 3D lyric');
        const added = makeSign({beat: cursorBeat});
        lyric3dDesign.panels.push(added); sortSigns(added); refresh();
        break;
      }
      case 'add-world':
        if(!trackPreviewData){ setStatus(say('needScene')); break; }
        state.placing = true; rearmUndo(); setStatus(say('placing'));
        break;
      case 'duplicate': {
        if(!sign) break;
        rearmUndo(); checkpoint('duplicate 3D lyric');
        const copy = JSON.parse(JSON.stringify(sign));
        const shift = Math.max(1, sign.duration);
        copy.beat += shift;
        if(copy.anchor === 'world'){ copy.appear += shift; copy.disappear += shift; copy.position.x += 3; }
        lyric3dDesign.panels.push(copy); sortSigns(copy); refresh();
        break;
      }
      case 'delete':
        if(!sign) break;
        rearmUndo(); checkpoint('delete 3D lyric');
        lyric3dDesign.panels.splice(state.selected, 1);
        state.selected = Math.min(state.selected, signs().length - 1);
        refresh();
        break;
      case 'add-line':
        if(!sign) break;
        rearmUndo(); checkpoint('edit 3D lyric');
        sign.lines.push({text: 'LINE', size: 0.85, color: sign.lines.at(-1)?.color || '#ffffff', bold: true, italic: false});
        refresh();
        break;
      case 'remove-line':
        if(!sign || sign.lines.length < 2) break;
        rearmUndo(); checkpoint('edit 3D lyric');
        sign.lines.splice(Number(button.dataset.line), 1);
        refresh();
        break;
      case 'copy-look': {
        if(!sign) break;
        rearmUndo(); checkpoint('copy 3D lyric look');
        const look = ['font', 'scale', 'opacity', 'outline', 'spacing', 'gradient', 'reveal', 'enter', 'exit', 'pulse'];
        signs().forEach(other => {
          if(other === sign) return;
          look.forEach(key => { if(sign[key] === undefined) delete other[key]; else other[key] = JSON.parse(JSON.stringify(sign[key])); });
        });
        refresh();
        break;
      }
      case 'face-camera': {
        if(!sign || sign.anchor !== 'world') break;
        rearmUndo(); checkpoint('turn 3D lyric');
        const camera = getTrackPreviewCamera(trackPreviewCanvas.clientWidth || 1, trackPreviewCanvas.clientHeight || 1);
        sign.yaw = Math.round(forwardToYaw(flat(vecSub(sign.position, camera.position))));
        refresh();
        break;
      }
      case 'move-here':
        if(!sign || sign.anchor !== 'world') break;
        rearmUndo(); checkpoint('move 3D lyric');
        sign.position = {x: trackPreviewCamera.target.x, y: trackPreviewCamera.target.y + 6, z: trackPreviewCamera.target.z};
        refresh();
        break;
      case 'driver': if(sign) driverView(sign); break;
      case 'jump':
        if(sign){
          seekTimelineToBeat(sign.anchor === 'world' ? sign.appear : sign.beat - 4, false);
          renderTrackPreview(true);
        }
        break;
    }
  }

  function selectSign(index){
    state.selected = index;
    rearmUndo();
    renderList();
    renderFields();
    renderTrackPreview(true);
  }

  function refresh(){
    renderList();
    renderFields();
    renderTrackPreview(true);
    if(typeof render === 'function') render();
  }

  /** Put the 3D camera roughly where the rider is a moment before reaching the sign. */
  function driverView(sign){
    const pose = signPose(sign);
    if(!pose) return;
    trackPreviewAutoFollow = false;
    const followToggle = document.getElementById('trackPreviewAutoFollow');
    if(followToggle) followToggle.checked = false;
    let target, viewDirection;
    if(sign.anchor !== 'world' && trackPreviewData){
      // stand on the road ~2.5 s before the sign, looking down the road at it
      const sample = sampleTrackAtDistance(pose.roadDistance);
      viewDirection = sample ? flat(sample.direction) : pose.forward;
      target = vecAdd(sample ? sample.position : pose.centre, vecScale(up, 3));
      trackPreviewCamera.distance = 55;
    } else {
      // stand in front of a world sign, on its readable side
      viewDirection = flat(pose.forward);
      target = {...pose.centre};
      trackPreviewCamera.distance = 45;
    }
    trackPreviewCamera.target = target;
    trackPreviewCamera.yaw = Math.atan2(-viewDirection.x, -viewDirection.z);
    trackPreviewCamera.pitch = 0.1;
    renderTrackPreview(true);
  }

  // ------------------------------------------------------------------ open / close

  function openDesigner(){
    if(!panel) buildPanel();
    state.open = true;
    panel.classList.add('open');
    document.documentElement.classList.add('l3d-open');
    state.previousAutoFollow = trackPreviewAutoFollow;
    trackPreviewAutoFollow = false;
    const followToggle = document.getElementById('trackPreviewAutoFollow');
    if(followToggle) followToggle.checked = false;
    if(typeof setTrackPreviewMinimized === 'function' && typeof trackPreviewMinimized !== 'undefined' && trackPreviewMinimized) setTrackPreviewMinimized(false);
    state.wasFullscreen = typeof trackPreviewFullscreen !== 'undefined' && trackPreviewFullscreen;
    if(typeof setTrackPreviewFullscreen === 'function' && !state.wasFullscreen) setTrackPreviewFullscreen(true);
    if(state.selected < 0 && signs().length) state.selected = 0;
    renderList(); renderFields();
    setStatus(trackPreviewData ? state.scenery.status : say('needScene'));
    loadScenery();
    renderTrackPreview(true);
    panel.querySelector('button')?.focus();
  }

  function closeDesigner(){
    if(!panel) return;
    state.open = false; state.placing = false; state.drag = null; state.rideAlong = false;
    panel.classList.remove('open');
    document.documentElement.classList.remove('l3d-open');
    trackPreviewAutoFollow = state.previousAutoFollow;
    const followToggle = document.getElementById('trackPreviewAutoFollow');
    if(followToggle) followToggle.checked = state.previousAutoFollow;
    if(typeof setTrackPreviewFullscreen === 'function' && !state.wasFullscreen) setTrackPreviewFullscreen(false);
    renderTrackPreview(true);
    document.getElementById('lyric3dOpenButton')?.focus();
  }

  // ------------------------------------------------------------------ wiring into the editor

  function install(){
    if(typeof renderTrackPreview !== 'function' || typeof trackPreviewCanvas === 'undefined') return;
    // draw signs after every preview frame
    const originalRender = renderTrackPreview;
    window.renderTrackPreview = function(...args){
      // During playback the preview skips calls to hold 30 fps. Only add our layer when it really drew a new
      // frame: drawing the see-through buildings onto an old frame again made them stack up and flicker.
      const force = args[0] === true;
      const frameDue = force || !isPlaying || performance.now() - trackPreviewLastRenderTime >= TRACK_PREVIEW_PLAYBACK_FRAME_MS;
      if(frameDue){
        try { updateRideCamera(); updatePlayButton(); } catch(error){ console.warn('[Lyric Designer] ride camera failed', error); }
      }
      const renderedBefore = trackPreviewLastRenderTime;
      const result = originalRender.apply(this, args);
      if(trackPreviewLastRenderTime === renderedBefore) return result;   // preview skipped this call
      try {
        if(state.open){
          const width = trackPreviewCanvas.clientWidth || 1, height = trackPreviewCanvas.clientHeight || 1;
          drawScenery(trackPreviewCtx, getTrackPreviewCamera(width, height), width, height);
          loadScenery();
        }
        drawSigns();
        if(state.open){
          const width = trackPreviewCanvas.clientWidth || 1, height = trackPreviewCanvas.clientHeight || 1;
          drawTimeMarks(trackPreviewCtx, getTrackPreviewCamera(width, height), width, height);
        }
      } catch(error){ console.warn('[Lyric Designer] draw failed', error); }
      return result;
    };
    trackPreviewCanvas.addEventListener('mousedown', onCanvasMouseDown, true);
    window.addEventListener('mousemove', onWindowMouseMove, true);
    window.addEventListener('mouseup', onWindowMouseUp, true);
    window.addEventListener('keydown', event => {
      if(state.open && event.key === 'Escape' && state.placing){ state.placing = false; setStatus(''); event.stopImmediatePropagation(); }
    }, true);

    const openButton = document.createElement('button');
    openButton.type = 'button';
    openButton.id = 'lyric3dOpenButton';
    openButton.textContent = say('open');
    openButton.addEventListener('click', () => state.open ? closeDesigner() : openDesigner());
    document.getElementById('lyricsAssistantBtn')?.insertAdjacentElement('afterend', openButton);

    // undo / load replaced the design: keep the panel in sync
    window.onLyric3dDesignReplaced = () => {
      if(state.selected >= signs().length) state.selected = signs().length - 1;
      if(state.open){ renderList(); renderFields(); }
    };
    window.lyricDesigner = {open: openDesigner, close: closeDesigner, generate: generateFromLyrics};
  }

  install();
})();
