using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using Il2CppTMPro;
using UnityEngine;

namespace BfsLyric3D
{
    /// <summary>Builds the TextMeshPro rich text for a sign and finds fonts.</summary>
    public class SignText
    {
        readonly Settings settings;
        readonly Action<string> log;
        readonly Dictionary<string, TMP_FontAsset> fontCache = new();
        bool gameFontsListed;

        public SignText(Settings settings, Action<string> log)
        {
            this.settings = settings;
            this.log = log;
        }

        /// <summary>
        /// Rich text for a sign. <paramref name="visibleCharacters"/> drives the typewriter reveal,
        /// <paramref name="sungCharacters"/> the karaoke highlight, <paramref name="dissolvedCharacters"/> the dissolve exit.
        /// Characters that are not shown are made fully transparent rather than removed, so the layout never shifts.
        /// </summary>
        public static string BuildRichText(SignSpec sign, int visibleCharacters, int sungCharacters, HashSet<int> dissolvedCharacters)
        {
            var text = new StringBuilder("<line-height=88%>");
            int characterIndex = 0;
            for (int lineIndex = 0; lineIndex < sign.Lines.Count; lineIndex++)
            {
                var line = sign.Lines[lineIndex];
                if (lineIndex > 0) text.Append('\n');
                text.Append($"<size={(int)(line.RelativeSize * 100)}%>");
                if (line.Bold) text.Append("<b>");
                if (line.Italic) text.Append("<i>");
                // With a gradient, letters are white so the gradient shows through.
                string baseColor = sign.HasGradient ? "#ffffff" : (line.Color.Length == 7 ? line.Color : "#ffffff");

                foreach (char character in line.Text)
                {
                    bool shown = characterIndex < visibleCharacters
                                 && (dissolvedCharacters == null || !dissolvedCharacters.Contains(characterIndex));
                    bool notYetSung = sign.Reveal == "karaoke" && characterIndex >= sungCharacters;
                    string alphaHex = !shown ? "00" : notYetSung ? "6e" : "ff";
                    text.Append("<color=").Append(baseColor).Append(alphaHex).Append('>')
                        .Append(EscapeRichText(character.ToString()))
                        .Append("</color>");
                    characterIndex++;
                }

                if (line.Italic) text.Append("</i>");
                if (line.Bold) text.Append("</b>");
                text.Append("</size>");
            }
            return text.ToString();
        }

        static string EscapeRichText(string text) => text.Replace("<", "&lt;").Replace(">", "&gt;");

        /// <summary>
        /// A font by name: a font already in the game, else an installed Windows font, else the game's lyric font.
        /// Results are cached per name.
        /// </summary>
        public TMP_FontAsset GetFont(string fontName)
        {
            fontName ??= "";
            if (fontCache.TryGetValue(fontName, out var cachedFont)) return cachedFont;

            var gameFonts = Resources.FindObjectsOfTypeAll<TMP_FontAsset>();
            if (!gameFontsListed)
            {
                gameFontsListed = true;
                log("game fonts: " + string.Join(", ", gameFonts.Where(font => font != null).Select(font => font.name).Distinct()));
            }

            TMP_FontAsset chosenFont = null;
            if (fontName != "")
            {
                chosenFont = gameFonts.FirstOrDefault(font => font != null && font.name.IndexOf(fontName, StringComparison.OrdinalIgnoreCase) >= 0);
                if (chosenFont == null) chosenFont = LoadWindowsFont(fontName);
                if (chosenFont == null) log($"font '{fontName}' not found - using the game's lyric font");
            }
            chosenFont ??= FindGameLyricFont();
            fontCache[fontName] = chosenFont;
            if (settings.DebugLog)
                log($"font '{(fontName == "" ? "(default)" : fontName)}' -> {(chosenFont != null ? chosenFont.name : "TextMeshPro default")}");
            return chosenFont;
        }

        TMP_FontAsset LoadWindowsFont(string fontName)
        {
            try
            {
                var windowsFont = Font.CreateDynamicFontFromOSFont(fontName, 90);
                if (windowsFont == null) return null;
                var fontAsset = TMP_FontAsset.CreateFontAsset(windowsFont);
                if (fontAsset != null) fontAsset.name = fontName;
                return fontAsset;
            }
            catch (Exception error)
            {
                log($"Windows font '{fontName}' could not be loaded: {error.Message}");
                return null;
            }
        }

        static TMP_FontAsset FindGameLyricFont()
        {
            var lyricsDisplay = UnityEngine.Object.FindFirstObjectByType<Il2Cpp.ChartLyricsDisplay>();
            var lyricText = lyricsDisplay != null ? lyricsDisplay.GetComponentInChildren<TMP_Text>(true) : null;
            if (lyricText != null && lyricText.font != null) return lyricText.font;
            foreach (var anyText in UnityEngine.Object.FindObjectsByType<TMP_Text>(FindObjectsInactive.Include, FindObjectsSortMode.None))
                if (anyText != null && anyText.font != null) return anyText.font;
            return null;
        }
    }
}
