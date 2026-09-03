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
        private int generation;
        private string currentUtterance;
        private int nextStreamSequence;
        private GestureTag pendingStreamGesture = GestureTag.Auto;
        private float pendingStreamGestureIntensity = 1f;
        private string currentStreamEmotion = "neutral";

        private void OnEnable()
        {
            if (player != null) player.StreamClipStarted -= OnStreamClipStarted;
        }

        private void OnDisable()
        {
            if (player != null) player.StreamClipStarted -= OnStreamClipStarted;
        }

        private void OnStreamClipStarted(int sequence) => motion?.OnSpeechSegmentStarted(sequence);

        public void SetAudioMuted(bool muted) { player?.SetMuted(muted); }

        public void Speak(AvatarCommand command, AvatarCommandPayload payload)
        {
            generation++; currentUtterance = payload.utterance_id;
            var targetIntensity = payload.intensity > 0f ? payload.intensity : (payload.gesture_intensity > 0f ? payload.gesture_intensity : 1f);
            emotion.SetEmotion(payload.emotion, targetIntensity);
            motion?.SetEmotion(payload.emotion);
            motion?.StopGesture(false);
            state.SetState(AvatarState.Downloading);
            fallback.SetActive(fallback.ShouldBeActive());
            var localGeneration = generation;
            player.Play(payload.audio_url, localGeneration,
                () =>
                {
                    if (localGeneration != generation) return;
                    emotion.SetSpeaking(true);
                    if (AvatarEmotionController.IsTransient(payload.emotion)) emotion.SetEmotion("neutral", 1f);
                    state.SetState(AvatarState.Speaking);
                    motion?.TriggerGesture(AvatarMotionNames.ParseGesture(payload.gesture), payload.gesture_intensity, payload.interrupt);
                    client.SendPlayback("avatar.playback.started", payload.utterance_id, command.message_id, null, AvatarProtocol.ClientLatencyMs(command));
                },
                () =>
                {
                    if (localGeneration != generation) return;
                    emotion.SetSpeaking(false);
                    fallback.ResetMouth();
                    emotion.SetEmotion("neutral", 1f);
                    motion?.ResetToNeutral();
                    state.SetState(AvatarState.Idle);
                    client.SendPlayback("avatar.playback.finished", payload.utterance_id, command.message_id);
                },
                reason =>
                {
                    if (localGeneration != generation) return;
                    emotion.SetSpeaking(false);
                    fallback.ResetMouth();
                    state.SetState(AvatarState.Error);
                    client.SendPlayback("avatar.playback.failed", payload.utterance_id, command.message_id, reason);
                });
        }

        public void Stop(string utteranceId)
        {
            if (!string.IsNullOrEmpty(utteranceId) && utteranceId != currentUtterance) return;
            generation++;
            pendingStreamGesture = GestureTag.Auto;
            currentStreamEmotion = "neutral";
            emotion.SetSpeaking(false);
            player.Stop();
            fallback.ResetMouth();
            emotion.SetEmotion("neutral", 1f);
            motion?.ResetToNeutral();
            state.SetState(AvatarState.Idle);
        }

        public void StreamStart(AvatarCommand command, AvatarCommandPayload payload)
        {
            generation++;
            currentUtterance = payload.utterance_id;
            nextStreamSequence = 0;
            pendingStreamGesture = GestureTag.Auto;
            pendingStreamGestureIntensity = 1f;
            currentStreamEmotion = payload.emotion ?? "thinking";
            emotion.SetEmotion(payload.emotion ?? "thinking", 1f);
            motion?.SetEmotion(payload.emotion ?? "thinking");
            motion?.StopGesture(false);
            motion?.BeginSpeechMotion();
            state.SetState(AvatarState.Thinking);
            var localGeneration = generation;
            player.BeginStream(localGeneration,
                () =>
                {
                    if (localGeneration != generation) return;
                    emotion.SetSpeaking(true);
                    if (AvatarEmotionController.IsTransient(currentStreamEmotion)) emotion.SetEmotion("neutral", 1f);
                    state.SetState(AvatarState.Speaking);
                    motion?.TriggerGesture(pendingStreamGesture, pendingStreamGestureIntensity, true);
                    client.SendPlayback("avatar.playback.started", currentUtterance, command.message_id, null, AvatarProtocol.ClientLatencyMs(command));
                },
                () =>
                {
                    if (localGeneration != generation) return;
                    emotion.SetSpeaking(false);
                    pendingStreamGesture = GestureTag.Auto;
                    currentStreamEmotion = "neutral";
                    fallback.ResetMouth();
                    emotion.SetEmotion("neutral", 1f);
                    motion?.ResetToNeutral();
                    state.SetState(AvatarState.Idle);
                    client.SendPlayback("avatar.playback.finished", currentUtterance, command.message_id);
                },
                reason =>
                {
                    if (localGeneration != generation) return;
                    emotion.SetSpeaking(false);
                    fallback.ResetMouth();
                    state.SetState(AvatarState.Error);
                    client.SendPlayback("avatar.playback.failed", currentUtterance, command.message_id, reason);
                });
        }

        public void StreamMetadata(AvatarCommand command, AvatarCommandPayload payload)
        {
            if (payload.utterance_id != currentUtterance) return;
            var intensity = payload.intensity > 0f ? payload.intensity : Mathf.Clamp01(payload.gesture_intensity);
            currentStreamEmotion = payload.emotion ?? "neutral";
            emotion.SetEmotion(payload.emotion ?? "neutral", intensity);
            motion?.SetEmotion(payload.emotion ?? "neutral");
            pendingStreamGesture = AvatarMotionNames.ParseGesture(payload.gesture);
            pendingStreamGestureIntensity = intensity;
        }

        public void StreamSegment(AvatarCommand command, AvatarCommandPayload payload, byte[] audio)
        {
            if (payload.utterance_id != currentUtterance || payload.sequence != nextStreamSequence)
                throw new System.InvalidOperationException("Unexpected stream segment order");
            fallback.SetActive(fallback.ShouldBeActive());
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
