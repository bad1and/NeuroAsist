using NUnit.Framework;
using UnityEngine;

namespace NeuroAsist.Avatar.Tests
{
    public sealed class AvatarEdgeFeatherTests
    {
        private static Color Key => Color.clear;

        private static Texture2D Apply(Color fill, int width = 500, int height = 520)
        {
            var shader = Resources.Load<Shader>("AvatarEdgeFeather");
            Assert.That(shader, Is.Not.Null, "The player must include the edge shader.");
            Assert.That(shader.isSupported, Is.True);
            var source = new Texture2D(width, height, TextureFormat.RGBAFloat, false, true)
                { filterMode = FilterMode.Bilinear, wrapMode = TextureWrapMode.Clamp };
            var pixels = new Color[width * height];
            for (var i = 0; i < pixels.Length; i++) pixels[i] = fill;
            source.SetPixels(pixels);
            source.Apply();
            var target = RenderTexture.GetTemporary(width, height, 0,
                RenderTextureFormat.ARGBFloat, RenderTextureReadWrite.Linear);
            var previous = RenderTexture.active;
            var material = new Material(shader);
            try
            {
                Graphics.Blit(source, target, material);
                RenderTexture.active = target;
                var result = new Texture2D(width, height, TextureFormat.RGBAFloat, false, true);
                result.ReadPixels(new Rect(0, 0, width, height), 0, 0);
                result.Apply();
                return result;
            }
            finally
            {
                RenderTexture.active = previous;
                RenderTexture.ReleaseTemporary(target);
                Object.DestroyImmediate(source);
                Object.DestroyImmediate(material);
            }
        }

        private static void AssertColor(Color actual, Color expected)
        {
            Assert.That(actual.r, Is.EqualTo(expected.r).Within(.0001f));
            Assert.That(actual.g, Is.EqualTo(expected.g).Within(.0001f));
            Assert.That(actual.b, Is.EqualTo(expected.b).Within(.0001f));
        }

        [TestCase(500, 520)]
        [TestCase(275, 286)]
        [TestCase(750, 780)]
        public void PreservesCentreAndDockContactWhileFeatheringBothSides(int width, int height)
        {
            var fill = new Color(.65f, .42f, .75f, 1f);
            var result = Apply(fill, width, height);
            try
            {
                AssertColor(result.GetPixel(width / 2, height / 2), fill);
                AssertColor(result.GetPixel(width / 2, 0), fill);
                AssertColor(result.GetPixel(0, height / 2), Key);
                AssertColor(result.GetPixel(width - 1, height / 2), Key);
                AssertColor(result.GetPixel(width / 2, height - 1), Key);
                var edgeWidth = Mathf.Min(width * .14f, height * (36f / 520f));
                Assert.That(result.GetPixel((int)(edgeWidth / 2), height / 2).r,
                    Is.GreaterThan(Key.r).And.LessThan(fill.r));
                var previous = result.GetPixel(0, height / 2).a;
                for (var x = 2; x < (int)edgeWidth; x++)
                {
                    var pixel = result.GetPixel(x, height / 2);
                    Assert.That(pixel.a, Is.GreaterThanOrEqualTo(previous));
                    Assert.That(pixel.a, Is.LessThanOrEqualTo(1f));
                    Assert.That(result.GetPixel(width - x - 1, height / 2).a,
                        Is.EqualTo(pixel.a).Within(.0001f));
                    // Recover the hair colour from the compositor's coverage.
                    // Fading must reveal the background, never add a dark matte.
                    var display = QualitySettings.activeColorSpace == ColorSpace.Linear ? pixel.gamma : pixel;
                    var expected = QualitySettings.activeColorSpace == ColorSpace.Linear ? fill.gamma : fill;
                    AssertColor(new Color(display.r / pixel.a, display.g / pixel.a, display.b / pixel.a), expected);
                    previous = pixel.a;
                }
            }
            finally { Object.DestroyImmediate(result); }
        }

        [Test]
        public void EmptyPixelsStayFullyTransparentWithoutAMatte()
        {
            var result = Apply(Key);
            try
            {
                var key = Key;
                var maximumError = 0f;
                foreach (var pixel in result.GetPixels())
                    maximumError = Mathf.Max(maximumError, Mathf.Abs(pixel.r - key.r),
                        Mathf.Abs(pixel.g - key.g), Mathf.Abs(pixel.b - key.b), pixel.a);
                Assert.That(maximumError, Is.LessThan(.00001f),
                    "Empty pixels must reveal any background, including in the feather.");
            }
            finally { Object.DestroyImmediate(result); }
        }

        [Test]
        public void CameraPostEffectPreservesZeroCoverageInTheFramebuffer()
        {
            var cameraObject = new GameObject("Portrait edge test camera", typeof(Camera));
            var camera = cameraObject.GetComponent<Camera>();
            camera.enabled = false;
            camera.cullingMask = 0;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = Color.clear;
            camera.allowHDR = false;
            cameraObject.AddComponent<AvatarEdgeFeather>();
            var target = RenderTexture.GetTemporary(500, 520, 24,
                RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB);
            var previous = RenderTexture.active;
            var pixels = new Texture2D(500, 520, TextureFormat.RGBA32, false);
            try
            {
                camera.targetTexture = target;
                camera.Render();
                RenderTexture.active = target;
                pixels.ReadPixels(new Rect(0, 0, 500, 520), 0, 0);
                pixels.Apply();
                foreach (var pixel in pixels.GetPixels32())
                    if (pixel.r != 0 || pixel.g != 0 || pixel.b != 0 || pixel.a != 0)
                        Assert.Fail($"Transparent camera clear changed to {pixel}.");
            }
            finally
            {
                camera.targetTexture = null;
                RenderTexture.active = previous;
                RenderTexture.ReleaseTemporary(target);
                Object.DestroyImmediate(pixels);
                Object.DestroyImmediate(cameraObject);
            }
        }

        [TestCase(.25f)]
        [TestCase(.5f)]
        public void PartlyCoveredHairRetainsItsColourOverAnyBackground(float alpha)
        {
            var straight = new Color(.65f, .42f, .75f, 1f);
            var result = Apply(new Color(straight.r * alpha, straight.g * alpha, straight.b * alpha, alpha));
            try
            {
                var pixel = result.GetPixel(250, 260);
                var display = QualitySettings.activeColorSpace == ColorSpace.Linear ? pixel.gamma : pixel;
                var expected = QualitySettings.activeColorSpace == ColorSpace.Linear ? straight.gamma : straight;
                Assert.That(pixel.a, Is.EqualTo(alpha).Within(.00001f));
                AssertColor(new Color(display.r / alpha, display.g / alpha, display.b / alpha), expected);
                foreach (var background in new[] { Color.white, new Color(.6f, .5f, .9f), Color.cyan })
                {
                    var composite = new Color(display.r + background.r * (1 - alpha),
                        display.g + background.g * (1 - alpha), display.b + background.b * (1 - alpha));
                    AssertColor(composite, new Color(expected.r * alpha + background.r * (1 - alpha),
                        expected.g * alpha + background.g * (1 - alpha), expected.b * alpha + background.b * (1 - alpha)));
                }
            }
            finally { Object.DestroyImmediate(result); }
        }
    }
}
