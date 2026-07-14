# NeuroAsist Unity Avatar

The standalone Windows renderer uses the `Liqu.vrm` character and connects to the desktop core through the Avatar WebSocket v2 protocol.

Build it with Unity 2022.3.62f3:

```powershell
$env:NEUROASIST_UNITY_EDITOR = 'C:\Program Files\Unity\Hub\Editor\2022.3.62f3\Editor\Unity.exe'
.\apps\avatar-unity\scripts\build-windows.ps1
```

The output is `Builds\NeuroAsistAvatar\NeuroAsistAvatar.exe`. It is intentionally ignored by Git. Tauri passes the loopback backend URL and short-lived authentication token at launch; starting the player from the Unity editor continues to use the settings asset's local fallback.
