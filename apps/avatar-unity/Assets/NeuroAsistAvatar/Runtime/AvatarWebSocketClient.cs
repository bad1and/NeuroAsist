using System;
using System.Collections.Concurrent;
using System.Collections;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    public sealed class AvatarWebSocketClient : MonoBehaviour
    {
        [SerializeField] private AvatarRuntimeSettings settings;
        [SerializeField] private AvatarCommandRouter router;
        [SerializeField] private AvatarStateController state;
        private readonly ConcurrentQueue<Action> mainThread = new ConcurrentQueue<Action>();
        private ClientWebSocket socket;
        private CancellationTokenSource cancellation;
        private Task loop;
        private bool manualShutdown;
        private readonly AvatarReadinessGate readiness = new AvatarReadinessGate();
        private readonly SemaphoreSlim sendGate = new SemaphoreSlim(1, 1);
        private ClientWebSocket greetedSocket;
        public bool IsConnected => socket != null && socket.State == WebSocketState.Open;

        private int parentPid = -1;
        private float nextParentCheckTime;

        private void Awake()
        {
            if (state != null) state.SetClient(this);
            var pidStr = Environment.GetEnvironmentVariable("NEUROASIST_DESKTOP_PID");
            if (!string.IsNullOrWhiteSpace(pidStr) && int.TryParse(pidStr, out var parsedPid))
            {
                parentPid = parsedPid;
            }
        }

        private void Start()
        {
            if (settings == null) { Debug.LogError("[AvatarWS] Missing AvatarRuntimeSettings", this); return; }
            StartCoroutine(TrackRendererReadiness());
            StartClient();
        }

        private IEnumerator TrackRendererReadiness()
        {
            for (var frame = 0; frame < AvatarReadinessGate.RequiredFrames; frame++)
            {
                yield return new WaitForEndOfFrame();
                readiness.MarkFrameComplete();
            }
            AnnounceRendererReady();
        }

        private void Update()
        {
            CheckParentProcess();
            while (mainThread.TryDequeue(out var action))
            {
                try { action(); }
                catch (Exception ex) { Debug.LogError("[AvatarWS] Main thread action error: " + ex, this); }
            }
        }

        private void CheckParentProcess()
        {
            if (parentPid <= 0) return;
            if (Time.unscaledTime < nextParentCheckTime) return;
            nextParentCheckTime = Time.unscaledTime + 1f;
            try
            {
                var parent = System.Diagnostics.Process.GetProcessById(parentPid);
                if (parent == null || parent.HasExited)
                {
                    DebugLog("Parent process exited, shutting down avatar.");
                    Application.Quit();
                }
            }
            catch
            {
                DebugLog("Parent process not found, shutting down avatar.");
                Application.Quit();
            }
        }

        private void OnDestroy() { StopClient(); }
        public void StartClient() { if (loop != null && !loop.IsCompleted) return; manualShutdown = false; cancellation = new CancellationTokenSource(); loop = RunAsync(cancellation.Token); }
        public void StopClient() { manualShutdown = true; cancellation?.Cancel(); _ = CloseAsync(); }
        public void SendState(string value) => Send("avatar.state.changed", new AvatarStatePayload { state = value });
        public void SendPong(string replyTo) => Send("avatar.pong", new AvatarPongPayload { reply_to = replyTo });
        public void SendAck(string replyTo, bool accepted, string error = null) => Send("avatar.ack", new AvatarAckPayload { reply_to = replyTo, accepted = accepted, error = error });
        public void SendPlayback(string type, string utteranceId, string replyTo = null, string reason = null, int latencyMs = 0) => Send(type, new AvatarPlaybackPayload { utterance_id = utteranceId, reply_to = replyTo, reason = reason, client_latency_ms = latencyMs });
        public void SendPlaybackSegmentStarted(string utteranceId, int sequence) => Send("avatar.playback.segment_started", new AvatarPlaybackPayload { utterance_id = utteranceId, sequence = sequence });
        public void SendStreamReceived(string utteranceId, int sequence, int latencyMs) => Send("avatar.stream.received", new AvatarStreamReceiptPayload { utterance_id = utteranceId, sequence = sequence, client_latency_ms = latencyMs });
        public void SendOverlayBounds(float x, float y, float width, float height) => Send("avatar.overlay.bounds_changed", new AvatarOverlayBoundsPayload { x = x, y = y, width = width, height = height });
        public void Send<T>(string type, T payload)
        {
            if (!IsConnected) return;
            _ = SendTextAsync(AvatarProtocol.Serialize(type, payload), cancellation.Token);
        }

        private async Task RunAsync(CancellationToken token)
        {
            var attempt = 0;
            while (!token.IsCancellationRequested && !manualShutdown)
            {
                try
                {
                    socket = new ClientWebSocket();
                    using (var timeout = CancellationTokenSource.CreateLinkedTokenSource(token))
                    {
                        timeout.CancelAfter(TimeSpan.FromSeconds(settings.ConnectTimeoutSeconds));
                        await socket.ConnectAsync(new Uri(settings.ResolveBackendWebSocketUrl()), timeout.Token);
                    }
                    attempt = 0;
                    mainThread.Enqueue(() => state.SetState(AvatarState.Idle, false));
                    var connectedSocket = socket;
                    var helloSent = await SendTextAsync(AvatarProtocol.Serialize("avatar.hello", new AvatarHelloPayload { platform = Application.platform.ToString() }), token, connectedSocket);
                    if (!helloSent) continue;
                    Volatile.Write(ref greetedSocket, connectedSocket);
                    AnnounceRendererReady();
                    await ReceiveAsync(token);
                }
                catch (OperationCanceledException)
                {
                    if (token.IsCancellationRequested || manualShutdown) break;
                    DebugLog("Connection attempt timed out; retrying.");
                }
                catch (Exception ex) { DebugLog("Connect/receive failed: " + ex.GetType().Name); }
                finally { await CloseAsync(); mainThread.Enqueue(() => state.SetState(AvatarState.Disconnected, false)); }
                if (!settings.ReconnectEnabled || manualShutdown || token.IsCancellationRequested) break;
                await Task.Delay(TimeSpan.FromSeconds(ReconnectBackoff.GetDelay(attempt++)), token);
            }
        }
        private void AnnounceRendererReady()
        {
            var current = socket;
            if (current == null
                || current.State != WebSocketState.Open
                || !ReferenceEquals(Volatile.Read(ref greetedSocket), current)
                || !readiness.TryClaimAnnouncement(current)) return;
            _ = SendRendererReadyAsync(current);
        }
        private async Task SendRendererReadyAsync(ClientWebSocket connection)
        {
            var sent = await SendTextAsync(
                AvatarProtocol.Serialize("avatar.ready", new AvatarReadyPayload()),
                cancellation.Token,
                connection);
            if (!sent) readiness.ReleaseAnnouncement(connection);
        }

        private async Task ReceiveAsync(CancellationToken token)
        {
            var buffer = new byte[16384];
            while (IsConnected && !token.IsCancellationRequested)
            {
                var result = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), token);
                if (result.MessageType == WebSocketMessageType.Close) break;
                var builder = new StringBuilder(); builder.Append(Encoding.UTF8.GetString(buffer, 0, result.Count));
                while (!result.EndOfMessage) { result = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), token); builder.Append(Encoding.UTF8.GetString(buffer, 0, result.Count)); }
                var raw = builder.ToString();
                mainThread.Enqueue(() => router.Receive(raw));
            }
        }
        private async Task<bool> SendTextAsync(string text, CancellationToken token, ClientWebSocket expectedSocket = null)
        {
            try
            {
                await sendGate.WaitAsync(token);
                try
                {
                    var current = socket;
                    if (current == null
                        || current.State != WebSocketState.Open
                        || (expectedSocket != null && !ReferenceEquals(expectedSocket, current))) return false;
                    await current.SendAsync(new ArraySegment<byte>(Encoding.UTF8.GetBytes(text)), WebSocketMessageType.Text, true, token);
                    return true;
                }
                finally { sendGate.Release(); }
            }
            catch (Exception ex) { DebugLog("Send failed: " + ex.GetType().Name); return false; }
        }
        private async Task CloseAsync()
        {
            var current = socket; socket = null;
            if (ReferenceEquals(Volatile.Read(ref greetedSocket), current)) Volatile.Write(ref greetedSocket, null);
            if (current == null) return;
            await sendGate.WaitAsync(CancellationToken.None);
            try
            {
                try { if (current.State == WebSocketState.Open) await current.CloseAsync(WebSocketCloseStatus.NormalClosure, "shutdown", CancellationToken.None); }
                catch (Exception) { }
                current.Dispose();
            }
            finally { sendGate.Release(); }
        }
        private void DebugLog(string message) { if (settings != null && settings.DebugLogging) Debug.Log("[AvatarWS] " + message, this); }
    }
}
