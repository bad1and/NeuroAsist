using System;
using System.Collections.Generic;
using System.Linq;
using NeuroAsist.Avatar;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace NeuroAsist.AvatarEditor
{
    /// <summary>
    /// Bakes deliberately authored performances into ordinary Humanoid clips.
    /// Existing source curves retain recognizable hand shapes; recipes change
    /// trajectories, supporting arm poses and the number/placement of strokes.
    /// Generated files are created once: rerunning setup never overwrites tuning.
    /// </summary>
    public static class AvatarGestureLibrary
    {
        public const string GeneratedRoot = AvatarMotionSetup.Root + "/Generated";
        private static AvatarGestureClipLibrary Library()
        {
            var path = GeneratedRoot + "/Performances.asset";
            var library = AssetDatabase.LoadAssetAtPath<AvatarGestureClipLibrary>(path);
            if (library == null) { library = ScriptableObject.CreateInstance<AvatarGestureClipLibrary>(); AssetDatabase.CreateAsset(library, path); }
            return library;
        }
        public static bool SourceIsLeftHanded(GestureTag family) => family == GestureTag.Facepalm;
        [MenuItem("Iris/Avatar/Rebuild Generated Performances (overwrites generated tuning)")]
        public static void RebuildGeneratedClips()
        {
            var settings = AssetDatabase.LoadAssetAtPath<AvatarMotionSettings>(AvatarMotionSetup.SettingsPath);
            var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(AvatarMotionSetup.ControllerPath);
            foreach (var definition in settings.GestureDefinitions.Where(d => d.Tag == AvatarBehaviorPolicy.Family(d.Tag)))
            {
                var source = controller.layers[1].stateMachine.states.First(s => s.state.name == definition.AnimatorState).state.motion as AnimationClip;
                foreach (var recipe in Recipes(definition.Tag))
                {
                    var id = definition.Tag + "_" + recipe.Name;
                    var existing = Library().Clips.Find(c => c.name == id) ?? AssetDatabase.LoadAssetAtPath<AnimationClip>(GeneratedRoot + "/" + id + ".anim");
                    var metadata = definition.Variants.First(v => v.PatternId == id);
                    var authoredSource = definition.Tag == GestureTag.Farewell ? controller.layers[1].stateMachine.states.First(s => s.state.name == "Greeting").state.motion as AnimationClip : source;
                    var contact = metadata.ContactSensitive;
                    var prep = definition.Tag==GestureTag.Facepalm?1.55f:contact ? .72f : .58f;
                    var stroke = Mathf.Clamp(authoredSource.length * .66f, 1.3f, 3f) + (recipe.Beats - 1) * .3f;
                    var recovery = definition.Tag==GestureTag.Facepalm?1.20f:contact ? .95f : .82f;
                    foreach (var matching in settings.GestureDefinitions.SelectMany(d => d.Variants).Where(v => v.PatternId == id))
                    { matching.PreparationSeconds = prep; matching.StrokeSeconds = stroke; matching.RecoverySeconds = recovery; }
                    var clip = Bake(authoredSource, definition.Tag, recipe, metadata.PreparationSeconds, metadata.StrokeSeconds, metadata.RecoverySeconds, metadata.PreparationSeconds + metadata.StrokeSeconds + metadata.HoldSeconds + metadata.RecoverySeconds);
                    clip.name = id;
                    EditorUtility.CopySerialized(clip, existing);
                    EditorUtility.SetDirty(existing);
                    UnityEngine.Object.DestroyImmediate(clip);
                }
            }
            foreach (var definition in settings.GestureDefinitions) EditorUtility.SetDirty(definition);
            AssetDatabase.SaveAssets();
            PackGeneratedClips();
        }
        // Unity's native binary serialization keeps the baked library compact.
        // Recipes remain readable above; GUIDs and local file IDs are preserved.
        public static void PackGeneratedClips()
        {
            var library = Library();
            var oldPaths = AssetDatabase.FindAssets("t:AnimationClip", new[] { GeneratedRoot }).Select(AssetDatabase.GUIDToAssetPath).Where(p => p.EndsWith(".anim")).ToArray();
            if (oldPaths.Length == 0) return;
            foreach (var path in oldPaths)
            {
                var clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(path);
                if (library.Clips.Any(c => c.name == clip.name)) continue;
                var packed = UnityEngine.Object.Instantiate(clip); packed.name = clip.name;
                AssetDatabase.AddObjectToAsset(packed, library); library.Clips.Add(packed);
            }
            var settings = AssetDatabase.LoadAssetAtPath<AvatarMotionSettings>(AvatarMotionSetup.SettingsPath);
            foreach (var definition in settings.GestureDefinitions)
            {
                foreach (var variant in definition.Variants) variant.Clip = library.Clips.Find(c => c.name == variant.PatternId);
                EditorUtility.SetDirty(definition);
            }
            var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(AvatarMotionSetup.ControllerPath);
            foreach (var layer in controller.layers) foreach (var state in layer.stateMachine.states)
                if (state.state.motion is AnimationClip clip)
                {
                    var packed = library.Clips.Find(c => c.name == clip.name);
                    if (packed != null) { state.state.motion = packed; EditorUtility.SetDirty(state.state); }
                }
            EditorUtility.SetDirty(library); EditorUtility.SetDirty(controller); AssetDatabase.SaveAssets();
            // Only the loose files just migrated into this new library are removed.
            foreach (var path in oldPaths) AssetDatabase.DeleteAsset(path);
            AssetDatabase.SaveAssets();
        }
        public static void CompactGeneratedClips()
        {
            foreach (var clip in Library().Clips)
            {
                foreach (var binding in AnimationUtility.GetCurveBindings(clip))
                { var curve = AnimationUtility.GetEditorCurve(clip, binding); Smooth(curve); AnimationUtility.SetEditorCurve(clip, binding, curve); }
                EditorUtility.SetDirty(clip);
            }
            AssetDatabase.SaveAssets();
        }
        private struct Recipe
        {
            public string Name;
            public float ArmLift, ArmReach, Elbow, Wrist, Support, HeadTilt, Turns;
            public int Beats;
            public float Hold;
            public Recipe(string name, float lift, float reach, float elbow, float wrist, float support, float head, int beats = 1, float hold = .15f, float turns = 0)
            { Name = name; ArmLift = lift; ArmReach = reach; Elbow = elbow; Wrist = wrist; Support = support; HeadTilt = head; Beats = beats; Hold = hold; Turns = turns; }
        }

        public static int RequiredPatterns(GestureTag tag)
        {
            var family = AvatarBehaviorPolicy.Family(tag);
            return family == GestureTag.Talk || family == GestureTag.Question || family == GestureTag.Explanation || family == GestureTag.Thinking ? 8 : 6;
        }

        public static List<GestureVariant> Create(GestureTag tag, AnimationClip source, AnimatorController controller)
        {
            var family = AvatarBehaviorPolicy.Family(tag);
            if (family == GestureTag.Farewell) source = controller.layers[1].stateMachine.states.First(s => s.state.name == "Greeting").state.motion as AnimationClip;
            var channels = ChannelsFor(family);
            var layerName = channels == MotionChannels.Head ? "Head Gesture Layer" : (channels & MotionChannels.Head) == 0 ? "Arms Gesture Layer" : AvatarMotionNames.GestureLayer;
            var machine = controller.layers.First(l => l.name == layerName).stateMachine;
            if (source == null) throw new InvalidOperationException("Missing source clip for " + family);
            if (!AssetDatabase.IsValidFolder(GeneratedRoot)) AssetDatabase.CreateFolder(AvatarMotionSetup.Root, "Generated");
            var recipes = Recipes(family);
            var result = new List<GestureVariant>();
            for (var index = 0; index < recipes.Length; index++)
            {
                var recipe = recipes[index];
                var id = family + "_" + recipe.Name;
                var library = Library();
                var clip = library.Clips.Find(c => c.name == id) ?? AssetDatabase.LoadAssetAtPath<AnimationClip>(GeneratedRoot + "/" + id + ".anim");
                var contact = family == GestureTag.Facepalm || family == GestureTag.Head_Scratch || family == GestureTag.Thinking;
                var preparation = family==GestureTag.Facepalm?1.55f:contact ? .72f : .58f;
                var stroke = Mathf.Clamp(source.length * .66f, 1.3f, 3f) + (recipe.Beats - 1) * .3f;
                var recovery = family==GestureTag.Facepalm?1.20f:contact ? .95f : .82f;
                var duration = preparation + stroke + recipe.Hold + recovery;
                if (clip == null)
                {
                    clip = Bake(source, family, recipe, preparation, stroke, recovery, duration);
                    clip.name = id;
                    AssetDatabase.AddObjectToAsset(clip, library); library.Clips.Add(clip); EditorUtility.SetDirty(library);
                }
                foreach (var mirror in new[] { false, true })
                {
                    var stateName = "Iris_" + id + (mirror ? "_Left" : "_Right");
                    var state = machine.states.Select(s => s.state).FirstOrDefault(s => s.name == stateName) ?? machine.AddState(stateName);
                    state.motion = clip;
                    state.mirror = mirror ^ SourceIsLeftHanded(family);
                    state.speedParameter = "GesturePlaybackSpeed";
                    state.speedParameterActive = true;
                    state.writeDefaultValues = true;
                    result.Add(new GestureVariant {
                        Id = stateName, PatternId = id, AnimatorState = stateName, LayerName = layerName, Clip = clip,
                        Side = family == GestureTag.Clapping ? GestureSide.Both : mirror ? GestureSide.Left : GestureSide.Right,
                        Channels = ChannelsFor(family), ContactSensitive = contact,
                        LargeMotion = family == GestureTag.Greeting || family == GestureTag.Farewell || family == GestureTag.Clapping || family == GestureTag.Bow || family == GestureTag.Surprise || family == GestureTag.Frustration,
                        PreparationSeconds = preparation, StrokeSeconds = stroke, HoldSeconds = recipe.Hold, RecoverySeconds = recovery,
                        SpeedRange = new Vector2(.92f, 1.08f), IntensityRange = new Vector2(contact ? .85f : .58f, contact ? 1f : .92f),
                        TorsoAccent = new Vector3(family == GestureTag.Bow ? 5.5f : family == GestureTag.Laughing ? 1.5f : .45f,
                            0, mirror ? -recipe.Support * 2.5f : recipe.Support * 2.5f)
                    });
                }
            }
            return result;
        }

        private static MotionChannels ChannelsFor(GestureTag family)
        {
            if (family == GestureTag.Agreement || family == GestureTag.Disagreement) return MotionChannels.Head;
            return MotionChannels.BothArms | (family == GestureTag.Thinking || family == GestureTag.Facepalm || family == GestureTag.Bow || family == GestureTag.Surprise || family == GestureTag.Laughing ? MotionChannels.Head : MotionChannels.None)
                | MotionChannels.Torso;
        }

        private static AnimationClip Bake(AnimationClip source, GestureTag family, Recipe recipe, float prep, float stroke, float recovery, float duration)
        {
            var clip = new AnimationClip { frameRate = 60f, legacy = false };
            var bindings = AnimationUtility.GetCurveBindings(source);
            var contact = family == GestureTag.Facepalm || family == GestureTag.Head_Scratch || family == GestureTag.Thinking;
            // Sample the authored source's complete action, never an arbitrary loop offset.
            foreach (var binding in bindings)
            {
                if (binding.type != typeof(Animator) || !UpperMuscle(binding.propertyName)) continue;
                var original = AnimationUtility.GetEditorCurve(source, binding);
                var curve = new AnimationCurve();
                for (var frame = 0; frame <= Mathf.CeilToInt(duration * 60); frame++)
                {
                    var t = Mathf.Min(duration, frame / 60f);
                    var progress = SourceProgress(t, prep, stroke, recipe.Hold, recovery, recipe.Beats, contact);
                    var value = original.Evaluate(progress * source.length);
                    // Source animation owns the contact stroke. Supporting paths can
                    // differ during approach/release without pulling a palm off the face.
                    var supportSide = SourceIsLeftHanded(family) ? "Right" : "Left";
                    var supportArm = binding.propertyName.StartsWith(supportSide + " Arm") || binding.propertyName.StartsWith(supportSide + " Forearm");
                    var envelope = contact && !supportArm ? ContactApproach(t, prep, stroke, recipe.Hold, duration) : Envelope(t, duration);
                    value += Offset(binding.propertyName, recipe, family) * envelope;
                    // Repeated accents are small, smooth excursions around a
                    // forward-moving action, never reversals of the whole clip.
                    if (!contact && recipe.Beats > 1 && (binding.propertyName == "Right Arm Front-Back" || binding.propertyName == "Right Forearm Stretch"))
                    {
                        var u = Mathf.Clamp01((t - prep) / stroke);
                        value += .035f * Mathf.Sin(u * Mathf.PI * 2 * recipe.Beats) * Mathf.Pow(Mathf.Sin(u * Mathf.PI), 2);
                    }
                    if (binding.propertyName.EndsWith("Forearm Stretch")) value = Mathf.Clamp(value, -.90f, .90f);
                    if (binding.propertyName.EndsWith("Hand Down-Up") || binding.propertyName.EndsWith("Hand In-Out")) value = Mathf.Clamp(value, -.5f, .5f);
                    curve.AddKey(t, Mathf.Clamp(value, -1f, 1f));
                }
                Smooth(curve);
                AnimationUtility.SetEditorCurve(clip, binding, curve);
            }
            if (AnimationUtility.GetCurveBindings(clip).Length == 0)
                throw new InvalidOperationException("Source contains no Humanoid muscle curves: " + source.name);
            // Agreement and disagreement have distinct single/double strokes and
            // supporting tilt rather than six time-scaled copies of one nod.
            if (family == GestureTag.Agreement || family == GestureTag.Disagreement)
            {
                var isNod = family == GestureTag.Agreement;
                var curve = new AnimationCurve();
                for (var frame = 0; frame <= Mathf.CeilToInt(duration * 60); frame++)
                {
                    var t = Mathf.Min(duration, frame / 60f);
                    var u = Mathf.Clamp01((t - prep) / stroke);
                    var accent = Mathf.Sin(u * Mathf.PI * 2f * recipe.Beats) * Mathf.Sin(u * Mathf.PI);
                    curve.AddKey(t, accent * (isNod ? .13f : .18f));
                }
                Smooth(curve);
                AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve("", typeof(Animator), isNod ? "Head Nod Down-Up" : "Head Turn Left-Right"), curve);
            }
            var clipSettings = AnimationUtility.GetAnimationClipSettings(clip);
            clipSettings.loopTime = false;
            clipSettings.stopTime = duration;
            AnimationUtility.SetAnimationClipSettings(clip, clipSettings);
            return clip;
        }

        private static bool UpperMuscle(string name)
        {
            if (name.StartsWith("Root") || name.StartsWith("Motion") || name.Contains("Leg") || name.Contains("Foot") || name.Contains("Toes")) return false;
            return HumanTrait.MuscleName.Contains(name) || name.StartsWith("LeftHand.") || name.StartsWith("RightHand.");
        }
        private static void Smooth(AnimationCurve curve)
        {
            // Keep authored trajectories, without checking millions of redundant
            // sampled keys into source control (maximum normalized error .0015).
            var samples = curve.keys;
            var keep = new SortedSet<int> { 0, samples.Length - 1 };
            Reduce(samples, 0, samples.Length - 1, keep);
            curve.keys = keep.Select(i => samples[i]).ToArray();
            for (var i = 0; i < curve.length; i++)
            {
                AnimationUtility.SetKeyLeftTangentMode(curve, i, AnimationUtility.TangentMode.ClampedAuto);
                AnimationUtility.SetKeyRightTangentMode(curve, i, AnimationUtility.TangentMode.ClampedAuto);
            }
            var first = curve[0]; first.inTangent = first.outTangent = 0; curve.MoveKey(0, first);
            var last = curve[curve.length - 1]; last.inTangent = last.outTangent = 0; curve.MoveKey(curve.length - 1, last);
        }
        private static void Reduce(Keyframe[] keys, int first, int last, ISet<int> keep)
        {
            if (last - first < 2) return;
            var maximum = .0015f; var index = -1;
            for (var i = first + 1; i < last; i++)
            {
                var u = (keys[i].time - keys[first].time) / Mathf.Max(.00001f, keys[last].time - keys[first].time);
                var error = Mathf.Abs(keys[i].value - Mathf.Lerp(keys[first].value, keys[last].value, u));
                if (error > maximum) { maximum = error; index = i; }
            }
            if (index < 0) return;
            keep.Add(index); Reduce(keys, first, index, keep); Reduce(keys, index, last, keep);
        }
        private static float Envelope(float t, float duration) => Mathf.Pow(Mathf.Sin(Mathf.PI * Mathf.Clamp01(t / duration)), 2);
        private static float ContactApproach(float t, float prep, float stroke, float hold, float duration)
        {
            if (t < prep) return Mathf.Pow(Mathf.Sin(Mathf.PI * t / prep), 2);
            if (t > prep + stroke + hold) return Mathf.Pow(Mathf.Sin(Mathf.PI * (t - prep - stroke - hold) / Mathf.Max(.01f, duration - prep - stroke - hold)), 2);
            return 0f;
        }
        private static float SourceProgress(float t, float prep, float stroke, float hold, float recovery, int beats, bool contact)
        {
            var approach = contact ? .20f : .12f;
            if (t < prep) return Mathf.Lerp(0, approach, Ease(t / prep));
            var u = (t - prep) / stroke;
            if (u < 1f)
            {
                return Mathf.Lerp(approach, .78f, Ease(u));
            }
            if (t < prep + stroke + hold) return .78f;
            return Mathf.Lerp(.78f, 1f, Ease((t - prep - stroke - hold) / recovery));
        }
        private static float Ease(float t) { t = Mathf.Clamp01(t); return t * t * t * (t * (t * 6 - 15) + 10); }
        private static float Offset(string muscle, Recipe recipe, GestureTag family)
        {
            // Normalized Humanoid muscles retarget to Iris's proportions.
            switch (muscle)
            {
                case "Right Arm Down-Up": return recipe.ArmLift;
                case "Right Arm Front-Back": return recipe.ArmReach;
                case "Right Forearm Stretch": return recipe.Elbow;
                case "Right Hand Down-Up": return recipe.Wrist * .35f;
                case "Right Forearm Twist In-Out": return recipe.Turns * .45f;
                case "Left Arm Down-Up": return recipe.Support;
                case "Left Arm Front-Back": return -recipe.Support * .5f;
                case "Left Forearm Stretch": return recipe.Support * .7f;
                case "Head Tilt Left-Right": return recipe.HeadTilt;
                default: return 0f;
            }
        }

        private static Recipe[] Recipes(GestureTag family)
        {
            switch (family)
            {
                case GestureTag.Talk: return new[] {
                    new Recipe("open_palm", .10f,-.08f,-.08f,.13f,-.04f,.015f),
                    new Recipe("measured_beat", -.08f,.12f,.12f,-.09f,-.10f,0),
                    new Recipe("two_points", .03f,-.04f,.04f,.06f,-.05f,0,2),
                    new Recipe("inclusive", .13f,.10f,-.13f,.08f,.14f,-.015f),
                    new Recipe("low_sweep", -.17f,-.12f,-.15f,-.06f,-.12f,.025f),
                    new Recipe("weighing", .05f,.14f,.08f,.14f,.12f,-.025f,2),
                    new Recipe("precision", -.05f,.16f,.18f,-.12f,-.15f,.01f,1,.28f,.12f),
                    new Recipe("hand_to_self", -.02f,-.18f,.20f,.06f,-.08f,-.02f,1,.3f,-.10f) };
                case GestureTag.Question: return new[] {
                    new Recipe("palm_up", .08f,-.08f,.06f,.18f,-.10f,-.035f),
                    new Recipe("both_palms", .13f,.08f,-.08f,.16f,.18f,.025f),
                    new Recipe("half_shrug", .20f,.12f,.16f,.12f,-.13f,-.05f,1,.28f),
                    new Recipe("offer", -.10f,-.18f,-.20f,.06f,-.06f,.015f),
                    new Recipe("to_self", -.05f,-.14f,.24f,-.06f,-.10f,-.025f),
                    new Recipe("alternatives", .07f,.15f,-.12f,.13f,.16f,.025f,2),
                    new Recipe("small_tilt", -.16f,.07f,.20f,-.10f,-.16f,-.065f),
                    new Recipe("clarify", .02f,.20f,.13f,-.15f,-.09f,.035f,2,.2f,.10f) };
                case GestureTag.Explanation: return new[] {
                    new Recipe("present", .08f,-.15f,-.16f,.12f,-.10f,.01f),
                    new Recipe("enumerate", -.04f,.10f,.13f,-.08f,-.08f,0,3),
                    new Recipe("compare", .13f,.10f,-.13f,.10f,.18f,-.02f,2),
                    new Recipe("underline", -.13f,.16f,.08f,-.15f,-.10f,.02f),
                    new Recipe("expand", .20f,-.08f,-.21f,.04f,.20f,0),
                    new Recipe("detail", -.07f,.18f,.25f,-.10f,-.16f,-.015f,1,.28f,.12f),
                    new Recipe("sequence", .02f,-.05f,-.06f,.14f,.05f,.01f,2),
                    new Recipe("conclude", -.15f,.04f,.17f,.06f,-.08f,.03f,1,.35f) };
                case GestureTag.Thinking: return new[] {
                    new Recipe("chin_pause", 0,0,0,0,-.10f,-.02f,1,.5f),
                    new Recipe("elbow_support", .04f,-.07f,.10f,.06f,.22f,.01f,1,.65f),
                    new Recipe("brief_reflection", -.10f,.10f,.12f,-.08f,-.17f,-.045f,1,.1f),
                    new Recipe("inclined", .06f,-.13f,.08f,.10f,-.04f,.065f,1,.45f),
                    new Recipe("consider_then_release", -.06f,.12f,-.10f,-.09f,-.12f,-.035f,1,.25f),
                    new Recipe("temple_approach", .15f,.07f,.14f,-.12f,-.06f,.035f,1,.4f),
                    new Recipe("folded_support", .02f,-.16f,.16f,.06f,.28f,-.02f,1,.55f),
                    new Recipe("quiet_realization", -.13f,.02f,.06f,.12f,-.18f,.025f,1,.15f) };
                case GestureTag.Agreement: return new[] {
                    new Recipe("single",0,0,0,0,0,0), new Recipe("double",0,0,0,0,0,.015f,2),
                    new Recipe("inclined",0,0,0,0,0,.07f,1,.3f), new Recipe("assured",0,0,0,0,0,-.04f,2,.25f),
                    new Recipe("thankful",0,0,0,0,0,-.015f,1,.55f), new Recipe("small_bow",0,0,0,0,0,.035f,1,.35f) };
                case GestureTag.Disagreement: return new[] {
                    new Recipe("single",0,0,0,0,0,0), new Recipe("double",0,0,0,0,0,0,2),
                    new Recipe("skeptical",0,0,0,0,0,.075f,1,.4f), new Recipe("averted",0,0,0,0,0,-.06f,1,.3f),
                    new Recipe("firm",0,0,0,0,0,-.025f,2,.25f), new Recipe("soft",0,0,0,0,0,.035f,1,.5f) };
                case GestureTag.Greeting: case GestureTag.Farewell: return new[] {
                    new Recipe("open_wave", .07f,-.04f,-.05f,.06f,-.10f,.02f),
                    new Recipe("wrist_wave", -.14f,.10f,.20f,.18f,-.15f,0,2),
                    new Recipe("double_wave", .03f,.06f,.02f,.10f,-.05f,-.015f,2),
                    new Recipe("low_wave", -.23f,-.06f,-.12f,.12f,-.14f,.025f),
                    new Recipe("greet_and_tilt", .10f,-.12f,.12f,-.08f,-.08f,-.065f,1,.3f),
                    new Recipe("palm_salute", .16f,.12f,.17f,-.12f,-.10f,.02f,1,.45f,.12f) };
                case GestureTag.Shrug: return new[] {
                    new Recipe("both_palms", .10f,-.08f,-.08f,.15f,.12f,.02f),
                    new Recipe("one_palm", .15f,.10f,.10f,.14f,-.24f,-.045f),
                    new Recipe("low_open", -.17f,-.16f,-.18f,.10f,-.10f,.035f),
                    new Recipe("small_shoulders", -.22f,.13f,.23f,-.10f,-.20f,-.02f),
                    new Recipe("alternating", .07f,.16f,-.04f,.12f,.17f,.05f,2),
                    new Recipe("resigned", -.10f,-.10f,.10f,-.14f,-.06f,-.06f,1,.45f) };
                default: return new[] {
                    new Recipe("direct", .04f,-.04f,.04f,.04f,-.08f,.01f,1,.2f),
                    new Recipe("supported", .08f,-.12f,.10f,.10f,.22f,-.025f,1,.4f),
                    new Recipe("brief", -.13f,.14f,.17f,-.10f,-.20f,.035f,1,.05f),
                    new Recipe("inclined", .16f,.08f,-.10f,.13f,-.10f,-.065f,1,.25f),
                    new Recipe("two_stage", -.06f,-.16f,.12f,-.12f,.10f,.045f,2,.15f),
                    new Recipe("settled", -.17f,.06f,-.13f,.06f,-.13f,-.03f,1,.55f,-.10f) };
            }
        }
    }
}
