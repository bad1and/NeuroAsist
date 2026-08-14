using System;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    public enum LipSyncMode { Auto, ULipSync, VolumeFallback, Disabled }

    [CreateAssetMenu(menuName = "Iris/Avatar Runtime Settings", fileName = "AvatarRuntimeSettings")]
    public sealed class AvatarRuntimeSettings : ScriptableObject
    {
        public string BackendHttpBaseUrl = "http://127.0.0.1:8000";
        public string BackendWebSocketUrl = "ws://127.0.0.1:8000/ws/avatar?version=2";
        public bool ReconnectEnabled = true;
        public float ConnectTimeoutSeconds = 10f;
        public float DownloadTimeoutSeconds = 30f;
        public LipSyncMode LipSyncMode = LipSyncMode.Auto;
        [Range(0f, 1f)] public float AudioVolume = 1f;
        public string DefaultEmotion = "neutral";
        [Min(.05f)] public float EmotionBlendInSeconds = .45f;
        [Min(.05f)] public float EmotionBlendOutSeconds = .6f;
        [Range(0f, 1f)] public float StreamPlaybackPrebufferSeconds = .2f;
        public bool ApplyAvatarLowProfile;
        public int AvatarFrameRate = 60;
        public int AvatarWidth = 1280;
        public int AvatarHeight = 720;
        public bool DebugLogging;

        /// <summary>
        /// Tauri gives each desktop launch an ephemeral loopback URL and token.
        /// The serialized values remain the safe editor fallback.
        /// </summary>
        public string ResolveBackendHttpBaseUrl()
        {
            var runtimeUrl = Environment.GetEnvironmentVariable("NEUROASIST_BACKEND_URL");
            return string.IsNullOrWhiteSpace(runtimeUrl) ? BackendHttpBaseUrl.TrimEnd('/') : runtimeUrl.TrimEnd('/');
        }

        public string ResolveBackendWebSocketUrl()
        {
            var runtimeUrl = Environment.GetEnvironmentVariable("NEUROASIST_BACKEND_URL");
            var token = Environment.GetEnvironmentVariable("NEUROASIST_BACKEND_TOKEN");
            if (string.IsNullOrWhiteSpace(runtimeUrl)) return BackendWebSocketUrl;
            return AvatarEndpointResolver.BuildWebSocketUrl(runtimeUrl, token);
        }
    }

    public static class AvatarEndpointResolver
    {
        public static string BuildWebSocketUrl(string httpBaseUrl, string token)
        {
            if (!Uri.TryCreate(httpBaseUrl, UriKind.Absolute, out var source))
                throw new ArgumentException("Backend URL must be absolute", nameof(httpBaseUrl));
            var builder = new UriBuilder(source)
            {
                Scheme = source.Scheme == "https" ? "wss" : "ws",
                Path = "/ws/avatar",
                Port = source.IsDefaultPort ? -1 : source.Port,
            };
            var query = "version=2";
            if (!string.IsNullOrWhiteSpace(token)) query += "&token=" + Uri.EscapeDataString(token);
            builder.Query = query;
            return builder.Uri.AbsoluteUri;
        }
    }
}
