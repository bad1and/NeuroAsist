using System.Collections.Generic;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    /// <summary>Clothed torso cross sections, fitted once from torso-weighted mesh vertices.</summary>
    internal sealed class AvatarTorsoEnvelope
    {
        private struct Section { public float Y, X, Z, CenterZ; }
        private readonly List<Section> sections = new List<Section>();
        private readonly Transform reference;
        private readonly Vector3 origin, right, up, front;
        public int SampleCount { get; private set; }
        public AvatarTorsoEnvelope(Animator animator, Vector3 worldFront, Vector3 worldRight)
        {
            reference = animator.GetBoneTransform(HumanBodyBones.Chest) ?? animator.GetBoneTransform(HumanBodyBones.Spine);
            origin = reference.InverseTransformPoint(animator.GetBoneTransform(HumanBodyBones.Hips).position);
            right = reference.InverseTransformDirection(worldRight).normalized;
            up = reference.InverseTransformDirection(animator.transform.up).normalized;
            front = reference.InverseTransformDirection(worldFront).normalized;
            var torsoBones = new HashSet<Transform>();
            foreach (var bone in new[] { HumanBodyBones.Hips, HumanBodyBones.Spine, HumanBodyBones.Chest, HumanBodyBones.UpperChest })
            { var transform = animator.GetBoneTransform(bone); if (transform != null) torsoBones.Add(transform); }
            var points = new List<Vector3>();
            var top = ToFrame(animator.GetBoneTransform(HumanBodyBones.Neck).position).y - .045f;
            foreach (var renderer in animator.GetComponentsInChildren<SkinnedMeshRenderer>())
            {
                var weights = renderer.sharedMesh.boneWeights;
                if (weights.Length != renderer.sharedMesh.vertexCount) continue;
                var mesh = new Mesh(); renderer.BakeMesh(mesh); var vertices = mesh.vertices; var bones = renderer.bones;
                for (var i = 0; i < vertices.Length; i++)
                {
                    var w = weights[i]; var weight = 0f;
                    if (w.boneIndex0 < bones.Length && torsoBones.Contains(bones[w.boneIndex0])) weight += w.weight0;
                    if (w.boneIndex1 < bones.Length && torsoBones.Contains(bones[w.boneIndex1])) weight += w.weight1;
                    if (w.boneIndex2 < bones.Length && torsoBones.Contains(bones[w.boneIndex2])) weight += w.weight2;
                    if (w.boneIndex3 < bones.Length && torsoBones.Contains(bones[w.boneIndex3])) weight += w.weight3;
                    if (weight < .70f) continue;
                    var point = ToFrame(renderer.transform.TransformPoint(vertices[i]));
                    if (point.y >= -.075f && point.y <= top + .03f) points.Add(point);
                }
                Object.Destroy(mesh);
            }
            SampleCount = points.Count;
            for (var i = 0; i < 25; i++)
            {
                var y = Mathf.Lerp(-.06f, top, i / 24f);
                var x = .075f; var zMin = -.055f; var zMax = .055f;
                foreach (var point in points) if (Mathf.Abs(point.y - y) < .014f)
                { x = Mathf.Max(x, Mathf.Abs(point.x)); zMin = Mathf.Min(zMin, point.z); zMax = Mathf.Max(zMax, point.z); }
                sections.Add(new Section { Y = y, X = x + .008f, Z = (zMax - zMin) * .5f + .010f, CenterZ = (zMax + zMin) * .5f });
            }
        }
        public Vector3 ToFrame(Vector3 world)
        { var offset = reference.InverseTransformPoint(world) - origin; return new Vector3(Vector3.Dot(offset, right), Vector3.Dot(offset, up), Vector3.Dot(offset, front)); }
        public Vector3 FromFrame(Vector3 frame) => reference.TransformPoint(origin + right * frame.x + up * frame.y + front * frame.z);
        public Vector3 DirectionToWorld(Vector3 direction) => reference.TransformDirection(right * direction.x + up * direction.y + front * direction.z).normalized;
        private Section At(float y)
        {
            if (y <= sections[0].Y) return sections[0];
            if (y >= sections[sections.Count-1].Y) return sections[sections.Count-1];
            var index = (y-sections[0].Y)/(sections[sections.Count-1].Y-sections[0].Y)*(sections.Count-1);
            var lower = Mathf.Min(Mathf.FloorToInt(index),sections.Count-2);
            var a = sections[lower]; var b = sections[lower+1]; var t = index-lower;
            return new Section { Y = y, X = Mathf.Lerp(a.X,b.X,t), Z = Mathf.Lerp(a.Z,b.Z,t), CenterZ = Mathf.Lerp(a.CenterZ,b.CenterZ,t) };
        }
        public float FrontAt(float y) { var section = At(y); return section.CenterZ + section.Z; }
        public float BackAt(float y) { var section = At(y); return section.CenterZ - section.Z; }
        public float WidthAt(float y) => At(y).X;
        public Vector3 RestRoute(Vector3 source, float side, float handRadius)
        {
            // Hang beside the hips, with a little rear clearance for the skirt.
            // Do not gather the wrists at the back centreline: that pulls the
            // sleeves behind the chest and collapses the front silhouette.
            return new Vector3(side*.17f,-.015f,-.15f);
        }
        public float Distance(Vector3 point)
        {
            var section = At(point.y);
            var p = new Vector2(point.x, point.z - section.CenterZ);
            var k0 = new Vector2(p.x / section.X, p.y / section.Z).magnitude;
            var k1 = new Vector2(p.x / (section.X * section.X), p.y / (section.Z * section.Z)).magnitude;
            var radial = k1 > .00001f ? k0 * (k0 - 1) / k1 : -Mathf.Min(section.X, section.Z);
            var vertical = Mathf.Max(sections[0].Y - point.y, point.y - sections[sections.Count - 1].Y);
            return Mathf.Max(radial, vertical);
        }
        public string Describe()
        {
            var result = "";
            foreach (var section in sections) result += $"y={section.Y:F3} width={section.X:F3} depth={section.Z:F3} centerZ={section.CenterZ:F3}\n";
            return result;
        }
        public Vector3 FrontRoute(Vector3 point, float margin)
        {
            var section = At(point.y);
            if (point.y > sections[0].Y - .03f && point.y < sections[sections.Count - 1].Y + .04f && Mathf.Abs(point.x) < section.X + .055f)
                point.z = Mathf.Max(point.z, section.CenterZ + section.Z + margin);
            return Project(point, .055f);
        }
        public Vector3 Project(Vector3 point, float margin)
        {
            if (Distance(point) >= margin) return point;
            var section = At(point.y);
            var direction = new Vector2(point.x / section.X, (point.z-section.CenterZ)/section.Z);
            if (direction.sqrMagnitude < .0001f) direction = Vector2.up;
            direction.Normalize();
            point.x = direction.x * (section.X + margin + .004f);
            point.z = section.CenterZ + direction.y * (section.Z + margin + .004f);
            return point;
        }
    }
}
