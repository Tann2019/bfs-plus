using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using UnityEngine;

namespace BfsLyric3D
{
    /// <summary>
    /// Saves the buildings and other large scenery near the road as simple boxes, so the chart
    /// editor's 3D Lyric Designer can show them (the editor's own track data only has the road,
    /// bridges and a few landmarks). Written once per track to
    /// Tools/chart_editor/scene_context/&lt;track&gt;.json; delete that file to export it again.
    /// </summary>
    public class SceneExporter
    {
        const float MaxDistanceFromRoad = 260f;   // metres; scenery further out is not useful for placing lyrics
        const float MinimumSize = 2.5f;           // ignore small props
        const float MaximumSize = 600f;           // ignore terrain-sized and whole-scene meshes
        const int MaximumBoxes = 6000;

        readonly Action<string> log;
        readonly HashSet<string> exportedThisSession = new();

        public SceneExporter(Action<string> log) => this.log = log;

        public static string ContextFolder =>
            Path.Combine(Directory.GetParent(Application.dataPath).FullName, "Tools", "chart_editor", "scene_context");

        public bool NeedsExport(RoadPath road) =>
            road != null && !exportedThisSession.Contains(road.Name) && !File.Exists(Path.Combine(ContextFolder, road.Name + ".json"));

        public void Export(RoadPath road)
        {
            exportedThisSession.Add(road.Name);
            var started = DateTime.Now;
            var roadPoints = road.SamplePoints(4f);
            var boxes = new List<(float distance, string json)>();

            foreach (var renderer in UnityEngine.Object.FindObjectsByType<MeshRenderer>(FindObjectsSortMode.None))
            {
                if (renderer == null || !renderer.enabled || !renderer.gameObject.activeInHierarchy) continue;
                if (renderer.GetComponentInParent<Rigidbody>() != null) continue;   // cars and other moving things

                if (!TryGetBox(renderer, out Vector3 centre, out Vector3 axisX, out Vector3 axisY, out Vector3 axisZ)) continue;
                float largest = Mathf.Max(axisX.magnitude, axisY.magnitude, axisZ.magnitude) * 2f;
                if (largest < MinimumSize || largest > MaximumSize) continue;

                float nearestRoad = NearestHorizontalDistance(centre, roadPoints) - largest / 2f;
                if (nearestRoad > MaxDistanceFromRoad) continue;

                boxes.Add((nearestRoad, BoxJson(renderer.gameObject.name, centre, axisX, axisY, axisZ)));
            }

            var kept = boxes.OrderBy(box => box.distance).Take(MaximumBoxes).Select(box => box.json).ToList();
            Directory.CreateDirectory(ContextFolder);
            string path = Path.Combine(ContextFolder, road.Name + ".json");
            File.WriteAllText(path, "{\"version\":1,\"track\":\"" + road.Name + "\",\"boxes\":[\n" + string.Join(",\n", kept) + "\n]}");
            log($"exported {kept.Count} scenery boxes for '{road.Name}' to {path} in {(DateTime.Now - started).TotalMilliseconds:F0} ms");
        }

        /// <summary>
        /// A box around the renderer: rotated with the object when its mesh is its own, otherwise
        /// (statically batched meshes) the world-aligned bounds. Axes are half-extent vectors.
        /// </summary>
        static bool TryGetBox(MeshRenderer renderer, out Vector3 centre, out Vector3 axisX, out Vector3 axisY, out Vector3 axisZ)
        {
            var filter = renderer.GetComponent<MeshFilter>();
            var mesh = filter != null ? filter.sharedMesh : null;
            bool ownMesh = mesh != null && !(mesh.name ?? "").StartsWith("Combined Mesh", StringComparison.Ordinal);
            if (ownMesh)
            {
                var local = mesh.bounds;
                var transform = renderer.transform;
                centre = transform.TransformPoint(local.center);
                axisX = transform.TransformVector(new Vector3(local.extents.x, 0, 0));
                axisY = transform.TransformVector(new Vector3(0, local.extents.y, 0));
                axisZ = transform.TransformVector(new Vector3(0, 0, local.extents.z));
            }
            else
            {
                var world = renderer.bounds;
                centre = world.center;
                axisX = new Vector3(world.extents.x, 0, 0);
                axisY = new Vector3(0, world.extents.y, 0);
                axisZ = new Vector3(0, 0, world.extents.z);
            }
            return float.IsFinite(centre.x) && float.IsFinite(axisX.x);
        }

        static float NearestHorizontalDistance(Vector3 position, List<Vector3> roadPoints)
        {
            float nearest = float.MaxValue;
            foreach (var point in roadPoints)
            {
                float dx = point.x - position.x, dz = point.z - position.z;
                float squared = dx * dx + dz * dz;
                if (squared < nearest) nearest = squared;
            }
            return Mathf.Sqrt(nearest);
        }

        static string BoxJson(string name, Vector3 centre, Vector3 axisX, Vector3 axisY, Vector3 axisZ)
        {
            string Number(float value) => value.ToString("0.##", CultureInfo.InvariantCulture);
            string Vector(Vector3 value) => $"[{Number(value.x)},{Number(value.y)},{Number(value.z)}]";
            string safeName = (name ?? "").Replace("\\", "/").Replace("\"", "'");
            if (safeName.Length > 40) safeName = safeName.Substring(0, 40);
            return $"{{\"name\":\"{safeName}\",\"center\":{Vector(centre)},\"halfX\":{Vector(axisX)},\"halfY\":{Vector(axisY)},\"halfZ\":{Vector(axisZ)}}}";
        }
    }
}
