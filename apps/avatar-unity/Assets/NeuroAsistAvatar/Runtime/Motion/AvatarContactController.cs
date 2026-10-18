using UnityEngine;

namespace NeuroAsist.Avatar
{
    /// <summary>Retargets authored face contacts to Iris's actual head/hand proportions.</summary>
    [DefaultExecutionOrder(350)]
    public sealed class AvatarContactController : MonoBehaviour
    {
        [SerializeField] private Animator animator;
        [SerializeField] private AvatarGestureController gestures;
        private Transform upper, lower, hand;
        private Quaternion upperBefore, lowerBefore, handBefore, upperAfter, lowerAfter, handAfter;
        private bool applied;
        private Quaternion leftHandRest, rightHandRest;
        private Quaternion leftForearmRest, rightForearmRest;
        private Vector3 leftForearmAxis, rightForearmAxis;
        private Vector3 leftHandAxis, rightHandAxis, bendDirection;
        private string bendVariant;
        private readonly Vector3[] fingerOffsets = new Vector3[15];
        private readonly System.Collections.Generic.List<Vector3> faceSurface = new System.Collections.Generic.List<Vector3>();
        private Transform contactHead;
        private Vector3 anatomicalFront;
        private Vector3 faceOrigin, faceFront, faceUp, faceRight;
        private float faceDepth, faceScale;
        private bool protectFace;
        private bool coupledArm;
        public void RefreshFaceProtection()
        {
            if (!protectFace) return;
            faceOrigin = (animator.GetBoneTransform(HumanBodyBones.LeftEye).position + animator.GetBoneTransform(HumanBodyBones.RightEye).position) * .5f;
            faceUp = animator.transform.up;
            faceFront = animator.transform.TransformDirection(anatomicalFront).normalized;
            faceRight = Vector3.ProjectOnPlane(animator.GetBoneTransform(HumanBodyBones.RightUpperArm).position - animator.GetBoneTransform(HumanBodyBones.LeftUpperArm).position,faceUp).normalized;
            faceDepth = ForeheadDepth(faceOrigin,faceFront,faceUp,faceRight,faceScale);
        }
        public float FingerFaceClearance(Vector3 point)
        {
            if (!protectFace) return float.PositiveInfinity;
            var offset = point - faceOrigin; var height = Vector3.Dot(offset,faceUp);
            if (Mathf.Abs(Vector3.Dot(offset,faceRight)) > .16f * faceScale || height < -.05f * faceScale || height > .25f * faceScale) return float.PositiveInfinity;
            return Vector3.Dot(offset,faceFront) - faceDepth - .007f * faceScale;
        }
        public Vector3 ProjectHandOutsideFace(Vector3 wrist,Quaternion rotation,Vector3[] offsets,int count)
        {
            if(!protectFace)return wrist;
            var clearance=float.PositiveInfinity;
            for(var i=0;i<count;i++)clearance=Mathf.Min(clearance,FingerFaceClearance(wrist+rotation*offsets[i]));
            return clearance<.012f?wrist+faceFront*(.012f-clearance):wrist;
        }
        public Vector3 PalmTarget { get; private set; }
        public Vector3 PalmPosition { get; private set; }
        public float ContactWeight { get; private set; }
        public Quaternion ContactRotation { get; private set; }
        public Vector3 WristTarget { get; private set; }
        public Quaternion TargetRotation { get; private set; }
        public bool HasTarget { get; private set; }
        public int FaceSurfaceSampleCount => faceSurface.Count;
        public float MeasureFingerFaceClearance()
        {
            if (gestures?.ActiveVariant == null || contactHead == null) return float.PositiveInfinity;
            var eyes = (animator.GetBoneTransform(HumanBodyBones.LeftEye).position + animator.GetBoneTransform(HumanBodyBones.RightEye).position) * .5f;
            var up = animator.transform.up;
            var front = animator.transform.TransformDirection(anatomicalFront).normalized;
            var right = Vector3.ProjectOnPlane(animator.GetBoneTransform(HumanBodyBones.RightUpperArm).position - animator.GetBoneTransform(HumanBodyBones.LeftUpperArm).position, up).normalized;
            var depth = ForeheadDepth(eyes, front, up, right, Mathf.Abs(animator.transform.lossyScale.x));
            var left = gestures.ActiveVariant.Side == GestureSide.Left;
            var minimum = float.PositiveInfinity;
            for (var bone = left ? HumanBodyBones.LeftThumbProximal : HumanBodyBones.RightThumbProximal;
                bone <= (left ? HumanBodyBones.LeftLittleDistal : HumanBodyBones.RightLittleDistal); bone++)
            {
                var finger = animator.GetBoneTransform(bone);
                if (finger != null) minimum = Mathf.Min(minimum, Vector3.Dot(finger.position - eyes, front) - depth);
            }
            return minimum;
        }
        public void Configure(Animator value, AvatarGestureController controller) { animator = value; gestures = controller; }
        private void Awake()
        {
            if (gestures == null) gestures = GetComponent<AvatarGestureController>();
            if (animator == null || !animator.isHuman) return;
            coupledArm=GetComponent<AvatarArmRig>()!=null;
            var head = animator.GetBoneTransform(HumanBodyBones.Head);
            var initialFront = Camera.main != null ? Camera.main.transform.position - head.position : animator.transform.forward;
            anatomicalFront = animator.transform.InverseTransformDirection(Vector3.ProjectOnPlane(initialFront, animator.transform.up).normalized);
            CacheFaceSurface();
            foreach (var left in new[] { true, false })
            {
                var wrist = animator.GetBoneTransform(left ? HumanBodyBones.LeftHand : HumanBodyBones.RightHand);
                var finger = animator.GetBoneTransform(left ? HumanBodyBones.LeftMiddleProximal : HumanBodyBones.RightMiddleProximal);
                if (wrist == null || finger == null) continue;
                var axis = wrist.InverseTransformDirection(finger.position - wrist.position).normalized;
                var forearm = animator.GetBoneTransform(left ? HumanBodyBones.LeftLowerArm : HumanBodyBones.RightLowerArm);
                var forearmAxis = forearm.InverseTransformDirection(wrist.position - forearm.position).normalized;
                if (left) { leftHandRest = wrist.localRotation; leftHandAxis = axis; leftForearmRest = forearm.localRotation; leftForearmAxis = forearmAxis; }
                else { rightHandRest = wrist.localRotation; rightHandAxis = axis; rightForearmRest = forearm.localRotation; rightForearmAxis = forearmAxis; }
            }
        }
        private void CacheFaceSurface()
        {
            contactHead = animator.GetBoneTransform(HumanBodyBones.Head);
            var eyes = (animator.GetBoneTransform(HumanBodyBones.LeftEye).position + animator.GetBoneTransform(HumanBodyBones.RightEye).position) * .5f;
            var cells = new System.Collections.Generic.HashSet<Vector3Int>();
            foreach (var renderer in animator.GetComponentsInChildren<SkinnedMeshRenderer>())
            {
                var mesh = new Mesh(); renderer.BakeMesh(mesh);
                var vertices = mesh.vertices; var materials = renderer.sharedMaterials;
                for (var sub = 0; sub < materials.Length && sub < mesh.subMeshCount; sub++)
                {
                    var material = materials[sub];
                    if (material == null || !(material.name.Contains("Hair") || material.name.Contains("Face") && material.name.Contains("SKIN"))) continue;
                    foreach (var index in mesh.GetTriangles(sub))
                    {
                        var world = renderer.transform.TransformPoint(vertices[index]);
                        if (Vector3.Distance(world, eyes) > .23f * animator.transform.lossyScale.x) continue;
                        var local = contactHead.InverseTransformPoint(world);
                        if (cells.Add(Vector3Int.RoundToInt(local * 100))) faceSurface.Add(local);
                    }
                }
                Destroy(mesh);
            }
        }
        private float ForeheadDepth(Vector3 eyes, Vector3 front, Vector3 up, Vector3 right, float scale)
        {
            var depth = .10f * scale;
            foreach (var point in faceSurface)
            {
                var offset = contactHead.TransformPoint(point) - eyes;
                var height = Vector3.Dot(offset, up);
                if (height >= -.01f * scale && height < .15f * scale && Mathf.Abs(Vector3.Dot(offset, right)) < .10f * scale)
                    depth = Mathf.Max(depth, Vector3.Dot(offset, front));
            }
            return depth;
        }
        private void Update() => Restore();
        private void OnDisable() => Restore();
        internal void Restore()
        {
            if (!applied) return;
            if (upper != null && Quaternion.Angle(upper.localRotation, upperAfter) < .01f) upper.localRotation = upperBefore;
            if (lower != null && Quaternion.Angle(lower.localRotation, lowerAfter) < .01f) lower.localRotation = lowerBefore;
            if (hand != null && Quaternion.Angle(hand.localRotation, handAfter) < .01f) hand.localRotation = handBefore;
            applied = false;
        }
        private void LateUpdate()
        {
            ContactWeight = 0;
            HasTarget = false;
            protectFace = false;
            var variant = gestures != null ? gestures.ActiveVariant : null;
            if (variant == null || animator == null || !animator.isHuman) return;
            var family = AvatarBehaviorPolicy.Family(gestures.Active.Tag);
            var thumbsUp = family == GestureTag.Thumbs_Up;
            if (!variant.ContactSensitive && !thumbsUp) return;
            var left = variant.Side == GestureSide.Left;
            upper = animator.GetBoneTransform(left ? HumanBodyBones.LeftUpperArm : HumanBodyBones.RightUpperArm);
            lower = animator.GetBoneTransform(left ? HumanBodyBones.LeftLowerArm : HumanBodyBones.RightLowerArm);
            hand = animator.GetBoneTransform(left ? HumanBodyBones.LeftHand : HumanBodyBones.RightHand);
            var middle = animator.GetBoneTransform(left ? HumanBodyBones.LeftMiddleProximal : HumanBodyBones.RightMiddleProximal);
            var index = animator.GetBoneTransform(left ? HumanBodyBones.LeftIndexProximal : HumanBodyBones.RightIndexProximal);
            var little = animator.GetBoneTransform(left ? HumanBodyBones.LeftLittleProximal : HumanBodyBones.RightLittleProximal);
            var head = animator.GetBoneTransform(HumanBodyBones.Head);
            var leftEye = animator.GetBoneTransform(HumanBodyBones.LeftEye); var rightEye = animator.GetBoneTransform(HumanBodyBones.RightEye);
            if (upper == null || lower == null || hand == null || middle == null || head == null || leftEye == null || rightEye == null) return;
            var elapsed = gestures.Elapsed;
            var attack = Mathf.SmoothStep(0, 1, Mathf.InverseLerp(variant.PreparationSeconds * .5f, variant.PreparationSeconds + variant.StrokeSeconds * .6f, elapsed));
            var release = Mathf.SmoothStep(0, 1, Mathf.Clamp01((variant.Duration - elapsed) / Mathf.Max(.1f, variant.RecoverySeconds)));
            ContactWeight = Mathf.Min(attack, release) * (thumbsUp ? Mathf.SmoothStep(0, 1, Mathf.Clamp01(gestures.GestureWeight * 1.5f)) : gestures.GestureWeight);
            var eyes = (leftEye.position + rightEye.position) * .5f;
            var up = animator.transform.up;
            var front = animator.transform.TransformDirection(anatomicalFront).normalized;
            var right = Vector3.ProjectOnPlane(animator.GetBoneTransform(HumanBodyBones.RightUpperArm).position - animator.GetBoneTransform(HumanBodyBones.LeftUpperArm).position, up).normalized;
            var side = left ? -1f : 1f;
            // Iris's eye bones are rotation pivots deep inside the head; their
            // separation is not the visible face width. The mesh is in metres.
            var scale = Mathf.Max(.001f, Mathf.Abs(animator.transform.lossyScale.x));
            var offset = ContactOffset(family, variant.PatternId);
            PalmTarget = eyes + (right * offset.x * side + up * offset.y + front * offset.z) * scale;
            if (thumbsUp && Camera.main != null)
            {
                var screen = Camera.main.WorldToViewportPoint(PalmTarget);
                screen.x = Mathf.Clamp(screen.x, .18f, .82f); screen.y = Mathf.Clamp(screen.y, .18f, .82f);
                PalmTarget = Camera.main.ViewportToWorldPoint(screen);
            }
            // Direction-space offsets are in metres; InverseTransformPoint would
            // lose the imported avatar's world scale when multiplied by rotation.
            var palmLocal = hand.InverseTransformDirection(middle.position - hand.position) * .55f;
            var fingerCount = 0;
            for (var bone = left ? HumanBodyBones.LeftThumbProximal : HumanBodyBones.RightThumbProximal;
                bone <= (left ? HumanBodyBones.LeftLittleDistal : HumanBodyBones.RightLittleDistal); bone++)
            {
                var finger = animator.GetBoneTransform(bone);
                if (finger != null) fingerOffsets[fingerCount++] = hand.InverseTransformDirection(finger.position - hand.position);
            }
            var desiredRotation = hand.rotation;
            if (thumbsUp)
            {
                var thumbMiddle = animator.GetBoneTransform(left ? HumanBodyBones.LeftThumbIntermediate : HumanBodyBones.RightThumbIntermediate);
                var thumbTip = animator.GetBoneTransform(left ? HumanBodyBones.LeftThumbDistal : HumanBodyBones.RightThumbDistal);
                if (thumbMiddle != null && thumbTip != null)
                    desiredRotation = Quaternion.FromToRotation(thumbTip.position - thumbMiddle.position, up) * hand.rotation;
            }
            if (family == GestureTag.Facepalm && index != null && little != null)
            {
                var lengthLocal = hand.InverseTransformDirection(middle.position - hand.position).normalized;
                var widthLocal = hand.InverseTransformDirection(index.position - little.position).normalized;
                var normalLocal = Vector3.Cross(widthLocal, lengthLocal).normalized * (left ? 1 : -1);
                var fingerDirection = (up + right * side * (variant.PatternId.Contains("inclined") ? -.35f : -.12f)).normalized;
                desiredRotation = Quaternion.LookRotation(fingerDirection, -front) * Quaternion.Inverse(Quaternion.LookRotation(lengthLocal, normalLocal));
            }
            upperBefore = upper.localRotation; lowerBefore = lower.localRotation; handBefore = hand.localRotation;
            var sourceWrist = hand.position;
            var sourceRotation = hand.rotation;
            // A persistent bend plane cannot flip at a nearly straight elbow.
            // Prefer an elbow below and slightly outside the shoulder, acquiring
            // that plane continuously from the authored pose during approach.
            var ray = (PalmTarget - upper.position).normalized;
            var preferred = Vector3.ProjectOnPlane(-up + right * side * .55f + front * .12f, ray).normalized;
            if (bendVariant != variant.Id)
            {
                bendVariant = variant.Id;
                bendDirection = Vector3.ProjectOnPlane(lower.position - upper.position, ray).normalized;
                if (bendDirection.sqrMagnitude < .1f) bendDirection = preferred;
            }
            bendDirection = Vector3.RotateTowards(bendDirection, preferred, Time.deltaTime * 1.8f, 0).normalized;
            var rotation = Quaternion.Slerp(sourceRotation, desiredRotation, ContactWeight);
            TargetRotation = desiredRotation;
            ContactRotation = rotation;
            var contactTarget = PalmTarget;
            var forehead = family == GestureTag.Facepalm ? ForeheadDepth(eyes, front, up, right, scale) : 0;
            protectFace = family == GestureTag.Facepalm;
            faceOrigin = eyes; faceFront = front; faceUp = up; faceRight = right; faceDepth = forehead; faceScale = scale;
            // Solve position AND a reachable palm orientation. Keeping the old
            // world hand rotation after moving the forearm folded wrists back.
            // Iterate with the anatomically limited orientation instead.
            for (var iteration = 0; iteration < 3; iteration++)
            {
                if (family == GestureTag.Facepalm)
                {
                    // A safe wrist can leave the fingers angled towards the
                    // forehead. Keep their whole footprint outside the face,
                    // rather than putting the palm centre on skin and driving
                    // the fingers through it.
                    var closest = 0f;
                    var footprintRotation=coupledArm?desiredRotation:rotation;
                    for (var f = 0; f < fingerCount; f++) closest = Mathf.Min(closest, Vector3.Dot(footprintRotation * (fingerOffsets[f] - palmLocal), front));
                    var clearance = Mathf.Max(0, forehead + .02f * scale - Vector3.Dot(contactTarget - eyes, front) - closest);
                    PalmTarget = contactTarget + front * clearance;
                }
                var wrist = Vector3.Lerp(sourceWrist, PalmTarget - rotation * palmLocal, ContactWeight);
                Solve(upper, lower, hand, wrist, bendDirection);
                // Pronation belongs to the forearm, not the wrist. Transfer the
                // excessive axial component there before limiting the hand.
                var relative = Quaternion.Inverse(left ? leftHandRest : rightHandRest) * Quaternion.Inverse(lower.rotation) * desiredRotation;
                var handAxis = left ? leftHandAxis : rightHandAxis;
                var twistVector = Vector3.Project(new Vector3(relative.x, relative.y, relative.z), handAxis);
                var signedTwist = Mathf.DeltaAngle(0, 2 * Mathf.Atan2(Vector3.Dot(twistVector, handAxis), relative.w) * Mathf.Rad2Deg);
                var transfer = signedTwist - Mathf.Clamp(signedTwist, -18, 18);
                lower.rotation = Quaternion.AngleAxis(transfer * ContactWeight, (hand.position - lower.position).normalized) * lower.rotation;
                lower.localRotation = AvatarPoseFilter.LimitJoint(lower.localRotation, left ? leftForearmRest : rightForearmRest,
                    left ? leftForearmAxis : rightForearmAxis, 145, 80);
                hand.rotation = Quaternion.Slerp(sourceRotation, desiredRotation, ContactWeight);
                hand.localRotation = AvatarPoseFilter.LimitJoint(hand.localRotation, left ? leftHandRest : rightHandRest,
                    left ? leftHandAxis : rightHandAxis, 42, 18);
                rotation = hand.rotation;
            }
            upperAfter = upper.localRotation; lowerAfter = lower.localRotation; handAfter = hand.localRotation; applied = true;
            PalmPosition = hand.position + hand.rotation * palmLocal;
            WristTarget = PalmTarget-rotation*palmLocal;
            HasTarget = true;
        }
        private static Vector3 ContactOffset(GestureTag family, string pattern)
        {
            if (family == GestureTag.Thumbs_Up)
            {
                if (pattern.Contains("supported")) return new Vector3(.12f, -.24f, .16f);
                if (pattern.Contains("brief")) return new Vector3(.17f, -.17f, .18f);
                if (pattern.Contains("inclined")) return new Vector3(.21f, -.20f, .18f);
                if (pattern.Contains("two_stage")) return new Vector3(.14f, -.20f, .25f);
                if (pattern.Contains("settled")) return new Vector3(.12f, -.29f, .15f);
                return new Vector3(.15f, -.22f, .18f);
            }
            if (family == GestureTag.Facepalm)
            {
                if (pattern.Contains("inclined")) return new Vector3(.045f, .035f, .09f);
                if (pattern.Contains("brief")) return new Vector3(.015f, .02f, .095f);
                if (pattern.Contains("two_stage")) return new Vector3(.025f, .05f, .09f);
                if (pattern.Contains("settled")) return new Vector3(0, .05f, .09f);
                return new Vector3(0, .03f, .095f);
            }
            if (family == GestureTag.Head_Scratch) return new Vector3(.12f, pattern.Contains("inclined") ? .11f : .065f, .065f);
            if (pattern.Contains("temple")) return new Vector3(.105f, .01f, .085f);
            if (pattern.Contains("brief") || pattern.Contains("realization")) return new Vector3(.065f, -.045f, .09f);
            if (pattern.Contains("inclined")) return new Vector3(.025f, -.085f, .09f);
            return new Vector3(.005f, -.10f, .09f);
        }
        private static void Solve(Transform shoulder, Transform elbow, Transform wrist, Vector3 target, Vector3 bendDirection)
        {
            var origin = shoulder.position;
            var a = Vector3.Distance(origin, elbow.position); var b = Vector3.Distance(elbow.position, wrist.position);
            var ray = target - origin;
            var minimum = Mathf.Sqrt(a * a + b * b + 2 * a * b * Mathf.Cos(145 * Mathf.Deg2Rad));
            var distance = Mathf.Clamp(ray.magnitude, minimum, (a + b) * .97f);
            if (ray.sqrMagnitude < .000001f) return;
            var direction = ray.normalized;
            var pole = Vector3.ProjectOnPlane(bendDirection, direction);
            if (pole.sqrMagnitude < .000001f) pole = Vector3.ProjectOnPlane(shoulder.root.right, direction);
            var along = (a * a - b * b + distance * distance) / (2 * distance);
            var height = Mathf.Sqrt(Mathf.Max(0, a * a - along * along));
            var elbowTarget = origin + direction * along + pole.normalized * height;
            var wristTarget = origin + direction * distance;
            shoulder.rotation = Quaternion.FromToRotation(elbow.position - origin, elbowTarget - origin) * shoulder.rotation;
            elbow.rotation = Quaternion.FromToRotation(wrist.position - elbow.position, wristTarget - elbow.position) * elbow.rotation;
        }
    }
}
