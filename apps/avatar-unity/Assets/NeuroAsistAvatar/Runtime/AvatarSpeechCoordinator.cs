using System;
using System.Collections.Generic;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    public sealed class AvatarSpeechCoordinator : MonoBehaviour
    {
        [SerializeField] private AvatarWebSocketClient client;
        [SerializeField] private AvatarAudioPlayer player;
        [SerializeField] private AvatarEmotionController emotion;
        [SerializeField] private AvatarStateController state;
        [SerializeField] private VolumeLipSyncFallback fallback;
        [SerializeField] private AvatarMotionController motion;
        [SerializeField] private AvatarLookController lookController;
        private int generation;
        private string currentUtterance;
        private int nextStreamSequence;
        private GestureTag pendingStreamGesture = GestureTag.Auto;
        private float pendingStreamGestureIntensity = 1f;
        private string currentStreamEmotion = "neutral";

        private sealed class SegmentEmotionCue
        {
            public string Emotion;
            public float Intensity;
        }

        private readonly Dictionary<int, SegmentEmotionCue> segmentEmotions = new Dictionary<int, SegmentEmotionCue>();

        private void Awake()
        {
            if (player == null) player = GetComponent<AvatarAudioPlayer>() ?? GetComponentInChildren<AvatarAudioPlayer>();
            if (lookController == null) lookController = GetComponent<AvatarLookController>() ?? GetComponentInChildren<AvatarLookController>();
            HookStreamEvents();
        }

        private void OnEnable()
        {
            HookStreamEvents();
        }

        private void OnDisable()
        {
            UnhookStreamEvents();
        }

        private void OnDestroy()
        {
            UnhookStreamEvents();
        }

        private void HookStreamEvents()
        {
            if (player != null)
            {
                player.StreamClipStarted -= OnStreamClipStarted;
                player.StreamClipStarted += OnStreamClipStarted;
            }
        }

        private void UnhookStreamEvents()
        {
            if (player != null)
            {
                player.StreamClipStarted -= OnStreamClipStarted;
            }
        }

        private void ApplyEmotion(string emotionName, float intensity)
        {
            if (string.IsNullOrEmpty(emotionName)) return;
            currentStreamEmotion = emotionName;
            emotion.SetEmotion(emotionName, intensity);
            motion?.SetEmotion(emotionName);
            if (string.Equals(emotionName, "thinking", StringComparison.OrdinalIgnoreCase))
            {
                var look = lookController ?? (motion != null ? motion.GetComponent<AvatarLookController>() : null);
                look?.PlayLookAround(2.5f, IdleLookPattern.Thoughtful);
            }
        }

        private void OnStreamClipStarted(int sequence)
        {
            if (segmentEmotions.TryGetValue(sequence, out var cue) && !string.IsNullOrEmpty(cue.Emotion))
            {
                ApplyEmotion(cue.Emotion, cue.Intensity);
                segmentEmotions.Remove(sequence);
            }
            motion?.OnSpeechSegmentStarted(sequence);
        }

        public void SetAudioMuted(bool muted) { player?.SetMuted(muted); }

        public void Speak(AvatarCommand command, AvatarCommandPayload payload)
        {
            generation++; currentUtterance = payload.utterance_id;
            var targetIntensity = payload.intensity > 0f ? payload.intensity : (payload.gesture_intensity > 0f ? payload.gesture_intensity : 1f);
            ApplyEmotion(payload.emotion, targetIntensity);
            motion?.StopGesture(false);
            state.SetState(AvatarState.Downloading);
            fallback.SetActive(fallback.ShouldBeActive());
            var localGeneration = generation;
            player.Play(payload.audio_url, localGeneration,
                () =>
                {
                    if (localGeneration != generation) return;
                    emotion.SetSpeaking(true);
                    state.SetState(AvatarState.Speaking);
                    motion?.TriggerGesture(AvatarMotionNames.ParseGesture(payload.gesture), payload.gesture_intensity, payload.interrupt);
                    client.SendPlayback("avatar.playback.started", payload.utterance_id, command.message_id, null, AvatarProtocol.ClientLatencyMs(command));
                },
                () =>
                {
                    if (localGeneration != generation) return;
                    emotion.SetSpeaking(false);
                    fallback.ResetMouth();
                    motion?.StopGesture(false);
                    state.SetState(AvatarState.Idle);
                    client.SendPlayback("avatar.playback.finished", payload.utterance_id, command.message_id);
                },
                reason =>
                {
                    if (localGeneration != generation) return;
                    emotion.SetSpeaking(false);
                    fallback.ResetMouth();
                    motion?.StopGesture(false);
                    state.SetState(AvatarState.Error);
                    client.SendPlayback("avatar.playback.failed", payload.utterance_id, command.message_id, reason);
                });
        }

        public void Stop(string utteranceId)
        {
            if (!string.IsNullOrEmpty(utteranceId) && utteranceId != currentUtterance) return;
            generation++;
            segmentEmotions.Clear();
            pendingStreamGesture = GestureTag.Auto;
            emotion.SetSpeaking(false);
            player.Stop();
            fallback.ResetMouth();
            motion?.StopGesture(true);
            state.SetState(AvatarState.Idle);
        }

        public void StreamStart(AvatarCommand command, AvatarCommandPayload payload)
        {
            generation++;
            segmentEmotions.Clear();
            currentUtterance = payload.utterance_id;
            nextStreamSequence = 0;
            pendingStreamGesture = GestureTag.Auto;
            pendingStreamGestureIntensity = 1f;
            if (!string.IsNullOrEmpty(payload.emotion))
            {
                ApplyEmotion(payload.emotion, 1f);
            }
            motion?.StopGesture(false);
            motion?.BeginSpeechMotion();
            state.SetState(AvatarState.Thinking);
            var localGeneration = generation;
            player.BeginStream(localGeneration,
                () =>
                {
                    if (localGeneration != generation) return;
                    emotion.SetSpeaking(true);
                    state.SetState(AvatarState.Speaking);
                    motion?.TriggerGesture(pendingStreamGesture, pendingStreamGestureIntensity, true);
                    client.SendPlayback("avatar.playback.started", currentUtterance, command.message_id, null, AvatarProtocol.ClientLatencyMs(command));
                },
                () =>
                {
                    if (localGeneration != generation) return;
                    emotion.SetSpeaking(false);
                    segmentEmotions.Clear();
                    pendingStreamGesture = GestureTag.Auto;
                    fallback.ResetMouth();
                    motion?.StopGesture(false);
                    state.SetState(AvatarState.Idle);
                    client.SendPlayback("avatar.playback.finished", currentUtterance, command.message_id);
                },
                reason =>
                {
                    if (localGeneration != generation) return;
                    emotion.SetSpeaking(false);
                    segmentEmotions.Clear();
                    fallback.ResetMouth();
                    motion?.StopGesture(false);
                    state.SetState(AvatarState.Error);
                    client.SendPlayback("avatar.playback.failed", currentUtterance, command.message_id, reason);
                });
        }

        public void StreamMetadata(AvatarCommand command, AvatarCommandPayload payload)
        {
            if (payload.utterance_id != currentUtterance) return;
            var intensity = payload.intensity > 0f ? payload.intensity : Mathf.Clamp01(payload.gesture_intensity);
            ApplyEmotion(payload.emotion ?? "neutral", intensity);
            pendingStreamGesture = AvatarMotionNames.ParseGesture(payload.gesture);
            pendingStreamGestureIntensity = intensity;
            if (pendingStreamGesture != GestureTag.Auto && pendingStreamGesture != GestureTag.None && player != null && player.IsPlaying)
            {
                motion?.TriggerGesture(pendingStreamGesture, pendingStreamGestureIntensity, true);
            }
        }

        public void StreamSegment(AvatarCommand command, AvatarCommandPayload payload, byte[] audio)
        {
            if (payload.utterance_id != currentUtterance || payload.sequence != nextStreamSequence)
                throw new System.InvalidOperationException("Unexpected stream segment order");
            fallback.SetActive(fallback.ShouldBeActive());
            if (payload.motion != null && !string.IsNullOrEmpty(payload.motion.emotion))
            {
                segmentEmotions[payload.sequence] = new SegmentEmotionCue
                {
                    Emotion = payload.motion.emotion,
                    Intensity = payload.motion.intensity > 0f ? payload.motion.intensity : 1f,
                };
            }
            motion?.QueueSpeechCue(payload.sequence, payload.duration_seconds, payload.motion);
            player.EnqueueWav(audio, generation, payload.sequence);
            nextStreamSequence++;
            if (payload.is_final) player.EndStream(generation);
        }

        public void StreamEnd(AvatarCommand command, AvatarCommandPayload payload)
        {
            if (payload.utterance_id != currentUtterance) return;
            player.EndStream(generation);
        }
    }
}
