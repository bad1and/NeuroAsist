# Iris Unity Avatar

The standalone Windows renderer uses the `IRIS.vrm` character and connects to the desktop core through the Avatar WebSocket v2 protocol.

The renderer is optional: text and voice work without it. Tauri can present
it inside the dialogue or as a separate desktop overlay; placement and controls
are described in the [desktop guide](../desktop/README.md#avatar-placement).
[Hardware requirements](../../Docs/system-requirements.md) include the reference
GPU; a minimum GPU for this avatar has not been measured.

Its release metadata mirrors Iris `0.9.1`: product `Iris Avatar`, company
`NeuroAsist`, and application identifier `com.neuroasist.avatar`. The root
documentation check prevents version drift.

The public checkout excludes the VRM and restricted animation inputs. Official
Unity builds run in `Gogowski/NeuroAsist-avatar-private` from a reviewed public
commit. See the [split build guide](../../Docs/avatar-distribution.md) for private
input import, Player packaging and public application assembly.

With authorized private inputs imported into an isolated checkout, build it
from the repository root with Unity 2022.3.62f3 and the
Windows Build Support (Mono) module. The built executable is absent from a
clean clone; the editor is required for the first build and later rebuilds,
not for running the finished renderer. Close the editor and running avatar
before the build:

```powershell
$env:NEUROASIST_UNITY_EDITOR = 'C:\Program Files\Unity\Hub\Editor\2022.3.62f3\Editor\Unity.exe'
.\apps\avatar-unity\scripts\build-windows.ps1
```

The output is `apps\avatar-unity\Builds\NeuroAsistAvatar\NeuroAsistAvatar.exe`. It is intentionally ignored by Git. Tauri discovers this local build and passes the loopback backend URL and short-lived authentication token at launch; starting the player from the Unity editor continues to use the settings asset's local fallback.

The code license does not grant redistribution rights for `IRIS.vrm` or the
included animations. Their origin and unresolved release conditions are in
[third-party assets](../../THIRD_PARTY_ASSETS.md).
