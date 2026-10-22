using System.Collections.Generic;
using UnityEngine;
using UniVRM10;

namespace NeuroAsist.Avatar
{
    /// <summary>A full-body welcome scene driven by an imported seated Humanoid clip.</summary>
    [DefaultExecutionOrder(10500)]
    public sealed class AvatarWelcomeController : MonoBehaviour
    {
        [SerializeField] private Animator animator;
        [SerializeField] private AvatarPresentationController presentation;
        [SerializeField] private AnimationClip sittingIdle;
        [SerializeField] private bool useStool;
        private RuntimeAnimatorController originalController;
        private AnimatorOverrideController seatedController;
        private readonly Dictionary<Behaviour, bool> suspended = new Dictionary<Behaviour, bool>();
        private readonly List<Vector3> visiblePoints = new List<Vector3>();
        private GameObject seat;
        private Vrm10Instance vrm;
        private VRM10SpringBoneColliderGroup floorCollider;
        private Material seatMaterial;
        private readonly Dictionary<SkinnedMeshRenderer, bool> originalOffscreen = new Dictionary<SkinnedMeshRenderer, bool>();
        private Vector3 originalPosition;
        private Quaternion originalRotation;
        private float settleUntil;
        private sealed class ClothAnchor
        { public Transform Joint, Parent; public Vector3 Position, Scale; public Quaternion Rotation; public GameObject Anchor; }
        private readonly List<ClothAnchor> clothAnchors = new List<ClothAnchor>();
        private readonly Dictionary<Transform, Quaternion> footRest = new Dictionary<Transform, Quaternion>();
        private readonly Dictionary<VRM10SpringBoneJoint, Vector3> clothSettings = new Dictionary<VRM10SpringBoneJoint, Vector3>();
        public bool IsSeated { get; private set; }
        public AnimationClip SittingIdle => sittingIdle;
        public Bounds SceneBounds { get; private set; }
        public IReadOnlyList<Vector3> VisiblePoints => visiblePoints;

        public void Configure(Animator value, AvatarPresentationController cameraController, AnimationClip clip, bool stool = false)
        { animator = value; presentation = cameraController; sittingIdle = clip; useStool = stool; }

        public bool SetPresentation(string mode, bool preview = false)
        {
            if (mode != "portrait" && mode != "welcome_seated") return false;
            if (mode == "portrait") { RestorePortrait(); return true; }
            if (IsSeated) return true;
            if (!preview && !AvatarPerformanceProfile.IsEmbeddedHost()) return false;
            if (animator == null || !animator.isHuman || sittingIdle == null || presentation == null) return false;
            originalController = animator.runtimeAnimatorController;
            if (originalController == null) return false;
            seatedController = new AnimatorOverrideController(originalController);
            var overrides = new List<KeyValuePair<AnimationClip, AnimationClip>>();
            seatedController.GetOverrides(overrides);
            var foundIdle = false;
            for (var i = 0; i < overrides.Count; i++)
                if (overrides[i].Key != null && overrides[i].Key.name == "Idle")
                { overrides[i] = new KeyValuePair<AnimationClip, AnimationClip>(overrides[i].Key, sittingIdle); foundIdle = true; }
            if (!foundIdle) { Destroy(seatedController); seatedController = null; return false; }
            seatedController.ApplyOverrides(overrides);
            originalPosition = animator.transform.localPosition;
            originalRotation = animator.transform.localRotation;
            GetComponent<AvatarMotionController>()?.StopGesture(true);
            RestoreProceduralInputs();
            footRest.Clear();
            foreach (var bone in new[] { HumanBodyBones.LeftFoot, HumanBodyBones.RightFoot })
            { var foot = animator.GetBoneTransform(bone); if(foot != null) footRest[foot] = foot.localRotation; }
            if (!useStool) PrepareSeatedCloth();
            // Standing arm-rest constraints must not overwrite the imported seated pose.
            Suspend(GetComponent<AvatarMotionController>());
            Suspend(GetComponent<AvatarGestureController>());
            Suspend(GetComponent<AvatarIdleScheduler>());
            Suspend(GetComponent<AvatarArmRig>());
            Suspend(GetComponent<AvatarContactController>());
            Suspend(GetComponent<AvatarBodyController>());
            Suspend(GetComponent<AvatarPoseFilter>());
            Suspend(GetComponent<AvatarLifeController>());
            Suspend(GetComponent<AvatarLookController>());
            // The face and hair retain standing import bounds. At floor height
            // Unity can cull them even though their deformed vertices are visible.
            foreach (var renderer in animator.GetComponentsInChildren<SkinnedMeshRenderer>())
            { originalOffscreen[renderer] = renderer.updateWhenOffscreen; renderer.updateWhenOffscreen = true; }
            animator.runtimeAnimatorController = seatedController;
            animator.applyRootMotion = false;
            animator.Play("Base Layer.IdleNeutral", 0, 0f);
            animator.Update(0f);
            animator.transform.localPosition = originalPosition;
            animator.transform.localRotation = originalRotation;
            IsSeated = true;
            if (useStool) BuildSeat();
            else
            {
                CorrectSeatedLegs();
                BuildFloorSupport();
            }
            SceneBounds = MeasureVisibleBounds();
            presentation.SetFullBodyFraming(SceneBounds, visiblePoints, !useStool);
            settleUntil = Time.unscaledTime + .75f;
            Debug.Log("[AvatarWelcome] Imported seated idle active; full-body scene framed.");
            return true;
        }

        private void Suspend(Behaviour component)
        {
            if (component == null) return;
            suspended[component] = component.enabled;
            component.enabled = false;
        }

        private void RestoreProceduralInputs()
        {
            GetComponent<AvatarArmRig>()?.RestoreInput();
            GetComponent<AvatarContactController>()?.Restore();
            GetComponent<AvatarPoseFilter>()?.RestoreInput();
            GetComponent<AvatarBodyController>()?.RestoreInput();
            GetComponent<AvatarLifeController>()?.RestoreOffsets();
            GetComponent<AvatarLookController>()?.RestoreLook();
        }

        private void RestorePortrait()
        {
            if (!IsSeated) return;
            IsSeated = false;
            RestoreSeatedCloth();
            RemoveFloorSupport();
            foreach (var item in originalOffscreen) if (item.Key != null) item.Key.updateWhenOffscreen = item.Value;
            originalOffscreen.Clear();
            if (seat != null) { seat.SetActive(false); Destroy(seat); }
            if (seatMaterial != null) Destroy(seatMaterial);
            animator.runtimeAnimatorController = originalController;
            animator.Play("Base Layer.IdleNeutral", 0, 0f);
            animator.Update(0f);
            animator.transform.localPosition = originalPosition;
            animator.transform.localRotation = originalRotation;
            foreach (var item in suspended) if (item.Key != null) item.Key.enabled = item.Value;
            suspended.Clear();
            if (seatedController != null) Destroy(seatedController);
            seatedController = null;
            footRest.Clear();
            presentation.SetFullBodyFraming(null);
        }

        private void OnDestroy()
        {
            if (seatMaterial != null) Destroy(seatMaterial);
            if (seat != null) Destroy(seat);
            if (seatedController != null) Destroy(seatedController);
        }

        private void LateUpdate()
        {
            if (IsSeated && !useStool) { CorrectSeatedLegs(); }
            // Let VRM spring bones follow the new hips before taking the final frame.
            if (IsSeated && settleUntil > 0 && Time.unscaledTime >= settleUntil)
            {
                settleUntil = 0;
                SceneBounds = MeasureVisibleBounds();
                presentation.SetFullBodyFraming(SceneBounds, visiblePoints, !useStool);
            }
        }

        private void PrepareSeatedCloth()
        {
            vrm = animator.GetComponent<Vrm10Instance>();
            if (vrm == null) return;
            var hips = animator.GetBoneTransform(HumanBodyBones.Hips);
            var seen = new HashSet<Transform>();
            foreach (var spring in vrm.SpringBone.Springs)
            {
                if (spring.Name != "Skirt" || spring.Joints.Count == 0) continue;
                var joint = spring.Joints[0].transform;
                if (!seen.Add(joint)) continue;
                var anchor = new GameObject("Welcome skirt waist anchor");
                anchor.transform.SetPositionAndRotation(joint.parent.position, joint.parent.rotation);
                anchor.transform.localScale = joint.parent.lossyScale;
                anchor.transform.SetParent(hips, true);
                clothAnchors.Add(new ClothAnchor { Joint = joint, Parent = joint.parent, Position = joint.localPosition,
                    Rotation = joint.localRotation, Scale = joint.localScale, Anchor = anchor });
                // Keep the authored local axes/default rotations for spring bones,
                // while the waist follows the pelvis instead of rolling thighs.
                joint.SetParent(anchor.transform, false);
            }
        }

        private void RestoreSeatedCloth()
        {
            foreach (var item in clothAnchors)
            {
                item.Joint.SetParent(item.Parent, false);
                item.Joint.localPosition = item.Position; item.Joint.localRotation = item.Rotation; item.Joint.localScale = item.Scale;
                Destroy(item.Anchor);
            }
            clothAnchors.Clear();
        }

        private void CorrectSeatedLegs()
        {
            // Close the raised knee toward the lap by rotating its bend plane
            // around hip-to-ankle. Both segment lengths and the ankle contact
            // stay fixed; no independent knee translation or scaling is used.
            var thigh = animator.GetBoneTransform(HumanBodyBones.LeftUpperLeg);
            var knee = animator.GetBoneTransform(HumanBodyBones.LeftLowerLeg);
            var ankle = animator.GetBoneTransform(HumanBodyBones.LeftFoot);
            var contact = ankle.position;
            var axis = (contact - thigh.position).normalized;
            var targetKnee = thigh.position + Quaternion.AngleAxis(-65f, axis) * (knee.position - thigh.position);
            thigh.rotation = Quaternion.FromToRotation(knee.position - thigh.position, targetKnee - thigh.position) * thigh.rotation;
            knee.rotation = Quaternion.FromToRotation(ankle.position - knee.position, contact - knee.position) * knee.rotation;
            // Reduce excessive foot bend/twist relative to standing neutral.
            foreach (var item in footRest)
            {
                var relative = Quaternion.Inverse(item.Value) * item.Key.localRotation;
                item.Key.localRotation = item.Value * Quaternion.RotateTowards(Quaternion.identity, relative, 48f);
            }
        }

        private void BuildFloorSupport()
        {
            vrm = animator.GetComponent<Vrm10Instance>();
            if (vrm == null) return;
            vrm.Runtime.Process();
            var floor = new GameObject("Welcome floor support");
            floor.transform.SetParent(transform, true);
            var left = animator.GetBoneTransform(HumanBodyBones.LeftFoot);
            var right = animator.GetBoneTransform(HumanBodyBones.RightFoot);
            floor.transform.position = new Vector3(0, Mathf.Min(left.position.y, right.position.y) - .035f, 0);
            var collider = floor.AddComponent<VRM10SpringBoneCollider>();
            collider.ColliderType = VRM10SpringBoneColliderTypes.Plane;
            collider.Normal = Vector3.up;
            floorCollider = floor.AddComponent<VRM10SpringBoneColliderGroup>();
            floorCollider.Name = "Welcome floor";
            floorCollider.Colliders.Add(collider);
            foreach (var side in new[] { true, false })
            {
                var thigh = animator.GetBoneTransform(side ? HumanBodyBones.LeftUpperLeg : HumanBodyBones.RightUpperLeg);
                var knee = animator.GetBoneTransform(side ? HumanBodyBones.LeftLowerLeg : HumanBodyBones.RightLowerLeg);
                var clothCollider = thigh.gameObject.AddComponent<VRM10SpringBoneCollider>();
                clothCollider.ColliderType = VRM10SpringBoneColliderTypes.Capsule;
                clothCollider.Offset = thigh.InverseTransformPoint(Vector3.Lerp(thigh.position, knee.position, .35f));
                clothCollider.Tail = thigh.InverseTransformPoint(knee.position);
                clothCollider.Radius = Vector3.Distance(thigh.position, knee.position) * .3f;
                floorCollider.Colliders.Add(clothCollider);
            }
            vrm.SpringBone.ColliderGroups.Add(floorCollider);
            foreach (var spring in vrm.SpringBone.Springs)
                if (spring.Name == "Skirt")
                {
                    spring.ColliderGroups.Add(floorCollider);
                    foreach (var joint in spring.Joints)
                    {
                        if (!clothSettings.ContainsKey(joint)) clothSettings[joint] = new Vector3(joint.m_stiffnessForce, joint.m_gravityPower, joint.m_dragForce);
                        joint.m_stiffnessForce = .18f; joint.m_gravityPower = .15f; joint.m_dragForce = .7f;
                    }
                }
            vrm.Runtime.SpringBone.ReconstructSpringBone();
            vrm.Runtime.SpringBone.RestoreInitialTransform();
            // Settle secondary clothing/hair physics against the floor before
            // measuring the silhouette. The authored body clip is unchanged.
            for (var i = 0; i < 90; i++) vrm.Runtime.SpringBone.Process(1f / 60);
        }

        private void RemoveFloorSupport()
        {
            if (floorCollider == null || vrm == null) return;
            foreach (var item in clothSettings)
            { item.Key.m_stiffnessForce = item.Value.x; item.Key.m_gravityPower = item.Value.y; item.Key.m_dragForce = item.Value.z; }
            clothSettings.Clear();
            vrm.SpringBone.ColliderGroups.Remove(floorCollider);
            foreach (var spring in vrm.SpringBone.Springs) spring.ColliderGroups.Remove(floorCollider);
            foreach (var collider in floorCollider.Colliders) if (collider.gameObject != floorCollider.gameObject) Destroy(collider);
            var floor = floorCollider.gameObject;
            floorCollider = null;
            vrm.Runtime.SpringBone.ReconstructSpringBone();
            Destroy(floor);
        }

        private void BuildSeat()
        {
            var hips = animator.GetBoneTransform(HumanBodyBones.Hips);
            var upper = animator.GetBoneTransform(HumanBodyBones.LeftUpperLeg);
            var knee = animator.GetBoneTransform(HumanBodyBones.LeftLowerLeg);
            var footL = animator.GetBoneTransform(HumanBodyBones.LeftFoot);
            var footR = animator.GetBoneTransform(HumanBodyBones.RightFoot);
            var unit = Vector3.Distance(upper.position, knee.position);
            var width = unit * 1.5f;
            var thickness = unit * .12f;
            var top = hips.position.y - unit * .20f;
            var floor = Mathf.Min(footL.position.y, footR.position.y) - unit * .12f;
            var front = Vector3.ProjectOnPlane(Camera.main.transform.position - hips.position, Vector3.up).normalized;
            var center = hips.position - front * unit * .08f;
            center.y = top - thickness * .5f;
            seat = new GameObject("Welcome graphite stool");
            seat.transform.SetParent(transform, true);
            seatMaterial = new Material(Resources.Load<Shader>("WelcomeSeat")) { color = new Color(.25f, .25f, .29f) };
            AddPart("Rounded cushion", PrimitiveType.Sphere, center, new Vector3(width, thickness * 1.4f, width * .82f));
            var right = Vector3.Cross(Vector3.up, front);
            var legTop = top - thickness;
            var legHeight = Mathf.Max(.05f, legTop - floor);
            foreach (var side in new[] { -1f, 1f })
            foreach (var depth in new[] { -1f, 1f })
            {
                var point = center + right * (side * width * .32f) + front * (depth * width * .25f);
                point.y = floor + legHeight * .5f;
                AddPart("Stool leg", PrimitiveType.Cylinder, point, new Vector3(unit * .055f, legHeight * .5f, unit * .055f));
            }
        }

        private void AddPart(string partName, PrimitiveType type, Vector3 position, Vector3 scale)
        {
            var part = GameObject.CreatePrimitive(type);
            part.name = partName;
            part.transform.SetParent(seat.transform, true);
            part.transform.position = position;
            part.transform.localScale = scale;
            Destroy(part.GetComponent<Collider>());
            part.GetComponent<Renderer>().sharedMaterial = seatMaterial;
        }

        private Bounds MeasureVisibleBounds()
        {
            // Skinned renderer bounds may still contain the standing bind pose.
            // Measure the actual retargeted vertices once, rather than shrinking a portrait.
            var bounds = new Bounds(animator.GetBoneTransform(HumanBodyBones.Hips).position, Vector3.zero);
            visiblePoints.Clear();
            var mesh = new Mesh();
            foreach (var renderer in animator.GetComponentsInChildren<SkinnedMeshRenderer>())
            {
                if (!renderer.enabled || !renderer.gameObject.activeInHierarchy) continue;
                renderer.BakeMesh(mesh);
                foreach (var vertex in mesh.vertices)
                {
                    var world = renderer.transform.TransformPoint(vertex);
                    bounds.Encapsulate(world);
                    visiblePoints.Add(world);
                }
                mesh.Clear();
            }
            Destroy(mesh);
            if (seat != null)
                foreach (var renderer in seat.GetComponentsInChildren<Renderer>())
                {
                    var part = renderer.bounds;
                    bounds.Encapsulate(part);
                    foreach (var x in new[] { -1f, 1f })
                    foreach (var y in new[] { -1f, 1f })
                    foreach (var z in new[] { -1f, 1f })
                        visiblePoints.Add(part.center + Vector3.Scale(part.extents, new Vector3(x, y, z)));
                }
            return bounds;
        }
    }
}
