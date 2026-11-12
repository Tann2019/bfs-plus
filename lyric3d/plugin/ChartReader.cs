using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using UnityEngine;

namespace BfsLyric3D
{
    /// <summary>
    /// Finds the chart file for the song that is playing and turns its lyrics into signs.
    /// Charts with a "lyric3d" design use it; otherwise signs are built from the normal lyrics.
    /// </summary>
    public class ChartReader
    {
        readonly Settings settings;
        readonly Action<string> log;

        public ChartReader(Settings settings, Action<string> log)
        {
            this.settings = settings;
            this.log = log;
        }

        // ------------------------------------------------------------- finding the chart

        /// <summary>
        /// The chart for a music clip: first the game's imported songs (UserSongs/manifest.json),
        /// then Steam Workshop items. Workshop audio is often just called "audio", so a Workshop
        /// match is only used when exactly one item fits.
        /// </summary>
        public string FindChartForClip(string clipName)
        {
            string wantedName = SimplifyName(clipName);
            string userSongsFolder = Path.Combine(Application.persistentDataPath, "UserSongs");
            string manifestPath = Path.Combine(userSongsFolder, "manifest.json");

            if (File.Exists(manifestPath))
            {
                using var manifest = JsonDocument.Parse(File.ReadAllText(manifestPath));
                if (manifest.RootElement.TryGetProperty("songs", out var songs))
                {
                    foreach (var song in songs.EnumerateArray())
                    {
                        string audioFile = ReadString(song, "wavFileName");
                        string title = ReadString(song, "title");
                        bool matches = SimplifyName(Path.GetFileNameWithoutExtension(audioFile)) == wantedName
                                       || SimplifyName(title) == wantedName;
                        if (!matches) continue;
                        string chartPath = Path.Combine(userSongsFolder, ReadString(song, "id"), ReadString(song, "jsonFileName"));
                        if (File.Exists(chartPath)) return chartPath;
                    }
                }
            }

            var workshopMatches = new List<string>();
            string workshopFolder = FindWorkshopFolder();
            if (workshopFolder != null)
            {
                foreach (string file in Directory.EnumerateFiles(workshopFolder, "*.*", SearchOption.AllDirectories))
                {
                    string extension = Path.GetExtension(file).ToLowerInvariant();
                    if (extension != ".mp3" && extension != ".ogg" && extension != ".wav") continue;
                    if (SimplifyName(Path.GetFileNameWithoutExtension(file)) != wantedName) continue;
                    string chartPath = Directory.EnumerateFiles(Path.GetDirectoryName(file), "*.json").FirstOrDefault();
                    if (chartPath != null) workshopMatches.Add(chartPath);
                }
            }
            if (workshopMatches.Count == 1) return workshopMatches[0];
            if (workshopMatches.Count > 1 && settings.DebugLog)
                log($"clip '{clipName}' matches {workshopMatches.Count} workshop charts - skipped (ambiguous)");
            return null;
        }

        static string FindWorkshopFolder()
        {
            try
            {
                var steamappsFolder = Directory.GetParent(Application.dataPath)?.Parent?.Parent;   // <game>/../../ = steamapps
                string folder = steamappsFolder == null ? null : Path.Combine(steamappsFolder.FullName, "workshop", "content", "4430260");
                return folder != null && Directory.Exists(folder) ? folder : null;
            }
            catch { return null; }
        }

        // ------------------------------------------------------------- chart -> signs

        /// <summary>Reads the chart's BPM and builds its signs.</summary>
        public List<SignSpec> BuildSigns(JsonElement chart, out double beatsPerMinute)
        {
            beatsPerMinute = 120;
            if (chart.TryGetProperty("musicData", out var musicData) && musicData.TryGetProperty("bpm", out var bpmElement)
                && bpmElement.TryGetDouble(out var bpmValue) && bpmValue > 0)
                beatsPerMinute = bpmValue;

            if (chart.TryGetProperty("lyric3d", out var design) && design.TryGetProperty("panels", out var designedSigns))
                return BuildDesignedSigns(designedSigns, beatsPerMinute);
            if (settings.AutoSpatial && chart.TryGetProperty("lyrics", out var lyrics))
                return BuildAutoSigns(chart, lyrics, beatsPerMinute);
            return new List<SignSpec>();
        }

        /// <summary>Signs exactly as designed in the chart's "lyric3d" block (anything missing uses the user's defaults).</summary>
        List<SignSpec> BuildDesignedSigns(JsonElement designedSigns, double beatsPerMinute)
        {
            var signs = new List<SignSpec>();
            foreach (var designed in designedSigns.EnumerateArray())
            {
                var sign = settings.NewSignWithDefaults();
                double startBeat = ReadNumber(designed, "beat", 0);
                sign.SungStart = BeatToSeconds(startBeat, beatsPerMinute);
                sign.SungEnd = BeatToSeconds(startBeat + ReadNumber(designed, "duration", 2), beatsPerMinute);
                double revealStartBeat = ReadNumber(designed, "revealStart", double.NaN), revealEndBeat = ReadNumber(designed, "revealEnd", double.NaN);
                if (!double.IsNaN(revealStartBeat)) sign.RevealStart = BeatToSeconds(revealStartBeat, beatsPerMinute);   // each end optional
                if (!double.IsNaN(revealEndBeat)) sign.RevealEnd = BeatToSeconds(revealEndBeat, beatsPerMinute);
                sign.Side = (int)ReadNumber(designed, "side", 1);
                sign.SideDistance = (float)ReadNumber(designed, "distance", sign.SideDistance);
                sign.Height = (float)ReadNumber(designed, "height", sign.Height);
                sign.Scale = (float)ReadNumber(designed, "scale", 1);
                sign.Turn = (float)ReadNumber(designed, "turn", sign.Turn);
                double passAtBeat = ReadNumber(designed, "passAt", double.NaN);
                if (!double.IsNaN(passAtBeat)) sign.PassAt = BeatToSeconds(passAtBeat, beatsPerMinute);
                sign.Opacity = (float)ReadNumber(designed, "opacity", sign.Opacity);
                sign.Outline = (float)ReadNumber(designed, "outline", sign.Outline);
                sign.LetterSpacing = (float)ReadNumber(designed, "spacing", sign.LetterSpacing);
                sign.BeatPulse = ReadBool(designed, "pulse", sign.BeatPulse);
                if (ReadString(designed, "font") != "") sign.Font = ReadString(designed, "font");
                if (ReadString(designed, "reveal") != "") sign.Reveal = ReadString(designed, "reveal");
                if (ReadString(designed, "enter") != "") sign.EnterEffect = ReadString(designed, "enter");
                if (ReadString(designed, "exit") != "") sign.ExitEffect = ReadString(designed, "exit");
                if (ReadString(designed, "anchor") == "world" && designed.TryGetProperty("position", out var position))
                {
                    sign.FixedInWorld = true;
                    sign.WorldPosition = new Vector3((float)ReadNumber(position, "x", 0), (float)ReadNumber(position, "y", 0), (float)ReadNumber(position, "z", 0));
                    sign.WorldYaw = (float)ReadNumber(designed, "yaw", 0);
                    sign.WorldTilt = (float)ReadNumber(designed, "tilt", 0);
                    sign.AppearAt = BeatToSeconds(ReadNumber(designed, "appear", startBeat - 8), beatsPerMinute);
                    sign.DisappearAt = BeatToSeconds(ReadNumber(designed, "disappear", startBeat + 8), beatsPerMinute);
                }
                if (designed.TryGetProperty("gradient", out var gradient) && gradient.ValueKind == JsonValueKind.Array && gradient.GetArrayLength() == 2)
                {
                    sign.GradientTop = gradient[0].GetString() ?? "";
                    sign.GradientBottom = gradient[1].GetString() ?? "";
                }
                if (designed.TryGetProperty("lines", out var lines))
                {
                    foreach (var line in lines.EnumerateArray())
                    {
                        sign.Lines.Add(new SignLine
                        {
                            Text = ReadString(line, "text"),
                            RelativeSize = (float)ReadNumber(line, "size", 1.0),
                            Color = ReadString(line, "color") != "" ? ReadString(line, "color") : "#ffffff",
                            Bold = ReadBool(line, "bold", true),
                            Italic = ReadBool(line, "italic", false),
                        });
                    }
                }
                if (sign.TotalCharacters > 0) signs.Add(sign);
            }
            return signs;
        }

        /// <summary>One sign per visible lyric line, alternating sides of the road.</summary>
        List<SignSpec> BuildAutoSigns(JsonElement chart, JsonElement lyrics, double beatsPerMinute)
        {
            bool candidateRowHidden = true;
            string defaultColor = "#ffffff";
            if (chart.TryGetProperty("lyricSettings", out var lyricSettings))
            {
                if (lyricSettings.TryGetProperty("draftRowHidden", out var draftHidden) && draftHidden.ValueKind == JsonValueKind.False)
                    candidateRowHidden = false;
                if (ReadString(lyricSettings, "color") != "") defaultColor = ReadString(lyricSettings, "color");
            }
            // Charts made with the Lyric FX tool keep their original, un-animated lines in "lyricFxSource".
            var lyricLines = chart.TryGetProperty("lyricFxSource", out var originalLines) ? originalLines : lyrics;

            var signs = new List<SignSpec>();
            int side = 1;
            foreach (var lyric in lyricLines.EnumerateArray().OrderBy(line => ReadNumber(line, "beat", 0)))
            {
                if ((int)ReadNumber(lyric, "row", 1) == 0 && candidateRowHidden) continue;   // hidden draft row
                string text = ReadString(lyric, "text").Trim();
                if (text.Length == 0) continue;
                if (settings.UppercaseAuto) text = text.ToUpperInvariant();
                string color = ReadString(lyric, "color") != "" ? ReadString(lyric, "color") : defaultColor;

                var sign = settings.NewSignWithDefaults();
                double startBeat = ReadNumber(lyric, "beat", 0);
                sign.SungStart = BeatToSeconds(startBeat, beatsPerMinute);
                sign.SungEnd = BeatToSeconds(startBeat + ReadNumber(lyric, "duration", 2), beatsPerMinute);
                sign.Side = side;
                sign.Lines = StackIntoLines(text, color);
                signs.Add(sign);
                side = -side;
            }
            return signs;
        }

        /// <summary>Title-card stacking: "AT THE END" over "of the night" - two lines, the shorter one bigger.</summary>
        static List<SignLine> StackIntoLines(string text, string color)
        {
            var words = text.Split(' ', StringSplitOptions.RemoveEmptyEntries);
            if (words.Length < 3 || text.Length < 12)
                return new List<SignLine> { new SignLine { Text = text, RelativeSize = 1.25f, Color = color } };

            int splitAt = words.Length / 2;
            string firstLine = string.Join(' ', words.Take(splitAt));
            string secondLine = string.Join(' ', words.Skip(splitAt));
            bool firstIsBigger = firstLine.Length <= secondLine.Length;
            return new List<SignLine>
            {
                new SignLine { Text = firstLine, RelativeSize = firstIsBigger ? 1.35f : 0.85f, Color = color },
                new SignLine { Text = secondLine, RelativeSize = firstIsBigger ? 0.85f : 1.35f, Color = color },
            };
        }

        // ------------------------------------------------------------- JSON helpers

        static double BeatToSeconds(double beat, double beatsPerMinute) => beat * 60.0 / beatsPerMinute;

        public static string ReadString(JsonElement element, string name) =>
            element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";

        static double ReadNumber(JsonElement element, string name, double fallback) =>
            element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var number)
                ? number : fallback;

        static bool ReadBool(JsonElement element, string name, bool fallback) =>
            element.TryGetProperty(name, out var value)
                ? value.ValueKind == JsonValueKind.True || (value.ValueKind != JsonValueKind.False && fallback)
                : fallback;

        /// <summary>Lowercase letters and digits only, so "We Found Love (5).mp3" and "we found love 5" compare equal.</summary>
        static string SimplifyName(string name) => new string((name ?? "").ToLowerInvariant().Where(char.IsLetterOrDigit).ToArray());
    }
}
