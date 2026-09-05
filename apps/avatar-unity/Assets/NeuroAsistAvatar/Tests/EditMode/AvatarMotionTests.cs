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
        [Test] public void AutomaticSpeechAccentRespectsExplicitNeuralControl()
        {
            var history = new List<float> { 0f };
            // Auto/None gestures are never scheduled automatically
            Assert.That(AvatarMotionController.CanScheduleAutomaticAccent(1.6f, GestureTag.Auto, 10f, history), Is.False);
            Assert.That(AvatarMotionController.CanScheduleAutomaticAccent(3f, GestureTag.Auto, 5f, history), Is.False);
            Assert.That(AvatarMotionController.CanScheduleAutomaticAccent(1.8f, GestureTag.None, 7f, history), Is.False);
            // Explicit gestures chosen by the neural model are always scheduled
            Assert.That(AvatarMotionController.CanScheduleAutomaticAccent(3f, GestureTag.Question, 2f, new List<float>()), Is.True);
            Assert.That(AvatarMotionController.CanScheduleAutomaticAccent(1.5f, GestureTag.Greeting_Right, 10f, new List<float>()), Is.True);
        }
        [Test] public void GestureVariantAvoidsRecentStateWhenAlternativeExists()
        {
            var gesture = ScriptableObject.CreateInstance<GestureDefinition>();
            gesture.AnimatorState = "Talk"; gesture.VariantAnimatorStates.Add("TalkMirror");
            var selected = gesture.SelectAnimatorState(new FixedRandom(), new[] { "Talk" });
            Assert.That(selected, Is.EqualTo("TalkMirror"));
            Object.DestroyImmediate(gesture);
        }
        [Test] public void ExplicitLeftHandSelectsMirroredVariant()
        {
            var gesture = ScriptableObject.CreateInstance<GestureDefinition>();
            gesture.AnimatorState = "Greeting"; gesture.VariantAnimatorStates.Add("GreetingMirror");
            var selected = gesture.SelectAnimatorState(new FixedRandom(), null, preferMirror: true);
            Assert.That(selected, Is.EqualTo("GreetingMirror"));
            Object.DestroyImmediate(gesture);
        }
        [Test] public void ExplicitRightHandSelectsNonMirroredVariant()
        {
            var gesture = ScriptableObject.CreateInstance<GestureDefinition>();
            gesture.AnimatorState = "Greeting"; gesture.VariantAnimatorStates.Add("GreetingMirror");
            var selected = gesture.SelectAnimatorState(new FixedRandom(), null, preferMirror: false);
            Assert.That(selected, Is.EqualTo("Greeting"));
            Object.DestroyImmediate(gesture);
        }
        [Test] public void HandSpecificGesturesFallBackToBaseTagInSelect()
        {
            var gesture = ScriptableObject.CreateInstance<GestureDefinition>();
            gesture.Id = "greeting"; gesture.AnimatorState = "Greeting"; gesture.Tag = GestureTag.Greeting;
            var pickedRight = AvatarGestureController.Select(new List<GestureDefinition> { gesture }, GestureTag.Greeting_Right, AvatarEmotion.Neutral, false, -1, 0f, new Dictionary<string, float>(), new FixedRandom());
            var pickedLeft = AvatarGestureController.Select(new List<GestureDefinition> { gesture }, GestureTag.Greeting_Left, AvatarEmotion.Neutral, false, -1, 0f, new Dictionary<string, float>(), new FixedRandom());
            Assert.That(pickedRight, Is.SameAs(gesture));
            Assert.That(pickedLeft, Is.SameAs(gesture));
            Object.DestroyImmediate(gesture);
        }
        [Test] public void NewEmotionsAndGesturesParseCorrectly()
        {
            Assert.That(AvatarMotionNames.ParseEmotion("pouting"), Is.EqualTo(AvatarEmotion.Pouting));
            Assert.That(AvatarMotionNames.ParseEmotion("wink_left"), Is.EqualTo(AvatarEmotion.Wink_Left));
            Assert.That(AvatarMotionNames.ParseEmotion("excited"), Is.EqualTo(AvatarEmotion.Excited));
            Assert.That(AvatarMotionNames.ParseGesture("greeting_right"), Is.EqualTo(GestureTag.Greeting_Right));
            Assert.That(AvatarMotionNames.ParseGesture("farewell_left"), Is.EqualTo(GestureTag.Farewell_Left));
            Assert.That(AvatarMotionNames.ParseGesture("nod"), Is.EqualTo(GestureTag.Nod));
        }

        [Test] public void ExplicitGestureBypassesCooldownWhenIgnoreCooldownIsTrue()
        {
            var gesture = ScriptableObject.CreateInstance<GestureDefinition>();
            gesture.Id = "greeting"; gesture.AnimatorState = "Greeting"; gesture.Tag = GestureTag.Greeting; gesture.CooldownSeconds = 10f;
            var played = new Dictionary<string, float> { ["greeting"] = 15f };
            var blocked = AvatarGestureController.Select(new List<GestureDefinition> { gesture }, GestureTag.Greeting, AvatarEmotion.Neutral, false, -1, 20f, played, new FixedRandom(), false);
            Assert.That(blocked, Is.Null);
            var allowed = AvatarGestureController.Select(new List<GestureDefinition> { gesture }, GestureTag.Greeting, AvatarEmotion.Neutral, false, -1, 20f, played, new FixedRandom(), true);
            Assert.That(allowed, Is.SameAs(gesture));
            Object.DestroyImmediate(gesture);
        }
    }
}
