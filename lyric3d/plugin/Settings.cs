using System;
using System.IO;
using MelonLoader;

namespace BfsLyric3D
{
    /// <summary>
    /// All user settings, stored in UserData/MelonPreferences.cfg under [BfsLyric3D].
    /// Edit that file while the game is closed (MelonLoader rewrites it when the game exits).
    /// </summary>
    public class Settings
    {
        // on/off switches
        readonly MelonPreferences_Entry<bool> enabled, autoSpatial, hideFlatLyrics, uppercaseAuto, debugLog, wallSnap, beatPulse, exportScenery;
        // timing and placement
        readonly MelonPreferences_Entry<float> leadSeconds, timeOffset, passPoint, lockDistance,
            sideDistance, height, turn, wallSearchDistance, scale;
        // look
        readonly MelonPreferences_Entry<float> opacity, outline, letterSpacing;
        readonly MelonPreferences_Entry<string> font, reveal, enterEffect, exitEffect, gradientTop, gradientBottom;
        readonly MelonPreferences_Entry<int> settingsVersion;

        const int CurrentSettingsVersion = 2;
        static string PreferencesFile => Path.Combine(MelonLoader.Utils.MelonEnvironment.UserDataDirectory, "MelonPreferences.cfg");
        DateTime preferencesFileTime;
        float nextFileCheck;

        public Settings()
        {
            var category = MelonPreferences.CreateCategory("BfsLyric3D", "BFS Lyric3D");

            enabled = category.CreateEntry("Enabled", true, "Show spatial 3D lyrics");
            autoSpatial = category.CreateEntry("AutoSpatial", true, "Build signs from normal lyrics when a chart has no lyric3d design");
            hideFlatLyrics = category.CreateEntry("HideFlatLyrics", true, "Hide the normal on-screen lyrics while 3D lyrics are showing");
            uppercaseAuto = category.CreateEntry("UppercaseAuto", true, "Auto signs in uppercase (title-card style)");

            leadSeconds = category.CreateEntry("LeadSeconds", 8f, "How many seconds before you reach a sign it appears down the road");
            timeOffset = category.CreateEntry("TimeOffset", 4.5f, "Seconds to push every sign later along the road (bigger = you see the whole karaoke line before passing)");
            passPoint = category.CreateEntry("PassPoint", 0.4f, "Where in the sung line you pass the sign (0 = start, 1 = end)");
            lockDistance = category.CreateEntry("LockDistance", 140f, "Signs keep re-aiming for speed changes until they are this close (m), then stay put");
            sideDistance = category.CreateEntry("SideDistance", 15f, "Metres from the road centre to a sign when no wall is found");
            height = category.CreateEntry("Height", 7f, "Sign height above the road in metres");
            turn = category.CreateEntry("Turn", 60f, "Sign angle: 0 = faces the driver, 90 = parallel to the road");
            wallSnap = category.CreateEntry("WallSnap", true, "Mount lyrics on buildings/walls beside the road when there are any");
            wallSearchDistance = category.CreateEntry("WallSearchDistance", 45f, "How far sideways to look for a wall (metres)");
            scale = category.CreateEntry("Scale", 0.7f, "Overall sign size");

            font = category.CreateEntry("Font", "", "Font: a Windows font name (e.g. Impact, Bebas Neue, Arial Black) or a game font; empty = game lyric font");
            opacity = category.CreateEntry("Opacity", 0.95f, "Sign opacity 0-1");
            outline = category.CreateEntry("Outline", 0.15f, "Text outline thickness 0-0.5");
            letterSpacing = category.CreateEntry("LetterSpacing", 4f, "Extra space between letters");
            gradientTop = category.CreateEntry("GradientTop", "", "Optional gradient: top colour (#rrggbb); empty = use the lyric colour");
            gradientBottom = category.CreateEntry("GradientBottom", "", "Optional gradient: bottom colour (#rrggbb)");
            reveal = category.CreateEntry("Reveal", "karaoke", "none | typewriter (letters appear as sung) | karaoke (words light up as sung)");
            beatPulse = category.CreateEntry("BeatPulse", true, "Signs pulse gently on every beat");
            enterEffect = category.CreateEntry("Enter", "rise", "rise | fade | pop | drop");
            exitEffect = category.CreateEntry("Exit", "fade", "fade | dissolve | shrink | rise");

            exportScenery = category.CreateEntry("ExportSceneryForEditor", true, "Save the buildings near each track (once) so the chart editor's 3D Lyric Designer can show them");
            debugLog = category.CreateEntry("Debug", true, "Verbose log in MelonLoader/Latest.log");
            settingsVersion = category.CreateEntry("SettingsVersion", 0, "Used by the mod to update old settings; leave alone");

            if (settingsVersion.Value < CurrentSettingsVersion)
            {
                settingsVersion.Value = CurrentSettingsVersion;
                MelonPreferences.Save();
            }
            preferencesFileTime = File.Exists(PreferencesFile) ? File.GetLastWriteTimeUtc(PreferencesFile) : default;
        }

        /// <summary>Reload the settings when MelonPreferences.cfg is edited while the game runs (checked every 2 s).</summary>
        public bool ReloadIfFileChanged(float now, Action<string> log)
        {
            if (now < nextFileCheck) return false;
            nextFileCheck = now + 2f;
            if (!File.Exists(PreferencesFile)) return false;
            var fileTime = File.GetLastWriteTimeUtc(PreferencesFile);
            if (fileTime == preferencesFileTime) return false;
            preferencesFileTime = fileTime;
            float previousOffset = TimeOffset;
            MelonPreferences.Load();
            log($"settings file changed: reloaded (TimeOffset {previousOffset} -> {TimeOffset}, LeadSeconds {LeadSeconds})");
            return true;
        }

        public bool Enabled { get => enabled.Value; set => enabled.Value = value; }
        public bool AutoSpatial => autoSpatial.Value;
        public bool HideFlatLyrics => hideFlatLyrics.Value;
        public bool UppercaseAuto => uppercaseAuto.Value;
        public bool DebugLog => debugLog.Value;
        public bool WallSnap => wallSnap.Value;
        public bool ExportScenery => exportScenery.Value;

        public float LeadSeconds => leadSeconds.Value;
        public float TimeOffset => timeOffset.Value;
        public float PassPoint => passPoint.Value;
        public float LockDistance => lockDistance.Value;
        public float WallSearchDistance => wallSearchDistance.Value;
        public float Scale => scale.Value;

        /// <summary>A sign with every style option filled in from the user's defaults.</summary>
        public SignSpec NewSignWithDefaults() => new SignSpec
        {
            SideDistance = sideDistance.Value,
            Height = height.Value,
            Turn = turn.Value,
            Font = font.Value,
            Opacity = opacity.Value,
            Outline = outline.Value,
            LetterSpacing = letterSpacing.Value,
            GradientTop = gradientTop.Value,
            GradientBottom = gradientBottom.Value,
            Reveal = reveal.Value,
            BeatPulse = beatPulse.Value,
            EnterEffect = enterEffect.Value,
            ExitEffect = exitEffect.Value,
        };
    }
}
