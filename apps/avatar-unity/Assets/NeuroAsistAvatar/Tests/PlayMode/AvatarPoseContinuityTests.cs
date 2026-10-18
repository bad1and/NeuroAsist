using System.Collections;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;
#if UNITY_EDITOR
using UnityEditor;
#endif

namespace NeuroAsist.Avatar.Tests
{
    public sealed class AvatarPoseContinuityTests
    {
        [UnityTest, Timeout(600000)] public IEnumerator EveryPerformanceAndMirrorKeepsContinuousAnatomicalWrists()
        {
#if UNITY_EDITOR
            SceneManager.sceneLoaded += Offline;
            SceneManager.LoadScene("AvatarOverlay");
            yield return null;
            SceneManager.sceneLoaded -= Offline;
            Random.InitState(7081);
            var args=System.Environment.GetCommandLineArgs();
            var familyArgument=System.Array.IndexOf(args,"-avatarTestFamilies");
            var families=familyArgument>=0 && familyArgument+1<args.Length?args[familyArgument+1].Split(','):null;
            var variantArgument=System.Array.IndexOf(args,"-avatarTestVariant");
            var onlyVariant=variantArgument>=0 && variantArgument+1<args.Length?args[variantArgument+1]:null;
            var motion = Object.FindFirstObjectByType<AvatarMotionController>();
            var gestures = Object.FindFirstObjectByType<AvatarGestureController>();
            var contact = Object.FindFirstObjectByType<AvatarContactController>();
            var armRig = Object.FindFirstObjectByType<AvatarArmRig>();
            Assert.That(armRig, Is.Not.Null);
            Assert.That(armRig.TorsoSamples, Is.GreaterThan(100));
            Assert.That(contact.FaceSurfaceSampleCount, Is.GreaterThan(100), "Face collision plane must use Iris's actual mesh");
            motion.enabled = false;
            var original = AssetDatabase.LoadAssetAtPath<AvatarMotionSettings>("Assets/NeuroAsistAvatar/Motion/AvatarMotionSettings.asset");
            var isolated = Object.Instantiate(original);
            var probe = new GameObject("Full final pose continuity probe").AddComponent<AvatarPoseContinuityProbe>();
            probe.Animator = motion.Animator;
            probe.Contact = contact; probe.Gestures = gestures;
            probe.Arms = armRig;
            var posture = probe.gameObject.AddComponent<AvatarPostureProbe>(); posture.Arms = armRig;
            probe.Filter = Object.FindFirstObjectByType<AvatarPoseFilter>();
            var previousRate = Time.captureFramerate;
            var previousVsync = QualitySettings.vSyncCount;
            var previousTargetRate = Application.targetFrameRate;
            var camera = Camera.main;
            probe.Garment = new AvatarGarmentProbe(motion.Animator, camera);
            var previousTarget = camera.targetTexture;
            var smallTarget = new RenderTexture(64, 64, 16);
            camera.targetTexture = smallTarget;
            QualitySettings.vSyncCount = 0; Application.targetFrameRate = -1;
            Time.captureFramerate = 30;
            var count = 0;
            try
            {
                for (var i = 0; i < 24; i++) yield return null;
                probe.Collect = true;
                foreach (var speedEdge in new[]{-1f,.92f,1.08f})
                foreach (var definition in original.GestureDefinitions.Where(d => d.Tag == AvatarBehaviorPolicy.Family(d.Tag)))
                foreach (var authored in definition.Variants)
                {
                    if(families!=null && !families.Contains(definition.Tag.ToString()))continue;
                    if(onlyVariant!=null && authored.Id!=onlyVariant)continue;
                    if(speedEdge>0 && !new[]{"Question_clarify","Facepalm_supported","Facepalm_brief","Thumbs_Up_direct","Thinking_chin_pause"}.Contains(authored.PatternId))continue;
                    var variant=authored;
                    if(speedEdge>0)
                    {
                        variant=JsonUtility.FromJson<GestureVariant>(JsonUtility.ToJson(authored));
                        variant.SpeedRange=new Vector2(speedEdge,speedEdge);
                    }
                    var single = Object.Instantiate(definition);
                    single.CooldownSeconds = 0; single.AllowedEmotions.Clear(); single.DeniedEmotions.Clear();
                    single.Variants = new List<GestureVariant> { variant };
                    isolated.GestureDefinitions = new List<GestureDefinition> { single };
                    gestures.Configure(isolated, motion.Animator); gestures.SetPolicy(new AvatarBehaviorPolicy());
                    probe.Context = variant.Id+(speedEdge>0?" speed="+speedEdge:"");
                    var left = variant.Side == GestureSide.Left;
                    var initialHand = left ? probe.LeftWrist : probe.RightWrist;
                    var travel = 0f;
                    Assert.That(gestures.Trigger(single.Tag, AvatarEmotion.Neutral, false, 1, false), Is.True, variant.Id);
                    var until = Time.time + variant.Duration / .92f + 3.5f;
                    while (Time.time < until)
                    {
                        yield return null;
                        Assert.That(probe.Failure, Is.Null, probe.Failure);
                        travel = Mathf.Max(travel, Vector3.Distance(initialHand, left ? probe.LeftWrist : probe.RightWrist));
                    }
                    Assert.That(gestures.IsPlaying, Is.False, variant.Id);
                    var leftAtDeadline = posture.LeftAbduction; var rightAtDeadline = posture.RightAbduction;
                    if (args.Contains("-avatarDiagnoseRest"))
                    {
                        Debug.Log("[RestDiagnostic] deadline " + variant.Id + "\n" + armRig.DescribeArms());
                        for (var restFrame=0;restFrame<240;restFrame++) yield return null;
                        Debug.Log("[RestDiagnostic] eight seconds later " + variant.Id + "\n" + armRig.DescribeArms());
                    }
                    Assert.That(leftAtDeadline,Is.InRange(-10f,20f),variant.Id+" left return\n"+armRig.DescribeArms());
                    Assert.That(rightAtDeadline,Is.InRange(-10f,20f),variant.Id+" right return\n"+armRig.DescribeArms());
                    AvatarPostureTests.AssertRelaxedLoweredHands(posture,variant.Id+" return");
                    if (single.Tag == GestureTag.Talk || single.Tag == GestureTag.Explanation || single.Tag == GestureTag.Thinking || single.Tag == GestureTag.Thumbs_Up || single.Tag == GestureTag.Greeting)
                        Assert.That(travel, Is.GreaterThan(.06f), variant.Id + " must retain visible gesture amplitude: " + armRig.Diagnostic(left));
                    Object.Destroy(single);
                    count++;
                    if (count % 32 == 0) Debug.Log($"[PoseContinuity] checked {count} performances (232 unique states plus speed edges)");
                }
                // Cancel at several points in a stroke, then acquire the opposite
                // hand. Cancellation is an equally important transition boundary.
                var reaction = original.GestureDefinitions.First(d => d.Tag == GestureTag.Thinking);
                for (var i = 0; i < 6; i++)
                {
                    var single = Object.Instantiate(reaction); single.CooldownSeconds = 0;
                    single.Variants = new List<GestureVariant> { reaction.Variants[i] };
                    isolated.GestureDefinitions = new List<GestureDefinition> { single };
                    gestures.Configure(isolated, motion.Animator); gestures.SetPolicy(new AvatarBehaviorPolicy());
                    Assert.That(gestures.Trigger(single.Tag, AvatarEmotion.Neutral, false, 1, false), Is.True);
                    yield return new WaitForSeconds(.25f + i * .22f);
                    gestures.Stop(true);
                    for (var f = 0; f < 30; f++) { yield return null; Assert.That(probe.Failure, Is.Null, probe.Failure); }
                    Object.Destroy(single);
                }
                Assert.That(probe.Garment.TriangleCount, Is.GreaterThan(100));
                Debug.Log($"[PoseContinuity] {count} performances and mirrored states; max joint speed={probe.PeakSpeed:F2} deg/s; max wrist bend={probe.PeakBend:F2} deg; final garment clearance={probe.GarmentClearance:F4} m; cancellation transitions passed.");
            }
            finally
            {
                Time.captureFramerate = previousRate; QualitySettings.vSyncCount = previousVsync; Application.targetFrameRate = previousTargetRate;
                camera.targetTexture = previousTarget; Object.Destroy(smallTarget);
                probe.Garment.Dispose();
                Object.Destroy(probe.gameObject); Object.Destroy(isolated);
            }
#else
            yield break;
#endif
        }
        private static void Offline(Scene scene, LoadSceneMode mode)
        {
            foreach (var ws in Object.FindObjectsByType<AvatarWebSocketClient>(FindObjectsSortMode.None)) ws.enabled = false;
            foreach (var overlay in Object.FindObjectsByType<WindowsDesktopOverlay>(FindObjectsSortMode.None)) overlay.enabled = false;
        }
    }
    [DefaultExecutionOrder(12000)]
    public sealed class AvatarPoseContinuityProbe : MonoBehaviour
    {
        public Animator Animator;
        public AvatarContactController Contact;
        public AvatarGestureController Gestures;
        public AvatarArmRig Arms;
        public AvatarPoseFilter Filter;
        internal AvatarGarmentProbe Garment;
        public float GarmentClearance = float.PositiveInfinity;
        public Vector3 LeftWrist, RightWrist;
        public Vector3 LeftFingersViewport, RightFingersViewport;
        public bool Collect;
        public string Context, Failure;
        public float PeakSpeed, PeakBend;
        private readonly Dictionary<HumanBodyBones, Quaternion> previous = new Dictionary<HumanBodyBones, Quaternion>();
        private void LateUpdate()
        {
            if (Animator == null || !Collect) return;
            LeftWrist = Animator.GetBoneTransform(HumanBodyBones.LeftHand).position;
            RightWrist = Animator.GetBoneTransform(HumanBodyBones.RightHand).position;
            LeftFingersViewport = Camera.main.WorldToViewportPoint(Animator.GetBoneTransform(HumanBodyBones.LeftMiddleDistal).position);
            RightFingersViewport = Camera.main.WorldToViewportPoint(Animator.GetBoneTransform(HumanBodyBones.RightMiddleDistal).position);
            var angles = Filter.MeasureHeadAngles();
            var budget = Mathf.Pow(angles.x/(angles.x>=0?26:16),2)+Mathf.Pow(angles.y/32,2)+Mathf.Pow(angles.z/12,2);
            if (budget > 1.02f && Failure == null) Failure = $"{Context}: combined head/neck exceeds anatomical limits: {angles}";
            if (Time.frameCount % 15 == 0)
            {
                Garment.Bake();
                foreach (var left in new[] { true, false })
                {
                    var clearance = Garment.Measure(left); GarmentClearance = Mathf.Min(GarmentClearance, clearance);
                    if (clearance < -.006f && Failure == null) Failure = $"{Context}: {(left ? "left" : "right")} forearm/fingers inside final garment surface by {-clearance:F4} m";
                }
            }
            foreach (var left in new[] { true, false })
            {
                var clearance = Arms.MeasureBodyClearance(left);
                var sideBend = Arms.MeasureElbowSideBend(left);
                if (clearance < -.003f && Failure == null) Failure = $"{Context}: {(left ? "left" : "right")} arm enters torso/clothing by {-clearance:F4} m\n"+Arms.DescribeArms()+"\n"+Arms.Diagnostic(left);
                if (sideBend > .5f && Failure == null) Failure = $"{Context}: elbow bends sideways by {sideBend:F2} degrees";
                if (Arms.MeasureEndpointError(left) > .003f && Failure == null) Failure = $"{Context}: arm chain endpoint disagrees with constrained wrist";
            }
            var variant = Gestures.ActiveVariant;
            // Positional contact belongs to the hold. The stroke is the
            // approach; collision and anatomical bounds still apply throughout.
            if(variant!=null && Contact.ContactWeight>.98f && Gestures.Phase==GesturePhase.Hold
                && Gestures.Active.Tag==GestureTag.Facepalm)
            {
                var left=variant.Side==GestureSide.Left;
                var hand=Animator.GetBoneTransform(left?HumanBodyBones.LeftHand:HumanBodyBones.RightHand);
                var finger=Animator.GetBoneTransform(left?HumanBodyBones.LeftMiddleProximal:HumanBodyBones.RightMiddleProximal);
                var palm=Vector3.Lerp(hand.position,finger.position,.55f);
                var error=Vector3.Distance(palm,Contact.PalmTarget);
                if(error>.085f && Failure==null)Failure=$"{Context}: final palm misses semantic target by {error:F3} m\n"+Arms.DescribeArms();
            }
            if(variant!=null && Gestures.Active.Tag==GestureTag.Thumbs_Up && Contact.ContactWeight>.98f
                && Gestures.Elapsed>variant.PreparationSeconds+variant.StrokeSeconds*.6f+.30f)
            {
                var left=variant.Side==GestureSide.Left;
                var hand=Animator.GetBoneTransform(left?HumanBodyBones.LeftHand:HumanBodyBones.RightHand);
                var middle=Animator.GetBoneTransform(left?HumanBodyBones.LeftThumbIntermediate:HumanBodyBones.RightThumbIntermediate);
                var tip=Animator.GetBoneTransform(left?HumanBodyBones.LeftThumbDistal:HumanBodyBones.RightThumbDistal);
                // The wrist may be below a waist-up crop. The raised thumb
                // itself must remain visible, including in a low support pose.
                var screen=Camera.main.WorldToViewportPoint(tip.position);
                if((screen.x<.02f || screen.x>.98f || screen.y<.02f || screen.y>.98f) && Failure==null)Failure=$"{Context}: raised thumb leaves the portrait at {Gestures.Elapsed:F3}s: {screen}\n"+Arms.Diagnostic(left)+"\n"+Arms.DescribeArms();
                var angle=Vector3.Angle(tip.position-middle.position,Vector3.up);
                // Inclined and supported performances need not share an exact
                // vertical pose; the thumb must remain recognizably upward.
                if(angle>45 && Failure==null)Failure=$"{Context}: thumb no longer points upward: {angle:F2} degrees\n"+Arms.DescribeArms()+"\n"+Arms.Diagnostic(left);
            }
            if (variant != null && AvatarBehaviorPolicy.Family(Gestures.Active.Tag) == GestureTag.Facepalm && Contact.ContactWeight > .98f
                && Gestures.Elapsed > variant.PreparationSeconds + variant.StrokeSeconds * .6f + .30f)
            {
                var clearance = Contact.MeasureFingerFaceClearance();
                if (clearance < -.012f && Failure == null) Failure = $"{Context}: fingers enter forehead surface by {-clearance:F3} m\n"+Arms.DescribeArms();
            }
            foreach (var id in new[] { HumanBodyBones.Head, HumanBodyBones.LeftUpperArm, HumanBodyBones.RightUpperArm,
                HumanBodyBones.LeftLowerArm, HumanBodyBones.RightLowerArm, HumanBodyBones.LeftHand, HumanBodyBones.RightHand })
            {
                var bone = Animator.GetBoneTransform(id); var rotation = bone.localRotation;
                var limit = id == HumanBodyBones.Head ? 92 : id == HumanBodyBones.LeftUpperArm || id == HumanBodyBones.RightUpperArm ? 245
                    : id == HumanBodyBones.LeftHand || id == HumanBodyBones.RightHand ? 115 : 150;
                if (previous.TryGetValue(id, out var last))
                {
                    var speed = Quaternion.Angle(last, rotation) / Time.deltaTime;
                    PeakSpeed = Mathf.Max(PeakSpeed, speed);
                    if (speed > limit && Failure == null) Failure = $"{Context}: {id} discontinuity {speed:F2} deg/s, limit {limit}";
                }
                previous[id] = rotation;
                if (id != HumanBodyBones.LeftHand && id != HumanBodyBones.RightHand) continue;
                var left = id == HumanBodyBones.LeftHand;
                var elbow = Animator.GetBoneTransform(left ? HumanBodyBones.LeftLowerArm : HumanBodyBones.RightLowerArm);
                var finger = Animator.GetBoneTransform(left ? HumanBodyBones.LeftMiddleProximal : HumanBodyBones.RightMiddleProximal);
                var bend = Vector3.Angle(bone.position - elbow.position, finger.position - bone.position);
                PeakBend = Mathf.Max(PeakBend, bend);
                if (bend > 58 && Failure == null) Failure = $"{Context}: {id} wrist folds {bend:F2} degrees";
            }
        }
    }
}
