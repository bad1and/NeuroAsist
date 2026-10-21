using System;
using System.Collections;
using System.IO;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;
using Object = UnityEngine.Object;

namespace NeuroAsist.Avatar.Tests
{
    public sealed class AvatarEdgeFeatherPlayModeTests
    {
        private static void Offline(Scene scene, LoadSceneMode mode)
        {
            foreach (var client in Object.FindObjectsByType<AvatarWebSocketClient>(FindObjectsSortMode.None))
                client.enabled = false;
            foreach (var overlay in Object.FindObjectsByType<WindowsDesktopOverlay>(FindObjectsSortMode.None))
                overlay.enabled = false;
        }

        private static Texture2D Capture(Camera camera)
        {
            camera.Render();
            var previous = RenderTexture.active;
            RenderTexture.active = camera.targetTexture;
            try
            {
                var result = new Texture2D(camera.targetTexture.width, camera.targetTexture.height,
                    TextureFormat.RGBA32, false);
                result.ReadPixels(new Rect(0, 0, result.width, result.height), 0, 0);
                result.Apply();
                return result;
            }
            finally { RenderTexture.active = previous; }
        }

        [UnityTest, Timeout(60000)]
        public IEnumerator RealPortraitKeepsItsCentreAndDockWhileItsEdgesDisappear()
        {
            SceneManager.sceneLoaded += Offline;
            try
            {
                SceneManager.LoadScene("AvatarOverlay");
                yield return null;
            }
            finally { SceneManager.sceneLoaded -= Offline; }
            Object.FindFirstObjectByType<AvatarStateController>().SetState(AvatarState.Idle, false);
            yield return new WaitForSeconds(1f);
            var camera = Camera.main;
            Assert.That(camera, Is.Not.Null);
            camera.backgroundColor = Color.clear;
            camera.allowHDR = false;
            var effect = camera.gameObject.AddComponent<AvatarEdgeFeather>();
            var presentation = Object.FindFirstObjectByType<AvatarPresentationController>();
            var evidence = Environment.GetEnvironmentVariable("NEUROASIST_AVATAR_EDGE_EVIDENCE");
            foreach (var width in new[] { 500, 280 })
            {
                var target = RenderTexture.GetTemporary(width, 520, 24,
                    RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB);
                Texture2D before = null, after = null;
                try
                {
                    camera.targetTexture = target;
                    presentation.FrameNow();
                    var position = camera.transform.position;
                    var rotation = camera.transform.rotation;
                    effect.enabled = false;
                    before = Capture(camera);
                    effect.enabled = true;
                    after = Capture(camera);
                    Assert.That(camera.transform.position, Is.EqualTo(position));
                    Assert.That(camera.transform.rotation, Is.EqualTo(rotation));
                    var maximumCentreDifference = 0;
                    for (var y = 0; y < 495; y++)
                    for (var x = 36; x < width - 36; x++)
                    {
                        var a = (Color32)before.GetPixel(x, y);
                        var b = (Color32)after.GetPixel(x, y);
                        if (a.a < 255 || b.a < 255) continue; // Silhouette coverage is intentionally corrected.
                        maximumCentreDifference = Mathf.Max(maximumCentreDifference,
                            Mathf.Abs(a.r - b.r), Mathf.Abs(a.g - b.g), Mathf.Abs(a.b - b.b));
                    }
                    Assert.That(maximumCentreDifference, Is.LessThanOrEqualTo(1),
                        "The centre and bottom contact must remain unchanged.");
                    for (var y = 0; y < 520; y++)
                    foreach (var x in new[] { 0, width - 1 })
                    {
                        var pixel = (Color32)after.GetPixel(x, y);
                        Assert.That(new[] { pixel.r, pixel.g, pixel.b, pixel.a }, Is.EqualTo(new byte[] { 0, 0, 0, 0 }));
                    }
                    if (!string.IsNullOrEmpty(evidence))
                    {
                        Directory.CreateDirectory(evidence);
                        File.WriteAllBytes(Path.Combine(evidence, $"portrait-{width}-before.png"), before.EncodeToPNG());
                        File.WriteAllBytes(Path.Combine(evidence, $"portrait-{width}-after.png"), after.EncodeToPNG());
                        var composite = new Texture2D(width, 520, TextureFormat.RGBA32, false);
                        var colours = after.GetPixels();
                        for (var i = 0; i < colours.Length; i++)
                        {
                            var background = ((i % width / 20 + i / width / 20) % 2 == 0)
                                ? new Color(.72f, .66f, .92f) : new Color(.93f, .9f, 1f);
                            var foreground = colours[i];
                            colours[i] = new Color(foreground.r + background.r * (1 - foreground.a),
                                foreground.g + background.g * (1 - foreground.a),
                                foreground.b + background.b * (1 - foreground.a), 1f);
                        }
                        composite.SetPixels(colours); composite.Apply();
                        File.WriteAllBytes(Path.Combine(evidence, $"portrait-{width}-checker.png"), composite.EncodeToPNG());
                        Object.Destroy(composite);
                    }
                }
                finally
                {
                    camera.targetTexture = null;
                    RenderTexture.ReleaseTemporary(target);
                    if (before != null) Object.Destroy(before);
                    if (after != null) Object.Destroy(after);
                }
            }
            Object.Destroy(effect);
        }
    }
}
