// BFS Lyric3D - spatial lyrics for Beat For Speed (MelonLoader mod).
//
// Lyrics become 2D text signs standing in the 3D world that you drive past, styled like a
// lyric video: mounted on buildings/walls beside the road when there are any, otherwise standing
// off to the side.
//
// How it works:
//   1. Song      - the playing music clip is matched to its chart (ChartReader). Clips without a
//                  chart, like the engine loop, are ignored.
//   2. Road      - the car's position is matched to the track's centreline (RoadPath), which gives
//                  how far along the road it is and how fast it is moving along it.
//   3. Placement - each sign is placed where the car will be part-way through its sung line.
//                  Far-off signs keep re-aiming smoothly as the car's speed changes, then lock in place.
//   4. Look      - text, fonts, karaoke/typewriter reveal, enter/exit effects (SignText, below).
//
// Files: Settings.cs (user settings), SignModels.cs (data), RoadPath.cs, ChartReader.cs, SignText.cs.
// It never touches the game's obfuscated code.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using MelonLoader;
using UnityEngine;
using Il2CppTMPro;

[assembly: MelonInfo(typeof(BfsLyric3D.Lyric3DMod), "BFS Lyric3D", "0.8.1", "beatspeederhelper")]
[assembly: MelonGame(null, "beatforspeed")]

namespace BfsLyric3D
{
    public class Lyric3DMod : MelonMod
    {
        const float SignCanvasUnitsToMetres = 0.02f;   // canvas pixels -> world metres (before the user's Scale)
        const float EnterDurationSeconds = 0.6f;
        const float ExitDurationSeconds = 0.6f;

        Settings settings;
        ChartReader chartReader;
        SignText signText;
        SceneExporter sceneExporter;

        // the song
        AudioSource music;
        string musicClipName, chartPath;
        double beatsPerMinute = 120;
        List<SignSpec> songSigns = new();
        readonly HashSet<SignSpec> signsAlreadyShown = new();
        readonly HashSet<string> clipsWithoutChart = new();
        double previousSongTime;

        // the road and the car
        readonly List<RoadPath> roads = new();
        RoadPath currentRoad;
        float carRoadDistance, carSpeedAlongRoad;
        bool carRoadDistanceKnown;
        Transform car;

        // signs in the world
        readonly List<LiveSign> liveSigns = new();
        readonly List<TMP_Text> hiddenFlatLyrics = new();
        static readonly System.Random random = new();

        float nextSlowCheckTime, nextRoadLogTime;

        // ================================================================= MelonLoader events

        public override void OnInitializeMelon()
        {
            settings = new Settings();
            chartReader = new ChartReader(settings, LoggerInstance.Msg);
            signText = new SignText(settings, LoggerInstance.Msg);
            sceneExporter = new SceneExporter(LoggerInstance.Msg);
            LoadRoads();
            LoggerInstance.Msg($"BFS Lyric3D 0.8.1 loaded ({roads.Count} track paths).");
        }

        public override void OnSceneWasLoaded(int buildIndex, string sceneName)
        {
            RemoveAllSigns();
            car = null;
            music = null; musicClipName = null; chartPath = null; songSigns = new();
            currentRoad = null; carRoadDistanceKnown = false;
            if (settings.DebugLog) LoggerInstance.Msg($"scene loaded: {sceneName}");
        }

        public override void OnUpdate()
        {
            settings.ReloadIfFileChanged(Time.unscaledTime, LoggerInstance.Msg);
            if (!settings.Enabled) return;
            try { UpdateFrame(); }
            catch (Exception error)
            {
                LoggerInstance.Error($"stopped after an error: {error}");
                settings.Enabled = false;   // never break the game; turn ourselves off instead
            }
        }

        // ================================================================= per frame

        void UpdateFrame()
        {
            if (Time.unscaledTime >= nextSlowCheckTime)   // things that only need checking twice a second
            {
                nextSlowCheckTime = Time.unscaledTime + 0.5f;
                FindSongPlaying();
                if (car == null) car = FindCar();
                if (songSigns.Count > 0 && settings.HideFlatLyrics) HideFlatLyrics();
            }
            if (music == null || songSigns.Count == 0) return;

            double songTime = music.time;
            if (songTime + 0.5 < previousSongTime) RemoveAllSigns();   // song restarted or seeked back
            previousSongTime = songTime;
            if (!music.isPlaying) return;

            Transform followed = car != null ? car : Camera.main != null ? Camera.main.transform : null;
            if (followed != null) TrackCarOnRoad(followed.position);
            bool roadKnown = currentRoad != null && carRoadDistanceKnown && carSpeedAlongRoad >= 1f;
            if (roadKnown && settings.ExportScenery && sceneExporter.NeedsExport(currentRoad))
            {
                try { sceneExporter.Export(currentRoad); }
                catch (Exception error) { LoggerInstance.Warning($"scenery export failed: {error.Message}"); }
            }

            foreach (var sign in songSigns)
            {
                if (signsAlreadyShown.Contains(sign)) continue;
                if (sign.FixedInWorld)
                {
                    // placed by hand in the editor: shows at its own times, needs no road tracking
                    if (songTime >= sign.AppearAt && songTime < sign.DisappearAt) ShowSign(sign, songTime);
                    continue;
                }
                if (!roadKnown) continue;   // road signs wait until we know where the road goes
                double passTime = PassTime(sign);
                if (songTime >= passTime - settings.LeadSeconds && songTime < passTime) ShowSign(sign, songTime);
            }

            Camera camera = Camera.main;
            for (int index = liveSigns.Count - 1; index >= 0; index--)
            {
                if (UpdateSign(liveSigns[index], songTime, camera)) continue;
                if (liveSigns[index].Root != null) UnityEngine.Object.Destroy(liveSigns[index].Root);
                liveSigns.RemoveAt(index);
            }
        }

        /// <summary>The song time at which the car should drive past this sign.</summary>
        double PassTime(SignSpec sign) =>
            !double.IsNaN(sign.PassAt) ? sign.PassAt   // placed by hand: exactly there, no offset
            : sign.SungStart + Math.Clamp(settings.PassPoint, 0f, 1f) * (sign.SungEnd - sign.SungStart) + settings.TimeOffset;

        // ================================================================= song

        void ForgetSong()
        {
            if (settings.DebugLog) LoggerInstance.Msg($"song '{musicClipName}' stopped: signs cleared");
            RemoveAllSigns();
            music = null; musicClipName = null; chartPath = null; songSigns = new();
        }

        void FindSongPlaying()
        {
            bool currentSongStillPlaying = music != null && music.isPlaying && music.clip != null && music.clip.name == musicClipName;
            if (currentSongStillPlaying) return;

            // The song we had signs for stopped or the player switched to another clip: forget it now, so a
            // following song without a chart (or without lyrics) never shows the previous song's signs.
            if (musicClipName != null) ForgetSong();

            foreach (var source in UnityEngine.Object.FindObjectsByType<AudioSource>(FindObjectsSortMode.None))
            {
                if (source == null || source.clip == null || !source.isPlaying || source.clip.length < 30f) continue;
                string clipName = source.clip.name ?? "";
                if (clipsWithoutChart.Contains(clipName)) continue;

                string foundChart = chartReader.FindChartForClip(clipName);
                if (foundChart == null)
                {
                    clipsWithoutChart.Add(clipName);
                    if (settings.DebugLog) LoggerInstance.Msg($"ignoring clip '{clipName}' (no chart)");
                    continue;
                }
                music = source; musicClipName = clipName; chartPath = foundChart;
                RemoveAllSigns();
                using (var chart = JsonDocument.Parse(File.ReadAllText(foundChart)))
                    songSigns = chartReader.BuildSigns(chart.RootElement, out beatsPerMinute);
                LoggerInstance.Msg(songSigns.Count > 0
                    ? $"song '{clipName}' ({source.clip.length:F0}s): {songSigns.Count} lyric signs ready ({foundChart})"
                    : $"song '{clipName}': chart has no lyrics (3D lyrics off)");
                return;
            }
        }

        // ================================================================= road + car

        void LoadRoads()
        {
            try
            {
                string folder = Path.Combine(Directory.GetParent(Application.dataPath).FullName, "Tools", "chart_editor", "track_previews");
                foreach (string file in Directory.EnumerateFiles(folder, "*.json")) roads.Add(RoadPath.Load(file));
            }
            catch (Exception error) { LoggerInstance.Warning($"could not load track paths: {error.Message}"); }
        }

        Transform FindCar()
        {
            var vehicle = UnityEngine.Object.FindFirstObjectByType<Il2Cpp.PlayerVehicleController>();
            if (vehicle == null) return null;
            if (settings.DebugLog) LoggerInstance.Msg($"player vehicle found: {vehicle.name}");
            return vehicle.transform;
        }

        /// <summary>Where along the road the car is, and its speed along the road (smoothed).</summary>
        void TrackCarOnRoad(Vector3 carPosition)
        {
            if (currentRoad == null)
            {
                LockOntoNearestRoad(carPosition);
                return;
            }

            float roadDistance = currentRoad.FindRoadDistance(carPosition, out float metresOffCentre);
            if (metresOffCentre > 25f) roadDistance = currentRoad.FindRoadDistance(carPosition, out metresOffCentre, searchWholeRoad: true);
            if (metresOffCentre > 25f)
            {
                LoggerInstance.Msg($"lost track path '{currentRoad.Name}' ({metresOffCentre:F0} m off)");
                currentRoad = null; carRoadDistanceKnown = false;
                return;
            }

            if (carRoadDistanceKnown && Time.deltaTime > 0)
            {
                float speed = currentRoad.DistanceAhead(carRoadDistance, roadDistance) / Time.deltaTime;
                float smoothing = 1f - Mathf.Exp(-Time.deltaTime / 1.5f);   // ~1.5 s average: frame-to-frame jitter made far signs shake
                if (speed > -5f && speed < 250f) carSpeedAlongRoad = Mathf.Lerp(carSpeedAlongRoad, speed, smoothing);
            }
            carRoadDistance = roadDistance;
            carRoadDistanceKnown = true;

            if (settings.DebugLog && Time.unscaledTime > nextRoadLogTime)
            {
                nextRoadLogTime = Time.unscaledTime + 10f;
                LoggerInstance.Msg($"track {currentRoad.Name}: {roadDistance:F0} m along, car {metresOffCentre:F1} m off centreline, {carSpeedAlongRoad:F1} m/s");
            }
        }

        void LockOntoNearestRoad(Vector3 carPosition)
        {
            RoadPath nearestRoad = null;
            float nearestOffset = float.MaxValue;
            foreach (var road in roads)
            {
                road.FindRoadDistance(carPosition, out float metresOffCentre, searchWholeRoad: true);
                if (metresOffCentre < nearestOffset) { nearestOffset = metresOffCentre; nearestRoad = road; }
            }
            if (nearestRoad != null && nearestOffset < 15f)
            {
                currentRoad = nearestRoad; carRoadDistanceKnown = false; carSpeedAlongRoad = 0;
                LoggerInstance.Msg($"locked to track path '{nearestRoad.Name}' (car {nearestOffset:F1} m from its centreline)");
            }
            else if (settings.DebugLog && Time.unscaledTime > nextRoadLogTime)
            {
                nextRoadLogTime = Time.unscaledTime + 10f;
                LoggerInstance.Msg($"no track path near the car (closest '{nearestRoad?.Name}' at {nearestOffset:F0} m) - signs paused");
            }
        }

        /// <summary>Where along the road the car will be at the sign's pass time, at its current speed.</summary>
        float PredictedRoadDistance(SignSpec sign, double songTime) =>
            carRoadDistance + carSpeedAlongRoad * (float)Math.Max(0.3, PassTime(sign) - songTime);

        // ================================================================= placing signs

        /// <summary>Position and rotation for a sign at a road distance: on a wall if there is one, otherwise standing off the road.</summary>
        void PlaceSign(LiveSign live, float roadDistance)
        {
            var sign = live.Spec;
            currentRoad.PointAt(roadDistance, out Vector3 roadPoint, out Vector3 roadDirection);
            Vector3 alongRoad = new Vector3(roadDirection.x, 0, roadDirection.z);
            if (alongRoad.sqrMagnitude < 1e-4f) alongRoad = Vector3.forward;
            alongRoad.Normalize();
            Vector3 roadRight = Vector3.Cross(Vector3.up, alongRoad).normalized;

            // Where the driver reads the sign from: the road ~2.5 s before it (at least 35 m).
            currentRoad.PointAt(roadDistance - Mathf.Max(35f, carSpeedAlongRoad * 2.5f), out Vector3 readerPoint, out _);
            Vector3 approachDirection = roadPoint - readerPoint;
            approachDirection.y = 0;
            if (approachDirection.sqrMagnitude < 1f) approachDirection = alongRoad;
            approachDirection.Normalize();

            live.MountedOnWall = false;
            if (sign.Side == 0)   // gantry over the road, facing the driver
            {
                live.Position = roadPoint + Vector3.up * (sign.Height + 3f);
                live.Rotation = Quaternion.LookRotation(approachDirection, Vector3.up);
                return;
            }

            Vector3 awayFromRoad = roadRight * sign.Side;
            Vector3 signForward = Quaternion.AngleAxis(sign.Side * sign.Turn, Vector3.up) * alongRoad;
            live.Position = roadPoint + awayFromRoad * sign.SideDistance + Vector3.up * sign.Height;

            // Walls are searched again only after the sign moved a few metres: re-checking every frame made far
            // signs hop between a wall and open ground.
            bool checkWall = settings.WallSnap && (float.IsNaN(live.WallCheckedAtRoadDistance)
                                                   || Mathf.Abs(roadDistance - live.WallCheckedAtRoadDistance) > 8f);
            if (checkWall)
            {
                live.WallCheckedAtRoadDistance = roadDistance;
                live.HasWall = FindWallBesideRoad(roadPoint + Vector3.up * sign.Height, awayFromRoad, out live.Wall);
            }
            if (settings.WallSnap && live.HasWall)
            {
                live.Position = live.Wall.point - awayFromRoad * 0.6f;   // just in front of the wall
                Vector3 wallFacing = new Vector3(live.Wall.normal.x, 0, live.Wall.normal.z);
                if (wallFacing.sqrMagnitude > 0.1f) signForward = -wallFacing.normalized;
                live.MountedOnWall = true;
            }

            // A world-space canvas reads correctly from the side its forward points away from. Check that against
            // the real sightline (reader -> sign); comparing with the road direction got bends and parallel
            // walls wrong and showed a few signs backwards.
            Vector3 sightline = live.Position - (readerPoint + Vector3.up * 1.5f);
            sightline.y = 0;
            if (sightline.sqrMagnitude < 1f) sightline = approachDirection;
            if (Vector3.Dot(signForward, sightline) < 0) signForward = -signForward;
            live.Rotation = Quaternion.LookRotation(signForward, Vector3.up);
        }

        /// <summary>The nearest static wall/building to the side of the road (ignores barriers close to the road, floors, and moving traffic).</summary>
        bool FindWallBesideRoad(Vector3 from, Vector3 direction, out RaycastHit wall)
        {
            wall = default;
            bool found = false;
            float nearest = float.MaxValue;
            foreach (var hit in Physics.RaycastAll(from, direction, settings.WallSearchDistance))
            {
                if (hit.distance < 9f || hit.distance > nearest) continue;                         // road edge / barriers
                if (hit.collider == null || hit.collider.attachedRigidbody != null) continue;      // cars and other moving things
                if (Mathf.Abs(hit.normal.y) > 0.6f) continue;                                      // floors and roofs, not walls
                nearest = hit.distance; wall = hit; found = true;
            }
            return found;
        }

        // ================================================================= sign life cycle

        void ShowSign(SignSpec sign, double songTime)
        {
            signsAlreadyShown.Add(sign);

            var root = new GameObject("BfsLyric3D Sign");
            var canvas = root.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            root.GetComponent<RectTransform>().sizeDelta = new Vector2(1800, 800);

            var textObject = new GameObject("Text");
            textObject.transform.SetParent(root.transform, false);
            var text = textObject.AddComponent<TextMeshProUGUI>();
            var font = signText.GetFont(sign.Font);
            if (font != null) text.font = font;
            text.richText = true;
            text.fontSize = 150;
            text.alignment = TextAlignmentOptions.Center;
            text.enableWordWrapping = false;
            text.characterSpacing = sign.LetterSpacing;
            text.outlineWidth = Mathf.Clamp(sign.Outline, 0f, 0.5f);
            text.outlineColor = new Color32(0, 0, 0, 200);
            if (sign.HasGradient)
            {
                var top = ParseColor(sign.GradientTop, Color.white);
                var bottom = ParseColor(sign.GradientBottom, Color.white);
                text.enableVertexGradient = true;
                text.colorGradient = new VertexGradient(top, top, bottom, bottom);
            }
            text.alpha = 0f;
            var textRect = textObject.GetComponent<RectTransform>();
            textRect.anchorMin = Vector2.zero; textRect.anchorMax = Vector2.one;
            textRect.offsetMin = Vector2.zero; textRect.offsetMax = Vector2.zero;

            var live = new LiveSign { Spec = sign, Root = root, Text = text, AppearedAtSongTime = songTime };
            if (sign.FixedInWorld)
            {
                // exactly where the designer put it; the reader looks along its facing
                live.Position = sign.WorldPosition;
                live.Rotation = Quaternion.Euler(sign.WorldTilt, sign.WorldYaw, 0f);
                live.LockedInPlace = true;
            }
            else
            {
                live.RoadDistance = PredictedRoadDistance(sign, songTime);
                PlaceSign(live, live.RoadDistance);
            }
            root.transform.SetPositionAndRotation(live.Position, live.Rotation);
            root.transform.localScale = Vector3.zero;   // first UpdateSign call sizes it
            liveSigns.Add(live);

            if (settings.DebugLog)
            {
                string where = sign.FixedInWorld
                    ? $"fixed at ({sign.WorldPosition.x:F0}, {sign.WorldPosition.y:F0}, {sign.WorldPosition.z:F0})"
                    : $"at {live.RoadDistance:F0} m, side {sign.Side}, {(live.MountedOnWall ? "on wall" : "open")}";
                LoggerInstance.Msg($"sign for {sign.SungStart:F1}s {where}: {string.Join(" / ", sign.Lines.Select(line => line.Text))}");
            }
        }

        /// <summary>Animates a sign for this frame. Returns false when it is finished and can be removed.</summary>
        bool UpdateSign(LiveSign live, double songTime, Camera camera)
        {
            if (live.Root == null) return false;
            var sign = live.Spec;

            // Far away: keep re-aiming for speed changes - smoothly, and unnoticeable at that distance.
            if (!live.LockedInPlace && currentRoad != null)
            {
                if (currentRoad.DistanceAhead(carRoadDistance, live.RoadDistance) < settings.LockDistance)
                    live.LockedInPlace = true;
                else
                {
                    float correction = PredictedRoadDistance(sign, songTime) - live.RoadDistance;
                    if (Mathf.Abs(correction) > 4f)   // small corrections are not worth a visible move
                    {
                        float step = Mathf.Clamp(correction, -12f * Time.deltaTime, 12f * Time.deltaTime);
                        live.RoadDistance += step;
                        PlaceSign(live, live.RoadDistance);
                    }
                }
            }

            // ---- enter effect
            float enterProgress = Mathf.Clamp01((float)(songTime - live.AppearedAtSongTime) / EnterDurationSeconds);
            float easedEnter = 1f - Mathf.Pow(1f - enterProgress, 2);
            float alpha = easedEnter;
            float scale = 1f;
            Vector3 positionOffset = Vector3.zero;
            switch (sign.EnterEffect)
            {
                // kept small on purpose: big moves while driving read as distracting bounces
                case "rise": positionOffset = Vector3.down * (1f - easedEnter) * 0.5f; break;
                case "drop": positionOffset = Vector3.up * (1f - easedEnter) * 1.0f; break;
                case "pop": scale = Mathf.Lerp(0.9f, 1f, easedEnter); break;
            }

            // ---- beat pulse
            if (sign.BeatPulse && beatsPerMinute > 0)
            {
                double positionInBeat = (songTime * beatsPerMinute / 60.0) % 1.0;
                scale *= 1f + 0.01f * Mathf.Exp(-(float)positionInBeat * 7f);
            }

            // ---- exit effect: world signs leave at their disappear time; road signs once the car has passed them
            bool timeToLeave;
            if (sign.FixedInWorld)
                timeToLeave = songTime >= sign.DisappearAt - ExitDurationSeconds;
            else
            {
                Vector3 cameraToSign = live.Position - (camera != null ? camera.transform.position : live.Position);
                bool carHasPassed = camera != null && Vector3.Dot(cameraToSign, camera.transform.forward) < 2f && cameraToSign.magnitude < 60f;
                timeToLeave = carHasPassed || songTime > PassTime(sign) + 6;
            }
            if (live.ExitStartedAtSongTime < 0 && timeToLeave) live.ExitStartedAtSongTime = songTime;

            HashSet<int> dissolvedCharacters = null;
            if (live.ExitStartedAtSongTime >= 0)
            {
                float exitProgress = Mathf.Clamp01((float)(songTime - live.ExitStartedAtSongTime) / ExitDurationSeconds);
                if (exitProgress >= 1f) return false;
                switch (sign.ExitEffect)
                {
                    case "dissolve":
                        live.DissolveOrder ??= Enumerable.Range(0, sign.TotalCharacters).OrderBy(_ => random.Next()).ToArray();
                        dissolvedCharacters = new HashSet<int>(live.DissolveOrder.Take((int)(exitProgress * live.DissolveOrder.Length)));
                        break;
                    case "shrink": scale *= 1f - 0.6f * exitProgress; alpha *= 1f - exitProgress; break;
                    case "rise": positionOffset += Vector3.up * exitProgress * 4f; alpha *= 1f - exitProgress; break;
                    default: alpha *= 1f - exitProgress; break;   // fade
                }
            }

            // ---- reveal, timed to when the line is actually sung (independent of where the sign stands)
            int totalCharacters = sign.TotalCharacters;
            double revealFrom = double.IsNaN(sign.RevealStart) ? sign.SungStart : sign.RevealStart;
            double revealTo = double.IsNaN(sign.RevealEnd) ? sign.SungEnd : sign.RevealEnd;
            float sungFraction = (float)Math.Clamp((songTime - revealFrom) / Math.Max(0.2, revealTo - revealFrom), 0, 1);
            int sungCharacters = (int)Math.Round(sungFraction * totalCharacters);
            int visibleCharacters = sign.Reveal == "typewriter" ? Math.Max(1, sungCharacters) : totalCharacters;
            int highlightedCharacters = sign.Reveal == "karaoke" ? sungCharacters : totalCharacters;
            string richText = SignText.BuildRichText(sign, visibleCharacters, highlightedCharacters, dissolvedCharacters);
            if (richText != live.LastRichText)
            {
                live.Text.text = richText;
                live.LastRichText = richText;
            }

            live.Text.alpha = alpha * Mathf.Clamp01(sign.Opacity);
            if (!live.ShownPoseReady || live.LockedInPlace && (live.ShownPosition - live.Position).sqrMagnitude < 0.0001f)
            {
                live.ShownPosition = live.Position; live.ShownRotation = live.Rotation; live.ShownPoseReady = true;
            }
            else
            {
                float glide = 1f - Mathf.Exp(-Time.deltaTime * 3f);   // any re-aim slides over ~1/3 s
                live.ShownPosition = Vector3.Lerp(live.ShownPosition, live.Position, glide);
                live.ShownRotation = Quaternion.Slerp(live.ShownRotation, live.Rotation, glide);
            }
            live.Root.transform.SetPositionAndRotation(live.ShownPosition + positionOffset, live.ShownRotation);
            live.Root.transform.localScale = Vector3.one * SignCanvasUnitsToMetres * settings.Scale * sign.Scale * scale;
            return true;
        }

        static Color ParseColor(string hex, Color fallback) => ColorUtility.TryParseHtmlString(hex, out var color) ? color : fallback;

        // ================================================================= flat lyrics + cleanup

        /// <summary>Hides the game's normal on-screen lyrics while 3D lyrics are showing (restored in RemoveAllSigns).</summary>
        void HideFlatLyrics()
        {
            var lyricsDisplay = UnityEngine.Object.FindFirstObjectByType<Il2Cpp.ChartLyricsDisplay>();
            if (lyricsDisplay == null) return;
            foreach (var lyricText in lyricsDisplay.GetComponentsInChildren<TMP_Text>(true))
            {
                if (lyricText == null || !lyricText.enabled) continue;
                lyricText.enabled = false;
                hiddenFlatLyrics.Add(lyricText);
            }
        }

        void RemoveAllSigns()
        {
            foreach (var live in liveSigns)
                if (live.Root != null) UnityEngine.Object.Destroy(live.Root);
            liveSigns.Clear();
            signsAlreadyShown.Clear();
            foreach (var lyricText in hiddenFlatLyrics)
                if (lyricText != null) lyricText.enabled = true;
            hiddenFlatLyrics.Clear();
            previousSongTime = 0;
        }
    }
}
