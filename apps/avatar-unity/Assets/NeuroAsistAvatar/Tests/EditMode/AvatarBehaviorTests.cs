using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;

namespace NeuroAsist.Avatar.Tests
{
    public sealed class AvatarBehaviorTests
    {
        private sealed class First : IMotionRandom
        { public float Range(float a, float b) => a; public int Range(int a, int b) => a; }
        [TestCase(GestureTag.Head_Scratch_Left, GestureTag.Head_Scratch, GestureSide.Left)]
        [TestCase(GestureTag.Head_Scratch_Right, GestureTag.Head_Scratch, GestureSide.Right)]
        [TestCase(GestureTag.Thumbs_Up_Left, GestureTag.Thumbs_Up, GestureSide.Left)]
        [TestCase(GestureTag.Thumbs_Up_Right, GestureTag.Thumbs_Up, GestureSide.Right)]
        [TestCase(GestureTag.Pointing_Left, GestureTag.Pointing, GestureSide.Left)]
        [TestCase(GestureTag.Pointing_Right, GestureTag.Pointing, GestureSide.Right)]
        [TestCase(GestureTag.Facepalm_Left, GestureTag.Facepalm, GestureSide.Left)]
        [TestCase(GestureTag.Facepalm_Right, GestureTag.Facepalm, GestureSide.Right)]
        public void ExplicitHandSelectsTheRequestedMirror(GestureTag requested, GestureTag family, GestureSide side)
        {
            Assert.That(AvatarMotionNames.BaseGesture(requested), Is.EqualTo(family));
            var settings = AssetDatabase.LoadAssetAtPath<AvatarMotionSettings>("Assets/NeuroAsistAvatar/Motion/AvatarMotionSettings.asset");
            var definition = settings.GestureDefinitions.First(d => d.Tag == family);
            var selected = new AvatarBehaviorPolicy().Select(definition.Variants, requested, AvatarState.Idle, .85f, new First());
            Assert.That(selected, Is.Not.Null);
            Assert.That(selected.Side, Is.EqualTo(side));
        }
        [Test] public void QuietActivityGraduallySettlesAndNeverDies()
        {
            Assert.That(AvatarBehaviorPolicy.QuietActivityAfter(30), Is.EqualTo(1));
            Assert.That(AvatarBehaviorPolicy.QuietActivityAfter(100), Is.InRange(.5f, 1f));
            Assert.That(AvatarBehaviorPolicy.QuietActivityAfter(3600), Is.EqualTo(.5f));
        }
        [Test] public void MirroringDoesNotEvadeRecentPatternHistory()
        {
            var policy = new AvatarBehaviorPolicy();
            var variants = new List<GestureVariant>();
            for (var i = 0; i < 6; i++) foreach (var side in new[] { GestureSide.Right, GestureSide.Left })
                variants.Add(new GestureVariant { Id = i + "_" + side, PatternId = i.ToString(), AnimatorState = i.ToString(), Side = side });
            var lastFour = new Queue<string>();
            for (var i = 0; i < 60; i++)
            {
                var variant = policy.Select(variants, i % 2 == 0 ? GestureTag.Greeting_Right : GestureTag.Greeting_Left, AvatarState.Idle, .7f, new First());
                Assert.That(lastFour.Contains(variant.PatternId), Is.False);
                Assert.That(variant.Side, Is.EqualTo(i % 2 == 0 ? GestureSide.Right : GestureSide.Left));
                policy.Remember(GestureTag.Greeting, variant);
                lastFour.Enqueue(variant.PatternId); if (lastFour.Count > 4) lastFour.Dequeue();
            }
        }
        [Test] public void FamilyCooldownIsSharedByAliasesAndHands()
        {
            var policy = new AvatarBehaviorPolicy();
            policy.Finished(GestureTag.Greeting_Left, 10);
            Assert.That(policy.FamilyReady(GestureTag.Greeting_Right, 11, 2), Is.False);
            policy.Finished(GestureTag.Nod, 12);
            Assert.That(policy.FamilyReady(GestureTag.Agreement, 13, 2), Is.False);
        }
        [Test] public void AnimatorSelectionCannotBypassFamilyCooldownByChangingHand()
        {
            var right = ScriptableObject.CreateInstance<GestureDefinition>();
            right.Id = "right"; right.Tag = GestureTag.Greeting_Right; right.AnimatorState = "wave";
            var left = ScriptableObject.CreateInstance<GestureDefinition>();
            left.Id = "left"; left.Tag = GestureTag.Greeting_Left; left.AnimatorState = "waveLeft";
            var history = new Dictionary<string, float> { ["@family:Greeting"] = 10 };
            Assert.That(AvatarGestureController.Select(new[] { right, left }, GestureTag.Greeting_Left, AvatarEmotion.Neutral, false, -1, 11, history, new First()), Is.Null);
            Object.DestroyImmediate(right); Object.DestroyImmediate(left);
        }
        [Test] public void AutomaticSpeechCannotBorrowALargeOrContactGesture()
        {
            var policy = new AvatarBehaviorPolicy();
            var variants = new[] { new GestureVariant { AnimatorState = "wave", LargeMotion = true }, new GestureVariant { AnimatorState = "face", ContactSensitive = true } };
            Assert.That(policy.Select(variants, GestureTag.Auto, AvatarState.Speaking, 1, new First(), true), Is.Null);
            Assert.That(policy.CanAccent(10, .7f, GestureTag.Auto, false), Is.False);
            Assert.That(policy.CanAccent(10, 3, GestureTag.None, false), Is.False);
            Assert.That(policy.CanAccent(10, 3, GestureTag.Auto, true), Is.False);
        }
        [Test] public void DuplicateCuesAreBoundedAndIgnored()
        {
            var policy = new AvatarBehaviorPolicy();
            Assert.That(policy.AcceptCue("u:0"), Is.True);
            Assert.That(policy.AcceptCue("u:0"), Is.False);
            for (var i = 0; i < 300; i++) policy.AcceptCue("u:" + (i + 1));
            Assert.That(policy.AcceptCue("u:0"), Is.True);
        }
        [Test] public void EveryCheckedInFamilyHasRealClipsAndEnoughDistinctPatterns()
        {
            var settings = AssetDatabase.LoadAssetAtPath<AvatarMotionSettings>("Assets/NeuroAsistAvatar/Motion/AvatarMotionSettings.asset");
            Assert.That(settings, Is.Not.Null);
            foreach (var definition in settings.GestureDefinitions)
            {
                var family = AvatarBehaviorPolicy.Family(definition.Tag);
                var expected = new[] { GestureTag.Talk, GestureTag.Question, GestureTag.Explanation, GestureTag.Thinking }.Contains(family) ? 8 : 6;
                Assert.That(definition.Variants.Select(v => v.PatternId).Distinct().Count(), Is.GreaterThanOrEqualTo(expected), definition.Id);
                foreach (var variant in definition.Variants)
                {
                    Assert.That(variant.Clip, Is.Not.Null, variant.Id);
                    Assert.That(variant.Clip.humanMotion, Is.True, variant.Id);
                    Assert.That(variant.Duration, Is.GreaterThan(.5f), variant.Id);
                    Assert.That(variant.SpeedRange.x, Is.GreaterThanOrEqualTo(.92f));
                    Assert.That(variant.SpeedRange.y, Is.LessThanOrEqualTo(1.08f));
                }
            }
        }
        [Test] public void GeneratedPatternsDifferInJointTrajectoriesNotOnlyTiming()
        {
            var settings = AssetDatabase.LoadAssetAtPath<AvatarMotionSettings>("Assets/NeuroAsistAvatar/Motion/AvatarMotionSettings.asset");
            foreach (var definition in settings.GestureDefinitions.Where(d => d.Tag == AvatarBehaviorPolicy.Family(d.Tag)))
            {
                var signatures = new HashSet<string>();
                foreach (var variant in definition.Variants.GroupBy(v => v.PatternId).Select(g => g.First()))
                {
                    var signature = new System.Text.StringBuilder();
                    foreach (var binding in AnimationUtility.GetCurveBindings(variant.Clip))
                    {
                        var curve = AnimationUtility.GetEditorCurve(variant.Clip, binding);
                        // Compare normalized time, so duration changes cannot pass.
                        for (var i = 1; i <= 8; i++) signature.Append(Mathf.RoundToInt(curve.Evaluate(variant.Duration * i / 9) * 1000)).Append(',');
                    }
                    Assert.That(signatures.Add(signature.ToString()), Is.True, "Duplicate performance: " + variant.Id);
                }
            }
        }
    }
}
