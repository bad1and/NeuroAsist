using NUnit.Framework;

namespace NeuroAsist.Avatar.Tests
{
    public sealed class AvatarProtocolTests
    {
        [Test] public void ParsesValidPing() { Assert.That(AvatarProtocol.TryParse("{\"protocol_version\":1,\"type\":\"avatar.ping\",\"message_id\":\"id\",\"payload\":{}}", out var command), Is.True); Assert.That(command.type, Is.EqualTo("avatar.ping")); }
        [Test] public void ParsesV2Ping() { Assert.That(AvatarProtocol.TryParse("{\"protocol_version\":2,\"type\":\"avatar.ping\",\"message_id\":\"id\",\"payload\":{}}", out var command), Is.True); Assert.That(command.protocol_version, Is.EqualTo(2)); }
        [Test] public void ParsesV2StreamMetadata() { Assert.That(AvatarProtocol.TryParse("{\"protocol_version\":2,\"type\":\"avatar.stream.metadata\",\"message_id\":\"id\",\"payload\":{\"utterance_id\":\"u\",\"emotion\":\"smirk\",\"gesture\":\"shrug\",\"gesture_intensity\":0.55}}", out var command), Is.True); Assert.That(command.payload.emotion, Is.EqualTo("smirk")); Assert.That(command.payload.gesture, Is.EqualTo("shrug")); }
        [Test] public void RejectsUnsupportedVersion() { Assert.That(AvatarProtocol.TryParse("{\"protocol_version\":3,\"type\":\"avatar.ping\",\"message_id\":\"id\",\"payload\":{}}", out _), Is.False); }
        [Test] public void ResolvesRelativeAudioUrl() { Assert.That(AvatarUrlResolver.Resolve("http://127.0.0.1:8000", "/voice/audio/a.wav"), Is.EqualTo("http://127.0.0.1:8000/voice/audio/a.wav")); }
        [Test] public void BuildsDesktopWebSocketFromDynamicPortAndEscapedToken() { Assert.That(AvatarEndpointResolver.BuildWebSocketUrl("http://127.0.0.1:43123", "a token&value"), Is.EqualTo("ws://127.0.0.1:43123/ws/avatar?version=2&token=a%20token%26value")); }
        [Test] public void DedupCacheIsBounded() { var cache = new BoundedMessageCache(2); Assert.That(cache.Add("1"), Is.True); Assert.That(cache.Add("1"), Is.False); cache.Add("2"); cache.Add("3"); Assert.That(cache.Count, Is.EqualTo(2)); Assert.That(cache.Add("1"), Is.True); }
        [Test] public void BackoffCapsAtFifteenSeconds() { Assert.That(ReconnectBackoff.GetDelay(0), Is.EqualTo(1)); Assert.That(ReconnectBackoff.GetDelay(99), Is.EqualTo(15)); }
        [Test] public void DetectsEmbeddedDesktopHostOnly() { Assert.That(WindowsDesktopOverlay.IsEmbeddedHost("embedded"), Is.True); Assert.That(WindowsDesktopOverlay.IsEmbeddedHost("overlay"), Is.False); Assert.That(WindowsDesktopOverlay.IsEmbeddedHost(null), Is.False); }
        [Test] public void LetsIrisHostControlEmbeddedResolution() { Assert.That(AvatarPerformanceProfile.ShouldSetStandaloneResolution(true), Is.False); Assert.That(AvatarPerformanceProfile.ShouldSetStandaloneResolution(false), Is.True); }
    }
}
