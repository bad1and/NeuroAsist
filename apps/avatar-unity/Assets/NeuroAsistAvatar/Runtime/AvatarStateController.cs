using System;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    public enum AvatarState { Disconnected, Idle, Listening, Thinking, Downloading, Speaking, Error }
    public sealed class AvatarStateController : MonoBehaviour
    {
        public AvatarState Current { get; private set; } = AvatarState.Disconnected;
        public event Action<AvatarState> Changed;
        [SerializeField] private AvatarWebSocketClient client;
        public void SetState(AvatarState value, bool report = true)
        {
            if (Current == value) return;
            Current = value;
            Changed?.Invoke(value);
            if (report && client != null) client.SendState(value.ToString());
        }
        public void SetClient(AvatarWebSocketClient value) => client = value;
    }
}
