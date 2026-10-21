using UnityEngine;

namespace NeuroAsist.Avatar
{
    /// <summary>Softens the native portrait's sides and top, preserving its dock contact.</summary>
    [DisallowMultipleComponent, RequireComponent(typeof(Camera))]
    public sealed class AvatarEdgeFeather : MonoBehaviour
    {
        private Material material;

        private void OnEnable()
        {
            var shader = Resources.Load<Shader>("AvatarEdgeFeather");
            if (shader == null || !shader.isSupported)
            {
                Debug.LogError("[AvatarEdgeFeather] Portrait edge shader is unavailable.", this);
                enabled = false;
                return;
            }
            material = new Material(shader) { hideFlags = HideFlags.HideAndDontSave };
        }

        private void OnRenderImage(RenderTexture source, RenderTexture destination)
        {
            if (material == null) Graphics.Blit(source, destination);
            else Graphics.Blit(source, destination, material);
        }

        private void OnDisable()
        {
            if (material == null) return;
            if (Application.isPlaying) Destroy(material);
            else DestroyImmediate(material);
            material = null;
        }
    }
}
