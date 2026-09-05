using System;
using System.Collections.Generic;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    [Serializable] public class AvatarEnvelope<T> { public int protocol_version = 2; public string type; public string message_id; public string timestamp; public string session_id = "default"; public T payload; }
    [Serializable] public class AvatarCommand { public int protocol_version; public string type; public string message_id; public string timestamp; public string session_id; public AvatarCommandPayload payload; }
    [Serializable] public class AvatarMotionCuePayload { public string gesture = "auto"; public bool emphasized; public string emotion; public float intensity = 1f; }
    [Serializable] public class AvatarCommandPayload { public string utterance_id; public string text; public string audio_url; public string emotion; public string intent; public string gesture = "auto"; public float gesture_intensity = 1f; public bool interrupt; public float intensity = 1f; public string state; public string sent_at; public int sequence; public string audio_base64; public string format; public int sample_rate; public int channels; public float duration_seconds; public bool is_final; public AvatarMotionCuePayload motion; public bool muted; public bool visible; public bool always_on_top; public bool locked; public float scale = 1f; public string monitor; public float x; public float y; public float width; public float height; }
    [Serializable] public class AvatarHelloPayload { public string client_name = "Iris Unity Avatar"; public string client_version = "0.6"; public int[] supported_protocol_versions = { 1, 2 }; public string platform; }
    [Serializable] public class AvatarPongPayload { public string reply_to; }
    [Serializable] public class AvatarAckPayload { public string reply_to; public bool accepted; public string error; }
    [Serializable] public class AvatarPlaybackPayload { public string utterance_id; public string reply_to; public string reason; public int client_latency_ms; }
    [Serializable] public class AvatarStreamReceiptPayload { public string utterance_id; public int sequence; public int client_latency_ms; }
    [Serializable] public class AvatarStatePayload { public string state; }
    [Serializable] public class AvatarMotionProfilePayload { public string profile; }
    [Serializable] public class AvatarOverlayBoundsPayload { public float x; public float y; public float width; public float height; }
    [Serializable] public class AvatarGesturePayload { public string gesture; public float intensity = 1f; public bool interrupt = true; }

    public static class AvatarProtocol
    {
        public static string NewMessageId() => Guid.NewGuid().ToString("N");
        public static string Timestamp() => DateTime.UtcNow.ToString("O");
        public static string Serialize<T>(string type, T payload, string sessionId = "default") => JsonUtility.ToJson(new AvatarEnvelope<T> { type = type, message_id = NewMessageId(), timestamp = Timestamp(), session_id = sessionId, payload = payload });
        public static int ClientLatencyMs(AvatarCommand command)
        {
            if (command == null || !DateTime.TryParse(command.timestamp, null, System.Globalization.DateTimeStyles.AdjustToUniversal, out var sent)) return 0;
            return Mathf.Clamp((int)(DateTime.UtcNow - sent.ToUniversalTime()).TotalMilliseconds, 0, 120000);
        }
        public static bool TryParse(string json, out AvatarCommand command)
        {
            command = null;
            try { command = JsonUtility.FromJson<AvatarCommand>(json); return command != null && (command.protocol_version == 1 || command.protocol_version == 2) && !string.IsNullOrEmpty(command.type) && !string.IsNullOrEmpty(command.message_id); }
            catch (Exception) { return false; }
        }
    }

    public sealed class BoundedMessageCache
    {
        private readonly int capacity;
        private readonly Queue<string> order = new Queue<string>();
        private readonly HashSet<string> ids = new HashSet<string>();
        public BoundedMessageCache(int capacity = 512) { this.capacity = Math.Max(1, capacity); }
        public bool Add(string id)
        {
            if (string.IsNullOrEmpty(id) || !ids.Add(id)) return false;
            order.Enqueue(id);
            while (order.Count > capacity) ids.Remove(order.Dequeue());
            return true;
        }
        public int Count => ids.Count;
    }

    public static class AvatarUrlResolver
    {
        public static string Resolve(string baseUrl, string audioUrl)
        {
            if (string.IsNullOrWhiteSpace(audioUrl)) throw new ArgumentException("Audio URL is empty", nameof(audioUrl));
            if (Uri.TryCreate(audioUrl, UriKind.Absolute, out var absolute)) return absolute.AbsoluteUri;
            return new Uri(new Uri(baseUrl.TrimEnd('/') + "/"), audioUrl.TrimStart('/')).AbsoluteUri;
        }
    }

    public static class ReconnectBackoff
    {
        private static readonly float[] Delays = { 1f, 2f, 5f, 10f, 15f };
        public static float GetDelay(int attempt) => Delays[Mathf.Clamp(attempt, 0, Delays.Length - 1)];
    }
}
