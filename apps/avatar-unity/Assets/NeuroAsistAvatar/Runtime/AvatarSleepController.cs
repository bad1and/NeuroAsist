using UnityEngine;

namespace NeuroAsist.Avatar
{
    /// <summary>
    /// Manages the avatar sleep/wake lifecycle.
    /// When inactive (not visible in the chat tab, or when navigating away to other tabs):
    /// - Disables camera rendering (0 draw calls, 0% GPU usage).
    /// - Sets Time.timeScale to 0 (pauses animations, physics, and procedural motion).
    /// - Sets targetFrameRate to 30 FPS (avoids starving the Win32 message pump, guarantees instant <33ms response).
    /// When waking up:
    /// - Instantly restores 60 FPS, Time.timeScale to 1, and re-enables camera rendering with 0 reload latency.
    /// </summary>
    public sealed class AvatarSleepController : MonoBehaviour
    {
        public const int SleepFrameRate = 30;
        public const int AwakeFrameRate = 60;

        [SerializeField] private Camera avatarCamera;
        [SerializeField] private AvatarSpeechCoordinator speech;
        [SerializeField] private AvatarWebSocketClient client;

        private bool isSleeping;

        public bool IsSleeping => isSleeping;

        private void Awake()
        {
            if (avatarCamera == null)
            {
                avatarCamera = Camera.main;
            }
        }

        private void Start()
        {
            if (avatarCamera == null)
            {
                avatarCamera = Camera.main;
            }
            if (speech == null)
            {
                speech = GetComponent<AvatarSpeechCoordinator>();
            }
            if (client == null)
            {
                client = GetComponent<AvatarWebSocketClient>();
            }
        }

        public void Configure(Camera cam, AvatarSpeechCoordinator speechCoordinator, AvatarWebSocketClient wsClient)
        {
            avatarCamera = cam != null ? cam : Camera.main;
            speech = speechCoordinator;
            client = wsClient;
        }

        public void SetSleeping(bool sleep)
        {
            if (isSleeping == sleep) return;
            isSleeping = sleep;

            if (avatarCamera == null)
            {
                avatarCamera = Camera.main;
            }

            if (isSleeping)
            {
                EnterSleep();
            }
            else
            {
                WakeUp();
            }
        }

        private void EnterSleep()
        {
            if (avatarCamera != null)
            {
                avatarCamera.enabled = false;
            }
            Time.timeScale = 0f;
            QualitySettings.vSyncCount = 0;
            Application.targetFrameRate = SleepFrameRate;

            if (speech != null)
            {
                speech.Stop(null);
            }

            Debug.Log("[AvatarSleep] Avatar entered sleep mode (Camera disabled, targetFrameRate = " + SleepFrameRate + ")");
        }

        private void WakeUp()
        {
            QualitySettings.vSyncCount = 0;
            Application.targetFrameRate = AwakeFrameRate;
            Time.timeScale = 1f;

            if (avatarCamera != null)
            {
                avatarCamera.enabled = true;
            }

            Debug.Log("[AvatarSleep] Avatar woke up (Camera enabled, targetFrameRate = " + AwakeFrameRate + ")");
        }
    }
}
