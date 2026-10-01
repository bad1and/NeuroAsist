using System;
using System.Collections;
using NUnit.Framework;
using UniVRM10;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.TestTools;

namespace NeuroAsist.Avatar.Tests
{
    public sealed class AvatarAudioPlayerTests
    {
        [UnityTest]
        public IEnumerator MutedSpeechKeepsPlayingAndMovingMouthWhileHidden()
        {
            EditorSceneManager.OpenScene("Assets/Scenes/AvatarOverlay.unity");
            // This is a local playback check, independent of the user's backend.
            UnityEngine.Object.FindFirstObjectByType<AvatarWebSocketClient>().enabled = false;
            yield return new EnterPlayMode();
            var player = UnityEngine.Object.FindFirstObjectByType<AvatarAudioPlayer>();
            var speech = UnityEngine.Object.FindFirstObjectByType<AvatarSpeechCoordinator>();
            var sleep = UnityEngine.Object.FindFirstObjectByType<AvatarSleepController>();
            var vrm = UnityEngine.Object.FindFirstObjectByType<Vrm10Instance>();
            var camera = Camera.main;
            var samples = new short[12000];
            for (var i = 0; i < samples.Length; i++)
                samples[i] = (short)(Math.Sin(i * 2 * Math.PI * 220 / 16000) * 9000);
            var wav = CreatePcm16Wav(samples);
            var command = new AvatarCommand { message_id = "local-playback-test" };
            var payload = new AvatarCommandPayload { utterance_id = "local-playback-test", emotion = "neutral" };
            speech.SetAudioMuted(true);
            speech.StreamStart(command, payload);
            speech.StreamSegment(command, new AvatarCommandPayload { utterance_id = payload.utterance_id, sequence = 0 }, wav);
            yield return new WaitForSecondsRealtime(.35f);
            var generation = player.Generation;
            sleep.SetSleeping(true);
            var previousSample = player.Source.timeSamples;
            yield return new WaitForSecondsRealtime(.15f);
            Assert.That(player.Source.isPlaying, Is.True);
            Assert.That(player.Source.timeSamples, Is.GreaterThan(previousSample));
            Assert.That(player.Generation, Is.EqualTo(generation));
            Assert.That(vrm.Runtime.Expression.GetWeight(ExpressionKey.Aa), Is.GreaterThan(.05f));
            Assert.That(camera.enabled, Is.False);
            speech.StreamSegment(command, new AvatarCommandPayload { utterance_id = payload.utterance_id, sequence = 1 }, wav);
            speech.StreamEnd(command, payload);
            yield return new WaitForSecondsRealtime(.6f);
            Assert.That(player.Source.isPlaying, Is.True, "The next segment must start while the renderer is hidden");
            Assert.That(vrm.Runtime.Expression.GetWeight(ExpressionKey.Aa), Is.GreaterThan(.05f));
            sleep.SetSleeping(false);
            Assert.That(camera.enabled, Is.True);
            Assert.That(player.Generation, Is.EqualTo(generation));
            yield return new WaitForSecondsRealtime(.7f);
            Assert.That(player.Source.isPlaying, Is.False);
            speech.Stop(null);
            yield return new ExitPlayMode();
        }

        [Test]
        public void HiddenAvatarPreservesSpeechAndScaledTime()
        {
            var go = new GameObject("HiddenAvatarSpeech");
            var settings = ScriptableObject.CreateInstance<AvatarRuntimeSettings>();
            var oldScale = Time.timeScale;
            var oldRate = Application.targetFrameRate;
            var oldSync = QualitySettings.vSyncCount;
            try
            {
                var source = go.AddComponent<AudioSource>();
                var player = go.AddComponent<AvatarAudioPlayer>();
                player.Configure(settings, source);
                var speech = go.AddComponent<AvatarSpeechCoordinator>();
                var state = go.AddComponent<AvatarStateController>();
                var emotion = go.AddComponent<AvatarEmotionController>();
                var fallback = go.AddComponent<VolumeLipSyncFallback>();
                foreach (var pair in new[] {
                    ("player", (UnityEngine.Object)player), ("state", state),
                    ("emotion", emotion), ("fallback", fallback),
                })
                    typeof(AvatarSpeechCoordinator).GetField(pair.Item1,
                        System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance).SetValue(speech, pair.Item2);
                var camera = go.AddComponent<Camera>();
                var sleep = go.AddComponent<AvatarSleepController>();
                sleep.Configure(camera, speech, null);
                player.BeginStream(7, () => { }, () => { }, _ => { });
                state.SetState(AvatarState.Speaking, false);
                emotion.SetSpeaking(true);

                sleep.SetSleeping(true);
                Assert.That(camera.enabled, Is.False);
                Assert.That(Time.timeScale, Is.EqualTo(1f), "Stream waits and mouth smoothing must keep advancing");
                Assert.That(player.Generation, Is.EqualTo(7), "Navigation must not cancel the active speech generation");
                Assert.That(emotion.IsSpeaking, Is.True);
                Assert.That(state.Current, Is.EqualTo(AvatarState.Speaking));
                sleep.SetSleeping(false);
                Assert.That(camera.enabled, Is.True);
                Assert.That(player.Generation, Is.EqualTo(7));
            }
            finally
            {
                Time.timeScale = oldScale;
                Application.targetFrameRate = oldRate;
                QualitySettings.vSyncCount = oldSync;
                UnityEngine.Object.DestroyImmediate(go);
                UnityEngine.Object.DestroyImmediate(settings);
            }
        }

        [Test]
        public void DecodesPcm16MonoWav()
        {
            var clip = WavClipDecoder.Decode(CreatePcm16Wav(new short[] { 0, 16384, -16384 }), "test");
            try
            {
                Assert.That(clip.channels, Is.EqualTo(1));
                Assert.That(clip.frequency, Is.EqualTo(16000));
                Assert.That(clip.samples, Is.EqualTo(3));
            }
            finally { UnityEngine.Object.DestroyImmediate(clip); }
        }

        [Test]
        public void RejectsCorruptedWav()
        {
            Assert.That(() => WavClipDecoder.Decode(new byte[44], "bad"), Throws.ArgumentException);
        }

        [Test]
        public void RejectsNonPcm16Wav()
        {
            var wav = CreatePcm16Wav(new short[] { 0 });
            BitConverter.GetBytes((short)8).CopyTo(wav, 34);
            Assert.That(() => WavClipDecoder.Decode(wav, "bad-format"), Throws.ArgumentException);
        }

        private static byte[] CreatePcm16Wav(short[] samples)
        {
            const int channels = 1;
            const int sampleRate = 16000;
            var bytes = new byte[44 + samples.Length * sizeof(short)];
            Array.Copy(System.Text.Encoding.ASCII.GetBytes("RIFF"), 0, bytes, 0, 4);
            BitConverter.GetBytes(bytes.Length - 8).CopyTo(bytes, 4);
            Array.Copy(System.Text.Encoding.ASCII.GetBytes("WAVEfmt "), 0, bytes, 8, 8);
            BitConverter.GetBytes(16).CopyTo(bytes, 16);
            BitConverter.GetBytes((short)1).CopyTo(bytes, 20);
            BitConverter.GetBytes((short)channels).CopyTo(bytes, 22);
            BitConverter.GetBytes(sampleRate).CopyTo(bytes, 24);
            BitConverter.GetBytes(sampleRate * channels * sizeof(short)).CopyTo(bytes, 28);
            BitConverter.GetBytes((short)(channels * sizeof(short))).CopyTo(bytes, 32);
            BitConverter.GetBytes((short)16).CopyTo(bytes, 34);
            Array.Copy(System.Text.Encoding.ASCII.GetBytes("data"), 0, bytes, 36, 4);
            BitConverter.GetBytes(samples.Length * sizeof(short)).CopyTo(bytes, 40);
            Buffer.BlockCopy(samples, 0, bytes, 44, samples.Length * sizeof(short));
            return bytes;
        }
    }
}
