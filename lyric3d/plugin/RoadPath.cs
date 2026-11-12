using System.IO;
using System.Text.Json;
using UnityEngine;

namespace BfsLyric3D
{
    /// <summary>
    /// The centreline of one game track in world space, loaded from the chart editor's
    /// Tools/chart_editor/track_previews/&lt;scene&gt;.json (data exported from the game itself).
    /// Positions along the road are measured in metres from the start ("road distance").
    /// </summary>
    public class RoadPath
    {
        public string Name;
        public bool Loops;
        public float TotalLength;

        Vector3[] pointPositions;
        Vector3[] pointDirections;
        float[] pointDistances;
        int lastNearestPoint;   // search starts here next time, since the car moves a little each frame

        public static RoadPath Load(string filePath)
        {
            using var document = JsonDocument.Parse(File.ReadAllText(filePath));
            var root = document.RootElement;
            var samples = root.GetProperty("samples");
            int count = samples.GetArrayLength();

            var road = new RoadPath
            {
                Name = Path.GetFileNameWithoutExtension(filePath),
                Loops = root.TryGetProperty("loop", out var loop) && loop.ValueKind == JsonValueKind.True,
                TotalLength = (float)root.GetProperty("totalLength").GetDouble(),
                pointPositions = new Vector3[count],
                pointDirections = new Vector3[count],
                pointDistances = new float[count],
            };
            int index = 0;
            foreach (var sample in samples.EnumerateArray())
            {
                road.pointDistances[index] = ReadFloat(sample, "distance");
                road.pointPositions[index] = new Vector3(ReadFloat(sample, "x"), ReadFloat(sample, "y"), ReadFloat(sample, "z"));
                road.pointDirections[index] = new Vector3(ReadFloat(sample, "dx"), ReadFloat(sample, "dy"), ReadFloat(sample, "dz")).normalized;
                index++;
            }
            return road;
        }

        static float ReadFloat(JsonElement element, string name) => (float)element.GetProperty(name).GetDouble();

        /// <summary>
        /// Road distance of the centreline point nearest to <paramref name="worldPosition"/>,
        /// plus how far the position is from the centreline. Searches near the last result unless told otherwise.
        /// </summary>
        public float FindRoadDistance(Vector3 worldPosition, out float metresOffCentre, bool searchWholeRoad = false)
        {
            int count = pointPositions.Length;
            int nearest = lastNearestPoint;
            float nearestSquaredDistance = float.MaxValue;
            int searchFrom = searchWholeRoad ? 0 : lastNearestPoint - 40;
            int searchTo = searchWholeRoad ? count : lastNearestPoint + 40;
            for (int step = searchFrom; step < searchTo; step++)
            {
                int index = ((step % count) + count) % count;
                float squaredDistance = (pointPositions[index] - worldPosition).sqrMagnitude;
                if (squaredDistance < nearestSquaredDistance) { nearestSquaredDistance = squaredDistance; nearest = index; }
            }
            lastNearestPoint = nearest;

            // refine between the nearest point and the next one
            int next = (nearest + 1) % count;
            Vector3 segment = pointPositions[next] - pointPositions[nearest];
            float along = segment.sqrMagnitude > 1e-6f
                ? Mathf.Clamp01(Vector3.Dot(worldPosition - pointPositions[nearest], segment) / segment.sqrMagnitude)
                : 0f;
            metresOffCentre = (pointPositions[nearest] + segment * along - worldPosition).magnitude;
            float segmentLength = next > nearest ? pointDistances[next] - pointDistances[nearest] : segment.magnitude;
            return pointDistances[nearest] + along * segmentLength;
        }

        /// <summary>World position and travel direction of the centreline at a road distance.</summary>
        public void PointAt(float roadDistance, out Vector3 position, out Vector3 direction)
        {
            if (Loops && TotalLength > 0)
            {
                roadDistance %= TotalLength;
                if (roadDistance < 0) roadDistance += TotalLength;
            }
            int last = pointDistances.Length - 1;
            if (roadDistance <= pointDistances[0]) { position = pointPositions[0]; direction = pointDirections[0]; return; }
            if (roadDistance >= pointDistances[last]) { position = pointPositions[last]; direction = pointDirections[last]; return; }

            int low = 0, high = last;   // binary search for the two points around roadDistance
            while (high - low > 1)
            {
                int middle = (low + high) / 2;
                if (pointDistances[middle] <= roadDistance) low = middle; else high = middle;
            }
            float blend = (roadDistance - pointDistances[low]) / Mathf.Max(1e-4f, pointDistances[high] - pointDistances[low]);
            position = Vector3.Lerp(pointPositions[low], pointPositions[high], blend);
            direction = Vector3.Slerp(pointDirections[low], pointDirections[high], blend).normalized;
        }

        /// <summary>Centreline points roughly every <paramref name="spacing"/> metres (for distance checks).</summary>
        public System.Collections.Generic.List<Vector3> SamplePoints(float spacing)
        {
            var points = new System.Collections.Generic.List<Vector3>();
            float lastDistance = float.MinValue;
            for (int index = 0; index < pointPositions.Length; index++)
            {
                if (pointDistances[index] - lastDistance < spacing) continue;
                points.Add(pointPositions[index]);
                lastDistance = pointDistances[index];
            }
            return points;
        }

        /// <summary>How far <paramref name="to"/> is ahead of <paramref name="from"/> along the road (negative = behind; handles looping).</summary>
        public float DistanceAhead(float from, float to)
        {
            float ahead = to - from;
            if (Loops && TotalLength > 0)
            {
                ahead %= TotalLength;
                if (ahead < -TotalLength / 2) ahead += TotalLength;
                if (ahead > TotalLength / 2) ahead -= TotalLength;
            }
            return ahead;
        }
    }
}
