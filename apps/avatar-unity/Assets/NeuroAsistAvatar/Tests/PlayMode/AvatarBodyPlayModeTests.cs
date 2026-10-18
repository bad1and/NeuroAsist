using System.Collections;
using System.Collections.Generic;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;

namespace NeuroAsist.Avatar.Tests
{
    public sealed class AvatarBodyPlayModeTests
    {
        private AvatarBodyController body;
        private AvatarMotionController motion;
        private AvatarArmRig arms;
        private readonly List<AvatarActionResultPayload> results = new List<AvatarActionResultPayload>();
        private static void Offline(Scene scene, LoadSceneMode mode)
        {
            foreach (var ws in Object.FindObjectsByType<AvatarWebSocketClient>(FindObjectsSortMode.None)) ws.enabled = false;
            foreach (var overlay in Object.FindObjectsByType<WindowsDesktopOverlay>(FindObjectsSortMode.None)) overlay.enabled = false;
        }
        [UnitySetUp] public IEnumerator Load()
        {
            SceneManager.sceneLoaded += Offline; SceneManager.LoadScene("AvatarOverlay");
            yield return null; SceneManager.sceneLoaded -= Offline;
            results.Clear();
            body = Object.FindFirstObjectByType<AvatarBodyController>();
            motion = Object.FindFirstObjectByType<AvatarMotionController>();
            arms = Object.FindFirstObjectByType<AvatarArmRig>();
            Assert.That(body, Is.Not.Null);
            body.Completed += results.Add;
            yield return new WaitForSeconds(.8f);
        }
        private IEnumerator Perform(string action)
        {
            results.Clear(); Assert.That(body.Execute(action, action), Is.True, action);
            var until = Time.time + 9;
            while (results.Count == 0 && Time.time < until) yield return null;
            Assert.That(results.Count, Is.EqualTo(1), action + " did not report a measured result");
            Assert.That(results[0].reached, Is.True, action + ": " + results[0].reason + "\n" + arms.DescribeArms());
        }
        [UnityTest] public IEnumerator LeftAndRightArmsRaiseIndependentlyAndSurviveSpeechBoundaries()
        {
            var rightRest = body.MeasuredRightHand;
            yield return Perform("raise_left_hand");
            Assert.That(body.MeasuredLeftHand.y, Is.GreaterThan(.40f));
            Assert.That(Vector3.Distance(body.MeasuredRightHand, rightRest), Is.LessThan(.045f));
            motion.BeginSpeechMotion(); motion.SetSpeaking(true);
            motion.QueueSpeechCue(0, 4, new AvatarMotionCuePayload { gesture = "auto" }); motion.OnSpeechSegmentStarted(0);
            yield return new WaitForSeconds(1);
            motion.ResetToNeutral(); yield return new WaitForSeconds(.5f);
            Assert.That(body.MeasuredLeftHand.y, Is.GreaterThan(.40f));
            yield return Perform("raise_right_hand");
            yield return Perform("lower_left_hand");
            Assert.That(body.MeasuredLeftHand.y, Is.LessThan(.08f));
            Assert.That(body.MeasuredRightHand.y, Is.GreaterThan(.40f));
            yield return Perform("lower_both_hands");
        }
        [UnityTest] public IEnumerator EveryHeadEyeAndExtensionActionHasAnActualResult()
        {
            foreach (var action in new[] { "extend_left_hand", "extend_right_hand", "extend_both_hands", "body_neutral",
                "tilt_head_left", "head_neutral", "tilt_head_right", "head_neutral", "turn_head_left", "head_neutral", "turn_head_right", "head_neutral",
                "look_up", "head_neutral", "look_down", "head_neutral", "blink_left", "blink_right", "blink",
                "close_left_eye", "open_left_eye", "close_right_eye", "open_right_eye", "close_eyes", "open_eyes", "body_neutral" })
                yield return Perform(action);
        }
        [UnityTest] public IEnumerator EyeAndHeadDirectionsStayIndependent()
        {
            yield return Perform("close_left_eye");
            Assert.That(results[0].left_eye, Is.GreaterThan(.94f)); Assert.That(results[0].right_eye, Is.LessThan(.05f));
            yield return Perform("open_eyes");
            yield return Perform("close_right_eye");
            Assert.That(results[0].right_eye, Is.GreaterThan(.94f)); Assert.That(results[0].left_eye, Is.LessThan(.05f));
            yield return Perform("open_eyes");
            yield return Perform("tilt_head_left"); Assert.That(results[0].head_roll, Is.GreaterThan(6));
            yield return Perform("tilt_head_right"); Assert.That(results[0].head_roll, Is.LessThan(-6));
            yield return Perform("head_neutral");
            yield return Perform("turn_head_left"); Assert.That(results[0].head_yaw, Is.LessThan(-18));
            yield return Perform("turn_head_right"); Assert.That(results[0].head_yaw, Is.GreaterThan(18));
        }
        [UnityTest] public IEnumerator SpeechWithNoModelGestureKeepsCompactRelaxedArms()
        {
            var gestures = Object.FindFirstObjectByType<AvatarGestureController>(); var count = 0;
            gestures.Started += _ => count++;
            motion.BeginSpeechMotion(); motion.SetSpeaking(true);
            motion.QueueSpeechCue(0, 10, new AvatarMotionCuePayload { gesture = "auto", emphasized = true }); motion.OnSpeechSegmentStarted(0);
            for (var elapsed = 0f; elapsed < 8; elapsed += Time.deltaTime)
            {
                yield return null;
                Assert.That(body.MeasuredLeftAbduction, Is.LessThan(25));
                Assert.That(body.MeasuredRightAbduction, Is.LessThan(25));
            }
            Assert.That(count, Is.Zero);
        }
        [UnityTest] public IEnumerator UnknownActionIsRejectedAndDisconnectReleasesHeldChannels()
        {
            Assert.That(body.Execute("fly"), Is.False);
            yield return Perform("raise_both_hands");
            body.ResetBody("disconnected");
            yield return new WaitForSeconds(7);
            Assert.That(body.MeasuredLeftHand.y, Is.LessThan(.08f));
            Assert.That(body.MeasuredRightHand.y, Is.LessThan(.08f));
        }
        [UnityTest] public IEnumerator ToolGesturesUseTheRequestedHandAndReportOnlyAfterPlayback()
        {
            var gestures = Object.FindFirstObjectByType<AvatarGestureController>();
            var sides = new List<GestureSide>(); gestures.Started += _ => sides.Add(gestures.ActiveVariant.Side);
            yield return Perform("raise_left_hand");
            yield return Perform("greeting_left");
            Assert.That(sides.Count, Is.EqualTo(1)); Assert.That(sides[0], Is.EqualTo(GestureSide.Left));
            yield return Perform("greeting_right");
            Assert.That(sides.Count, Is.EqualTo(2)); Assert.That(sides[1], Is.EqualTo(GestureSide.Right));
            yield return Perform("head_scratch_right");
            Assert.That(sides.Count, Is.EqualTo(3)); Assert.That(sides[2], Is.EqualTo(GestureSide.Right));
            Assert.That(results[0].action, Is.EqualTo("head_scratch_right"));
        }
        [UnityTest] public IEnumerator CancelledPlaybackDoesNotClaimItPerformedTheGesture()
        {
            Assert.That(body.Execute("greeting_left", "cancel-test"), Is.True);
            yield return new WaitForSeconds(.2f);
            motion.StopGesture(true);
            yield return new WaitForSeconds(.5f);
            Assert.That(results.Count, Is.EqualTo(1));
            Assert.That(results[0].reached, Is.False);
            Assert.That(results[0].reason, Is.EqualTo("animation_cancelled"));
        }
        [UnityTest] public IEnumerator OppositeEyeCanBlinkWhileOneEyeStaysClosedAndIdleBlinkReturns()
        {
            yield return Perform("close_right_eye");
            yield return Perform("blink_left");
            Assert.That(results[0].right_eye, Is.GreaterThan(.94f));
            Assert.That(results[0].left_eye, Is.LessThan(.05f));
            yield return Perform("open_eyes");
            var sawBlink = false; var until = Time.time + 8;
            while (Time.time < until)
            {
                yield return null;
                if (body.MeasuredLeftEye > .7f && body.MeasuredRightEye > .7f) sawBlink = true;
            }
            Assert.That(sawBlink, Is.True, "Opening the eyes must retain ordinary idle blinking");
        }
        [UnityTest] public IEnumerator BlinkingReplacesAHeldClosureOnlyOnTheRequestedEye()
        {
            yield return Perform("close_eyes");
            yield return Perform("blink_left");
            Assert.That(results[0].left_eye, Is.LessThan(.05f));
            Assert.That(results[0].right_eye, Is.GreaterThan(.94f));
            yield return Perform("close_eyes");
            yield return Perform("blink_right");
            Assert.That(results[0].right_eye, Is.LessThan(.05f));
            Assert.That(results[0].left_eye, Is.GreaterThan(.94f));
            yield return Perform("close_eyes");
            yield return Perform("blink");
            Assert.That(results[0].left_eye, Is.LessThan(.05f));
            Assert.That(results[0].right_eye, Is.LessThan(.05f));
        }
        [UnityTest] public IEnumerator DirectHandCommandsKeepSmoothNaturalWrists()
        {
            var probeObject = new GameObject("Direct hand continuity probe");
            var probe = probeObject.AddComponent<AvatarPoseContinuityProbe>();
            probe.Animator = motion.Animator; probe.Arms = arms;
            probe.Filter = Object.FindFirstObjectByType<AvatarPoseFilter>();
            probe.Contact = Object.FindFirstObjectByType<AvatarContactController>();
            probe.Gestures = Object.FindFirstObjectByType<AvatarGestureController>();
            probe.Garment = new AvatarGarmentProbe(motion.Animator, Camera.main);
            probe.Collect = true;
            try
            {
                foreach (var action in new[] { "raise_left_hand", "raise_right_hand", "lower_left_hand", "extend_right_hand", "lower_both_hands", "body_neutral" })
                {
                    probe.Context = action;
                    yield return Perform(action);
                    yield return new WaitForSeconds(.6f);
                    Assert.That(probe.Failure, Is.Null, probe.Failure);
                    if (action.StartsWith("raise"))
                    {
                        foreach (var point in action == "raise_right_hand" ? new[] { probe.LeftFingersViewport, probe.RightFingersViewport } : new[] { probe.LeftFingersViewport })
                        {
                            Assert.That(point.x, Is.InRange(.02f, .98f), action + " fingers outside portrait");
                            Assert.That(point.y, Is.InRange(.04f, .96f), action + " fingers outside portrait");
                        }
                    }
                }
                Assert.That(probe.PeakBend, Is.LessThan(20), "Explicit arm poses must keep a relaxed straight wrist");
                Assert.That(probe.GarmentClearance, Is.GreaterThan(-.006f));
            }
            finally { probe.Collect = false; probe.Garment.Dispose(); Object.Destroy(probeObject); }
        }
        [UnityTest] public IEnumerator LoweredHandsSweepContinuouslyWithoutAnExtraElbowFold()
        {
            var previousRate = Time.captureFramerate; Time.captureFramerate = 30;
            var probe = new GameObject("Final arm return probe").AddComponent<AvatarArmReturnProbe>();
            probe.Animator = motion.Animator; probe.Arms = arms;
            try
            {
                foreach (var action in new[] { "raise_left_hand", "extend_right_hand", "raise_right_hand", "extend_left_hand" })
                {
                    yield return Perform(action);
                    var left = action.Contains("left");
                    var side = left ? 0 : 1;
                    var initialFlex = probe.Flex[side];
                    var initialOutward = probe.Outward[side];
                    var peakFlex = initialFlex; var peakOutward = initialOutward;
                    var previous = probe.Position[side]; var slow = 0f; var longestSlow = 0f;
                    results.Clear();
                    Assert.That(body.Execute(left ? "lower_left_hand" : "lower_right_hand", "compact-return"), Is.True);
                    var started = Time.time;
                    while (Time.time - started < 6)
                    {
                        yield return null;
                        var position = probe.Position[side];
                        peakFlex = Mathf.Max(peakFlex, probe.Flex[side]);
                        peakOutward = Mathf.Max(peakOutward, probe.Outward[side]);
                        var resting = position.y < .07f && position.z < -.09f && probe.Abduction[side] < 20;
                        if (Time.time - started > .5f && !resting && Vector3.Distance(previous, position) / Time.deltaTime < .012f)
                            slow += Time.deltaTime;
                        else slow = 0;
                        longestSlow = Mathf.Max(longestSlow, slow); previous = position;
                    }
                    Debug.Log($"[ArmReturn] {action}: initial flex={initialFlex:F2}, peak flex={peakFlex:F2}, elbow outward={peakOutward:F4}m, intermediate dwell={longestSlow:F3}s");
                    Assert.That(results.Count, Is.EqualTo(1), action + " return result\n" + arms.DescribeArms());
                    Assert.That(results[0].reached, Is.True, action + " return must finish\n" + arms.DescribeArms());
                    Assert.That(peakFlex, Is.LessThanOrEqualTo(Mathf.Max(65, initialFlex + 8)), action + " must not fold before descending");
                    Assert.That(peakOutward, Is.LessThanOrEqualTo(Mathf.Max(.13f, initialOutward + .015f)), action + " returning elbow must stay within the compact clothing-clearance corridor");
                    Assert.That(longestSlow, Is.LessThan(.3f), action + " must not stop at an intermediate pose");
                }
            }
            finally { Time.captureFramerate = previousRate; Object.Destroy(probe.gameObject); }
        }
        [UnityTest] public IEnumerator LoweringAHandCannotResumeThePreviousGesture()
        {
            motion.TriggerGesture(GestureTag.Greeting_Left, 1, true);
            yield return new WaitForSeconds(.6f);
            yield return Perform("lower_left_hand");
            var until = Time.time + 4;
            while (Time.time < until)
            {
                yield return null;
                Assert.That(body.MeasuredLeftHand.y, Is.LessThan(.08f));
            }
        }
    }
    // Coroutines resume after input restoration and before the constrained
    // LateUpdate pose. Measure the rendered chain, not that intermediate input.
    [DefaultExecutionOrder(12000)] public sealed class AvatarArmReturnProbe : MonoBehaviour
    {
        public Animator Animator; public AvatarArmRig Arms;
        public readonly float[] Flex = new float[2], Outward = new float[2], Abduction = new float[2];
        public readonly Vector3[] Position = new Vector3[2];
        private void LateUpdate()
        {
            if (Animator == null || Arms == null) return;
            for (var side = 0; side < 2; side++)
            {
                var left = side == 0;
                var upper = Animator.GetBoneTransform(left ? HumanBodyBones.LeftUpperArm : HumanBodyBones.RightUpperArm);
                var lower = Animator.GetBoneTransform(left ? HumanBodyBones.LeftLowerArm : HumanBodyBones.RightLowerArm);
                var hand = Animator.GetBoneTransform(left ? HumanBodyBones.LeftHand : HumanBodyBones.RightHand);
                Flex[side] = Vector3.Angle(lower.position - upper.position, hand.position - lower.position);
                Outward[side] = Arms.MeasureElbowOutward(left); Abduction[side] = Arms.MeasureArmAbduction(left);
                Position[side] = Arms.MeasureHandPosition(left);
            }
        }
    }
}
