using System;
using System.Linq;
using NeuroAsist.Avatar;
using UnityEditor;
using UnityEngine;

namespace NeuroAsist.AvatarEditor
{
    /// <summary>Explicit, idempotent retiming of our generated face contacts; preserves poses and references.</summary>
    public static class AvatarContactTiming
    {
        [MenuItem("Iris/Avatar/Refine Face Contact Timing")]
        public static void Refine()
        {
            var settings=AssetDatabase.LoadAssetAtPath<AvatarMotionSettings>(AvatarMotionSetup.SettingsPath);
            var definitions=settings.GestureDefinitions.Where(d=>d!=null).ToArray();
            var variants=definitions.SelectMany(d=>d.Variants).Where(v=>v.Clip!=null).ToArray();
            var changed=0;
            foreach(var group in variants.Where(v=>v.PatternId.StartsWith("Facepalm_",StringComparison.Ordinal)) .GroupBy(v=>v.Clip))
            {
                var clip=group.Key;
                if(AssetDatabase.GetAssetPath(clip)!=AvatarGestureLibrary.GeneratedRoot+"/Performances.asset")continue;
                var old=group.First();var prep=old.PreparationSeconds;var recovery=old.RecoverySeconds;
                var newPrep=Mathf.Max(prep,1.55f);var newRecovery=Mathf.Max(recovery,1.20f);
                if(Mathf.Abs(newPrep-prep)<.001f && Mathf.Abs(newRecovery-recovery)<.001f)continue;
                var length=old.Duration;var end=length-recovery;var newLength=length+newPrep-prep+newRecovery-recovery;
                foreach(var binding in AnimationUtility.GetCurveBindings(clip))
                {
                    var curve=AnimationUtility.GetEditorCurve(clip,binding);var keys=curve.keys;
                    for(var i=0;i<keys.Length;i++)
                    {
                        var key=keys[i];var t=key.time;
                        var rate=t<=prep?prep/newPrep:t>=end?recovery/newRecovery:1;
                        key.time=t<=prep?t*newPrep/prep:t>=end?end+newPrep-prep+(t-end)*newRecovery/recovery:t+newPrep-prep;
                        key.inTangent*=rate;key.outTangent*=rate;keys[i]=key;
                    }
                    curve.keys=keys;AnimationUtility.SetEditorCurve(clip,binding,curve);
                }
                var clipSettings=AnimationUtility.GetAnimationClipSettings(clip);clipSettings.stopTime=newLength;
                AnimationUtility.SetAnimationClipSettings(clip,clipSettings);
                foreach(var variant in variants.Where(v=>v.Clip==clip))
                {variant.PreparationSeconds=newPrep;variant.RecoverySeconds=newRecovery;}
                EditorUtility.SetDirty(clip);changed++;
            }
            foreach(var definition in definitions)EditorUtility.SetDirty(definition);
            AssetDatabase.SaveAssets();Debug.Log($"[ContactTiming] Retimed {changed} generated face contacts; key poses and local file IDs retained.");
        }
    }
}
