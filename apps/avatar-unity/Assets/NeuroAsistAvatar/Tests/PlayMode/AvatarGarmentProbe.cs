using System.Collections.Generic;
using UnityEngine;

namespace NeuroAsist.Avatar.Tests
{
    // Independent of AvatarTorsoEnvelope: ray tests against the final skinned
    // garment triangles, including collar geometry and shoulder deformation.
    internal sealed class AvatarGarmentProbe
    {
        private sealed class Surface
        {
            public SkinnedMeshRenderer Renderer;
            public Mesh Baked = new Mesh();
            public int[] Triangles;
        }
        private struct Triangle { public Vector3 A, B, C; public Vector2 Min, Max; }
        private readonly List<Surface> surfaces = new List<Surface>();
        private readonly List<Triangle> triangles = new List<Triangle>();
        private readonly Dictionary<Vector2Int,List<int>> grid = new Dictionary<Vector2Int,List<int>>();
        private static Vector2Int Cell(Vector2 p) => new Vector2Int(Mathf.FloorToInt(p.x * 50),Mathf.FloorToInt(p.y * 50));
        private readonly Animator animator;
        private readonly Transform root;
        private readonly Vector3 localRight, localUp, localFront;
        public int TriangleCount => triangles.Count;
        public AvatarGarmentProbe(Animator value, Camera camera)
        {
            animator = value; root = value.transform;
            var front = Vector3.ProjectOnPlane(camera.transform.position - value.GetBoneTransform(HumanBodyBones.Head).position, root.up).normalized;
            var right = (value.GetBoneTransform(HumanBodyBones.RightUpperArm).position - value.GetBoneTransform(HumanBodyBones.LeftUpperArm).position).normalized;
            localRight = root.InverseTransformDirection(right); localUp = root.InverseTransformDirection(root.up); localFront = root.InverseTransformDirection(front);
            var torsoBones = new HashSet<Transform>();
            foreach (var id in new[] { HumanBodyBones.Hips, HumanBodyBones.Spine, HumanBodyBones.Chest, HumanBodyBones.UpperChest }) torsoBones.Add(value.GetBoneTransform(id));
            foreach (var renderer in value.GetComponentsInChildren<SkinnedMeshRenderer>())
            {
                var mesh = renderer.sharedMesh; var weights = mesh.boneWeights; var bones = renderer.bones;
                if (weights.Length != mesh.vertexCount) continue;
                var allowed = new bool[weights.Length];
                for (var i = 0; i < weights.Length; i++)
                {
                    var w = weights[i]; var weight = 0f;
                    if (w.boneIndex0 < bones.Length && torsoBones.Contains(bones[w.boneIndex0])) weight += w.weight0;
                    if (w.boneIndex1 < bones.Length && torsoBones.Contains(bones[w.boneIndex1])) weight += w.weight1;
                    if (w.boneIndex2 < bones.Length && torsoBones.Contains(bones[w.boneIndex2])) weight += w.weight2;
                    if (w.boneIndex3 < bones.Length && torsoBones.Contains(bones[w.boneIndex3])) weight += w.weight3;
                    allowed[i] = weight >= .85f;
                }
                var source = mesh.triangles; var selected = new List<int>();
                for (var i = 0; i < source.Length; i += 3)
                    if (allowed[source[i]] && allowed[source[i+1]] && allowed[source[i+2]])
                    { selected.Add(source[i]); selected.Add(source[i+1]); selected.Add(source[i+2]); }
                if (selected.Count > 0) surfaces.Add(new Surface { Renderer = renderer, Triangles = selected.ToArray() });
            }
        }
        private Vector3 ToFrame(Vector3 world)
        { var p = root.InverseTransformPoint(world); return new Vector3(Vector3.Dot(p, localRight), Vector3.Dot(p, localUp), Vector3.Dot(p, localFront)); }
        public void Bake()
        {
            triangles.Clear();
            foreach (var cell in grid.Values) cell.Clear();
            foreach (var surface in surfaces)
            {
                surface.Renderer.BakeMesh(surface.Baked);
                var vertices = surface.Baked.vertices;
                for (var i = 0; i < vertices.Length; i++) vertices[i] = ToFrame(surface.Renderer.transform.TransformPoint(vertices[i]));
                for (var i = 0; i < surface.Triangles.Length; i += 3)
                {
                    var a = vertices[surface.Triangles[i]]; var b = vertices[surface.Triangles[i+1]]; var c = vertices[surface.Triangles[i+2]];
                    if (Mathf.Abs(Vector3.Cross(b-a,c-a).z) < .0000001f) continue;
                    triangles.Add(new Triangle { A = a, B = b, C = c, Min = Vector2.Min(a,Vector2.Min(b,c)), Max = Vector2.Max(a,Vector2.Max(b,c)) });
                    var triangle = triangles[triangles.Count-1]; var min = Cell(triangle.Min); var max = Cell(triangle.Max);
                    for (var x = min.x; x <= max.x; x++) for (var y = min.y; y <= max.y; y++)
                    {
                        var key = new Vector2Int(x,y);
                        if (!grid.TryGetValue(key,out var indices)) { indices = new List<int>(); grid.Add(key,indices); }
                        indices.Add(triangles.Count-1);
                    }
                }
            }
        }
        private float Clearance(Vector3 world, float radius)
        {
            var p = ToFrame(world); var front = float.NegativeInfinity; var back = float.PositiveInfinity;
            if (!grid.TryGetValue(Cell(p),out var indices)) return float.PositiveInfinity;
            foreach (var index in indices)
            {
                var tri = triangles[index];
                if (p.x < tri.Min.x || p.x > tri.Max.x || p.y < tri.Min.y || p.y > tri.Max.y) continue;
                var a = tri.A; var b = tri.B; var c = tri.C;
                var divisor = (b.y-c.y)*(a.x-c.x)+(c.x-b.x)*(a.y-c.y);
                var u = ((b.y-c.y)*(p.x-c.x)+(c.x-b.x)*(p.y-c.y))/divisor;
                var v = ((c.y-a.y)*(p.x-c.x)+(a.x-c.x)*(p.y-c.y))/divisor;
                if (u < 0 || v < 0 || u+v > 1) continue;
                var depth = a.z*u+b.z*v+c.z*(1-u-v);
                front = Mathf.Max(front,depth); back = Mathf.Min(back,depth);
            }
            // Both sides matter: an arm resting behind the shirt is outside it,
            // not penetrating it just because the front surface is ahead.
            return float.IsNegativeInfinity(front) ? float.PositiveInfinity : Mathf.Max(p.z-front,back-p.z)-radius;
        }
        public float Measure(bool left)
        {
            var elbow = animator.GetBoneTransform(left ? HumanBodyBones.LeftLowerArm : HumanBodyBones.RightLowerArm);
            var hand = animator.GetBoneTransform(left ? HumanBodyBones.LeftHand : HumanBodyBones.RightHand);
            var result = float.PositiveInfinity;
            for (var i = 0; i <= 12; i++) result = Mathf.Min(result,Clearance(Vector3.Lerp(elbow.position,hand.position,i/12f),.018f));
            for (var id = left ? HumanBodyBones.LeftThumbProximal : HumanBodyBones.RightThumbProximal; id <= (left ? HumanBodyBones.LeftLittleDistal : HumanBodyBones.RightLittleDistal); id++)
            { var finger = animator.GetBoneTransform(id); if (finger != null) result = Mathf.Min(result,Clearance(finger.position,.008f)); }
            return result;
        }
        public void Dispose() { foreach (var surface in surfaces) Object.Destroy(surface.Baked); }
    }
}
