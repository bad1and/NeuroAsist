using System;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    public sealed class AvatarCommandRouter : MonoBehaviour
    {
        [SerializeField] private AvatarWebSocketClient client;
        [SerializeField] private AvatarSpeechCoordinator speech;
        [SerializeField] private AvatarEmotionController emotion;
        [SerializeField] private AvatarStateController state;
        [SerializeField] private AvatarMotionController motion;
        [SerializeField] private WindowsDesktopOverlay overlay;
        private readonly BoundedMessageCache received = new BoundedMessageCache(512);

        private void Awake()
        {
            if (overlay == null) overlay = GetComponent<WindowsDesktopOverlay>() ?? gameObject.AddComponent<WindowsDesktopOverlay>();
        }

        public void Receive(string json)
        {
            if (!AvatarProtocol.TryParse(json, out var command)) { Debug.LogWarning("[AvatarProtocol] Invalid command ignored", this); return; }
            if (!received.Add(command.message_id)) return;
            var payload = command.payload ?? new AvatarCommandPayload();
            switch (command.type)
            {
                case "avatar.speak":
                    if (string.IsNullOrEmpty(payload.utterance_id) || string.IsNullOrEmpty(payload.audio_url)) { client.SendAck(command.message_id, false, "speak requires utterance_id and audio_url"); return; }
                    client.SendAck(command.message_id, true); speech.Speak(command, payload); break;
                case "avatar.stream.start":
                    if (string.IsNullOrEmpty(payload.utterance_id)) { client.SendAck(command.message_id, false, "stream start requires utterance_id"); return; }
                    client.SendAck(command.message_id, true); speech.StreamStart(command, payload); break;
                case "avatar.stream.metadata":
                    if (string.IsNullOrEmpty(payload.utterance_id)) { client.SendAck(command.message_id, false, "stream metadata requires utterance_id"); return; }
                    client.SendAck(command.message_id, true); speech.StreamMetadata(command, payload); break;
                case "avatar.stream.segment":
                    if (string.IsNullOrEmpty(payload.utterance_id) || string.IsNullOrEmpty(payload.audio_base64) || payload.sequence < 0) { client.SendAck(command.message_id, false, "stream segment is malformed"); return; }
                    try { speech.StreamSegment(command, payload, Convert.FromBase64String(payload.audio_base64)); client.SendStreamReceived(payload.utterance_id, payload.sequence, AvatarProtocol.ClientLatencyMs(command)); client.SendAck(command.message_id, true); }
                    catch (Exception ex) { client.SendAck(command.message_id, false, "stream segment rejected: " + ex.Message); }
                    break;
                case "avatar.stream.end":
                    client.SendAck(command.message_id, true); speech.StreamEnd(command, payload); break;
                case "avatar.emotion": client.SendAck(command.message_id, true); emotion.SetEmotion(payload.emotion, payload.intensity); motion?.SetEmotion(payload.emotion); break;
                case "avatar.gesture":
                    client.SendAck(command.message_id, true);
                    motion?.TriggerGesture(AvatarMotionNames.ParseGesture(payload.gesture), payload.intensity, payload.interrupt);
                    break;
                case "avatar.stop": client.SendAck(command.message_id, true); speech.Stop(payload.utterance_id); motion?.ResetToNeutral(); break;
                case "avatar.state":
                    client.SendAck(command.message_id, true);
                    if (System.Enum.TryParse(payload.state, true, out AvatarState next)) state.SetState(next, false);
                    break;
                case "avatar.overlay.configure":
                    client.SendAck(command.message_id, true);
                    if (overlay != null) overlay.Configure(payload.visible, payload.always_on_top, payload.locked, payload.scale, payload.monitor, payload.x, payload.y, payload.width, payload.height);
                    break;
                case "avatar.ping": client.SendPong(command.message_id); break;
                default: client.SendAck(command.message_id, false, "unknown command"); break;
            }
        }
    }
}
