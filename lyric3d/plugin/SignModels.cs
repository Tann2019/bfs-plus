using System.Collections.Generic;
using System.Linq;
using Il2CppTMPro;
using UnityEngine;

namespace BfsLyric3D
{
    /// <summary>One line of text on a sign (a sign can stack several, e.g. "AT THE END" over "of the night").</summary>
    public class SignLine
    {
        public string Text = "";
        public float RelativeSize = 1f;     // 1 = 100%
        public string Color = "#ffffff";
        public bool Bold = true;
        public bool Italic;
    }

    /// <summary>What a sign says, when it is sung, where it stands and how it looks.</summary>
    public class SignSpec
    {
        // timing (seconds into the song)
        public double SungStart, SungEnd;
        public double RevealStart = double.NaN, RevealEnd = double.NaN;   // optional typewriter/karaoke window (seconds)

        // content
        public List<SignLine> Lines = new();
        public int TotalCharacters => Lines.Sum(line => line.Text.Length);

        // placement: "road" signs stand beside the road where the rider is while the line is sung;
        // "world" signs stand at a fixed spot (designed in the editor's 3D Lyric Designer)
        public bool FixedInWorld;
        public Vector3 WorldPosition;
        public float WorldYaw, WorldTilt;   // degrees; the reader looks along the sign's facing
        public double AppearAt, DisappearAt;   // seconds into the song (world signs only)

        public int Side = 1;                // -1 left of the road, 1 right, 0 over the road
        public float SideDistance = 15f;    // metres from the road centre (when no wall is found)
        public float Height = 7f;           // metres above the road
        public float Scale = 1f;
        public double PassAt = double.NaN;  // placed by hand in the designer: drive past it at this second (no TimeOffset)
        public float Turn = 60f;            // 0 = faces the oncoming driver, 90 = parallel to the road

        // look
        public string Font = "";
        public float Opacity = 1f, Outline = 0.15f, LetterSpacing;
        public string GradientTop = "", GradientBottom = "";
        public bool HasGradient => GradientTop != "" && GradientBottom != "";
        public string Reveal = "none";      // none | typewriter | karaoke
        public bool BeatPulse;
        public string EnterEffect = "rise"; // rise | fade | pop | drop
        public string ExitEffect = "fade";  // fade | dissolve | shrink | rise
    }

    /// <summary>A sign that currently exists in the game world.</summary>
    public class LiveSign
    {
        public SignSpec Spec;
        public GameObject Root;
        public TextMeshProUGUI Text;

        public float RoadDistance;          // where along the road it stands (metres)
        public Vector3 Position;
        public Quaternion Rotation;
        public bool LockedInPlace;          // stops re-aiming once the car is close
        public bool MountedOnWall;
        public bool HasWall;
        public UnityEngine.RaycastHit Wall;
        public float WallCheckedAtRoadDistance = float.NaN;   // walls are looked for again only after moving a few metres
        public bool ShownPoseReady;                           // the pose actually drawn glides toward Position/Rotation
        public Vector3 ShownPosition;
        public Quaternion ShownRotation;

        public double AppearedAtSongTime;
        public double ExitStartedAtSongTime = -1;
        public int[] DissolveOrder;          // random order characters disappear in, for the dissolve exit
        public string LastRichText;          // avoids re-layouting text that did not change
    }
}
