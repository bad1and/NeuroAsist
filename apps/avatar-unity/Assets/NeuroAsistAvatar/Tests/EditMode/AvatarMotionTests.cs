using System.Collections.Generic;
using NUnit.Framework;
using UnityEngine;

namespace NeuroAsist.Avatar.Tests
{
    public sealed class AvatarMotionTests
    {
        private sealed class FixedRandom : IMotionRandom
        {
            public float Range(float minimum, float maximum) => minimum;
            public int Range(int minimumInclusive, int maximumExclusive) => minimumInclusive;
        }

        [Test] public void UnknownGestureFallsBackToAuto() => Assert.That(AvatarMotionNames.ParseGesture("dance"), Is.EqualTo(GestureTag.Auto));
        [Test] public void EmotionParsingFallsBackToNeutral() => Assert.That(AvatarMotionNames.ParseEmotion("banana"), Is.EqualTo(AvatarEmotion.Neutral));
        [Test] public void IdleSelectionDoesNotImmediatelyRepeatAndHonorsCooldown()
        {
            var first = new AlternativeIdleDefinition { Id = "first", AnimatorState = "one", CooldownSeconds = 20f };
            var second = new AlternativeIdleDefinition { Id = "second", AnimatorState = "two", CooldownSeconds = 20f };
            var picked = AvatarIdleScheduler.Select(new List<AlternativeIdleDefinition> { first, second }, "first", 10f, new Dictionary<string, float> { ["first"] = 0f }, new FixedRandom(), false, false);
            Assert.That(picked, Is.SameAs(second));
        }
        [Test] public void SpeakingBlocksLongIdle()
        {
            var longIdle = new AlternativeIdleDefinition { Id = "long", AnimatorState = "long", Category = IdleCategory.Long };
            Assert.That(AvatarIdleScheduler.Select(new List<AlternativeIdleDefinition> { longIdle }, null, 0f, new Dictionary<string, float>(), new FixedRandom(), true, false), Is.Null);
        }
        [Test] public void PortraitMicroIdlesRotateWithoutRepetition()
        {
            var first = new AlternativeIdleDefinition { Id = "wander", AnimatorState = "IdleNeutral", LookPattern = IdleLookPattern.Wander, CooldownSeconds = 20f };
            var second = new AlternativeIdleDefinition { Id = "glance", AnimatorState = "IdleNeutral", LookPattern = IdleLookPattern.SideGlance, CooldownSeconds = 20f };
            var picked = AvatarIdleScheduler.Select(new List<AlternativeIdleDefinition> { first, second }, "wander", 10f, new Dictionary<string, float> { ["wander"] = 0f }, new FixedRandom(), false, false);
            Assert.That(picked, Is.SameAs(second));
            Assert.That(picked.LookPattern, Is.EqualTo(IdleLookPattern.SideGlance));
        }
        [Test] public void GestureSelectionHonorsCooldownAndEmotion()
        {
            var gesture = ScriptableObject.CreateInstance<GestureDefinition>();
            gesture.Id = "talk"; gesture.AnimatorState = "TalkGesture01"; gesture.Tag = GestureTag.Talk; gesture.CooldownSeconds = 10f; gesture.DeniedEmotions.Add(AvatarEmotion.Sad);
            Assert.That(AvatarGestureController.Select(new List<GestureDefinition> { gesture }, GestureTag.Talk, AvatarEmotion.Sad, true, -1, 20f, new Dictionary<string, float>(), new FixedRandom()), Is.Null);
            Assert.That(AvatarGestureController.Select(new List<GestureDefinition> { gesture }, GestureTag.Talk, AvatarEmotion.Neutral, true, -1, 20f, new Dictionary<string, float> { ["talk"] = 15f }, new FixedRandom()), Is.Null);
            Object.DestroyImmediate(gesture);
        }
        [Test] public void LookAnglesAreClamped()
        {
            var values = AvatarLookController.ClampAngles(100f, -50f, 35f, 20f);
            Assert.That(values.x, Is.EqualTo(35f)); Assert.That(values.y, Is.EqualTo(-20f));
        }
        [Test] public void MotionProfileNormalizesIntervals()
        {
            var profile = ScriptableObject.CreateInstance<MotionProfile>(); profile.IdleIntervalMinSeconds = 8f; profile.IdleIntervalMaxSeconds = 2f; profile.ValidateValues();
            Assert.That(profile.IdleIntervalMaxSeconds, Is.EqualTo(8f)); Object.DestroyImmediate(profile);
        }
        [Test] public void AutomaticSpeechAccentRespectsLengthAndTurnBudget()
        {
            var history = new List<float> { 0f };
            Assert.That(AvatarMotionController.CanScheduleAutomaticAccent(1.6f, GestureTag.Auto, 10f, history), Is.False);
            Assert.That(AvatarMotionController.CanScheduleAutomaticAccent(3f, GestureTag.Auto, 5f, history), Is.False);
            Assert.That(AvatarMotionController.CanScheduleAutomaticAccent(1.8f, GestureTag.Auto, 7f, history), Is.True);
            Assert.That(AvatarMotionController.CanScheduleAutomaticAccent(3f, GestureTag.Question, 2f, new List<float>()), Is.True);
            Assert.That(AvatarMotionController.CanScheduleAutomaticAccent(3f, GestureTag.Auto, 40f, new List<float> { 1f, 9f }), Is.True);
            Assert.That(AvatarMotionController.CanScheduleAutomaticAccent(3f, GestureTag.Auto, 25f, new List<float> { 1f, 10f, 20f }), Is.False);
        }
        [Test] public void GestureVariantAvoidsRecentStateWhenAlternativeExists()
        {
            var gesture = ScriptableObject.CreateInstance<GestureDefinition>();
            gesture.AnimatorState = "Talk"; gesture.VariantAnimatorStates.Add("TalkMirror");
            var selected = gesture.SelectAnimatorState(new FixedRandom(), new[] { "Talk" });
            Assert.That(selected, Is.EqualTo("TalkMirror"));
            Object.DestroyImmediate(gesture);
        }
    }
}
