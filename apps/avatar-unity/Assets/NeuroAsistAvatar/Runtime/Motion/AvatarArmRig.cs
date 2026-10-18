using System.Collections.Generic;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    /// <summary>Coupled arm motion: one elbow hinge, transported bend plane and a path outside the clothed torso.</summary>
    [DefaultExecutionOrder(400)]
    public sealed class AvatarArmRig : MonoBehaviour
    {
        private const float SafetyClearance = .012f;
        private const int ReturnSamples = 16;
        [SerializeField] private Animator animator;
        private sealed class Arm
        {
            public int BodyPose = -1;
            public Vector3 BodyGoal;
            public bool Left, Initialized;
            public Transform Upper, Lower, Hand;
            public Quaternion LowerRest, HandRest, BeforeUpper, BeforeLower, BeforeHand;
            public Vector3 UpperAim, Hinge, UpperHinge, LowerAim, HandAim;
            public Vector3 Position, Velocity, Pole, LastDirection;
            public Vector3 DirectionVelocity;
            public float FlexVelocity, SwivelVelocity;
            public float Activity;
            public Quaternion Rotation;
            public Vector3 RotationVelocity;
            public Quaternion WristRotation;
            public Vector3 WristVelocity;
            public float A, B, Flex, Twist, TwistVelocity;
            public float ForearmRadius, HandRadius;
            public int RadiusSamples;
            public bool NeutralReady;
            public Vector3 NeutralGoal, NeutralPole, NeutralShoulder;
            public Vector3 RestOffset;
            public int RouteStage = -1;
            public bool RouteFront;
            public Vector3 RouteEntry, RouteExit;
            public Vector3 ReturnStart, ReturnControlA, ReturnControlB, ReturnEnd, ReturnShoulder;
            public float ReturnProgress, ReturnInitialFlex, ReturnStartAngle;
            public bool ReturnPlanReady, ReturnPlanPending, ReturningToRest;
            public readonly Vector3[] ReturnPositions = new Vector3[ReturnSamples + 1];
            public readonly float[] ReturnAngles = new float[ReturnSamples + 1];
            public bool Detour;
            public Vector3 Source, Goal;
            public Vector3 PalmOffset;
            public bool ThumbUp;
            public bool ContactPose;
            public float TwistLimit=35;
            public float MotionRate=1;
            public bool ThumbReady;
            public float ThumbTwist, ThumbSolvedAt;
            public Quaternion ThumbWrist;
            public Vector3 ThumbPole, ThumbGoal, ThumbSolvedAxis;
            public bool FacePose,FaceReady,FaceApproaching;
            public float FaceTwist,FaceSolvedAt;
            public Quaternion FaceWrist,FaceWantedRotation;
            public Vector3 FaceGoal,FacePole,FaceWantedPalm;
            public Vector3 ThumbAxis;
            public float PredictionError, FinalPalmError;
            public readonly Vector3[] Fingers = new Vector3[15];
            public int FingerCount;
        }
        private readonly List<Arm> arms = new List<Arm>();
        private AvatarTorsoEnvelope torso;
        private bool applied;
        private AvatarContactController contact;
        private AvatarGestureController gestures;
        private int lastPlanningFrame = -1;
        public int TorsoSamples => torso?.SampleCount ?? 0;
        public string DescribeTorso() => torso?.Describe();
        public int BlockedSteps { get; private set; }
        public void SetBodyPose(bool left, int pose)
        {
            var arm = arms.Find(a => a.Left == left);
            if (arm != null) { arm.BodyPose = pose; arm.Detour = false; arm.RouteStage = -1; }
        }
        public void ReleaseLoweredBodyPoses()
        {
            foreach (var arm in arms)
                if (arm.BodyPose == 0 && BodyPoseReached(arm.Left)
                    && (gestures?.ActiveVariant == null || (gestures.ActiveVariant.Channels & (arm.Left ? MotionChannels.LeftArm : MotionChannels.RightArm)) == 0)) arm.BodyPose = -1;
        }
        public string BodyPoseName(bool left)
        {
            var arm = arms.Find(a => a.Left == left);
            if (arm == null || arm.Hand == null || arm.Upper == null) return "unavailable";
            var hand = torso.ToFrame(arm.Hand.position); var shoulder = torso.ToFrame(arm.Upper.position);
            if (hand.y > shoulder.y + .04f) return "raised";
            if (hand.z > shoulder.z + .18f && hand.y > shoulder.y - .18f) return "extended";
            return hand.y < shoulder.y - .22f && MeasureArmAbduction(left) < 20 ? "rest" : "moving";
        }
        public bool BodyPoseReached(bool left)
        {
            var arm = arms.Find(a => a.Left == left);
            return arm != null && Vector3.Distance(torso.ToFrame(arm.Hand.position), arm.BodyGoal) < .045f
                && (arm.BodyPose != 0 || MeasureArmAbduction(left) < 20);
        }
        public void Configure(Animator value) => animator = value;
        public float MeasureElbowOutward(bool left)
        {
            var arm = arms.Find(a => a.Left == left); if (arm == null) return 0;
            return (torso.ToFrame(arm.Lower.position).x - torso.ToFrame(arm.Upper.position).x) * (left ? -1 : 1);
        }
        public float MeasureArmAbduction(bool left)
        {
            var arm = arms.Find(a => a.Left == left); if (arm == null) return 0;
            var offset = torso.ToFrame(arm.Lower.position) - torso.ToFrame(arm.Upper.position);
            return Mathf.Atan2(offset.x * (left ? -1 : 1),-offset.y) * Mathf.Rad2Deg;
        }
        public float MeasureForearmAbduction(bool left)
        {
            var arm = arms.Find(a => a.Left == left); if (arm == null) return 0;
            var offset = torso.ToFrame(arm.Hand.position) - torso.ToFrame(arm.Lower.position);
            return Mathf.Atan2(offset.x * (left ? -1 : 1),-offset.y) * Mathf.Rad2Deg;
        }
        public Vector3 MeasureHandPosition(bool left)
        {
            var arm = arms.Find(a => a.Left == left);
            return arm == null ? Vector3.zero : torso.ToFrame(arm.Hand.position);
        }
        public string DescribeArms()
        {
            var result = $"gesture={gestures?.ActiveVariant?.Id} weight={gestures?.GestureWeight}\n";
            foreach (var arm in arms)
                result += $"left={arm.Left} upper={torso.ToFrame(arm.Upper.position):F4} elbow={torso.ToFrame(arm.Lower.position):F4} wrist={torso.ToFrame(arm.Hand.position):F4} solved={arm.Position:F4} pole={arm.Pole:F4} neutral={arm.NeutralGoal:F4}/{arm.NeutralPole:F4} route={arm.RouteStage}:{arm.RouteEntry:F4}/{arm.RouteExit:F4} goal={arm.Goal:F4} detour={arm.Detour} radius={arm.ForearmRadius:F4}/{arm.HandRadius:F4} samples={arm.RadiusSamples} lengths={arm.A:F4},{arm.B:F4} flex={arm.Flex:F2} twist={arm.Twist:F2} wristRestError={Quaternion.Angle(arm.WristRotation,arm.HandRest):F2} clearance={PoseClearance(arm,torso.ToFrame(arm.Upper.position),arm.Position,arm.Pole):F4}\n";
            foreach (var arm in arms)
                if (arm.RouteStage == 2)
                    result += $"sweep left={arm.Left} progress={arm.ReturnProgress:F3} start={arm.ReturnStart:F4} controls={arm.ReturnControlA:F4}/{arm.ReturnControlB:F4} end={arm.ReturnEnd:F4} restClearance={PoseClearance(arm,torso.ToFrame(arm.Upper.position),arm.ReturnEnd,arm.NeutralPole):F4}\n";
            return result;
        }
        private void Awake()
        {
            if (animator == null) animator = GetComponentInChildren<Animator>();
            if (animator == null || !animator.isHuman) return;
            contact = GetComponent<AvatarContactController>(); gestures = GetComponent<AvatarGestureController>();
            var head = animator.GetBoneTransform(HumanBodyBones.Head);
            var front = Camera.main != null ? Camera.main.transform.position - head.position : animator.transform.forward;
            front = Vector3.ProjectOnPlane(front, animator.transform.up).normalized;
            var right = (animator.GetBoneTransform(HumanBodyBones.RightUpperArm).position - animator.GetBoneTransform(HumanBodyBones.LeftUpperArm).position).normalized;
            torso = new AvatarTorsoEnvelope(animator, front, right);
            foreach (var left in new[] { true, false })
            {
                var arm = new Arm { Left = left,
                    Upper = animator.GetBoneTransform(left ? HumanBodyBones.LeftUpperArm : HumanBodyBones.RightUpperArm),
                    Lower = animator.GetBoneTransform(left ? HumanBodyBones.LeftLowerArm : HumanBodyBones.RightLowerArm),
                    Hand = animator.GetBoneTransform(left ? HumanBodyBones.LeftHand : HumanBodyBones.RightHand) };
                arm.A = Vector3.Distance(arm.Upper.position, arm.Lower.position);
                arm.B = Vector3.Distance(arm.Lower.position, arm.Hand.position);
                arm.LowerRest = arm.Lower.localRotation; arm.HandRest = arm.Hand.localRotation;
                arm.UpperAim = arm.Upper.InverseTransformDirection(arm.Lower.position - arm.Upper.position).normalized;
                arm.LowerAim = arm.Lower.InverseTransformDirection(arm.Hand.position - arm.Lower.position).normalized;
                arm.Hinge = arm.Lower.InverseTransformDirection(Vector3.Cross(arm.Hand.position - arm.Lower.position, front)).normalized;
                var finger = animator.GetBoneTransform(left ? HumanBodyBones.LeftMiddleProximal : HumanBodyBones.RightMiddleProximal);
                arm.HandAim = arm.Hand.InverseTransformDirection(finger.position - arm.Hand.position).normalized;
                FitForearm(arm);
                arms.Add(arm);
            }
            CalibrateHinges();
            foreach (var arm in arms) arm.UpperHinge = arm.LowerRest * arm.Hinge;
        }
        private void FitForearm(Arm arm)
        {
            // Measure the bare middle of this model's forearm, away from the
            // puffed sleeve and palm. A 55 mm wrist ball widened Iris's pose.
            var axis = (arm.Hand.position-arm.Lower.position).normalized; var radius = .016f;
            foreach (var renderer in animator.GetComponentsInChildren<SkinnedMeshRenderer>())
            {
                var weights = renderer.sharedMesh.boneWeights; var bones = renderer.bones;
                if (weights.Length != renderer.sharedMesh.vertexCount) continue;
                var mesh = new Mesh(); renderer.BakeMesh(mesh); var vertices = mesh.vertices;
                for (var i = 0; i < vertices.Length; i++)
                {
                    var w = weights[i]; var weight = 0f;
                    if (w.boneIndex0 < bones.Length && bones[w.boneIndex0] == arm.Lower) weight += w.weight0;
                    if (w.boneIndex1 < bones.Length && bones[w.boneIndex1] == arm.Lower) weight += w.weight1;
                    if (w.boneIndex2 < bones.Length && bones[w.boneIndex2] == arm.Lower) weight += w.weight2;
                    if (w.boneIndex3 < bones.Length && bones[w.boneIndex3] == arm.Lower) weight += w.weight3;
                    if (weight < .9f) continue;
                    var offset = renderer.transform.TransformPoint(vertices[i])-arm.Lower.position;
                    var t = Vector3.Dot(offset,axis)/arm.B;
                    if (t < .35f || t > .8f) continue;
                    radius = Mathf.Max(radius,Vector3.ProjectOnPlane(offset,axis).magnitude); arm.RadiusSamples++;
                }
                Destroy(mesh);
            }
            arm.ForearmRadius = arm.RadiusSamples > 10 ? Mathf.Clamp(radius+.002f,.018f,.028f) : .025f;
            var index = animator.GetBoneTransform(arm.Left ? HumanBodyBones.LeftIndexProximal : HumanBodyBones.RightIndexProximal);
            var little = animator.GetBoneTransform(arm.Left ? HumanBodyBones.LeftLittleProximal : HumanBodyBones.RightLittleProximal);
            arm.HandRadius = Mathf.Clamp(Vector3.Distance(index.position,little.position)*.6f+.006f,.024f,.034f);
        }
        private void CalibrateHinges()
        {
            // Ask this exact Humanoid avatar for a pure elbow flexion. A generic
            // swing cone permits sideways/backwards bends and damages skinning.
            var bones = animator.GetComponentsInChildren<Transform>();
            var rotations = new Quaternion[bones.Length]; var positions = new Vector3[bones.Length];
            for (var i = 0; i < bones.Length; i++) { rotations[i] = bones[i].localRotation; positions[i] = bones[i].localPosition; }
            using (var handler = new HumanPoseHandler(animator.avatar, animator.transform))
            {
                var pose = new HumanPose(); handler.GetHumanPose(ref pose);
                foreach (var arm in arms)
                {
                    for (var i = 0; i < bones.Length; i++) { bones[i].localRotation = rotations[i]; bones[i].localPosition = positions[i]; }
                    var sample = pose; sample.muscles = (float[])pose.muscles.Clone();
                    var name = arm.Left ? "Left Forearm Stretch" : "Right Forearm Stretch";
                    var index = System.Array.IndexOf(HumanTrait.MuscleName, name);
                    if (index < 0) continue;
                    sample.muscles[index] = .5f; handler.SetHumanPose(ref sample);
                    var delta = Quaternion.Inverse(arm.LowerRest) * arm.Lower.localRotation;
                    if (delta.w < 0) delta = new Quaternion(-delta.x, -delta.y, -delta.z, -delta.w);
                    delta.ToAngleAxis(out var angle, out var axis);
                    if (angle > 20 && axis.sqrMagnitude > .1f) arm.Hinge = axis.normalized;
                }
            }
            for (var i = 0; i < bones.Length; i++) { bones[i].localRotation = rotations[i]; bones[i].localPosition = positions[i]; }
        }
        private void CalibrateRest(Arm arm, Vector3 shoulder, Vector3 source)
        {
            var wanted = torso.RestRoute(source,arm.Left ? -1 : 1,arm.HandRadius);
            var best = float.PositiveInfinity; var side = arm.Left ? -1f : 1f;
            arm.WristRotation = arm.HandRest; arm.Twist = 0;
            // Solve a relaxed whole arm. Keep the forearm nearly vertical and
            // preserve sleeve volume instead of folding both arms behind us.
            for (var outward = 6; outward <= 18; outward += 2)
            for (var forward = -30; forward <= 5; forward += 5)
            for (var lowerOut = -5; lowerOut <= 15; lowerOut += 5)
            for (var lowerForward = -35; lowerForward <= 25; lowerForward += 5)
            {
                var f = forward*Mathf.Deg2Rad; var o = outward*Mathf.Deg2Rad;
                var upper = new Vector3(side*Mathf.Cos(f)*Mathf.Tan(o),-Mathf.Cos(f),Mathf.Sin(f)).normalized;
                f = lowerForward*Mathf.Deg2Rad; o = lowerOut*Mathf.Deg2Rad;
                var lower = new Vector3(side*Mathf.Sin(o),-Mathf.Cos(o)*Mathf.Cos(f),Mathf.Cos(o)*Mathf.Sin(f)).normalized;
                var flex = Vector3.Angle(upper,lower);
                if (flex < 14 || flex > 65) continue;
                var elbow = shoulder+upper*arm.A; var wrist = elbow+lower*arm.B;
                if (side*wrist.x < .13f || side*wrist.x > .19f || wrist.z < -.185f) continue;
                var pole = Vector3.ProjectOnPlane(elbow-shoulder,(wrist-shoulder).normalized).normalized;
                var clearance = PoseClearance(arm,shoulder,wrist,pole);
                if (clearance < SafetyClearance+.004f) continue;
                var cost = (wrist-wanted).sqrMagnitude + (outward-10)*(outward-10)*.000002f
                    + (forward+20)*(forward+20)*.0000003f + lowerOut*lowerOut*.000004f;
                if (cost >= best) continue;
                best = cost; arm.NeutralGoal = wrist; arm.NeutralPole = pole;
            }
            arm.NeutralReady = best < float.PositiveInfinity;
            arm.NeutralShoulder = shoulder;
            if (!arm.NeutralReady)
            {
                arm.NeutralGoal = torso.FrontRoute(source,.06f);
                arm.NeutralPole = new Vector3(side*.08f,-.5f,1).normalized;
                arm.NeutralReady = true;
                Debug.LogWarning("[AvatarArms] Compact rest calibration found no collision-free candidate");
            }
        }
        internal void RestoreInput()
        {
            if (!applied) return;
            foreach (var arm in arms)
            {
                if (arm.Upper != null) arm.Upper.localRotation = arm.BeforeUpper;
                if (arm.Lower != null) arm.Lower.localRotation = arm.BeforeLower;
                if (arm.Hand != null) arm.Hand.localRotation = arm.BeforeHand;
            }
            applied = false;
        }
        private void LateUpdate()
        {
            if (torso == null || !animator.enabled || Time.deltaTime <= 0) return;
            var dt = Mathf.Min(.1f, Time.deltaTime);
            contact?.RefreshFaceProtection(); // After the body/head spring has run.
            foreach (var arm in arms)
            {
                arm.BeforeUpper = arm.Upper.localRotation; arm.BeforeLower = arm.Lower.localRotation; arm.BeforeHand = arm.Hand.localRotation;
                var source = torso.ToFrame(arm.Hand.position);
                var variant = gestures?.ActiveVariant;
                var ownsArm = variant != null && (variant.Channels & (arm.Left ? MotionChannels.LeftArm : MotionChannels.RightArm)) != 0;
                var activity = ownsArm ? gestures.GestureWeight : 0;
                var reachesContact = variant != null && contact != null && contact.HasTarget && (variant.Side == GestureSide.Left) == arm.Left;
                arm.ThumbUp=reachesContact && gestures.Active.Tag==GestureTag.Thumbs_Up;
                if(!arm.ThumbUp)arm.ThumbReady=false;
                arm.ContactPose=reachesContact;
                arm.MotionRate=reachesContact?Mathf.Clamp(gestures.PlaybackSpeed,.92f,1.08f):1;
                arm.FacePose=reachesContact && gestures.Active.Tag==GestureTag.Facepalm;
                if(!arm.FacePose){arm.FaceReady=false;arm.FaceApproaching=false;}
                arm.TwistLimit=reachesContact && (arm.FacePose || arm.ThumbUp)?65:35;
                // Animator and contact preparation have already blended the
                // source pose. Navigate towards the actual contact target;
                // blending that source again delays the hand past the accent.
                // Strengthen arrival at a contact, but let the full recovery
                // envelope release it. Amplifying the release held the hand at
                // the face until the last fraction of the return phase.
                if (reachesContact && gestures.Phase != GesturePhase.Recovery)
                    activity = Mathf.SmoothStep(0,1,Mathf.Clamp01(activity*5));
                else if (reachesContact)
                    activity = contact.ContactWeight;
                if(arm.FacePose && gestures.Phase==GesturePhase.Preparation)
                    activity=Mathf.SmoothStep(0,1,Mathf.Clamp01(gestures.Elapsed/.35f));
                arm.Activity = activity;
                // The coupled spring already smooths the return trajectory.
                // Blending its target with the held gesture delayed the side
                // route until recovery was almost over. Start the safe route
                // at the recovery boundary; the wrist keeps its own soft fade.
                var motionActivity = ownsArm && gestures.Phase == GesturePhase.Recovery ? 0 : activity;
                var goal = torso.FrontRoute(source,.12f);
                var sourceRotation = arm.Hand.rotation;
                var rotation = sourceRotation;
                if (reachesContact) { goal = torso.FrontRoute(torso.ToFrame(contact.WristTarget),.04f); rotation = contact.TargetRotation; }
                arm.FingerCount = 0;
                for (var bone = arm.Left ? HumanBodyBones.LeftThumbProximal : HumanBodyBones.RightThumbProximal; bone <= (arm.Left ? HumanBodyBones.LeftLittleDistal : HumanBodyBones.RightLittleDistal); bone++)
                {
                    var finger = animator.GetBoneTransform(bone);
                    if (finger != null)
                    {
                        var offset=Quaternion.Inverse(sourceRotation)*(finger.position-arm.Hand.position);
                        arm.Fingers[arm.FingerCount++]=offset;
                        if(bone==(arm.Left?HumanBodyBones.LeftMiddleProximal:HumanBodyBones.RightMiddleProximal))arm.PalmOffset=offset*.55f;
                    }
                }
                var thumbMiddle=animator.GetBoneTransform(arm.Left?HumanBodyBones.LeftThumbIntermediate:HumanBodyBones.RightThumbIntermediate);
                var thumbTip=animator.GetBoneTransform(arm.Left?HumanBodyBones.LeftThumbDistal:HumanBodyBones.RightThumbDistal);
                arm.ThumbAxis=Quaternion.Inverse(sourceRotation)*(thumbTip.position-thumbMiddle.position).normalized;
                var shoulder = torso.ToFrame(arm.Upper.position);
                if (!arm.NeutralReady) CalibrateRest(arm,shoulder,source);
                var restGoal = arm.NeutralGoal + shoulder - arm.NeutralShoulder + arm.RestOffset;
                var family = gestures?.Active != null ? AvatarMotionNames.BaseGesture(gestures.Active.Tag) : GestureTag.None;
                var conversational = family == GestureTag.Talk || family == GestureTag.Explanation || family == GestureTag.Question;
                if (conversational && !reachesContact)
                    goal.x = Mathf.Clamp(goal.x, shoulder.x - .10f, shoulder.x + .10f);
                if(reachesContact && arm.Initialized)
                {
                    // Keep the palm at the semantic point with the orientation
                    // this constrained arm actually reaches, rather than the
                    // separate source IK's orientation before wrist limiting.
                    var currentWrist=shoulder+arm.LastDirection*Reach(arm.Flex,arm.A,arm.B);
                    var actualRotation=LowerRotation(arm,shoulder,currentWrist,arm.Pole)*Quaternion.AngleAxis(arm.Twist,arm.LowerAim)*arm.WristRotation;
                    var contactWrist=contact.PalmTarget-actualRotation*arm.PalmOffset;
                    contactWrist=contact.ProjectHandOutsideFace(contactWrist,actualRotation,arm.Fingers,arm.FingerCount);
                    goal=torso.FrontRoute(torso.ToFrame(contactWrist),.04f);
                    // Thumbs-up constrains a direction, not a full authored
                    // palm yaw. Preserve the nearest comfortable hand facing.
                    if(arm.ThumbUp)rotation=Quaternion.FromToRotation(actualRotation*arm.ThumbAxis,animator.transform.up)*actualRotation;
                }
                if(arm.FacePose && arm.Initialized)
                {
                    SolveFacePose(arm,shoulder);
                    goal=arm.FaceGoal;
                    if(arm.FaceApproaching)
                    {
                        // Orient the palm in free space before moving into
                        // contact. A direct fold towards the forehead can trap
                        // backward-facing fingers at the face boundary.
                        var approach=goal+new Vector3(arm.Left?-.045f:.045f,-.065f,.11f);
                        var approachRay=approach-shoulder;
                        approach=shoulder+approachRay.normalized*Mathf.Min(approachRay.magnitude,Reach(25,arm.A,arm.B));
                        var currentWrist=shoulder+arm.LastDirection*Reach(arm.Flex,arm.A,arm.B);
                        var currentHand=LowerRotation(arm,shoulder,currentWrist,arm.Pole)*Quaternion.AngleAxis(arm.Twist,arm.LowerAim)*arm.WristRotation;
                        var finalWrist=torso.FromFrame(arm.FaceGoal);
                        var protectedWrist=contact.ProjectHandOutsideFace(finalWrist,currentHand,arm.Fingers,arm.FingerCount);
                        var aligned=Vector3.Distance(finalWrist,protectedWrist)<.04f;
                        var reached=currentWrist.y>approach.y-.035f && currentWrist.z>approach.z-.035f && Mathf.Abs(currentWrist.x-approach.x)<.065f;
                        if(reached && aligned)arm.FaceApproaching=false;else goal=approach;
                    }
                }
                goal = Vector3.Lerp(restGoal,goal,motionActivity);
                var side = arm.Left ? -1f : 1f;
                // Resting elbows hang close to the body. During a gesture,
                // favour forward bend over sideways flare without pulling back.
                var restPole = arm.NeutralPole;
                var preferred = new Vector3(side * .55f, -.55f, .85f).normalized;
                if (conversational) preferred = new Vector3(side * .20f, -.80f, .70f).normalized;
                var authoredPole = Vector3.ProjectOnPlane(torso.ToFrame(arm.Lower.position) - shoulder, (goal - shoulder).normalized).normalized;
                if (authoredPole.sqrMagnitude > .1f && Vector3.Dot(authoredPole, preferred) > 0)
                    preferred = (preferred * .70f + authoredPole * .30f).normalized;
                preferred = Vector3.Slerp(restPole,preferred,motionActivity).normalized;
                if(arm.FacePose && arm.FaceReady)preferred=Vector3.Slerp(restPole,arm.FacePole,motionActivity).normalized;
                if (arm.BodyPose >= 0)
                {
                    // Explicit body channels survive speech boundaries and hold
                    // until Iris lowers the hand. Use the same constrained IK.
                    reachesContact = false; arm.ContactPose = arm.FacePose = arm.ThumbUp = false;
                    activity = motionActivity = arm.Activity = arm.BodyPose == 0 ? 0 : 1;
                    goal = arm.BodyPose == 1 ? shoulder + new Vector3(side * .05f, .14f, .24f)
                        : arm.BodyPose == 2 ? shoulder + new Vector3(side * .035f, -.10f, .34f) : restGoal;
                    rotation = sourceRotation;
                    preferred = arm.BodyPose == 0 ? restPole : new Vector3(side * .50f, -.65f, .65f).normalized;
                    arm.BodyGoal = goal;
                }
                arm.ReturningToRest = motionActivity <= .01f;
                if (!arm.Initialized)
                {
                    arm.Position = goal; arm.Rotation = rotation;
                    arm.Velocity = arm.DirectionVelocity = Vector3.zero; arm.FlexVelocity = arm.SwivelVelocity = 0;
                    arm.Pole = preferred; arm.LastDirection = (arm.Position - shoulder).normalized;
                    arm.WristRotation = arm.HandRest;
                    arm.Flex = Flexion(arm.Position - shoulder, arm.A, arm.B); arm.Initialized = true;
                    arm.Position = shoulder + arm.LastDirection * Reach(arm.Flex, arm.A, arm.B);
                    // Start in a reachable, outward rest pose. A source idle may
                    // already put the hand in clothing before the first frame.
                    for (var i = 0; i < 40 && PoseClearance(arm, shoulder, arm.Position, arm.Pole) < .004f; i++)
                    {
                        arm.Position += new Vector3(side * .006f, 0, .008f);
                        var ray = arm.Position - shoulder;
                        arm.Flex = Flexion(ray, arm.A, arm.B);
                        arm.Position = shoulder + ray.normalized * Reach(arm.Flex, arm.A, arm.B);
                    }
                    arm.LastDirection = (arm.Position - shoulder).normalized;
                    arm.Pole = Vector3.ProjectOnPlane(arm.Pole, arm.LastDirection).normalized;
                }
                goal = RouteGoal(arm,shoulder,goal,ref preferred);
                if (activity <= .01f) arm.Detour = false;
                if (arm.Detour && arm.RouteStage < 0 && activity > .01f)
                {
                    var waypointY = Mathf.Max(arm.Position.y, shoulder.y - .12f);
                    var lane = torso.FrontAt(waypointY) + .08f;
                    if (arm.Position.z > torso.FrontAt(arm.Position.y) + .05f && PoseClearance(arm, shoulder, arm.Position, arm.Pole) > .005f) arm.Detour = false;
                    else
                    {
                        goal = new Vector3(shoulder.x + side * .025f, waypointY, lane + .01f);
                        preferred = new Vector3(side * Mathf.Lerp(.08f,.65f,activity), -.3f, 1f).normalized;
                    }
                }
                arm.Source = source; arm.Goal = goal;
                arm.Position = shoulder + arm.LastDirection * Reach(arm.Flex, arm.A, arm.B);
                arm.Rotation = AvatarPoseFilter.DampRotation(arm.Rotation, rotation, ref arm.RotationVelocity, dt, .18f/arm.MotionRate, 155*arm.MotionRate, 850*arm.MotionRate*arm.MotionRate);
                if (motionActivity > .01f && !arm.FacePose && (arm.RouteStage < 0 || reachesContact)) preferred = Vector3.Slerp(preferred,SelectPole(arm, shoulder, goal, preferred),motionActivity).normalized;
                UpdateHand(arm, shoulder, dt*.5f);
                var steps = Mathf.Max(1, Mathf.CeilToInt(dt * 120)); var h = dt / steps;
                for (var step = 0; step < steps; step++)
                {
                    var previous = arm.Position; var previousPole = arm.Pole; var previousFlex = arm.Flex;
                    // One critically damped controller in the chain's own
                    // degrees of freedom. Cascading a Cartesian wrist spring
                    // with acceleration-limited joints caused lag and orbits
                    // around waypoints even when there was no collision.
                    var angularError=DirectionStep(arm.LastDirection,(goal-shoulder).normalized);
                    var rate=arm.MotionRate;var rateSquared=rate*rate;
                    var angularAcceleration=Vector3.ClampMagnitude(angularError*(85*rateSquared)-arm.DirectionVelocity*(18.5f*rate),320*rateSquared);
                    var angularVelocity=Vector3.ClampMagnitude(arm.DirectionVelocity+angularAcceleration*h,(reachesContact?125:95)*rate);
                    var direction=angularVelocity.sqrMagnitude>.000001f
                        ?Quaternion.AngleAxis(angularVelocity.magnitude*h,angularVelocity.normalized)*arm.LastDirection:arm.LastDirection;
                    var flexAcceleration=Mathf.Clamp((Flexion(goal-shoulder,arm.A,arm.B)-arm.Flex)*(85*rateSquared)-arm.FlexVelocity*(18.5f*rate),-420*rateSquared,420*rateSquared);
                    var flex=Mathf.Clamp(arm.Flex+Mathf.Clamp(arm.FlexVelocity+flexAcceleration*h,-105*rate,105*rate)*h,14,128);
                    var candidate = shoulder + direction * Reach(flex, arm.A, arm.B);
                    var transported = Quaternion.FromToRotation(arm.LastDirection, direction) * arm.Pole;
                    var requestedPole = Vector3.ProjectOnPlane(preferred, direction).normalized;
                    if (requestedPole.sqrMagnitude < .1f) requestedPole = transported;
                    var swivelError=SignedAngle(transported,requestedPole,direction);
                    var resting = arm.Activity <= .01f;
                    var recovery = arm.RouteStage >= 0 && !arm.RouteFront;
                    var swivelAccelerationLimit = recovery ? 360 : 220;
                    var swivelStiffness = recovery ? 144 : resting ? 85 : 60;
                    var swivelDamping = recovery ? 24 : resting ? 18.5f : 15.5f;
                    var swivelAcceleration=Mathf.Clamp(swivelError*(swivelStiffness*rateSquared)-arm.SwivelVelocity*(swivelDamping*rate),-swivelAccelerationLimit*rateSquared,swivelAccelerationLimit*rateSquared);
                    var swivelLimit=(recovery ? 110 : arm.ContactPose?85:resting?80:55)*rate;
                    var swivelVelocity=Mathf.Clamp(arm.SwivelVelocity+swivelAcceleration*h,-swivelLimit,swivelLimit);
                    var pole=Quaternion.AngleAxis(swivelVelocity*h,direction)*transported;
                    var clearance = PoseClearance(arm, shoulder, candidate, pole);
                    // A fitted return already has a clearance corridor. Let its
                    // coupled spring track safe poses instead of replacing every
                    // near-garment step with a greedy position-only escape.
                    var boundaryMargin = arm.RouteStage == 2 && arm.ReturnPlanReady ? SafetyClearance + .0015f : .025f;
                    if (clearance < boundaryMargin)
                        AvoidBoundary(arm, shoulder, goal, preferred, h, ref candidate, ref pole, ref flex);
                    LimitJointStep(arm, shoulder, h, ref candidate, ref pole, ref flex);
                    clearance = PoseClearance(arm, shoulder, candidate, pole);
                    var requiredClearance = Mathf.Min(SafetyClearance, PoseClearance(arm, shoulder, previous, previousPole));
                    if (clearance < requiredClearance)
                    {
                        arm.Detour = true; BlockedSteps++;
                        // Stop at the first surface intersection and acquire a
                        // front waypoint. Never teleport a limb out of the body.
                        var low = 0f; var high = 1f;
                        for (var i = 0; i < 9; i++)
                        {
                            var t = (low + high) * .5f;
                            var trial = shoulder + Vector3.Slerp(arm.LastDirection, direction, t).normalized * Reach(Mathf.Lerp(previousFlex, flex, t), arm.A, arm.B);
                            if (PoseClearance(arm, shoulder, trial, Vector3.Slerp(previousPole, pole, t)) >= requiredClearance) low = t; else high = t;
                        }
                        flex = Mathf.Lerp(previousFlex, flex, low);
                        candidate = shoulder + Vector3.Slerp(arm.LastDirection, direction, low).normalized * Reach(flex, arm.A, arm.B);
                        pole = Vector3.Slerp(previousPole, pole, low);
                        arm.Velocity *= .75f;
                    }
                    var actualDirection = (candidate - shoulder).normalized;
                    arm.DirectionVelocity = DirectionStep(arm.LastDirection, actualDirection) / h;
                    arm.FlexVelocity = (flex - previousFlex) / h;
                    var previousTransportedPole = Quaternion.FromToRotation(arm.LastDirection, actualDirection) * previousPole;
                    arm.SwivelVelocity = SignedAngle(previousTransportedPole, pole, actualDirection) / h;
                    arm.Position = candidate; arm.Pole = pole; arm.Flex = flex;
                    arm.Velocity=Vector3.ClampMagnitude((candidate-previous)/h,.68f);
                    arm.LastDirection = (candidate - shoulder).normalized;
                    arm.Pole = Vector3.ProjectOnPlane(arm.Pole, arm.LastDirection).normalized;
                }
                UpdateHand(arm, shoulder, dt*.5f);
                var wrist = torso.FromFrame(arm.Position);
                var elbow = Elbow(arm.Upper.position, wrist, torso.DirectionToWorld(arm.Pole), arm.A, arm.B);
                ApplyHinge(arm, elbow, wrist, dt);
                var predicted=LowerRotation(arm,torso.ToFrame(arm.Upper.position),arm.Position,arm.Pole)*Quaternion.AngleAxis(arm.Twist,arm.LowerAim)*arm.WristRotation;
                arm.PredictionError=Quaternion.Angle(predicted,arm.Hand.rotation);
                arm.FinalPalmError=reachesContact?Vector3.Distance(arm.Hand.position+arm.Hand.rotation*arm.PalmOffset,contact.PalmTarget):0;
            }
            applied = true;
            ReleaseLoweredBodyPoses();
        }
        private Vector3 RouteGoal(Arm arm, Vector3 shoulder, Vector3 goal, ref Vector3 preferred)
        {
            var front = goal.z > .025f; var back = goal.z < -.025f;
            // Rest completion and an authored gesture can both cross the waist.
            // Only rest completion has a neutral elbow as its destination.
            if ((arm.RouteStage == 2 && !arm.ReturningToRest)
                || (arm.ReturningToRest && arm.RouteStage >= 0 && arm.RouteStage != 2))
            { arm.RouteStage = -1; arm.Detour = false; }
            if (arm.RouteStage >= 0 && ((arm.RouteFront && back) || (!arm.RouteFront && front))) arm.RouteStage = -1;
            if (arm.RouteStage == 2) return ReturnGoal(arm, shoulder, goal, ref preferred);
            if (arm.RouteStage < 0 && arm.ReturningToRest && back && Vector3.Distance(arm.Position, goal) > .06f)
            {
                BeginReturn(arm, shoulder, goal);
                return ReturnGoal(arm, shoulder, goal, ref preferred);
            }
            if (arm.RouteStage < 0 && ((arm.Position.z < -.025f && front) || (arm.Position.z > .025f && back)))
            {
                // Travel around the narrow waist, with a bent elbow. A waypoint
                // at hip height can lie outside the arm's reachable sphere and
                // leave it permanently extended before the next route stage.
                var y = Mathf.Clamp(Mathf.Min(arm.Position.y,goal.y),.11f,shoulder.y-.16f);
                var x = 0f; var frontZ = 0f; var backZ = 0f;
                for (var i = 0; i < 4; i++)
                {
                    var footprint=arm.HandRadius;
                    if(!front)for(var f=0;f<arm.FingerCount;f++)footprint=Mathf.Max(footprint,arm.Fingers[f].magnitude);
                    // Keep the lift close to the waist; the measured hand
                    // footprint and per-step clearance still protect clothing.
                    x = (arm.Left ? -1 : 1)*(torso.WidthAt(y)+footprint+(front?.035f:.025f));
                    frontZ = torso.FrontAt(y)+arm.HandRadius+.04f;
                    backZ = torso.BackAt(y)-arm.HandRadius-.04f;
                    var reach = Reach(35,arm.A,arm.B);
                    var horizontal = Mathf.Pow(x-shoulder.x,2)+Mathf.Max(Mathf.Pow(frontZ-shoulder.z,2),Mathf.Pow(backZ-shoulder.z,2));
                    y = Mathf.Max(y,shoulder.y-Mathf.Sqrt(Mathf.Max(.0025f,reach*reach-horizontal))+.025f);
                }
                arm.RouteEntry = new Vector3(x,y,front?(frontZ+backZ)*.5f+.055f:frontZ);
                arm.RouteFront = front;
                var exitY = y; var exitX = x;
                // Cross behind the waist before descending to the compact rest.
                // A diagonal goal below the hip can trap the wrist on the skirt
                // while the elbow tries to unwind at the same time.
                arm.RouteExit = new Vector3(exitX,exitY,front ? frontZ : backZ);
                arm.RouteStage = 0; arm.Detour = false;
            }
            if (arm.RouteStage < 0) return goal;
            var waypoint = arm.RouteStage == 0 ? arm.RouteEntry : arm.RouteExit;
            var sideSign=arm.Left?-1f:1f;
            var sideReached=sideSign*arm.Position.x>=sideSign*waypoint.x-.025f;
            var crossedGate=arm.RouteStage==0
                ?sideReached && (arm.RouteFront?arm.Position.z>.025f:arm.Position.y<shoulder.y-.08f)
                :sideReached && (arm.RouteFront?arm.Position.z>arm.RouteExit.z-.025f
                    :arm.Position.z<arm.RouteExit.z+.025f && arm.Position.y<arm.RouteExit.y+.035f);
            // Turn towards the rest plane in the free waist corridor.
            // Per-step clearance protects the crossing; waiting for an exact
            // elbow plane here adds an unnecessary outward pause.
            var recoveryPole = arm.RouteStage == 0 ? new Vector3(sideSign,0,0) : arm.NeutralPole;
            // A collision-free corridor is a region, not a point. The hand can
            // clear the body before it converges to the waypoint's exact height.
            // Waiting for that height can deadlock the next lift or recovery.
            if (Vector3.Distance(arm.Position,waypoint) < .035f || (crossedGate && PoseClearance(arm,shoulder,arm.Position,arm.Pole)>=SafetyClearance))
            {
                if (arm.RouteStage==0 && arm.RouteFront && goal.y>shoulder.y-.15f)
                { arm.RouteStage=-1;arm.Detour=false;return goal; }
                arm.RouteStage++;
                if (arm.RouteStage > 1) { arm.RouteStage = -1; arm.Detour = false; return goal; }
                waypoint = arm.RouteExit;
            }
            var z = arm.RouteStage == 0 ? arm.RouteEntry.z : arm.RouteExit.z;
            // Return through the same elbow plane as the lowered rest.
            // A wide rear pole twists the sleeve before the hand can descend.
            preferred = !arm.RouteFront
                ? recoveryPole
                : new Vector3(sideSign*.43f,-.4f,z >= 0 ? 1 : -1).normalized;
            return waypoint;
        }
        private void BeginReturn(Arm arm, Vector3 shoulder, Vector3 goal)
        {
            arm.RouteStage = 2; arm.RouteFront = false; arm.Detour = false;
            arm.ReturnPlanReady = arm.ReturnPlanPending = false;
            arm.ReturnStart = arm.Position; arm.ReturnEnd = goal; arm.ReturnShoulder = shoulder;
            arm.ReturnProgress = 0; arm.ReturnInitialFlex = arm.Flex;
            var side = arm.Left ? -1f : 1f;
            var direction = (arm.Position - shoulder).normalized;
            arm.ReturnStartAngle = SignedAngle(Vector3.ProjectOnPlane(Vector3.right * side, direction).normalized, arm.Pole, direction);
            var y = Mathf.Clamp(goal.y + .055f, .025f, .08f);
            var footprint = arm.HandRadius;
            for (var f = 0; f < arm.FingerCount; f++) footprint = Mathf.Max(footprint, arm.Fingers[f].magnitude);
            // The free side of the waist is a tangent to a sweep, not a pose
            // to reach and hold. Its height/width follow the outgoing pose and
            // the measured clothing and fingers, rather than a random offset.
            var lane = torso.WidthAt(y) + footprint + .025f;
            var high = Mathf.SmoothStep(0, 1, Mathf.InverseLerp(.08f, shoulder.y, arm.Position.y));
            arm.ReturnControlA = new Vector3(side * (lane + .015f), Mathf.Lerp(arm.Position.y, y, .85f),
                Mathf.Max(Mathf.Lerp(.06f, .20f, high), arm.Position.z));
            // A low supporting hand needs clearance beside the skirt before
            // crossing behind it. Approach the rest from behind that surface,
            // so the final extension cannot get pinned on its widest section.
            arm.ReturnControlB = new Vector3(side * (lane + .085f), y - Mathf.Lerp(.015f, .065f, high), goal.z - .05f);
            if (arm.ReturnStart.z <= .025f)
            {
                // A hand already behind the waist finishes there; it must not
                // swing out to the front corridor for another lap.
                arm.ReturnControlA = Vector3.Lerp(arm.ReturnStart, goal, 1f / 3);
                arm.ReturnControlB = Vector3.Lerp(arm.ReturnStart, goal, 2f / 3);
            }
            // Two-handed returns prepare on adjacent frames; the avatar keeps
            // rendering and never pays for both searches in the same frame.
            if (lastPlanningFrame != Time.frameCount)
            { lastPlanningFrame = Time.frameCount; BuildReturnPlan(arm, shoulder); }
            else arm.ReturnPlanPending = true;
        }
        private Vector3 ReturnPoint(Arm arm, Vector3 shoulder, float t)
        {
            if (!arm.ReturnPlanReady) return ReturnCurvePoint(arm, shoulder, t);
            var sample = Mathf.Clamp01(t) * ReturnSamples;
            var index = Mathf.Min(ReturnSamples - 1, Mathf.FloorToInt(sample));
            return Vector3.Lerp(arm.ReturnPositions[index], arm.ReturnPositions[index + 1], sample - index) + shoulder - arm.ReturnShoulder;
        }
        private Vector3 ReturnCurvePoint(Arm arm, Vector3 shoulder, float t)
        {
            var s = 1 - t;
            var point = s*s*s*arm.ReturnStart + 3*s*s*t*arm.ReturnControlA
                + 3*s*t*t*arm.ReturnControlB + t*t*t*arm.ReturnEnd + shoulder - arm.ReturnShoulder;
            var ray = point - shoulder;
            // Descend and open the elbow together. A Cartesian curve alone can
            // shorten the reach in its middle and recreate the sharp fold.
            var maximumFlex = Mathf.Lerp(arm.ReturnInitialFlex, 55, Mathf.SmoothStep(0, 1, Mathf.Clamp01(t * 2)));
            var reach = Mathf.Clamp(ray.magnitude, Reach(Mathf.Max(55, maximumFlex), arm.A, arm.B), Reach(14, arm.A, arm.B));
            return shoulder + ray.normalized * reach;
        }
        private Vector3 ReturnGoal(Arm arm, Vector3 shoulder, Vector3 goal, ref Vector3 preferred)
        {
            if (arm.ReturnPlanPending)
            {
                if (lastPlanningFrame == Time.frameCount) { preferred = arm.Pole; return arm.Position; }
                BeginReturn(arm, shoulder, goal);
            }
            var restPlane = Vector3.ProjectOnPlane(arm.NeutralPole, arm.LastDirection).normalized;
            if (Vector3.Distance(arm.Position, goal) < .025f && Vector3.Angle(arm.Pole, restPlane) < 10)
            { arm.RouteStage = -1; arm.Detour = false; return goal; }
            // Follow one continuous whole-arm curve. Wrist-only progress lets
            // the hand cross behind the waist before the elbow has turned,
            // leaving an inward bend that can no longer unwind beside clothing.
            var actualElbow = Elbow(shoulder, arm.Position, arm.Pole, arm.A, arm.B);
            var nearest = arm.ReturnProgress; var distance = float.PositiveInfinity;
            for (var i = 0; i <= 20; i++)
            {
                var t = Mathf.Lerp(arm.ReturnProgress, Mathf.Min(1, arm.ReturnProgress + .25f), i / 20f);
                var error = ReturnPoseError(arm, shoulder, actualElbow, t);
                if (error < distance) { distance = error; nearest = t; }
            }
            arm.ReturnProgress = nearest;
            var ahead = nearest;
            while (ahead < 1 && ReturnPoseError(arm, shoulder, actualElbow, ahead) < .11f * .11f) ahead = Mathf.Min(1, ahead + .025f);
            var point = ReturnPoint(arm, shoulder, ahead);
            preferred = ReturnPole(arm, shoulder, point, ahead);
            return point;
        }
        private float ReturnPoseError(Arm arm, Vector3 shoulder, Vector3 actualElbow, float t)
        {
            var wrist = ReturnPoint(arm, shoulder, t);
            var elbow = Elbow(shoulder, wrist, ReturnPole(arm, shoulder, wrist, t), arm.A, arm.B);
            return (wrist - arm.Position).sqrMagnitude + (elbow - actualElbow).sqrMagnitude * 2;
        }
        private static Vector3 ReturnPole(Arm arm, Vector3 shoulder, Vector3 wrist, float t)
        {
            var direction = (wrist - shoulder).normalized;
            var outward = Vector3.ProjectOnPlane(Vector3.right * (arm.Left ? -1 : 1), direction).normalized;
            if (arm.ReturnPlanReady)
            {
                var sample = Mathf.Clamp01(t) * ReturnSamples;
                var index = Mathf.Min(ReturnSamples - 1, Mathf.FloorToInt(sample));
                var planned = arm.ReturnAngles[index] + Mathf.DeltaAngle(arm.ReturnAngles[index], arm.ReturnAngles[index + 1]) * (sample - index);
                return Quaternion.AngleAxis(planned, direction) * outward;
            }
            var rest = Vector3.ProjectOnPlane(arm.NeutralPole, direction).normalized;
            // Unwrapped angles pass through the outside of the elbow circle.
            // The authored starting bend opens together with the wrist sweep.
            var angle = Mathf.Lerp(arm.ReturnStartAngle, SignedAngle(outward, rest, direction), Mathf.SmoothStep(0, 1, t));
            return Quaternion.AngleAxis(angle, direction) * outward;
        }
        private struct ReturnPose
        {
            public Vector3 Wrist, Elbow, Pole;
            public float Angle, Cost;
            public int Previous;
        }
        private void FitReturnEnd(Arm arm, Vector3 shoulder)
        {
            var ideal = arm.NeutralGoal + shoulder - arm.NeutralShoulder;
            var side = arm.Left ? -1f : 1f;
            var best = float.PositiveInfinity; var selected = arm.ReturnEnd;
            for (var back = 0; back <= 3; back++)
            for (var outward = 0; outward <= 2; outward++)
            for (var up = 0; up <= 2; up++)
            {
                var point = ideal + new Vector3(side * outward * .004f, up * .004f, -back * .0075f);
                var ray = point - shoulder;
                point = shoulder + ray.normalized * Mathf.Min(ray.magnitude, Reach(18, arm.A, arm.B));
                var elbow = Elbow(shoulder, point, arm.NeutralPole, arm.A, arm.B);
                var upper = Mathf.Atan2((elbow.x - shoulder.x) * side, shoulder.y - elbow.y) * Mathf.Rad2Deg;
                var lower = Mathf.Atan2((point.x - elbow.x) * side, elbow.y - point.y) * Mathf.Rad2Deg;
                if (upper < -8 || upper > 19 || lower < -8 || lower > 16.5f) continue;
                if (Mathf.Abs(point.x) < .13f || Mathf.Abs(point.x) > .20f || point.y < -.05f || point.y > .07f || point.z < -.20f || point.z > -.09f) continue;
                if (PoseClearance(arm, shoulder, point, arm.NeutralPole) < SafetyClearance + .003f) continue;
                var cost = (point - ideal).sqrMagnitude;
                if (cost >= best) continue;
                best = cost; selected = point;
            }
            if (float.IsPositiveInfinity(best)) return;
            arm.ReturnEnd = selected;
            arm.RestOffset = selected - ideal;
            if (arm.BodyPose == 0) arm.BodyGoal = selected;
        }
        private void BuildReturnPlan(Arm arm, Vector3 shoulder)
        {
            arm.ReturnPlanReady = false;
            var timer = System.Diagnostics.Stopwatch.StartNew();
            var layers = new List<ReturnPose>[ReturnSamples + 1];
            var side = arm.Left ? -1f : 1f;
            var oldWrist = arm.WristRotation; var oldTwist = arm.Twist;
            try
            {
                // Finger shapes and the current shoulder pose can need a few
                // millimetres of extra room at rest. Fit that endpoint while
                // preserving the narrow shoulder/forearm silhouette.
                arm.WristRotation = arm.HandRest; arm.Twist = 0;
                FitReturnEnd(arm, shoulder);
                for (var sample = 0; sample <= ReturnSamples; sample++)
                {
                    var t = sample / (float)ReturnSamples;
                    var wanted = ReturnCurvePoint(arm, shoulder, t);
                    var layer = layers[sample] = new List<ReturnPose>();
                    var release = Mathf.SmoothStep(0, 1, Mathf.Clamp01(t * 4));
                    arm.WristRotation = Quaternion.Slerp(oldWrist, arm.HandRest, release);
                    arm.Twist = Mathf.Lerp(oldTwist, 0, release);
                    if (sample == 0)
                    {
                        Add(arm.ReturnStart, arm.Pole, 0);
                    }
                    else if (sample == ReturnSamples)
                    {
                        Add(arm.ReturnEnd, arm.NeutralPole, 0);
                    }
                    else
                    {
                        for (var offset = 0; offset < 5; offset++)
                        {
                            var point = wanted + new Vector3(side * (offset == 0 ? 0 : offset % 2 == 1 ? .025f : .05f),
                                offset >= 3 ? .015f : 0, offset >= 3 ? (t < .35f ? .04f : -.04f) : 0);
                            var ray = point - shoulder;
                            var maxFlex = Mathf.Max(55, Mathf.Lerp(arm.ReturnInitialFlex, 55, Mathf.SmoothStep(0, 1, Mathf.Clamp01(t * 2))));
                            point = shoulder + ray.normalized * Mathf.Clamp(ray.magnitude, Reach(maxFlex, arm.A, arm.B), Reach(14, arm.A, arm.B));
                            var direction = (point - shoulder).normalized;
                            var outward = Vector3.ProjectOnPlane(Vector3.right * side, direction).normalized;
                            for (var angle = -180; angle < 180; angle += 30)
                                Add(point, Quaternion.AngleAxis(angle, direction) * outward, (point - wanted).sqrMagnitude * 2);
                        }
                    }
                    if (layer.Count == 0)
                    {
                        Debug.LogWarning($"[AvatarArms] No complete return corridor for {(arm.Left ? "left" : "right")} at {t:F2}; variant={gestures?.ActiveVariant?.Id} phase={gestures?.Phase} end={arm.ReturnEnd:F3} endClearance={PoseClearance(arm, shoulder, arm.ReturnEnd, arm.NeutralPole):F4}");
                        return;
                    }
                    // Keep spatial alternatives without carrying every offset
                    // into the next layer's search.
                    if (sample > 0 && sample < ReturnSamples)
                    {
                        layer.Sort((a, b) => a.Cost.CompareTo(b.Cost));
                        var counts = new Dictionary<int, int>();
                        var retained = new List<ReturnPose>();
                        foreach (var pose in layer)
                        {
                            var key = Mathf.RoundToInt(pose.Angle / 30);
                            var count = counts.TryGetValue(key, out var n) ? n : 0;
                            if (count >= 2) continue;
                            counts[key] = count + 1; retained.Add(pose);
                        }
                        layers[sample] = retained;
                    }
                    void Add(Vector3 wrist, Vector3 pole, float deviation)
                    {
                        var direction = (wrist - shoulder).normalized;
                        pole = Vector3.ProjectOnPlane(pole, direction).normalized;
                        var basis = Vector3.ProjectOnPlane(Vector3.right * side, direction).normalized;
                        var localAngle = SignedAngle(basis, pole, direction);
                        if (sample > 0 && PoseClearance(arm, shoulder, wrist, pole) < SafetyClearance + .002f) return;
                        var elbow = Elbow(shoulder, wrist, pole, arm.A, arm.B);
                        var outward = (elbow.x - shoulder.x) * side;
                        var local = deviation + Mathf.Pow(Mathf.Max(0, outward - .08f), 2) * 4
                            + Mathf.Pow(Mathf.Min(0, outward), 2) * 10
                            + Mathf.Pow(Mathf.Max(0, elbow.y - shoulder.y + .10f), 2) * 2;
                        var best = sample == 0 ? local : float.PositiveInfinity; var previous = -1;
                        if (sample > 0)
                        {
                            var prior = layers[sample - 1];
                            for (var p = 0; p < prior.Count; p++)
                            {
                                var a = prior[p];
                                var swivel = Mathf.Abs(Mathf.DeltaAngle(a.Angle, localAngle));
                                if (swivel > 45 || (a.Wrist - wrist).sqrMagnitude > .14f * .14f || (a.Elbow - elbow).sqrMagnitude > .12f * .12f) continue;
                                var middleWrist = (a.Wrist + wrist) * .5f;
                                var middlePole = (a.Pole + pole).normalized;
                                var middleElbow = Elbow(shoulder, middleWrist, middlePole, arm.A, arm.B);
                                var clear = true;
                                for (var i = 0; i <= 2; i++)
                                    if (torso.Distance(Vector3.Lerp(middleElbow, middleWrist, i / 2f)) - arm.ForearmRadius < SafetyClearance)
                                    { clear = false; break; }
                                if (!clear) continue;
                                var cost = a.Cost + local + (elbow - a.Elbow).sqrMagnitude * 4
                                    + (wrist - a.Wrist).sqrMagnitude + swivel * swivel * .000001f;
                                if (cost < best) { best = cost; previous = p; }
                            }
                        }
                        if (float.IsPositiveInfinity(best)) return;
                        layer.Add(new ReturnPose { Wrist = wrist, Elbow = elbow, Pole = pole,
                            Angle = localAngle, Cost = best, Previous = previous });
                    }
                }
                var selected = 0;
                for (var sample = ReturnSamples; sample >= 0; sample--)
                {
                    var pose = layers[sample][selected];
                    arm.ReturnPositions[sample] = pose.Wrist;
                    arm.ReturnAngles[sample] = pose.Angle;
                    selected = pose.Previous;
                }
                arm.ReturnPlanReady = true;
                if (Application.isBatchMode) Debug.Log($"[AvatarArms] Planned continuous {(arm.Left ? "left" : "right")} return in {timer.Elapsed.TotalMilliseconds:F1} ms");
            }
            finally { arm.WristRotation = oldWrist; arm.Twist = oldTwist; }
        }
        private static Vector3 DirectionStep(Vector3 from, Vector3 to)
        {
            var axis = Vector3.Cross(from, to);
            return axis.sqrMagnitude < .000000000001f ? Vector3.zero : axis.normalized * Mathf.Atan2(axis.magnitude, Vector3.Dot(from, to)) * Mathf.Rad2Deg;
        }
        private static float SignedAngle(Vector3 from, Vector3 to, Vector3 axis)
            => Mathf.Atan2(Vector3.Dot(axis, Vector3.Cross(from.normalized, to.normalized)), Vector3.Dot(from.normalized, to.normalized)) * Mathf.Rad2Deg;
        private void LimitJointStep(Arm arm, Vector3 shoulder, float dt, ref Vector3 position, ref Vector3 pole, ref float flex)
        {
            // Smooth in the chain's degrees of freedom. Filtering upper/lower
            // rotations separately would destroy both the hinge and body clearance.
            var direction = (position - shoulder).normalized;
            var requestedVelocity = DirectionStep(arm.LastDirection, direction) / dt;
            var rateSquared=arm.MotionRate*arm.MotionRate;
            var velocity = Vector3.MoveTowards(arm.DirectionVelocity, requestedVelocity, 320 * rateSquared * dt);
            velocity = Vector3.ProjectOnPlane(velocity, arm.LastDirection);
            direction = velocity.sqrMagnitude > .000001f ? Quaternion.AngleAxis(velocity.magnitude * dt, velocity.normalized) * arm.LastDirection : arm.LastDirection;
            var flexVelocity = Mathf.MoveTowards(arm.FlexVelocity, (flex - arm.Flex) / dt, 420 * rateSquared * dt);
            flex = Mathf.Clamp(arm.Flex + flexVelocity * dt, 14, 128);
            var transported = Quaternion.FromToRotation(arm.LastDirection, direction) * arm.Pole;
            var swivel = SignedAngle(transported, Vector3.ProjectOnPlane(pole, direction), direction);
            var swivelAcceleration = arm.RouteStage == 2 ? 360 : 220;
            var swivelVelocity = Mathf.MoveTowards(arm.SwivelVelocity, swivel / dt, swivelAcceleration * rateSquared * dt);
            pole = Quaternion.AngleAxis(swivelVelocity * dt, direction) * transported;
            position = shoulder + direction.normalized * Reach(flex, arm.A, arm.B);
        }
        private void AvoidBoundary(Arm arm, Vector3 shoulder, Vector3 goal, Vector3 preferred, float dt,
            ref Vector3 position, ref Vector3 pole, ref float flex)
        {
            // A newly opening finger or a moving shoulder can invalidate the old
            // pose. Binary search alone would then pin the arm to that boundary.
            // Search small, speed-limited joint steps, including elbow swivel by
            // itself, so the whole chain can travel around clothing continuously.
            var initial = PoseClearance(arm, shoulder, arm.Position, arm.Pole);
            var required = Mathf.Min(SafetyClearance, initial);
            var bestPosition = position; var bestPole = pole; var bestFlex = flex;
            var bestClearance = PoseClearance(arm, shoulder, position, pole);
            var bestCost = EscapeCost(arm,shoulder,position, pole, goal, preferred, bestClearance);
            foreach (var axis in new[] { Vector3.right, Vector3.up, Vector3.forward })
            foreach (var sign in new[] { -1f, 1f })
            {
                var direction = Vector3.RotateTowards(arm.LastDirection, (arm.LastDirection + axis * sign * .2f).normalized, 95 * Mathf.Deg2Rad * dt, 0).normalized;
                var candidatePole = Quaternion.FromToRotation(arm.LastDirection, direction) * arm.Pole;
                Consider(direction, arm.Flex, candidatePole);
            }
            foreach (var sign in new[] { -1f, 1f })
            {
                Consider(arm.LastDirection, Mathf.Clamp(arm.Flex + sign * 105 * dt, 14, 128), arm.Pole);
                var swivelSpeed = arm.RouteStage >= 0 && !arm.RouteFront ? 110 : 55;
                Consider(arm.LastDirection, arm.Flex, Quaternion.AngleAxis(sign * swivelSpeed * dt, arm.LastDirection) * arm.Pole);
            }
            position = bestPosition; pole = bestPole; flex = bestFlex;
            void Consider(Vector3 direction, float candidateFlex, Vector3 candidatePole)
            {
                var candidate = shoulder + direction * Reach(candidateFlex, arm.A, arm.B);
                var clearance = PoseClearance(arm, shoulder, candidate, candidatePole);
                if (clearance < required - .000001f) return;
                var cost = EscapeCost(arm,shoulder,candidate, candidatePole, goal, preferred, clearance);
                if (bestClearance < required || (initial < SafetyClearance ? clearance > bestClearance + .000001f : cost < bestCost))
                { bestPosition = candidate; bestPole = candidatePole; bestFlex = candidateFlex; bestCost = cost; bestClearance = clearance; }
            }
        }
        private static float EscapeCost(Arm arm, Vector3 shoulder, Vector3 position, Vector3 pole, Vector3 goal, Vector3 preferred, float clearance)
        {
            var desired = Vector3.ProjectOnPlane(preferred,(position-shoulder).normalized).normalized;
            var angle = Vector3.Angle(pole,desired);
            // Collision avoidance must retain a rest-pose objective. Otherwise
            // the shortest wrist path can leave the elbow permanently flared.
            return (position-goal).sqrMagnitude + Mathf.Pow(Mathf.Max(0,.016f-clearance),2)*100
                + angle*angle*(.00003f*Mathf.Pow(1-arm.Activity,4)*(arm.RouteStage >= 0 ? (arm.RouteFront?.01f:.02f) : 1)+.000000001f);
        }
        private void ApplyHinge(Arm arm, Vector3 elbow, Vector3 wrist, float dt)
        {
            var upperDirection = (elbow - arm.Upper.position).normalized;
            var lowerDirection = (wrist - elbow).normalized;
            var normal = Vector3.Cross(upperDirection, lowerDirection).normalized;
            arm.Upper.rotation = Quaternion.LookRotation(upperDirection, normal) * Quaternion.Inverse(Quaternion.LookRotation(arm.UpperAim, arm.UpperHinge));
            arm.Lower.localRotation = arm.LowerRest * Quaternion.AngleAxis(arm.Flex, arm.Hinge);
            arm.Lower.localRotation *= Quaternion.AngleAxis(arm.Twist, arm.LowerAim);
            arm.Hand.localRotation = arm.WristRotation;
        }
        private Quaternion LowerRotation(Arm arm, Vector3 shoulder, Vector3 wrist, Vector3 pole)
        {
            var s = torso.FromFrame(shoulder); var w = torso.FromFrame(wrist);
            var e = Elbow(s, w, torso.DirectionToWorld(pole), arm.A, arm.B);
            var direction = (e - s).normalized; var normal = Vector3.Cross(direction, (w - e).normalized).normalized;
            var upper = Quaternion.LookRotation(direction, normal) * Quaternion.Inverse(Quaternion.LookRotation(arm.UpperAim, arm.UpperHinge));
            return upper * arm.LowerRest * Quaternion.AngleAxis(Flexion(w - s, arm.A, arm.B), arm.Hinge);
        }
        private float RequestedTwist(Arm arm, Quaternion lower)
        {
            var delta = Quaternion.Inverse(arm.HandRest) * Quaternion.Inverse(lower) * arm.Rotation;
            return Mathf.Clamp(Mathf.DeltaAngle(0, 2 * Mathf.Atan2(Vector3.Dot(new Vector3(delta.x, delta.y, delta.z), arm.HandAim), delta.w) * Mathf.Rad2Deg), -arm.TwistLimit, arm.TwistLimit);
        }
        private Vector3 SelectPole(Arm arm, Vector3 shoulder, Vector3 wrist, Vector3 preferred)
        {
            if(arm.ThumbUp)return SolveThumbPose(arm,shoulder,wrist,preferred);
            var ray = wrist - shoulder; var direction = ray.normalized;
            wrist = shoulder + direction * Reach(Flexion(ray, arm.A, arm.B), arm.A, arm.B);
            var basis = Vector3.ProjectOnPlane(preferred, direction).normalized;
            if (basis.sqrMagnitude < .1f) return preferred;
            var best = basis; var bestCost = float.PositiveInfinity;
            var extent=arm.ContactPose?140:80; var increment=arm.ContactPose?10:20;
            for (var angle = -extent; angle <= extent; angle += increment)
            {
                var pole = Quaternion.AngleAxis(angle, direction) * basis;
                var lower = LowerRotation(arm, shoulder, wrist, pole);
                lower *= Quaternion.AngleAxis(RequestedTwist(arm, lower), arm.LowerAim);
                var local = AvatarPoseFilter.LimitJoint(Quaternion.Inverse(lower) * arm.Rotation, arm.HandRest, arm.HandAim, 38, 15);
                var error = arm.ThumbUp?Vector3.Angle(lower*local*arm.ThumbAxis,animator.transform.up):Quaternion.Angle(lower * local, arm.Rotation);
                var clearance = PoseClearance(arm, shoulder, wrist, pole);
                var previousPole=Quaternion.FromToRotation(arm.LastDirection,direction)*arm.Pole;
                var continuity=arm.ContactPose?Vector3.Angle(previousPole,pole)*.08f:0;
                var cost = error + continuity + Mathf.Abs(angle) * (arm.ThumbUp?.02f:arm.ContactPose?.04f:.11f) + Mathf.Max(0, .012f - clearance) * 100000;
                if (cost < bestCost) { bestCost = cost; best = pole; }
            }
            return best;
        }
        private Vector3 SolveThumbPose(Arm arm,Vector3 shoulder,Vector3 wrist,Vector3 preferred)
        {
            if(arm.ThumbReady && Time.time-arm.ThumbSolvedAt<.15f && Vector3.Distance(wrist,arm.ThumbGoal)<.01f
                && Vector3.Angle(arm.ThumbAxis,arm.ThumbSolvedAxis)<3)return arm.ThumbPole;
            var ray=wrist-shoulder;var direction=ray.normalized;
            wrist=shoulder+direction*Reach(Flexion(ray,arm.A,arm.B),arm.A,arm.B);
            var basis=Vector3.ProjectOnPlane(preferred,direction).normalized;
            if(basis.sqrMagnitude<.1f)basis=Vector3.ProjectOnPlane(Vector3.forward,direction).normalized;
            var previousPole=Quaternion.FromToRotation(arm.LastDirection,direction)*arm.Pole;
            var savedTwist=arm.Twist;var savedWrist=arm.WristRotation;
            var bestCost=float.PositiveInfinity;var bestPole=basis;var bestTwist=0f;var bestWrist=arm.HandRest;var bestAngle=0f;
            for(var angle=-180f;angle<180;angle+=20)
            for(var twist=-arm.TwistLimit;twist<=arm.TwistLimit;twist+=arm.TwistLimit*.5f)Consider(angle,twist);
            var centerAngle=bestAngle;var centerTwist=bestTwist;
            for(var angle=centerAngle-10;angle<=centerAngle+10;angle+=5)
            for(var twist=Mathf.Max(-arm.TwistLimit,centerTwist-10);twist<=Mathf.Min(arm.TwistLimit,centerTwist+10);twist+=5)Consider(angle,twist);
            arm.Twist=savedTwist;arm.WristRotation=savedWrist;
            arm.ThumbReady=true;arm.ThumbSolvedAt=Time.time;arm.ThumbGoal=wrist;arm.ThumbSolvedAxis=arm.ThumbAxis;
            arm.ThumbPole=bestPole;arm.ThumbTwist=bestTwist;arm.ThumbWrist=bestWrist;
            return bestPole;
            void Consider(float angle,float twist)
            {
                var pole=Quaternion.AngleAxis(angle,direction)*basis;
                var lower=LowerRotation(arm,shoulder,wrist,pole)*Quaternion.AngleAxis(twist,arm.LowerAim);
                var comfortable=lower*arm.HandRest;
                var up=Quaternion.FromToRotation(comfortable*arm.ThumbAxis,animator.transform.up)*comfortable;
                var local=AvatarPoseFilter.LimitJoint(Quaternion.Inverse(lower)*up,arm.HandRest,arm.HandAim,38,15);
                var error=Vector3.Angle(lower*local*arm.ThumbAxis,animator.transform.up);
                arm.Twist=twist;arm.WristRotation=local;
                var clearance=PoseClearance(arm,shoulder,wrist,pole);
                var cost=error*4+Vector3.Angle(previousPole,pole)*.08f+Mathf.Abs(twist-savedTwist)*.04f
                    +Quaternion.Angle(local,savedWrist)*.02f+Mathf.Max(0,SafetyClearance-clearance)*100000;
                if(cost>=bestCost)return;
                bestCost=cost;bestPole=pole;bestTwist=twist;bestWrist=local;bestAngle=angle;
            }
        }
        private void SolveFacePose(Arm arm,Vector3 shoulder)
        {
            var first=!arm.FaceReady;
            var palm=torso.ToFrame(contact.PalmTarget);var wanted=contact.TargetRotation;
            if(arm.FaceReady && Time.time-arm.FaceSolvedAt<.2f && Vector3.Distance(palm,arm.FaceWantedPalm)<.01f
                && Quaternion.Angle(wanted,arm.FaceWantedRotation)<4)return;
            var seed=torso.ToFrame(contact.PalmTarget-wanted*arm.PalmOffset);
            var ray=(seed-shoulder).normalized;
            var basis=Vector3.ProjectOnPlane(new Vector3(arm.Left?-.55f:.55f,-1,.12f),ray).normalized;
            var savedTwist=arm.Twist;var savedWrist=arm.WristRotation;
            var bestCost=float.PositiveInfinity;var bestGoal=seed;var bestPole=basis;var bestTwist=0f;var bestWrist=arm.HandRest;
            var bestAngle=0f;
            for(var angle=-180f;angle<180;angle+=15)
            for(var i=0;i<=6;i++)Consider(angle,Mathf.Lerp(-65,65,i/6f));
            var centerAngle=bestAngle;var centerTwist=bestTwist;
            for(var angle=centerAngle-7.5f;angle<=centerAngle+7.5f;angle+=2.5f)
            for(var twist=Mathf.Max(-65,centerTwist-10);twist<=Mathf.Min(65,centerTwist+10);twist+=5)Consider(angle,twist);
            arm.Twist=savedTwist;arm.WristRotation=savedWrist;
            arm.FaceReady=true;arm.FaceSolvedAt=Time.time;arm.FaceWantedPalm=palm;arm.FaceWantedRotation=wanted;
            if(first)arm.FaceApproaching=true;
            arm.FaceGoal=bestGoal;arm.FacePole=bestPole;arm.FaceTwist=bestTwist;arm.FaceWrist=bestWrist;
            void Consider(float angle,float twist)
            {
                var pole=Quaternion.AngleAxis(angle,ray)*basis;var wrist=seed;var local=arm.HandRest;var handRotation=wanted;
                for(var iteration=0;iteration<4;iteration++)
                {
                    var offset=wrist-shoulder;
                    wrist=shoulder+offset.normalized*Reach(Flexion(offset,arm.A,arm.B),arm.A,arm.B);
                    var lower=LowerRotation(arm,shoulder,wrist,pole)*Quaternion.AngleAxis(twist,arm.LowerAim);
                    local=AvatarPoseFilter.LimitJoint(Quaternion.Inverse(lower)*wanted,arm.HandRest,arm.HandAim,38,15);
                    handRotation=lower*local;
                    var next=contact.PalmTarget-handRotation*arm.PalmOffset;
                    next=contact.ProjectHandOutsideFace(next,handRotation,arm.Fingers,arm.FingerCount);
                    wrist=torso.ToFrame(next);
                }
                var finalRay=wrist-shoulder;
                wrist=shoulder+finalRay.normalized*Reach(Flexion(finalRay,arm.A,arm.B),arm.A,arm.B);
                pole=Vector3.ProjectOnPlane(pole,(wrist-shoulder).normalized).normalized;
                var finalLower=LowerRotation(arm,shoulder,wrist,pole)*Quaternion.AngleAxis(twist,arm.LowerAim);
                var elbow=torso.ToFrame(Elbow(torso.FromFrame(shoulder),torso.FromFrame(wrist),torso.DirectionToWorld(pole),arm.A,arm.B));
                if(elbow.y>shoulder.y+arm.A*.15f || elbow.y>wrist.y-arm.B*.3f)return;
                local=AvatarPoseFilter.LimitJoint(Quaternion.Inverse(finalLower)*wanted,arm.HandRest,arm.HandAim,38,15);
                handRotation=finalLower*local;
                arm.Twist=twist;arm.WristRotation=local;
                var clearance=PoseClearance(arm,shoulder,wrist,pole);
                var error=Vector3.Distance(torso.FromFrame(wrist)+handRotation*arm.PalmOffset,contact.PalmTarget);
                var previousPole=Quaternion.FromToRotation(arm.LastDirection,(wrist-shoulder).normalized)*arm.Pole;
                var cost=error*100+Quaternion.Angle(handRotation,wanted)*.08f+Vector3.Angle(previousPole,pole)*.02f
                    +Mathf.Abs(twist-savedTwist)*.01f+Mathf.Max(0,SafetyClearance-clearance)*100000;
                if(cost>=bestCost)return;
                bestCost=cost;bestGoal=wrist;bestPole=pole;bestTwist=twist;bestWrist=local;bestAngle=angle;
            }
        }
        private void UpdateHand(Arm arm, Vector3 shoulder, float dt)
        {
            var oldTwist = arm.Twist; var oldWrist = arm.WristRotation;
            var lower = LowerRotation(arm, shoulder, arm.Position, arm.Pole);
            var desiredTwist=arm.BodyPose >= 0 ? 0 : arm.ContactPose?ClosestContactTwist(arm,lower):RequestedTwist(arm,lower);
            arm.Twist = Mathf.SmoothDampAngle(arm.Twist, Mathf.Lerp(0,desiredTwist,arm.Activity), ref arm.TwistVelocity, .25f/arm.MotionRate, 75*arm.MotionRate, dt);
            lower *= Quaternion.AngleAxis(arm.Twist, arm.LowerAim);
            var desired=ContactHandRotation(arm,lower);
            // A precise hand pose uses a straight, relaxed wrist. Trying to keep
            // the idle hand's world orientation while lifting the arm makes the
            // raised palm hang downward even though the wrist position is correct.
            var wristTarget = arm.BodyPose >= 0 ? arm.HandRest
                : AvatarPoseFilter.LimitJoint(Quaternion.Inverse(lower) * desired, arm.HandRest, arm.HandAim, 38, 15);
            wristTarget = Quaternion.Slerp(arm.HandRest,wristTarget,arm.Activity);
            arm.WristRotation = AvatarPoseFilter.DampRotation(arm.WristRotation, wristTarget, ref arm.WristVelocity, dt, .16f/arm.MotionRate, Mathf.Min(112,110*arm.MotionRate), 600*arm.MotionRate*arm.MotionRate);
            if (PoseClearance(arm, shoulder, arm.Position, arm.Pole) >= SafetyClearance) return;
            var twist = arm.Twist; var wrist = arm.WristRotation; var low = 0f; var high = 1f;
            for (var i = 0; i < 8; i++)
            {
                var t = (low + high) * .5f; arm.Twist = Mathf.Lerp(oldTwist, twist, t); arm.WristRotation = Quaternion.Slerp(oldWrist, wrist, t);
                if (PoseClearance(arm, shoulder, arm.Position, arm.Pole) >= SafetyClearance) low = t; else high = t;
            }
            arm.Twist = Mathf.Lerp(oldTwist, twist, low); arm.WristRotation = Quaternion.Slerp(oldWrist, wrist, low);
            arm.Detour = true;
        }
        private Quaternion ContactHandRotation(Arm arm,Quaternion lower)
        {
            if(!arm.ThumbUp)return arm.Rotation;
            var comfortable=lower*arm.HandRest;
            return Quaternion.FromToRotation(comfortable*arm.ThumbAxis,animator.transform.up)*comfortable;
        }
        private float ClosestContactTwist(Arm arm,Quaternion lower)
        {
            var best=arm.Twist;var cost=float.PositiveInfinity;
            for(var i=0;i<=16;i++)
            {
                var twist=Mathf.Lerp(-arm.TwistLimit,arm.TwistLimit,i/16f);
                var candidateLower=lower*Quaternion.AngleAxis(twist,arm.LowerAim);
                var desired=ContactHandRotation(arm,candidateLower);
                var local=AvatarPoseFilter.LimitJoint(Quaternion.Inverse(candidateLower)*desired,arm.HandRest,arm.HandAim,38,15);
                var actual=candidateLower*local;
                var error=arm.ThumbUp?Vector3.Angle(actual*arm.ThumbAxis,animator.transform.up):Quaternion.Angle(actual,desired);
                var candidateCost=error+Mathf.Abs(twist-arm.Twist)*.03f+Quaternion.Angle(local,arm.WristRotation)*.015f;
                if(candidateCost>=cost)continue;
                cost=candidateCost;best=twist;
            }
            return best;
        }
        public static float Flexion(Vector3 ray, float a, float b) => Mathf.Clamp(Mathf.Acos(Mathf.Clamp((ray.sqrMagnitude - a * a - b * b) / (2 * a * b), -1, 1)) * Mathf.Rad2Deg, 14, 128);
        private static float Reach(float flex, float a, float b) => Mathf.Sqrt(a * a + b * b + 2 * a * b * Mathf.Cos(flex * Mathf.Deg2Rad));
        public static Vector3 Elbow(Vector3 shoulder, Vector3 wrist, Vector3 pole, float a, float b)
        {
            var ray = wrist - shoulder; var d = Mathf.Clamp(ray.magnitude, Mathf.Abs(a - b) + .001f, a + b - .001f);
            var direction = ray.normalized; var bend = Vector3.ProjectOnPlane(pole, direction).normalized;
            if (bend.sqrMagnitude < .1f) bend = Vector3.ProjectOnPlane(Vector3.forward, direction).normalized;
            var along = (a * a - b * b + d * d) / (2 * d);
            return shoulder + direction * along + bend * Mathf.Sqrt(Mathf.Max(0, a * a - along * along));
        }
        private float PoseClearance(Arm arm, Vector3 shoulder, Vector3 wrist, Vector3 pole)
        {
            var elbowWorld = Elbow(torso.FromFrame(shoulder), torso.FromFrame(wrist), torso.DirectionToWorld(pole), arm.A, arm.B);
            var elbow = torso.ToFrame(elbowWorld);
            var result = torso.Distance(wrist) - arm.HandRadius;
            // Include every point used by the independent twelve-step final
            // pose probe, and resolve the narrow skirt/waist cross sections.
            for (var i = 0; i <= 24; i++) result = Mathf.Min(result, torso.Distance(Vector3.Lerp(elbow, wrist, i / 24f)) - arm.ForearmRadius);
            var handRotation = LowerRotation(arm, shoulder, wrist, pole) * Quaternion.AngleAxis(arm.Twist, arm.LowerAim) * arm.WristRotation;
            var handPosition = torso.FromFrame(wrist);
            for (var i = 0; i < arm.FingerCount; i++)
            {
                var point = handPosition + handRotation * arm.Fingers[i];
                result = Mathf.Min(result, torso.Distance(torso.ToFrame(point)) - .014f);
                if (contact != null) result = Mathf.Min(result, contact.FingerFaceClearance(point));
            }
            return result;
        }
        public float MeasureBodyClearance(bool left)
        {
            var arm = arms.Find(a => a.Left == left); if (arm == null) return float.PositiveInfinity;
            var result = float.PositiveInfinity;
            for (var i = 0; i <= 12; i++) result = Mathf.Min(result, torso.Distance(torso.ToFrame(Vector3.Lerp(arm.Lower.position, arm.Hand.position, i / 12f))) - arm.ForearmRadius);
            for (var bone = left ? HumanBodyBones.LeftThumbProximal : HumanBodyBones.RightThumbProximal; bone <= (left ? HumanBodyBones.LeftLittleDistal : HumanBodyBones.RightLittleDistal); bone++)
            { var finger = animator.GetBoneTransform(bone); if (finger != null) result = Mathf.Min(result, torso.Distance(torso.ToFrame(finger.position)) - .010f); }
            return result;
        }
        public float MeasureElbowSideBend(bool left)
        {
            var arm = arms.Find(a => a.Left == left); if (arm == null) return 0;
            var normal = arm.Upper.rotation * arm.UpperHinge;
            return Mathf.Asin(Mathf.Clamp(Mathf.Abs(Vector3.Dot((arm.Hand.position - arm.Lower.position).normalized, normal)), 0, 1)) * Mathf.Rad2Deg;
        }
        public float MeasureEndpointError(bool left)
        { var arm = arms.Find(a => a.Left == left); return arm == null ? 0 : Vector3.Distance(arm.Hand.position, torso.FromFrame(arm.Position)); }
        public string Diagnostic(bool left)
        {
            var arm = arms.Find(a => a.Left == left); if (arm == null) return "";
            var c = System.Globalization.CultureInfo.InvariantCulture;
            return string.Join(",", System.Array.ConvertAll(new[] { arm.Position.x, arm.Position.y, arm.Position.z, arm.Source.x, arm.Source.y, arm.Source.z,
                arm.Goal.x, arm.Goal.y, arm.Goal.z, arm.Flex, arm.Twist, MeasureEndpointError(left), MeasureBodyClearance(left), MeasureElbowSideBend(left), arm.Detour ? 1f : 0f, (float)BlockedSteps,
                (float)arm.RouteStage, PoseClearance(arm,torso.ToFrame(arm.Upper.position),arm.Position,arm.Pole),arm.PredictionError,arm.FinalPalmError,
                Quaternion.Angle(arm.Hand.rotation,arm.Rotation) }, f => f.ToString("F5", c)));
        }
        private void OnDisable() { RestoreInput(); foreach (var arm in arms) arm.Initialized = false; }
    }
}
