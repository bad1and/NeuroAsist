using System;
using NUnit.Framework;
using UnityEngine;

namespace NeuroAsist.Avatar.Tests
{
    public sealed class AvatarQualityTests
    {
        [Test]
        public void PlacementSelectsItsOwnQualityAndRejectsInvalidUpdates()
        {
            var host = Environment.GetEnvironmentVariable("NEUROASIST_AVATAR_HOST");
            var aa = QualitySettings.antiAliasing;
            var shadows = QualitySettings.shadows;
            var resolution = QualitySettings.shadowResolution;
            var filtering = QualitySettings.anisotropicFiltering;
            var rate = Application.targetFrameRate;
            var vsync = QualitySettings.vSyncCount;
            var root = new GameObject("QualityTest");
            try
            {
                var profile = root.AddComponent<AvatarPerformanceProfile>();
                Environment.SetEnvironmentVariable("NEUROASIST_AVATAR_HOST", "desktop_managed");
                Assert.That(profile.ConfigureQuality("high", "medium"), Is.True);
                Assert.That(profile.SelectedQuality, Is.EqualTo("medium"));
                Assert.That(QualitySettings.antiAliasing, Is.EqualTo(4));
                Assert.That(Application.targetFrameRate, Is.EqualTo(30));
                Assert.That(profile.ConfigureQuality("low", "medium"), Is.True);
                Assert.That(profile.SelectedQuality, Is.EqualTo("medium"), "Inactive placement cannot lower current quality");
                Assert.That(profile.ConfigureQuality("high", "invalid"), Is.False);
                Assert.That(QualitySettings.antiAliasing, Is.EqualTo(4));

                Environment.SetEnvironmentVariable("NEUROASIST_AVATAR_HOST", "embedded");
                Assert.That(profile.ConfigureQuality("high", "low"), Is.True);
                Assert.That(QualitySettings.antiAliasing, Is.EqualTo(8));
                Assert.That(Application.targetFrameRate, Is.EqualTo(60));
                var sleep = root.AddComponent<AvatarSleepController>();
                sleep.SetSleeping(true);
                profile.ConfigureQuality("low", "high");
                Assert.That(sleep.IsSleeping, Is.True);
                Assert.That(QualitySettings.shadows, Is.EqualTo(ShadowQuality.All), "Economical preset must preserve MToon skin tones");
                sleep.SetSleeping(false);
                Assert.That(Application.targetFrameRate, Is.EqualTo(30), "Wake must retain the chosen quality cap");
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(root);
                Environment.SetEnvironmentVariable("NEUROASIST_AVATAR_HOST", host);
                QualitySettings.antiAliasing = aa;
                QualitySettings.shadows = shadows;
                QualitySettings.shadowResolution = resolution;
                QualitySettings.anisotropicFiltering = filtering;
                QualitySettings.vSyncCount = vsync;
                Application.targetFrameRate = rate;
            }
        }
    }
}
