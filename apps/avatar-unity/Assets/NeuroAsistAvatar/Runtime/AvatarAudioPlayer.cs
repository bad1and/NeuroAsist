using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;

namespace NeuroAsist.Avatar
{
    public sealed class AvatarAudioPlayer : MonoBehaviour
    {
        private sealed class QueuedClip
        {
            public AudioClip Clip;
            public int Token;
        }

        [SerializeField] private AvatarRuntimeSettings settings;
        [SerializeField] private AudioSource audioSource;
        private readonly Queue<QueuedClip> queued = new Queue<QueuedClip>();
        private int generation;
        private AudioClip runtimeClip;
        private Coroutine playback;
        private bool streamEnded;
        private bool streamStarted;
        private Action onStreamStarted;
        private Action onStreamFinished;
        private Action<string> onStreamFailed;

        public AudioSource Source => audioSource;
        public int Generation => generation;
        public void Configure(AvatarRuntimeSettings value, AudioSource source) { settings = value; audioSource = source; }

        public void Play(string audioUrl, int token, Action onStarted, Action onFinished, Action<string> onFailed)
        {
            Stop(); generation = token; StartCoroutine(DownloadAndPlay(audioUrl, token, onStarted, onFinished, onFailed));
        }

        public void BeginStream(int token, Action onStarted, Action onFinished, Action<string> onFailed)
        {
            Stop(); generation = token; streamEnded = false; streamStarted = false;
            onStreamStarted = onStarted; onStreamFinished = onFinished; onStreamFailed = onFailed;
        }

        public void EnqueueWav(byte[] wav, int token)
        {
            if (token != generation) return;
            try
            {
                queued.Enqueue(new QueuedClip { Clip = WavClipDecoder.Decode(wav, "avatar-stream-" + token), Token = token });
                StartNextStreamClip();
            }
            catch (Exception ex) { onStreamFailed?.Invoke(ex.Message); Stop(); }
        }

        public void EndStream(int token)
        {
            if (token != generation) return;
            streamEnded = true;
            if (playback == null && queued.Count == 0) FinishStream(token);
        }

        public void Stop()
        {
            generation++;
            if (playback != null) { StopCoroutine(playback); playback = null; }
            if (audioSource != null) { audioSource.Stop(); audioSource.clip = null; }
            if (runtimeClip != null) { Destroy(runtimeClip); runtimeClip = null; }
            while (queued.Count > 0) { var item = queued.Dequeue(); if (item.Clip != null) Destroy(item.Clip); }
            streamEnded = false; streamStarted = false;
            onStreamStarted = null; onStreamFinished = null; onStreamFailed = null;
        }

        private void StartNextStreamClip()
        {
            if (playback != null || queued.Count == 0) return;
            var item = queued.Dequeue();
            playback = StartCoroutine(PlayStreamClip(item));
        }

        private IEnumerator PlayStreamClip(QueuedClip item)
        {
            if (item.Token != generation) { if (item.Clip != null) Destroy(item.Clip); playback = null; yield break; }
            if (!streamStarted && settings != null && settings.StreamPlaybackPrebufferSeconds > 0f)
                yield return new WaitForSeconds(settings.StreamPlaybackPrebufferSeconds);
            if (item.Token != generation) { if (item.Clip != null) Destroy(item.Clip); playback = null; yield break; }
            runtimeClip = item.Clip;
            audioSource.clip = runtimeClip; audioSource.volume = settings.AudioVolume; audioSource.Play();
            if (!streamStarted) { streamStarted = true; onStreamStarted?.Invoke(); }
            while (item.Token == generation && audioSource.isPlaying) yield return null;
            if (runtimeClip == item.Clip) { audioSource.clip = null; Destroy(runtimeClip); runtimeClip = null; }
            playback = null;
            if (item.Token != generation) yield break;
            if (queued.Count > 0) StartNextStreamClip(); else if (streamEnded) FinishStream(item.Token);
        }

        private void FinishStream(int token)
        {
            if (token != generation) return;
            streamEnded = false;
            onStreamFinished?.Invoke();
            onStreamStarted = null; onStreamFinished = null; onStreamFailed = null;
        }

        private IEnumerator DownloadAndPlay(string audioUrl, int token, Action onStarted, Action onFinished, Action<string> onFailed)
        {
            string url;
            try { url = AvatarUrlResolver.Resolve(settings.ResolveBackendHttpBaseUrl(), audioUrl); }
            catch (Exception ex) { onFailed(ex.Message); yield break; }
            using (var request = UnityWebRequestMultimedia.GetAudioClip(url, AudioType.WAV))
            {
                request.timeout = Mathf.CeilToInt(settings.DownloadTimeoutSeconds);
                yield return request.SendWebRequest();
                if (token != generation) yield break;
                if (request.result != UnityWebRequest.Result.Success) { onFailed("WAV download failed (HTTP " + request.responseCode + ")"); yield break; }
                runtimeClip = DownloadHandlerAudioClip.GetContent(request);
                if (runtimeClip == null) { onFailed("Downloaded WAV could not be decoded"); yield break; }
                audioSource.clip = runtimeClip; audioSource.volume = settings.AudioVolume; audioSource.Play(); onStarted();
                while (token == generation && audioSource.isPlaying) yield return null;
                if (token == generation) onFinished();
            }
        }
    }

    public static class WavClipDecoder
    {
        public static AudioClip Decode(byte[] wav, string name)
        {
            if (wav == null || wav.Length < 44 || wav[0] != 'R' || wav[1] != 'I' || wav[2] != 'F' || wav[3] != 'F') throw new ArgumentException("Invalid WAV header");
            var offset = 12; var channels = 0; var sampleRate = 0; var bits = 0; var dataOffset = -1; var dataLength = 0;
            while (offset + 8 <= wav.Length)
            {
                var id = System.Text.Encoding.ASCII.GetString(wav, offset, 4); var length = BitConverter.ToInt32(wav, offset + 4); offset += 8;
                if (length < 0 || offset + length > wav.Length) throw new ArgumentException("Invalid WAV chunk");
                if (id == "fmt ") { if (length < 16) throw new ArgumentException("Invalid WAV format"); channels = BitConverter.ToInt16(wav, offset + 2); sampleRate = BitConverter.ToInt32(wav, offset + 4); bits = BitConverter.ToInt16(wav, offset + 14); }
                if (id == "data") { dataOffset = offset; dataLength = length; break; }
                offset += length + (length & 1);
            }
            if (channels < 1 || channels > 2 || sampleRate < 8000 || bits != 16 || dataOffset < 0 || dataLength <= 0) throw new ArgumentException("Only PCM16 mono/stereo WAV is supported");
            var samples = new float[dataLength / 2];
            for (var i = 0; i < samples.Length; i++) samples[i] = BitConverter.ToInt16(wav, dataOffset + i * 2) / 32768f;
            var clip = AudioClip.Create(name, samples.Length / channels, channels, sampleRate, false);
            clip.SetData(samples, 0); return clip;
        }
    }
}
