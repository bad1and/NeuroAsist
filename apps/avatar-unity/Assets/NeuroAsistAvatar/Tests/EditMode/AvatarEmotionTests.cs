using NUnit.Framework;
using UnityEngine;

namespace NeuroAsist.Avatar.Tests
{
    public sealed class AvatarEmotionTests
    {
        [Test]
        public void TransientEmotionsIdentifiedCorrectly()
        {
            Assert.That(AvatarEmotionController.IsTransient("surprised"), Is.True);
            Assert.That(AvatarEmotionController.IsTransient("SURPRISED"), Is.True);
            Assert.That(AvatarEmotionController.IsTransient("happy"), Is.False);
            Assert.That(AvatarEmotionController.IsTransient("neutral"), Is.False);
        }

        [Test]
        public void EmotionMotionStartsSmoothlyWithZeroInitialPop()
        {
            var go = new GameObject("TestAvatarEmotion");
            var controller = go.AddComponent<AvatarEmotionController>();
            var settings = ScriptableObject.CreateInstance<AvatarRuntimeSettings>();
            settings.EmotionAttackTime = 0.80f;
            settings.EmotionReleaseTime = 1.40f;
            settings.EmotionMicroDynamics = false;
            controller.Configure(settings, null);

            controller.SetEmotion("happy", 1f);

            // Target should immediately be set (clamped to natural maximum of 0.80f)
            Assert.That(controller.GetTargetWeight("happy"), Is.EqualTo(0.80f));
            Assert.That(controller.GetWeight("happy"), Is.EqualTo(0f));

            // Step a single frame (16.6 ms at 60 fps)
            controller.ManualUpdate(0.0166f);

            var weight = controller.GetWeight("happy");
            var velocity = controller.GetVelocity("happy");

            // Movement must have started smoothly: weight > 0, but no huge initial jump
            Assert.That(weight, Is.GreaterThan(0.000001f));
            Assert.That(weight, Is.LessThan(0.05f), "First frame should not jump noticeably");
            Assert.That(velocity, Is.GreaterThan(0f), "Velocity must be positive and building inertia");

            Object.DestroyImmediate(settings);
            Object.DestroyImmediate(go);
        }

        [Test]
        public void PhysicalDecayIsAsymmetricAndGentle()
        {
            var go = new GameObject("TestAvatarEmotionDecay");
            var controller = go.AddComponent<AvatarEmotionController>();
            var settings = ScriptableObject.CreateInstance<AvatarRuntimeSettings>();
            settings.EmotionAttackTime = 0.80f;
            settings.EmotionReleaseTime = 1.40f;
            settings.EmotionHoldTime = 0f; // test pure decay without hold delay
            settings.EmotionMicroDynamics = false;
            controller.Configure(settings, null);

            controller.SetEmotion("happy", 1f);

            // Step forward until happy is close to target (0.80f)
            for (int i = 0; i < 140; i++)
            {
                controller.ManualUpdate(0.0166f);
            }

            var settledWeight = controller.GetWeight("happy");
            Assert.That(settledWeight, Is.GreaterThan(0.75f));

            // Release back to neutral
            controller.SetEmotion("neutral", 1f);
            Assert.That(controller.GetTargetWeight("happy"), Is.EqualTo(0f));

            // After 1 frame of release, weight shouldn't snap to zero
            controller.ManualUpdate(0.0166f);
            var afterOneFrame = controller.GetWeight("happy");
            Assert.That(afterOneFrame, Is.GreaterThan(0.70f), "Release must not snap to 0 immediately");

            // After 0.65s (40 frames), happy should still be partially active because release is slower (1.40s)
            for (int i = 0; i < 40; i++)
            {
                controller.ManualUpdate(0.0166f);
            }
            var halfwayRelease = controller.GetWeight("happy");
            Assert.That(halfwayRelease, Is.GreaterThan(0.15f), "Release is gentler than attack and lingers naturally");

            // Step until fully settled
            for (int i = 0; i < 250; i++)
            {
                controller.ManualUpdate(0.0166f);
            }
            Assert.That(controller.GetWeight("happy"), Is.EqualTo(0f));

            Object.DestroyImmediate(settings);
            Object.DestroyImmediate(go);
        }

        [Test]
        public void PostSpeechEmotionHoldLingerPreservesSmileBeforeDecay()
        {
            var go = new GameObject("TestAvatarEmotionHold");
            var controller = go.AddComponent<AvatarEmotionController>();
            var settings = ScriptableObject.CreateInstance<AvatarRuntimeSettings>();
            settings.EmotionAttackTime = 0.80f;
            settings.EmotionReleaseTime = 1.40f;
            settings.EmotionHoldTime = 0.55f;
            settings.EmotionMicroDynamics = false;
            controller.Configure(settings, null);

            controller.SetEmotion("happy", 1f);

            for (int i = 0; i < 140; i++)
            {
                controller.ManualUpdate(0.0166f);
            }
            Assert.That(controller.GetWeight("happy"), Is.GreaterThan(0.75f));

            // Transition to neutral
            controller.SetEmotion("neutral", 1f);

            // Hold is active
            Assert.That(controller.GetHoldRemaining("happy"), Is.GreaterThan(0.40f));

            // Advance 250ms (during hold)
            for (int i = 0; i < 15; i++)
            {
                controller.ManualUpdate(0.0166f);
            }
            Assert.That(controller.GetWeight("happy"), Is.GreaterThan(0.70f), "Smile must linger warmly after speech ends");

            // Advance another 350ms (hold expired, viscoelastic relaxation begins)
            for (int i = 0; i < 22; i++)
            {
                controller.ManualUpdate(0.0166f);
            }
            Assert.That(controller.GetHoldRemaining("happy"), Is.EqualTo(0f));

            // Step until fully settled
            for (int i = 0; i < 250; i++)
            {
                controller.ManualUpdate(0.0166f);
            }
            Assert.That(controller.GetWeight("happy"), Is.EqualTo(0f));

            Object.DestroyImmediate(settings);
            Object.DestroyImmediate(go);
        }

        [Test]
        public void MidFlightEmotionTransitionPreservesInertiaWithoutSnapping()
        {
            var go = new GameObject("TestAvatarEmotionTransition");
            var controller = go.AddComponent<AvatarEmotionController>();
            var settings = ScriptableObject.CreateInstance<AvatarRuntimeSettings>();
            settings.EmotionAttackTime = 0.80f;
            settings.EmotionReleaseTime = 1.40f;
            settings.EmotionMicroDynamics = false;
            controller.Configure(settings, null);

            // Start happy
            controller.SetEmotion("happy", 1f);

            // Step 120ms so velocity is built up
            for (int i = 0; i < 7; i++)
            {
                controller.ManualUpdate(0.0166f);
            }

            var happyWeightMid = controller.GetWeight("happy");
            var happyVelMid = controller.GetVelocity("happy");
            Assert.That(happyWeightMid, Is.GreaterThan(0.001f));
            Assert.That(happyVelMid, Is.GreaterThan(0f));

            // Switch to sad mid-flight (maximumIntensity for sad is 0.75f)
            controller.SetEmotion("sad", 1f);
            Assert.That(controller.GetTargetWeight("happy"), Is.EqualTo(0f));
            Assert.That(controller.GetTargetWeight("sad"), Is.EqualTo(0.75f));

            // Advance 1 frame
            controller.ManualUpdate(0.0166f);
            var happyWeightNext = controller.GetWeight("happy");
            var sadWeightNext = controller.GetWeight("sad");

            // Happy shouldn't snap to 0 in 1 frame
            Assert.That(happyWeightNext, Is.GreaterThan(0f));
            // Sad should start accelerating smoothly from 0
            Assert.That(sadWeightNext, Is.GreaterThan(0f));
            Assert.That(sadWeightNext, Is.LessThan(0.05f));

            Object.DestroyImmediate(settings);
            Object.DestroyImmediate(go);
        }

        [Test]
        public void SnapToEmotionAppliesImmediately()
        {
            var go = new GameObject("TestAvatarEmotionSnap");
            var controller = go.AddComponent<AvatarEmotionController>();
            controller.Configure(null, null);

            controller.SnapToEmotion("happy", 0.8f);

            Assert.That(controller.GetWeight("happy"), Is.EqualTo(0.8f));
            Assert.That(controller.GetVelocity("happy"), Is.EqualTo(0f));

            controller.SnapToEmotion("neutral", 1f);
            Assert.That(controller.GetWeight("happy"), Is.EqualTo(0f));

            Object.DestroyImmediate(go);
        }

        [Test]
        public void SpeechCoarticulationSoftensMouthMorphWeightsDuringSpeaking()
        {
            var go = new GameObject("TestAvatarSpeechCoarticulation");
            var controller = go.AddComponent<AvatarEmotionController>();
            controller.Configure(null, null);

            controller.SetEmotion("happy", 1f);
            Assert.That(controller.GetTargetWeight("happy"), Is.EqualTo(0.80f));

            controller.SetSpeaking(true);
            Assert.That(controller.IsSpeaking, Is.True);

            controller.SetSpeaking(false);
            Assert.That(controller.IsSpeaking, Is.False);

            Object.DestroyImmediate(go);
        }
    }
}
