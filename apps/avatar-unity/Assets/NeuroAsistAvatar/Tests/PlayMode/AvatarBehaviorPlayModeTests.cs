using System.Collections;
using System.Collections.Generic;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;
using UniVRM10;

namespace NeuroAsist.Avatar.Tests
{
    public sealed class AvatarBehaviorPlayModeTests
    {
        private AvatarMotionController motion;
        private AvatarGestureController gestures;
        private AvatarStateController state;
        private AvatarBehaviorFrameProbe frame;
        private static void Offline(Scene scene, LoadSceneMode mode)
        {
            foreach (var ws in Object.FindObjectsByType<AvatarWebSocketClient>(FindObjectsSortMode.None)) ws.enabled = false;
            foreach (var overlay in Object.FindObjectsByType<WindowsDesktopOverlay>(FindObjectsSortMode.None)) overlay.enabled = false;
        }
        [UnitySetUp] public IEnumerator Load()
        {
            SceneManager.sceneLoaded += Offline;
            SceneManager.LoadScene("AvatarOverlay");
            yield return null;
            SceneManager.sceneLoaded -= Offline;
            motion = Object.FindFirstObjectByType<AvatarMotionController>();
            gestures = Object.FindFirstObjectByType<AvatarGestureController>();
            state = Object.FindFirstObjectByType<AvatarStateController>();
            frame = new GameObject("Post-render-pose probe").AddComponent<AvatarBehaviorFrameProbe>();
            frame.Animator = motion.Animator;
            state.SetState(AvatarState.Idle, false);
            yield return new WaitForSeconds(.8f);
        }
        [UnityTest] public IEnumerator ANewRequestCannotEraseAnActiveStrokeAndQueueIsBounded()
        {
            var starts = new List<string>(); gestures.Started += d => starts.Add(d.Tag.ToString());
            motion.TriggerGesture(GestureTag.Facepalm, 1);
            yield return new WaitForSeconds(.6f);
            Assert.That(gestures.IsPlaying, Is.True);
            var original = gestures.ActiveVariantId;
            motion.TriggerGesture(GestureTag.Greeting_Left, .9f);
            motion.TriggerGesture(GestureTag.Greeting_Right, .9f);
            yield return null;
            Assert.That(gestures.ActiveVariantId, Is.EqualTo(original));
            Assert.That(motion.PendingCount, Is.EqualTo(1));
            yield return new WaitForSeconds(5f);
            Assert.That(starts.Count, Is.EqualTo(2));
            Assert.That(starts[1], Is.EqualTo("Greeting_Right"));
        }
        [UnityTest] public IEnumerator PlaybackSpeedControlsRealAnimatorTimeAndStopRecovers()
        {
            motion.TriggerGesture(GestureTag.Greeting_Left, .9f);
            yield return new WaitForSeconds(.3f);
            var variant = gestures.ActiveVariant;
            Assert.That(variant.Side, Is.EqualTo(GestureSide.Left));
            var layer = motion.Animator.GetLayerIndex(variant.LayerName);
            var before = motion.Animator.GetCurrentAnimatorStateInfo(layer).normalizedTime;
            var speed = gestures.PlaybackSpeed;
            yield return new WaitForSeconds(.4f);
            var after = motion.Animator.GetCurrentAnimatorStateInfo(layer).normalizedTime;
            Assert.That((after - before) * variant.Duration, Is.EqualTo(.4f * speed).Within(.12f));
            var weight = gestures.GestureWeight;
            motion.StopGesture(true);
            Assert.That(gestures.GestureWeight, Is.EqualTo(weight).Within(.001f));
            yield return new WaitForSeconds(.4f);
            Assert.That(gestures.IsPlaying, Is.False);
            Assert.That(motion.PendingCount, Is.Zero);
        }
        [UnityTest] public IEnumerator DuplicateSegmentsAndNewUtterancesCannotReplayOldCues()
        {
            var count = 0; gestures.Started += _ => count++;
            motion.BeginSpeechMotion(); state.SetState(AvatarState.Speaking, false);
            motion.SetSpeechMetadata(GestureTag.Greeting, .8f);
            motion.SetSpeechMetadata(GestureTag.Greeting, .8f);
            motion.QueueSpeechCue(0, 6, new AvatarMotionCuePayload { gesture = "greeting" });
            motion.OnSpeechSegmentStarted(0); motion.OnSpeechSegmentStarted(0);
            yield return new WaitForSeconds(.2f);
            Assert.That(count, Is.EqualTo(1));
            motion.QueueSpeechCue(1, 5, new AvatarMotionCuePayload { gesture = "facepalm" });
            motion.OnSpeechSegmentStarted(1);
            motion.BeginSpeechMotion(); state.SetState(AvatarState.Idle, false);
            yield return new WaitForSeconds(2f);
            Assert.That(count, Is.EqualTo(1));
            Assert.That(motion.PendingCount, Is.Zero);
        }
        [UnityTest] public IEnumerator NullableWireIntensityDoesNotLoseASpokenSemanticGesture()
        {
            var command = JsonUtility.FromJson<AvatarCommand>("{\"payload\":{\"motion\":{\"gesture\":\"facepalm\",\"intensity\":null}}}");
            motion.BeginSpeechMotion(); state.SetState(AvatarState.Speaking, false);
            motion.SetSpeechMetadata(GestureTag.Facepalm, .8f);
            motion.QueueSpeechCue(0, 4, command.payload.motion); motion.OnSpeechSegmentStarted(0);
            yield return new WaitForSeconds(.3f);
            Assert.That(gestures.IsPlaying, Is.True);
            Assert.That(gestures.Active.Tag, Is.EqualTo(GestureTag.Facepalm));
        }
        [UnityTest] public IEnumerator DuplicateMetadataDoesNotRestartATransientExpression()
        {
            var speech = Object.FindFirstObjectByType<AvatarSpeechCoordinator>();
            var emotion = Object.FindFirstObjectByType<AvatarEmotionController>();
            var command = new AvatarCommand { message_id = "metadata", timestamp = System.DateTime.UtcNow.ToString("O") };
            speech.StreamStart(command, new AvatarCommandPayload { utterance_id = "wink", emotion = "neutral" });
            var metadata = new AvatarCommandPayload { utterance_id = "wink", emotion = "wink", gesture = "none", intensity = .8f };
            speech.StreamMetadata(command, metadata);
            yield return new WaitForSeconds(.25f);
            var remaining = emotion.TransientRemaining;
            speech.StreamMetadata(command, metadata);
            yield return new WaitForSeconds(.1f);
            Assert.That(emotion.TransientRemaining, Is.LessThan(remaining));
            speech.Stop("wink");
        }
        [UnityTest] public IEnumerator NoneAndShortSpeechStayQuietAndHiddenPlaybackKeepsRunning()
        {
            var count = 0; gestures.Started += _ => count++;
            motion.BeginSpeechMotion(); state.SetState(AvatarState.Speaking, false);
            motion.QueueSpeechCue(0, 4, new AvatarMotionCuePayload { gesture = "none" }); motion.OnSpeechSegmentStarted(0);
            yield return new WaitForSeconds(4.1f);
            motion.QueueSpeechCue(1, .8f, new AvatarMotionCuePayload { gesture = "auto" }); motion.OnSpeechSegmentStarted(1);
            var sleep = Object.FindFirstObjectByType<AvatarSleepController>();
            sleep.SetSleeping(true); yield return new WaitForSeconds(1f);
            Assert.That(Time.timeScale, Is.EqualTo(1));
            Assert.That(count, Is.Zero);
            sleep.SetSleeping(false);
        }
        [UnityTest] public IEnumerator RootAndProceduralOffsetsDoNotAccumulateAcrossFrames()
        {
            var root = motion.Animator.transform; var position = root.localPosition; var rotation = root.localRotation;
            state.SetState(AvatarState.Listening, false);
            for (var i = 0; i < 300; i++)
            {
                yield return null;
                Assert.That(Vector3.Distance(root.localPosition, position), Is.LessThan(.001f));
                Assert.That(Quaternion.Angle(root.localRotation, rotation), Is.LessThan(.1f));
                var head = motion.Animator.GetBoneTransform(HumanBodyBones.Head);
                Assert.That(float.IsNaN(head.localRotation.x), Is.False);
            }
        }
        [UnityTest] public IEnumerator FacepalmReachesIrisForeheadRatherThanHerMouth()
        {
            motion.TriggerGesture(GestureTag.Facepalm, 1);
            var contact = Object.FindFirstObjectByType<AvatarContactController>();
            var deadline = Time.time + 3;
            while (Time.time < deadline && contact.ContactWeight < .85f) yield return null;
            Assert.That(contact.ContactWeight, Is.GreaterThan(.85f));
            Assert.That(Vector3.Distance(contact.PalmPosition, contact.PalmTarget), Is.LessThan(.035f));
            var leftEye = motion.Animator.GetBoneTransform(HumanBodyBones.LeftEye);
            Assert.That(contact.PalmPosition.y, Is.GreaterThan(leftEye.position.y));
            var otherHand = motion.Animator.GetBoneTransform(gestures.ActiveVariant.Side == GestureSide.Right ? HumanBodyBones.LeftHand : HumanBodyBones.RightHand);
            Assert.That(Vector3.Distance(otherHand.position, leftEye.position), Is.GreaterThan(.18f));
        }
        [UnityTest] public IEnumerator ThumbsUpKeepsTheHandInThePortraitWithAnUprightThumb()
        {
            motion.TriggerGesture(GestureTag.Thumbs_Up, 1);
            var contact = Object.FindFirstObjectByType<AvatarContactController>();
            var deadline = Time.time + 4;
            while (Time.time < deadline && contact.ContactWeight < .98f) yield return null;
            Assert.That(contact.ContactWeight, Is.GreaterThan(.98f));
            yield return new WaitForSeconds(.45f);
            Assert.That(Vector3.Distance(contact.PalmPosition, contact.PalmTarget), Is.LessThan(.05f));
            var side = gestures.ActiveVariant.Side == GestureSide.Left;
            // UnityTest resumes between Update and LateUpdate. The director has
            // deliberately removed last frame's offsets there; inspect the pose
            // sampled after UniVRM instead of the unfinished Animator frame.
            Assert.That(Vector3.Angle(side ? frame.LeftThumb : frame.RightThumb, Vector3.up), Is.LessThan(20));
            Assert.That(side ? frame.LeftElbow.y : frame.RightElbow.y, Is.LessThan(contact.PalmPosition.y + .04f));
            var projected = Camera.main.WorldToViewportPoint(contact.PalmPosition);
            Assert.That(projected.x, Is.InRange(.1f, .9f));
            Assert.That(projected.y, Is.InRange(.1f, .9f));
        }
        [UnityTest] public IEnumerator MutedHiddenStreamingStillAdvancesAudioAndLipSync()
        {
            var speech = Object.FindFirstObjectByType<AvatarSpeechCoordinator>();
            var player = Object.FindFirstObjectByType<AvatarAudioPlayer>();
            var command = new AvatarCommand { message_id = "offline-smoke", timestamp = System.DateTime.UtcNow.ToString("O") };
            speech.SetAudioMuted(true);
            speech.StreamStart(command, new AvatarCommandPayload { utterance_id = "offline-audio", emotion = "neutral" });
            var payload = new AvatarCommandPayload { utterance_id = "offline-audio", sequence = 0, duration_seconds = 2.5f, is_final = true, motion = new AvatarMotionCuePayload { gesture = "none" } };
            speech.StreamSegment(command, payload, TestWav());
            yield return new WaitForSeconds(.3f);
            var before = player.Source.timeSamples;
            var sleep = Object.FindFirstObjectByType<AvatarSleepController>(); sleep.SetSleeping(true);
            yield return new WaitForSeconds(.3f);
            Assert.That(player.Source.timeSamples, Is.GreaterThan(before));
            var vrm = Object.FindFirstObjectByType<Vrm10Instance>();
            Assert.That(vrm.Runtime.Expression.GetWeight(ExpressionKey.Aa), Is.GreaterThan(.01f));
            sleep.SetSleeping(false); speech.Stop("offline-audio");
        }
        private static byte[] TestWav()
        {
            const int rate = 24000, count = rate * 5 / 2;
            using (var memory = new System.IO.MemoryStream())
            using (var writer = new System.IO.BinaryWriter(memory))
            {
                writer.Write(System.Text.Encoding.ASCII.GetBytes("RIFF")); writer.Write(36 + count * 2);
                writer.Write(System.Text.Encoding.ASCII.GetBytes("WAVEfmt ")); writer.Write(16); writer.Write((short)1); writer.Write((short)1);
                writer.Write(rate); writer.Write(rate * 2); writer.Write((short)2); writer.Write((short)16);
                writer.Write(System.Text.Encoding.ASCII.GetBytes("data")); writer.Write(count * 2);
                for (var i = 0; i < count; i++) writer.Write((short)(Mathf.Sin(i * Mathf.PI * 2 * 190 / rate) * 9000));
                return memory.ToArray();
            }
        }
        [UnityTest] public IEnumerator TenMinutesOfScriptedConversationPreserveRootAndQueueBounds()
        {
            var previous = Time.timeScale; Time.timeScale = 12;
            var root = motion.Animator.transform; var position = root.localPosition; var rotation = root.localRotation;
            var beginning = Time.time; var turn = -1;
            try
            {
                while (Time.time - beginning < 600)
                {
                    var next = Mathf.FloorToInt((Time.time - beginning) / 10);
                    if (next != turn)
                    {
                        turn = next; motion.BeginSpeechMotion();
                        state.SetState(turn % 5 == 0 ? AvatarState.Listening : AvatarState.Speaking, false);
                        if (state.Current == AvatarState.Speaking)
                        {
                            motion.QueueSpeechCue(0, 8, new AvatarMotionCuePayload { gesture = turn % 7 == 0 ? "shrug" : "auto" });
                            motion.OnSpeechSegmentStarted(0);
                        }
                    }
                    yield return null;
                    Assert.That(motion.PendingCount, Is.InRange(0, 1));
                    Assert.That(Vector3.Distance(root.localPosition, position), Is.LessThan(.001f));
                    Assert.That(Quaternion.Angle(root.localRotation, rotation), Is.LessThan(.1f));
                }
            }
            finally { Time.timeScale = previous; motion.ResetToNeutral(); }
        }
    }

    [DefaultExecutionOrder(12000)]
    public sealed class AvatarBehaviorFrameProbe : MonoBehaviour
    {
        public Animator Animator;
        public Vector3 LeftThumb, RightThumb, LeftElbow, RightElbow;
        private void LateUpdate()
        {
            if (Animator == null) return;
            LeftThumb = Animator.GetBoneTransform(HumanBodyBones.LeftThumbDistal).position - Animator.GetBoneTransform(HumanBodyBones.LeftThumbIntermediate).position;
            RightThumb = Animator.GetBoneTransform(HumanBodyBones.RightThumbDistal).position - Animator.GetBoneTransform(HumanBodyBones.RightThumbIntermediate).position;
            LeftElbow = Animator.GetBoneTransform(HumanBodyBones.LeftLowerArm).position;
            RightElbow = Animator.GetBoneTransform(HumanBodyBones.RightLowerArm).position;
        }
    }
}
