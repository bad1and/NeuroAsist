using NUnit.Framework;
using UnityEngine;

namespace NeuroAsist.Avatar.Tests
{
    public sealed class AvatarWelcomeTests
    {
        [TestCase(.55f)] [TestCase(1f)] [TestCase(1.8f)]
        public void FullBodyDistanceFitsBothAxes(float aspect)
        {
            var bounds = new Bounds(new Vector3(0, .7f, 0), new Vector3(.7f, 1.4f, .6f));
            var distance = AvatarPresentationController.FullBodyDistance(bounds, aspect, 34);
            var halfHeightAtFront = (distance - bounds.extents.z) * Mathf.Tan(17 * Mathf.Deg2Rad);
            Assert.That(halfHeightAtFront, Is.GreaterThan(bounds.extents.y));
            Assert.That(halfHeightAtFront * aspect, Is.GreaterThan(bounds.extents.x));
        }

        [Test] public void SeatedModeRequiresAnImportedHumanoidClip()
        {
            var go = new GameObject("Welcome test");
            try
            {
                var welcome = go.AddComponent<AvatarWelcomeController>();
                Assert.That(welcome.SetPresentation("welcome_seated", true), Is.False);
                Assert.That(welcome.IsSeated, Is.False);
                Assert.That(welcome.SetPresentation("unknown", true), Is.False);
                Assert.That(welcome.SetPresentation("portrait", true), Is.True);
            }
            finally { Object.DestroyImmediate(go); }
        }
    }
}
