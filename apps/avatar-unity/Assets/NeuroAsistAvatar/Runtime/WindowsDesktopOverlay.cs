using System;
using System.Runtime.InteropServices;
using System.Text;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    /// <summary>Windows-only overlay shell. It deliberately falls back to a normal borderless player if DWM cannot enable transparency.</summary>
    public sealed class WindowsDesktopOverlay : MonoBehaviour
    {
        [SerializeField] private bool visible = true;
        [SerializeField] private bool alwaysOnTop = true;
        [SerializeField] private bool locked = true;
        [SerializeField] private float scale = 1f;
        [SerializeField] private AvatarWebSocketClient client;
        private IntPtr handle;
        private Rect lastBounds;
        private float nextBoundsReportAt;
        private bool embeddedInIris;
        private bool initialized;
        private bool currentClickThrough;

        private const int GWL_STYLE = -16;
        private const int GWL_EXSTYLE = -20;
        private const int WS_POPUP = unchecked((int)0x80000000);
        private const int WS_EX_LAYERED = 0x00080000;
        private const int WS_EX_TRANSPARENT = 0x00000020;
        private const uint LWA_COLORKEY = 0x00000001;
        private const uint SWP_NOSIZE = 0x0001;
        private const uint SWP_NOMOVE = 0x0002;
        private const uint SWP_NOACTIVATE = 0x0010;
        private static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
        private static readonly IntPtr HWND_NOTOPMOST = new IntPtr(-2);

        private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

        private void Awake()
        {
            if (Application.isEditor || Application.platform != RuntimePlatform.WindowsPlayer) return;
            embeddedInIris = IsEmbeddedHost(Environment.GetEnvironmentVariable("NEUROASIST_AVATAR_HOST"));
            // In the in-app mode Tauri owns the exact Unity HWND. GetActiveWindow
            // is unreliable while a player starts hidden or loses activation to
            // Iris, so this component must not alter native styles at all.
            if (embeddedInIris) return;
            InitializeWindow();
        }

        private void Update()
        {
            if (embeddedInIris) return;
            if (Application.platform != RuntimePlatform.WindowsPlayer) return;
            if (!initialized) InitializeWindow();
            if (handle == IntPtr.Zero) return;
            // Holding Ctrl+Alt temporarily makes the overlay interactive for drag/repositioning.
            var dragMode = (GetAsyncKeyState(0x11) & 0x8000) != 0 && (GetAsyncKeyState(0x12) & 0x8000) != 0;
            SetClickThrough(locked && !dragMode);
            if (dragMode && Input.GetMouseButtonDown(0)) { ReleaseCapture(); SendMessage(handle, 0xA1, new IntPtr(2), IntPtr.Zero); }
            if (Time.unscaledTime >= nextBoundsReportAt) { nextBoundsReportAt = Time.unscaledTime + 1f; ReportBoundsIfChanged(); }
        }

        public void Configure(bool nextVisible, bool nextAlwaysOnTop, bool nextLocked, float nextScale, string monitor, float x, float y, float width, float height)
        {
            visible = nextVisible;
            alwaysOnTop = nextAlwaysOnTop;
            locked = nextLocked;
            scale = Mathf.Clamp(nextScale, .5f, 2f);
            transform.localScale = Vector3.one * scale;
            if (embeddedInIris) return;
            if (!initialized) InitializeWindow();
            if (handle == IntPtr.Zero) return;
            ApplyWindowFlags();
            if (width > 0 && height > 0) SetWindowPos(handle, alwaysOnTop ? HWND_TOPMOST : HWND_NOTOPMOST, Mathf.RoundToInt(x), Mathf.RoundToInt(y), Mathf.RoundToInt(width), Mathf.RoundToInt(height), SWP_NOACTIVATE);
            SetVisible(visible);
        }

        private bool EnsureHandle()
        {
            if (handle != IntPtr.Zero) return true;
            handle = GetActiveWindow();
            if (handle != IntPtr.Zero) return true;

            var currentPid = GetCurrentProcessId();
            var candidate = IntPtr.Zero;
            var sb = new StringBuilder(128);
            EnumWindows((hWnd, lParam) =>
            {
                GetWindowThreadProcessId(hWnd, out var pid);
                if (pid == currentPid)
                {
                    sb.Clear();
                    GetClassName(hWnd, sb, sb.Capacity);
                    if (sb.ToString().Contains("UnityWndClass"))
                    {
                        candidate = hWnd;
                        return false;
                    }
                }
                return true;
            }, IntPtr.Zero);

            handle = candidate;
            return handle != IntPtr.Zero;
        }

        private void InitializeWindow()
        {
            if (initialized || !EnsureHandle()) return;
            if (client == null) client = GetComponent<AvatarWebSocketClient>();
            SetWindowLong(handle, GWL_STYLE, WS_POPUP);
            ApplyWindowFlags();
            SetVisible(visible);
            initialized = true;
        }

        private void ApplyWindowFlags()
        {
            if (handle == IntPtr.Zero) return;
            SetWindowLong(handle, GWL_EXSTYLE, GetWindowLong(handle, GWL_EXSTYLE) | WS_EX_LAYERED);
            // Matches the canonical scene camera background (49, 77, 121). Windows removes that
            // colour from the layered window; if the call fails, the player remains borderless.
            SetLayeredWindowAttributes(handle, (uint)(49 | (77 << 8) | (121 << 16)), 0, LWA_COLORKEY);
            currentClickThrough = false;
            SetClickThrough(locked);
            SetWindowPos(handle, alwaysOnTop ? HWND_TOPMOST : HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
        }

        public static bool IsEmbeddedHost(string host)
        {
            return string.Equals(host, "embedded", StringComparison.OrdinalIgnoreCase);
        }

        private void SetClickThrough(bool enabled)
        {
            if (handle == IntPtr.Zero) return;
            if (currentClickThrough == enabled && initialized) return;
            currentClickThrough = enabled;
            var style = GetWindowLong(handle, GWL_EXSTYLE) | WS_EX_LAYERED;
            SetWindowLong(handle, GWL_EXSTYLE, enabled ? style | WS_EX_TRANSPARENT : style & ~WS_EX_TRANSPARENT);
        }

        private void SetVisible(bool value)
        {
            if (handle != IntPtr.Zero) ShowWindow(handle, value ? 5 : 0);
        }

        private void ReportBoundsIfChanged()
        {
            if (client == null || !GetWindowRect(handle, out var rect)) return;
            var bounds = new Rect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top);
            if ((bounds.position - lastBounds.position).sqrMagnitude < 1f && (bounds.size - lastBounds.size).sqrMagnitude < 1f) return;
            lastBounds = bounds;
            client.SendOverlayBounds(bounds.x, bounds.y, bounds.width, bounds.height);
        }

        [DllImport("user32.dll")] private static extern IntPtr GetActiveWindow();
        [DllImport("user32.dll", SetLastError = true)] private static extern int GetWindowLong(IntPtr hWnd, int nIndex);
        [DllImport("user32.dll", SetLastError = true)] private static extern int SetWindowLong(IntPtr hWnd, int nIndex, int value);
        [DllImport("user32.dll", SetLastError = true)] private static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int x, int y, int cx, int cy, uint flags);
        [DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
        [DllImport("user32.dll", SetLastError = true)] private static extern bool SetLayeredWindowAttributes(IntPtr hwnd, uint crKey, byte bAlpha, uint dwFlags);
        [DllImport("user32.dll")] private static extern short GetAsyncKeyState(int vKey);
        [DllImport("user32.dll")] private static extern bool ReleaseCapture();
        [DllImport("user32.dll")] private static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, IntPtr lParam);
        [DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr hWnd, out NativeRect rect);
        [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
        [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
        [DllImport("user32.dll", CharSet = CharSet.Auto, SetLastError = true)] private static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);
        [DllImport("kernel32.dll")] private static extern uint GetCurrentProcessId();
        [StructLayout(LayoutKind.Sequential)] private struct NativeRect { public int left; public int top; public int right; public int bottom; }
    }
}
