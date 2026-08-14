use std::{
    env,
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::PathBuf,
    process::{Child, Command},
    sync::{
        atomic::{AtomicU64, Ordering},
        Mutex,
    },
    thread,
    time::Duration,
};

use keyring::Entry;
use serde::{Deserialize, Serialize};
use tauri::{
    menu::{MenuBuilder, MenuItemBuilder},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent,
};
use tauri_plugin_global_shortcut::ShortcutState;

#[cfg(windows)]
use windows::core::BOOL;
#[cfg(windows)]
use windows::Win32::{
    Foundation::{COLORREF, HWND, LPARAM, POINT},
    Graphics::Gdi::ClientToScreen,
    UI::WindowsAndMessaging::{
        EnumWindows, GetClassNameW, GetParent, GetWindowLongPtrW, GetWindowThreadProcessId,
        SetLayeredWindowAttributes, SetParent, SetWindowLongPtrW, SetWindowPos, ShowWindow,
        GWLP_HWNDPARENT, GWLP_USERDATA, GWL_EXSTYLE, GWL_STYLE, HWND_TOP, LWA_COLORKEY,
        SWP_ASYNCWINDOWPOS, SWP_FRAMECHANGED, SWP_NOACTIVATE, SWP_NOSIZE, SWP_NOZORDER, SW_HIDE,
        SW_SHOWNA, WS_EX_LAYERED, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TRANSPARENT, WS_POPUP,
    },
};

const CORE_STARTUP_ATTEMPTS: u8 = 60;
const CORE_STARTUP_DELAY: Duration = Duration::from_millis(250);
// A cold Unity start loads Mono, D3D and the VRM scene before it creates the
// player HWND. On the target machine this takes about fourteen seconds; five
// seconds caused the desktop shell to kill a healthy player before it could
// attach to the chat host.
#[cfg(windows)]
const UNITY_WINDOW_DISCOVERY_TIMEOUT: Duration = Duration::from_secs(30);
#[cfg(windows)]
const UNITY_GRAPHICS_READY_TIMEOUT: Duration = Duration::from_secs(15);
#[cfg(windows)]
const UNITY_WINDOW_POLL_INTERVAL: Duration = Duration::from_millis(50);
const KEYRING_SERVICE: &str = "NeuroAsist";
const KEYRING_ACCOUNT: &str = "deepseek_api_key";
// Matches the embedded Unity camera clear colour (#1d2022). A neutral matte
// makes the unavoidable colour-key transition much less visible at hair and
// clothing edges than the previous saturated blue key.
#[cfg(windows)]
const EMBEDDED_AVATAR_COLOR_KEY: COLORREF = COLORREF(29 | (32 << 8) | (34 << 16));

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum AvatarPlacement {
    DesktopOverlay,
    InApp,
}

impl Default for AvatarPlacement {
    fn default() -> Self {
        Self::DesktopOverlay
    }
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AvatarInAppBounds {
    x: i32,
    y: i32,
    width: i32,
    height: i32,
    revision: u64,
}

#[derive(Clone)]
struct AvatarInAppVisibility {
    visible: bool,
    revision: u64,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct AvatarHostStatus {
    placement: AvatarPlacement,
    running: bool,
    embedded: bool,
    visible: bool,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopRuntime {
    api_base_url: String,
    api_token: String,
    ws_events_url: String,
    safe_mode: bool,
    core_status: String,
}

struct DesktopState {
    root: PathBuf,
    safe_mode: bool,
    runtime: Mutex<DesktopRuntime>,
    core: Mutex<Option<CoreProcess>>,
    avatar: Mutex<Option<AvatarProcess>>,
    // Serializes every transition that creates or kills Unity. Without this,
    // two settings updates can both observe `None` and start two players.
    avatar_lifecycle: Mutex<()>,
    in_app_avatar_bounds: Mutex<Option<AvatarInAppBounds>>,
    // `None` means the React chat host has not reported yet.  Keeping this
    // separate from the desktop-overlay preference avoids a late startup
    // replacing a real `false` request with the persisted default.
    in_app_avatar_visible: Mutex<Option<AvatarInAppVisibility>>,
    // Bounds and visibility travel over separate asynchronous IPC calls. The
    // shared revision makes late messages from an old chat host harmless.
    in_app_avatar_revision: Mutex<u64>,
    in_app_avatar_update: Mutex<()>,
    avatar_visible: Mutex<bool>,
    crash_restarts: Mutex<u8>,
    core_generation: AtomicU64,
}

enum CoreProcess {
    Native(Child),
}

struct AvatarProcess {
    child: Child,
    placement: AvatarPlacement,
    // HWND is stored as an integer to keep the state platform-neutral. It is
    // present only for the Windows-owned surface used by the in-app mode.
    embedded_window: Option<usize>,
}

impl DesktopState {
    fn new() -> Self {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .ancestors()
            .nth(3)
            .expect("desktop source must be nested below the repository root")
            .to_path_buf();
        let port = available_loopback_port();
        let token = random_token();
        let api_base_url = format!("http://127.0.0.1:{port}");
        Self {
            root,
            safe_mode: env::args().any(|arg| arg == "--safe-mode"),
            runtime: Mutex::new(DesktopRuntime {
                ws_events_url: format!("ws://127.0.0.1:{port}/ws/events?token={token}"),
                api_base_url,
                api_token: token,
                safe_mode: env::args().any(|arg| arg == "--safe-mode"),
                core_status: "starting".into(),
            }),
            core: Mutex::new(None),
            avatar: Mutex::new(None),
            avatar_lifecycle: Mutex::new(()),
            in_app_avatar_bounds: Mutex::new(None),
            in_app_avatar_visible: Mutex::new(None),
            in_app_avatar_revision: Mutex::new(0),
            in_app_avatar_update: Mutex::new(()),
            avatar_visible: Mutex::new(true),
            crash_restarts: Mutex::new(0),
            core_generation: AtomicU64::new(0),
        }
    }

    fn runtime(&self) -> DesktopRuntime {
        self.runtime.lock().expect("runtime mutex poisoned").clone()
    }

    fn set_core_status(&self, app: &AppHandle, value: &str) {
        self.runtime
            .lock()
            .expect("runtime mutex poisoned")
            .core_status = value.into();
        let _ = app.emit("desktop-core-status", value);
    }

    fn start_core(&self, app: &AppHandle) -> Result<(), String> {
        if self
            .core
            .lock()
            .map_err(|_| "core mutex poisoned")?
            .is_some()
        {
            return Ok(());
        }
        self.set_core_status(app, "starting");
        let generation = self.core_generation.fetch_add(1, Ordering::SeqCst) + 1;
        let runtime = self.runtime();
        let data_root = desktop_data_root(&self.root);
        std::fs::create_dir_all(&data_root)
            .map_err(|error| format!("Could not create Iris data directory: {error}"))?;
        let port = runtime.api_base_url.rsplit(':').next().unwrap_or("8000");
        let api_key = read_api_key()?;
        let avatar_enabled = self.avatar_executable(app).is_some() && !self.safe_mode;
        let process =
            if cfg!(debug_assertions) || env::var_os("NEUROASIST_CORE_EXECUTABLE").is_some() {
                let mut command = core_command(&self.root)?;
                configure_core_command(
                    &mut command,
                    &self.root,
                    &data_root,
                    port,
                    &runtime.api_token,
                    self.safe_mode,
                    avatar_enabled,
                    api_key.as_deref(),
                );
                CoreProcess::Native(
                    command
                        .spawn()
                        .map_err(|error| format!("Could not start Neuro Core: {error}"))?,
                )
            } else {
                let executable = app
                    .path()
                    .resource_dir()
                    .map_err(|error| format!("Could not resolve Iris resources: {error}"))?
                    .join("core")
                    .join("neuroasist-core.exe");
                if !executable.exists() {
                    return Err(format!(
                        "Bundled Neuro Core is missing: {}",
                        executable.display()
                    ));
                }
                let mut command = Command::new(&executable);
                configure_core_command(
                    &mut command,
                    &self.root,
                    &data_root,
                    port,
                    &runtime.api_token,
                    self.safe_mode,
                    avatar_enabled,
                    api_key.as_deref(),
                );
                // PyInstaller onedir resolves its bundled DLLs relative to
                // the resource directory. The source checkout root is only
                // valid for the development Python launcher.
                if let Some(resource_root) = executable.parent() {
                    command.current_dir(resource_root);
                }
                let child = command
                    .spawn()
                    .map_err(|error| format!("Could not start bundled Neuro Core: {error}"))?;
                CoreProcess::Native(child)
            };
        *self.core.lock().map_err(|_| "core mutex poisoned")? = Some(process);

        for _ in 0..CORE_STARTUP_ATTEMPTS {
            if core_health_is_ready(&runtime) {
                self.set_core_status(app, "ready");
                self.watch_core(app.clone(), generation);
                return Ok(());
            }
            if self.core_exited()? {
                self.set_core_status(app, "failed");
                return Err("Neuro Core exited before its health check completed".into());
            }
            thread::sleep(CORE_STARTUP_DELAY);
        }
        self.stop_core();
        self.set_core_status(app, "failed");
        Err("Neuro Core did not become healthy within 15 seconds".into())
    }

    fn watch_core(&self, app: AppHandle, generation: u64) {
        thread::spawn(move || loop {
            thread::sleep(Duration::from_secs(1));
            let state = app.state::<DesktopState>();
            if state.core_generation.load(Ordering::SeqCst) != generation {
                break;
            }
            let exited = match state.core_exited() {
                Ok(value) => value,
                Err(_) => true,
            };
            if !exited {
                continue;
            }
            state.set_core_status(&app, "crashed");
            let restart = {
                let mut attempts = state.crash_restarts.lock().expect("restart mutex poisoned");
                if *attempts >= 1 {
                    false
                } else {
                    *attempts += 1;
                    true
                }
            };
            if restart {
                thread::sleep(Duration::from_secs(1));
                let _ = state.start_core(&app);
            }
            break;
        });
    }

    fn core_exited(&self) -> Result<bool, String> {
        let mut core = self.core.lock().map_err(|_| "core mutex poisoned")?;
        let Some(child) = core.as_mut() else {
            return Ok(true);
        };
        let CoreProcess::Native(child) = child;
        if child
            .try_wait()
            .map_err(|error| error.to_string())?
            .is_some()
        {
            *core = None;
            return Ok(true);
        }
        Ok(false)
    }

    fn restart_core(&self, app: &AppHandle) -> Result<DesktopRuntime, String> {
        self.stop_core();
        *self
            .crash_restarts
            .lock()
            .map_err(|_| "restart mutex poisoned")? = 0;
        self.start_core(app)?;
        Ok(self.runtime())
    }

    fn stop_core(&self) {
        self.core_generation.fetch_add(1, Ordering::SeqCst);
        let runtime = self.runtime();
        let _ = core_shutdown_request(&runtime);
        let child = self.core.lock().ok().and_then(|mut core| core.take());
        if let Some(child) = child {
            match child {
                CoreProcess::Native(mut child) => {
                    for _ in 0..12 {
                        if child.try_wait().ok().flatten().is_some() {
                            return;
                        }
                        thread::sleep(Duration::from_millis(250));
                    }
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        }
    }

    fn avatar_executable(&self, app: &AppHandle) -> Option<PathBuf> {
        if let Some(path) = env::var_os("NEUROASIST_AVATAR_EXECUTABLE") {
            let path = PathBuf::from(path);
            return path.exists().then_some(path);
        }
        let development = self
            .root
            .join("apps")
            .join("avatar-unity")
            .join("Builds")
            .join("NeuroAsistAvatar")
            .join("NeuroAsistAvatar.exe");
        if development.exists() {
            return Some(development);
        }
        app.path()
            .resource_dir()
            .ok()
            .map(|path| path.join("avatar").join("NeuroAsistAvatar.exe"))
            .filter(|path| path.exists())
    }

    fn start_avatar(&self, app: &AppHandle, placement: AvatarPlacement) -> Result<bool, String> {
        let _lifecycle = self
            .avatar_lifecycle
            .lock()
            .map_err(|_| "avatar lifecycle mutex poisoned")?;
        self.start_avatar_locked(app, placement)
    }

    fn start_avatar_locked(
        &self,
        app: &AppHandle,
        placement: AvatarPlacement,
    ) -> Result<bool, String> {
        if self.safe_mode
            || self
                .avatar
                .lock()
                .map_err(|_| "avatar mutex poisoned")?
                .is_some()
        {
            return Ok(false);
        }
        let Some(path) = self.avatar_executable(app) else {
            let _ = app.emit("desktop-avatar-status", "not-configured");
            return Ok(false);
        };
        let runtime = self.runtime();
        let mut command = Command::new(path);
        command
            .current_dir(&self.root)
            .env("NEUROASIST_BACKEND_URL", &runtime.api_base_url)
            .env("NEUROASIST_BACKEND_TOKEN", &runtime.api_token)
            .env(
                "NEUROASIST_AVATAR_HOST",
                if placement == AvatarPlacement::InApp {
                    "embedded"
                } else {
                    "overlay"
                },
            );
        if placement == AvatarPlacement::InApp {
            // Colour-key transparency is unsupported by Unity's DXGI flip
            // swapchain. The BitBlt D3D11 path is deliberate here: it keeps
            // the native avatar surface transparent over the Iris UI.
            //
            // Do not use Unity's `-parentHWND ... delayed` option here. With
            // this player and the Tauri WebView parent it never creates the
            // Unity render HWND, so the shell correctly times out and kills
            // the player. Start tiny, find its normal top-level render window,
            // then convert it to an Iris-owned transparent popup ourselves.
            #[cfg(windows)]
            {
                command.args([
                    "-force-d3d11",
                    "-force-d3d11-bitblt-model",
                    "-screen-fullscreen",
                    "0",
                    "-screen-width",
                    "1",
                    "-screen-height",
                    "1",
                ]);
            }
            #[cfg(not(windows))]
            {
                return Err("The in-app avatar is currently supported on Windows only".into());
            }
        }
        let child = command
            .spawn()
            .map_err(|error| format!("Could not start avatar process: {error}"))?;
        let process_id = child.id();
        *self.avatar.lock().map_err(|_| "avatar mutex poisoned")? = Some(AvatarProcess {
            child,
            placement,
            embedded_window: None,
        });
        // The popup stays hidden until both the React chat anchor and the
        // requested visibility are known. This also preserves requests that
        // arrived while Unity was still starting, rather than overwriting
        // them with the persisted desktop-overlay preference.
        let persisted_visible = if placement == AvatarPlacement::InApp {
            avatar_in_app_visible_from_settings(&desktop_data_root(&self.root))
        } else {
            avatar_overlay_visible_from_settings(&desktop_data_root(&self.root))
        };
        let initial_visible = if placement == AvatarPlacement::InApp {
            self.in_app_avatar_visible
                .lock()
                .map_err(|_| "in-app avatar visibility mutex poisoned")?
                .as_ref()
                .map(|request| request.visible)
                .unwrap_or(persisted_visible)
        } else {
            persisted_visible
        };
        *self
            .avatar_visible
            .lock()
            .map_err(|_| "avatar visibility mutex poisoned")? = initial_visible;
        if placement == AvatarPlacement::InApp {
            // Unity takes several seconds to construct its native render
            // window. Attaching it synchronously here blocks Tauri's command
            // path and makes Iris appear frozen. The worker below waits in the
            // background; bounds and visibility IPC are already queued in the
            // shared DesktopState and are applied as soon as it attaches.
            #[cfg(windows)]
            self.attach_in_app_avatar_in_background(app.clone(), process_id);
        }
        let _ = app.emit("desktop-avatar-status", "connecting");
        Ok(true)
    }

    #[cfg(windows)]
    fn attach_in_app_avatar_in_background(&self, app: AppHandle, process_id: u32) {
        thread::spawn(move || {
            let attached = attach_embedded_avatar_window(&app, process_id);
            let state = app.state::<DesktopState>();
            let Ok(_lifecycle) = state.avatar_lifecycle.lock() else {
                return;
            };
            let Ok(mut avatar) = state.avatar.lock() else {
                return;
            };
            let is_current_in_app_player = avatar.as_ref().is_some_and(|process| {
                process.placement == AvatarPlacement::InApp && process.child.id() == process_id
            });
            if !is_current_in_app_player {
                return;
            }

            match attached {
                Ok(window) => {
                    if let Some(process) = avatar.as_mut() {
                        process.embedded_window = Some(window);
                    }
                    drop(avatar);
                    let _ = state.apply_in_app_avatar_host(&app);
                    let _ = app.emit("desktop-avatar-status", "connected");
                }
                Err(error) => {
                    let failed = avatar.take();
                    drop(avatar);
                    if let Some(mut process) = failed {
                        let _ = process.child.kill();
                        let _ = process.child.wait();
                    }
                    let _ = app.emit("desktop-avatar-status", format!("failed: {error}"));
                    // Unity can create its native window after the discovery
                    // timeout on a cold graphics start. Retry the whole
                    // player, but only if the user still wants in-app mode.
                    let retry_app = app.clone();
                    thread::spawn(move || {
                        thread::sleep(Duration::from_secs(1));
                        start_avatar_with_retries(retry_app, AvatarPlacement::InApp);
                    });
                }
            }
        });
    }

    fn stop_avatar(&self) {
        let Ok(_lifecycle) = self.avatar_lifecycle.lock() else {
            return;
        };
        self.stop_avatar_locked();
    }

    fn stop_avatar_locked(&self) {
        let child = self.avatar.lock().ok().and_then(|mut avatar| avatar.take());
        if let Some(mut avatar) = child {
            let _ = avatar.child.kill();
            let _ = avatar.child.wait();
        }
    }

    fn avatar_host_status(&self) -> Result<AvatarHostStatus, String> {
        let avatar = self.avatar.lock().map_err(|_| "avatar mutex poisoned")?;
        let visible = *self
            .avatar_visible
            .lock()
            .map_err(|_| "avatar visibility mutex poisoned")?;
        let placement = avatar
            .as_ref()
            .map(|process| process.placement)
            .unwrap_or_default();
        Ok(AvatarHostStatus {
            placement,
            running: avatar.is_some(),
            embedded: avatar
                .as_ref()
                .is_some_and(|process| process.embedded_window.is_some()),
            visible,
        })
    }

    fn configure_avatar_placement(
        &self,
        app: &AppHandle,
        placement: AvatarPlacement,
    ) -> Result<AvatarHostStatus, String> {
        let _lifecycle = self
            .avatar_lifecycle
            .lock()
            .map_err(|_| "avatar lifecycle mutex poisoned")?;
        let current = self
            .avatar
            .lock()
            .map_err(|_| "avatar mutex poisoned")?
            .as_ref()
            .map(|process| process.placement);
        if current != Some(placement) {
            self.stop_avatar_locked();
            let _ = self.start_avatar_locked(app, placement)?;
        }
        self.avatar_host_status()
    }

    fn set_avatar_in_app_bounds(
        &self,
        app: &AppHandle,
        bounds: AvatarInAppBounds,
    ) -> Result<(), String> {
        let _update = self
            .in_app_avatar_update
            .lock()
            .map_err(|_| "in-app avatar update mutex poisoned")?;
        if bounds.width < 1 || bounds.height < 1 {
            return Err("Avatar bounds must be positive".into());
        }
        if !self.accept_in_app_avatar_revision(bounds.revision)? {
            return Ok(());
        }
        *self
            .in_app_avatar_bounds
            .lock()
            .map_err(|_| "avatar bounds mutex poisoned")? = Some(bounds.clone());
        self.apply_in_app_avatar_host(app)
    }

    /// An owned popup does not reliably follow a Tauri/WebView owner while
    /// Windows is dragging it. Move it natively from the latest DOM rectangle
    /// instead of waiting for React to re-render after a navigation change.
    fn move_in_app_avatar_with_parent(&self, app: &AppHandle) -> Result<(), String> {
        let _update = self
            .in_app_avatar_update
            .lock()
            .map_err(|_| "in-app avatar update mutex poisoned")?;
        let bounds = self
            .in_app_avatar_bounds
            .lock()
            .map_err(|_| "avatar bounds mutex poisoned")?
            .clone();
        let embedded_window = self
            .avatar
            .lock()
            .map_err(|_| "avatar mutex poisoned")?
            .as_ref()
            .filter(|process| process.placement == AvatarPlacement::InApp)
            .and_then(|process| process.embedded_window);
        #[cfg(windows)]
        if let (Some(bounds), Some(window)) = (bounds.as_ref(), embedded_window) {
            move_embedded_avatar_window(app, window, bounds)?;
        }
        Ok(())
    }

    fn apply_in_app_avatar_host(&self, app: &AppHandle) -> Result<(), String> {
        let bounds = self
            .in_app_avatar_bounds
            .lock()
            .map_err(|_| "avatar bounds mutex poisoned")?
            .clone();
        let fallback_visible = *self
            .avatar_visible
            .lock()
            .map_err(|_| "avatar visibility mutex poisoned")?;
        let visibility = self
            .in_app_avatar_visible
            .lock()
            .map_err(|_| "in-app avatar visibility mutex poisoned")?
            .clone();
        let requested_visible = visibility
            .as_ref()
            .map(|request| request.visible)
            .unwrap_or(fallback_visible);
        // A visible request is valid only together with a geometry request of
        // the same revision (or a newer one). This prevents a popup from
        // briefly reappearing in an old chat rectangle while IPC catches up.
        let has_current_bounds = matches!(
            (&bounds, &visibility),
            (Some(bounds), Some(visibility)) if bounds.revision >= visibility.revision
        ) || (bounds.is_some() && visibility.is_none());
        let embedded_window = self
            .avatar
            .lock()
            .map_err(|_| "avatar mutex poisoned")?
            .as_ref()
            .filter(|process| process.placement == AvatarPlacement::InApp)
            .and_then(|process| process.embedded_window);
        if let Some(window) = embedded_window {
            #[cfg(windows)]
            {
                if let Some(bounds) = bounds.as_ref() {
                    resize_embedded_avatar_window(app, window, bounds)?;
                }
                // Never reveal the owned popup at Unity's startup size.
                set_embedded_avatar_visibility(window, requested_visible && has_current_bounds)?;
            }
        }
        Ok(())
    }

    fn accept_in_app_avatar_revision(&self, revision: u64) -> Result<bool, String> {
        if revision == 0 {
            return Err("Avatar host revision must be positive".into());
        }
        let mut latest = self
            .in_app_avatar_revision
            .lock()
            .map_err(|_| "in-app avatar revision mutex poisoned")?;
        if revision < *latest {
            return Ok(false);
        }
        *latest = revision;
        Ok(true)
    }

    fn set_avatar_in_app_visible(
        &self,
        app: &AppHandle,
        visible: bool,
        revision: u64,
    ) -> Result<(), String> {
        let _update = self
            .in_app_avatar_update
            .lock()
            .map_err(|_| "in-app avatar update mutex poisoned")?;
        if !self.accept_in_app_avatar_revision(revision)? {
            return Ok(());
        }
        *self
            .in_app_avatar_visible
            .lock()
            .map_err(|_| "in-app avatar visibility mutex poisoned")? =
            Some(AvatarInAppVisibility { visible, revision });
        let in_app_running = self
            .avatar
            .lock()
            .map_err(|_| "avatar mutex poisoned")?
            .as_ref()
            .is_some_and(|process| process.placement == AvatarPlacement::InApp);
        if in_app_running {
            *self
                .avatar_visible
                .lock()
                .map_err(|_| "avatar visibility mutex poisoned")? = visible;
        }
        // Calling this command before Unity finishes starting is valid: the
        // requested value remains queued and is applied by start_avatar. Once
        // the native popup exists, apply it immediately as well.
        self.apply_in_app_avatar_host(app)
    }

    fn toggle_avatar(&self, app: &AppHandle) -> Result<bool, String> {
        let _lifecycle = self
            .avatar_lifecycle
            .lock()
            .map_err(|_| "avatar lifecycle mutex poisoned")?;
        let configured_placement = avatar_placement_from_settings(&desktop_data_root(&self.root));
        if configured_placement == AvatarPlacement::InApp {
            let next = !avatar_in_app_visible_from_settings(&desktop_data_root(&self.root));
            avatar_in_app_visibility_request(&self.runtime(), next)?;
            let _ = app.emit("desktop-avatar-visibility", next);
            return Ok(next);
        }
        let placement = self
            .avatar
            .lock()
            .map_err(|_| "avatar mutex poisoned")?
            .as_ref()
            .map(|process| process.placement);
        let running = placement.is_some();
        if running {
            if placement == Some(AvatarPlacement::InApp) {
                // The embedded player is only allowed to be visible while its
                // React chat host exists.  The tray shortcut changes the
                // persisted preference and lets React mount or unmount that
                // host; showing the native child directly here could place it
                // over Settings or another non-chat screen.
                let next = !avatar_in_app_visible_from_settings(&desktop_data_root(&self.root));
                avatar_in_app_visibility_request(&self.runtime(), next)?;
                let _ = app.emit("desktop-avatar-visibility", next);
                return Ok(next);
            }
            let next = {
                let mut visible = self
                    .avatar_visible
                    .lock()
                    .map_err(|_| "avatar visibility mutex poisoned")?;
                *visible = !*visible;
                *visible
            };
            avatar_overlay_visibility_request(&self.runtime(), next)?;
            let _ = app.emit(
                "desktop-avatar-status",
                if next { "visible" } else { "hidden" },
            );
            Ok(next)
        } else {
            self.start_avatar_locked(app, configured_placement)
        }
    }

    fn shutdown(&self) {
        self.stop_avatar();
        self.stop_core();
    }
}

fn start_avatar_with_retries(app: AppHandle, placement: AvatarPlacement) {
    let state = app.state::<DesktopState>();
    if avatar_placement_from_settings(&desktop_data_root(&state.root)) != placement {
        return;
    }
    for attempt in 0..5 {
        match state.start_avatar(&app, placement) {
            Ok(true) | Ok(false) => break,
            Err(error) => {
                eprintln!(
                    "Could not start Unity avatar (attempt {}/5): {}",
                    attempt + 1,
                    error
                );
                let _ = app.emit("desktop-avatar-status", format!("failed: {error}"));
                if attempt < 4 {
                    thread::sleep(Duration::from_secs(1));
                }
            }
        }
    }
}

#[tauri::command]
fn restart_core(app: AppHandle) -> Result<DesktopRuntime, String> {
    app.state::<DesktopState>().restart_core(&app)
}

#[tauri::command]
fn quit_app(app: AppHandle) {
    app.state::<DesktopState>().shutdown();
    app.exit(0);
}

/// The web UI owns the saved preference; the native shell mirrors it so the
/// system tray remains in the same language as the application interface.
#[tauri::command]
fn set_interface_locale(app: AppHandle, locale: String) -> Result<(), String> {
    if !matches!(locale.as_str(), "ru" | "en") {
        return Err("Unsupported interface locale".into());
    }
    let menu = build_tray_menu(&app, &locale).map_err(|error| error.to_string())?;
    let tray = app
        .tray_by_id("companion")
        .ok_or("Could not find Iris tray icon")?;
    tray.set_menu(Some(menu))
        .map_err(|error| error.to_string())?;
    tray.set_tooltip(Some(tray_tooltip(&locale)))
        .map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
fn toggle_avatar(app: AppHandle) -> Result<bool, String> {
    app.state::<DesktopState>().toggle_avatar(&app)
}

#[tauri::command]
fn configure_avatar_placement(
    app: AppHandle,
    placement: AvatarPlacement,
) -> Result<AvatarHostStatus, String> {
    app.state::<DesktopState>()
        .configure_avatar_placement(&app, placement)
}

#[tauri::command]
fn set_avatar_in_app_bounds(app: AppHandle, bounds: AvatarInAppBounds) -> Result<(), String> {
    app.state::<DesktopState>()
        .set_avatar_in_app_bounds(&app, bounds)
}

#[tauri::command]
fn set_avatar_in_app_visible(app: AppHandle, visible: bool, revision: u64) -> Result<(), String> {
    app.state::<DesktopState>()
        .set_avatar_in_app_visible(&app, visible, revision)
}

#[tauri::command]
fn desktop_runtime(app: AppHandle) -> DesktopRuntime {
    app.state::<DesktopState>().runtime()
}

#[tauri::command]
fn api_key_configured() -> Result<bool, String> {
    Ok(read_api_key()?.is_some())
}

#[tauri::command]
fn save_api_key(api_key: String, app: AppHandle) -> Result<DesktopRuntime, String> {
    let api_key = api_key.trim();
    if api_key.is_empty() {
        return Err("API key cannot be empty".into());
    }
    keyring_entry()?.set_password(api_key).map_err(|error| {
        format!("Could not save API key in Windows Credential Manager: {error}")
    })?;
    app.state::<DesktopState>().restart_core(&app)
}

#[tauri::command]
fn remove_api_key(app: AppHandle) -> Result<DesktopRuntime, String> {
    let entry = keyring_entry()?;
    match entry.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => {}
        Err(error) => {
            return Err(format!(
                "Could not remove API key from Windows Credential Manager: {error}"
            ))
        }
    }
    app.state::<DesktopState>().restart_core(&app)
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            show_main_window(app)
        }))
        .on_window_event(|window, event| {
            if window.label() != "main" {
                return;
            }
            match event {
                WindowEvent::Moved(_) => {
                    // Keep the transparent Unity popup in its chat slot while
                    // Iris is being dragged. This uses only a native position
                    // update (no resize or Z-order change), so it does not
                    // compete with Windows' drag loop.
                    let app = window.app_handle();
                    let _ = app
                        .state::<DesktopState>()
                        .move_in_app_avatar_with_parent(app);
                }
                WindowEvent::Resized(_) | WindowEvent::ScaleFactorChanged { .. } => {
                    // The owned Unity popup moves together with Iris. Calling
                    // SetWindowPos for every native `Moved` event fights the
                    // Windows drag loop and makes the whole window stutter.
                    // On resize/DPI changes React supplies one coalesced,
                    // fresh physical chat-slot rectangle instead.
                    let _ = window.emit("desktop-avatar-layout-invalidated", ());
                }
                _ => {}
            }
        })
        .setup(|app| {
            let state = DesktopState::new();
            app.manage(state);
            let shutdown_handle = app.handle().clone();
            ctrlc::set_handler(move || {
                // In development Ctrl+C reaches both Cargo/Tauri and the
                // Python core. Exit the desktop shell deliberately so Cargo
                // observes code 0 instead of STATUS_CONTROL_C_EXIT.
                shutdown_handle.state::<DesktopState>().shutdown();
                shutdown_handle.exit(0);
            })
            .map_err(std::io::Error::other)?;
            let state = app.state::<DesktopState>();
            create_main_window(&app.handle(), state.runtime())?;
            setup_tray(app)?;
            // Core health and Unity window discovery are independent. Start
            // both workers immediately so a cold Unity launch cannot delay the
            // text UI, while the existing attach/retry logic remains intact.
            let avatar_handle = app.handle().clone();
            thread::spawn(move || {
                let state = avatar_handle.state::<DesktopState>();
                let placement = avatar_placement_from_settings(&desktop_data_root(&state.root));
                start_avatar_with_retries(avatar_handle, placement);
            });
            let core_handle = app.handle().clone();
            thread::spawn(move || {
                let state = core_handle.state::<DesktopState>();
                let _ = state.start_core(&core_handle);
            });
            #[cfg(desktop)]
            app.handle().plugin(
                tauri_plugin_global_shortcut::Builder::new()
                    .with_shortcuts(["CommandOrControl+Shift+N", "CommandOrControl+Alt+A"])?
                    .with_handler(|app, shortcut, event| {
                        if event.state == ShortcutState::Pressed {
                            if shortcut.to_string() == "CTRL+ALT+A" {
                                let _ = app.state::<DesktopState>().toggle_avatar(app);
                            } else {
                                show_main_window(app);
                            }
                        }
                    })
                    .build(),
            )?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            desktop_runtime,
            restart_core,
            quit_app,
            set_interface_locale,
            toggle_avatar,
            configure_avatar_placement,
            set_avatar_in_app_bounds,
            set_avatar_in_app_visible,
            api_key_configured,
            save_api_key,
            remove_api_key
        ])
        .build(tauri::generate_context!())
        .expect("error while building Iris desktop shell");

    app.run(|app, event| {
        if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
            app.state::<DesktopState>().shutdown();
        }
    });
}

fn create_main_window(app: &AppHandle, runtime: DesktopRuntime) -> tauri::Result<()> {
    let bootstrap = format!(
        "window.__NEUROASIST_DESKTOP_CONFIG__ = {};",
        serde_json::to_string(&runtime).expect("desktop config serializes")
    );
    WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("Iris")
        .decorations(false)
        .inner_size(1120.0, 760.0)
        .min_inner_size(760.0, 540.0)
        .initialization_script(&bootstrap)
        .build()?;
    Ok(())
}

fn setup_tray(app: &tauri::App) -> tauri::Result<()> {
    let state = app.state::<DesktopState>();
    let locale = interface_locale_from_settings(&desktop_data_root(&state.root));
    let menu = build_tray_menu(app, &locale)?;
    TrayIconBuilder::with_id("companion")
        .icon(tauri::include_image!("./icons/32x32.png"))
        .tooltip(tray_tooltip(&locale))
        .menu(&menu)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "show" => show_main_window(app),
            "avatar" => {
                let _ = app.state::<DesktopState>().toggle_avatar(app);
            }
            "safe-mode" => restart_in_safe_mode(app),
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if matches!(
                event,
                TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                }
            ) {
                show_main_window(tray.app_handle());
            }
        })
        .build(app)?;
    Ok(())
}

fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn restart_in_safe_mode(app: &AppHandle) {
    let executable = match env::current_exe() {
        Ok(path) => path,
        Err(_) => return,
    };
    let _ = Command::new(executable).arg("--safe-mode").spawn();
    app.exit(0);
}

fn available_loopback_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .expect("could not reserve a loopback port")
        .local_addr()
        .expect("loopback listener has an address")
        .port()
}

fn random_token() -> String {
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes).expect("OS random source unavailable");
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn keyring_entry() -> Result<Entry, String> {
    Entry::new(KEYRING_SERVICE, KEYRING_ACCOUNT)
        .map_err(|error| format!("Windows Credential Manager is unavailable: {error}"))
}

fn desktop_data_root(root: &PathBuf) -> PathBuf {
    env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .map(|path| path.join("NeuroAsist"))
        .unwrap_or_else(|| root.join("data"))
}

/// The backend owns this persisted preference. The shell reads it only before
/// React has connected, preventing a one-frame desktop-overlay flash when the
/// previous session used the in-app renderer.
fn avatar_placement_from_settings(data_root: &PathBuf) -> AvatarPlacement {
    let path = data_root.join("settings.json");
    std::fs::read_to_string(path)
        .map(|json| avatar_placement_from_json(&json))
        .unwrap_or_default()
}

fn avatar_placement_from_json(json: &str) -> AvatarPlacement {
    let value = serde_json::from_str::<serde_json::Value>(json)
        .ok()
        .and_then(|payload| {
            payload
                .get("settings")?
                .get("avatar_placement")?
                .as_str()
                .map(str::to_owned)
        });
    match value.as_deref() {
        Some("in_app") => AvatarPlacement::InApp,
        _ => AvatarPlacement::DesktopOverlay,
    }
}

fn avatar_overlay_visible_from_settings(data_root: &PathBuf) -> bool {
    std::fs::read_to_string(data_root.join("settings.json"))
        .map(|json| avatar_overlay_visible_from_json(&json))
        .unwrap_or(true)
}

fn avatar_overlay_visible_from_json(json: &str) -> bool {
    serde_json::from_str::<serde_json::Value>(json)
        .ok()
        .and_then(|payload| {
            payload
                .get("settings")?
                .get("avatar_overlay_visible")?
                .as_bool()
        })
        .unwrap_or(true)
}

fn avatar_in_app_visible_from_settings(data_root: &PathBuf) -> bool {
    std::fs::read_to_string(data_root.join("settings.json"))
        .map(|json| avatar_in_app_visible_from_json(&json))
        .unwrap_or(true)
}

fn avatar_in_app_visible_from_json(json: &str) -> bool {
    serde_json::from_str::<serde_json::Value>(json)
        .ok()
        .and_then(|payload| {
            payload
                .get("settings")?
                .get("avatar_in_app_visible")?
                .as_bool()
        })
        .unwrap_or(true)
}

#[cfg(windows)]
fn attach_embedded_avatar_window(app: &AppHandle, process_id: u32) -> Result<usize, String> {
    let parent = app
        .get_webview_window("main")
        .ok_or("Could not find Iris main window")?
        .hwnd()
        .map_err(|error| format!("Could not get Iris native window handle: {error}"))?;

    let started_at = std::time::Instant::now();
    let window = loop {
        if let Some(window) = unity_window_for_process(process_id) {
            break window;
        }
        if started_at.elapsed() >= UNITY_WINDOW_DISCOVERY_TIMEOUT {
            return Err(
                "Unity avatar did not create an embeddable window within 30 seconds".into(),
            );
        }
        thread::sleep(UNITY_WINDOW_POLL_INTERVAL);
    };

    unsafe {
        // Unity starts at 1×1. Hide it before the final graphics startup and
        // never expose its standalone player bounds to the desktop.
        let _ = ShowWindow(window, SW_HIDE);
    }
    wait_for_unity_graphics(window)?;

    unsafe {
        // A layered Direct3D child window cannot reliably apply a colour key
        // on Windows. Convert it to a popup before detaching it, following
        // Win32's child/popup transition rules.
        // Replace the complete overlapped-window style, not only WS_CHILD.
        // Keeping Unity's caption bits was the source of the white native
        // title bar above an otherwise embedded avatar.
        SetWindowLongPtrW(window, GWL_STYLE, WS_POPUP.0 as isize);
        if GetParent(window)
            .map(|current| !current.0.is_null())
            .unwrap_or(false)
        {
            SetParent(window, None).map_err(|error| {
                format!("Could not detach Unity avatar window from Iris: {error}")
            })?;
        }
        // Keep Unity as an owned popup: it has no Alt+Tab or taskbar presence.
        let extended = GetWindowLongPtrW(window, GWL_EXSTYLE) as u32;
        let embedded_extended = extended
            | WS_EX_LAYERED.0
            | WS_EX_TRANSPARENT.0
            | WS_EX_TOOLWINDOW.0
            | WS_EX_NOACTIVATE.0;
        SetWindowLongPtrW(window, GWL_EXSTYLE, embedded_extended as isize);
        SetWindowLongPtrW(window, GWLP_HWNDPARENT, parent.0 as isize);
        SetLayeredWindowAttributes(window, EMBEDDED_AVATAR_COLOR_KEY, 0, LWA_COLORKEY).map_err(
            |error| format!("Could not make Unity avatar background transparent: {error}"),
        )?;
        SetWindowPos(
            window,
            Some(HWND_TOP),
            0,
            0,
            1,
            1,
            SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
        .map_err(|error| format!("Could not initialize Unity avatar host bounds: {error}"))?;
        let _ = ShowWindow(window, SW_HIDE);
    }

    Ok(window.0 as usize)
}

#[cfg(windows)]
fn wait_for_unity_graphics(window: HWND) -> Result<(), String> {
    let started_at = std::time::Instant::now();
    loop {
        let flags = unsafe { GetWindowLongPtrW(window, GWLP_USERDATA) as usize };
        if flags & 1 == 1 {
            return Ok(());
        }
        if started_at.elapsed() >= UNITY_GRAPHICS_READY_TIMEOUT {
            return Err("Unity avatar graphics did not initialize within 15 seconds".into());
        }
        thread::sleep(Duration::from_millis(25));
    }
}

#[cfg(windows)]
fn resize_embedded_avatar_window(
    app: &AppHandle,
    window: usize,
    bounds: &AvatarInAppBounds,
) -> Result<(), String> {
    let parent = app
        .get_webview_window("main")
        .ok_or("Could not find Iris main window")?
        .hwnd()
        .map_err(|error| format!("Could not get Iris native window handle: {error}"))?;
    unsafe {
        // DOM rectangles start at the WebView client origin; owned popups use
        // physical screen coordinates.  ClientToScreen accounts for the title
        // bar, window movement, and Windows DPI scaling.
        let mut position = POINT {
            x: bounds.x,
            y: bounds.y,
        };
        ClientToScreen(parent, &mut position)
            .ok()
            .map_err(|error| format!("Could not map avatar host bounds to screen: {error}"))?;
        SetWindowPos(
            HWND(window as *mut core::ffi::c_void),
            None,
            position.x,
            position.y,
            bounds.width,
            bounds.height,
            SWP_NOACTIVATE | SWP_NOZORDER,
        )
        .map_err(|error| format!("Could not resize Unity avatar host: {error}"))?;
    }
    Ok(())
}

fn interface_locale_from_settings(data_root: &PathBuf) -> String {
    std::fs::read_to_string(data_root.join("settings.json"))
        .ok()
        .and_then(|json| {
            serde_json::from_str::<serde_json::Value>(&json)
                .ok()
                .and_then(|payload| {
                    payload
                        .get("settings")?
                        .get("interface_locale")?
                        .as_str()
                        .map(str::to_owned)
                })
        })
        .filter(|locale| matches!(locale.as_str(), "ru" | "en"))
        .unwrap_or_else(|| "ru".to_owned())
}

fn tray_copy(locale: &str) -> (&'static str, &'static str, &'static str, &'static str) {
    match locale {
        "en" => (
            "Show Iris",
            "Show / hide avatar",
            "Restart in Safe Mode",
            "Quit",
        ),
        _ => (
            "Показать Iris",
            "Показать / скрыть аватар",
            "Перезапустить в безопасном режиме",
            "Выйти",
        ),
    }
}

fn tray_tooltip(locale: &str) -> &'static str {
    if locale == "en" {
        "Iris companion"
    } else {
        "Компаньон Iris"
    }
}

fn build_tray_menu<R: tauri::Runtime, M: Manager<R>>(
    manager: &M,
    locale: &str,
) -> tauri::Result<tauri::menu::Menu<R>> {
    let (show_label, avatar_label, safe_mode_label, quit_label) = tray_copy(locale);
    let show = MenuItemBuilder::with_id("show", show_label).build(manager)?;
    let avatar = MenuItemBuilder::with_id("avatar", avatar_label).build(manager)?;
    let safe_mode = MenuItemBuilder::with_id("safe-mode", safe_mode_label).build(manager)?;
    let quit = MenuItemBuilder::with_id("quit", quit_label).build(manager)?;
    MenuBuilder::new(manager)
        .items(&[&show, &avatar, &safe_mode, &quit])
        .build()
}

#[cfg(windows)]
fn move_embedded_avatar_window(
    app: &AppHandle,
    window: usize,
    bounds: &AvatarInAppBounds,
) -> Result<(), String> {
    let parent = app
        .get_webview_window("main")
        .ok_or("Could not find Iris main window")?
        .hwnd()
        .map_err(|error| format!("Could not get Iris native window handle: {error}"))?;
    unsafe {
        let mut position = POINT {
            x: bounds.x,
            y: bounds.y,
        };
        ClientToScreen(parent, &mut position)
            .ok()
            .map_err(|error| format!("Could not map avatar move to screen: {error}"))?;
        SetWindowPos(
            HWND(window as *mut core::ffi::c_void),
            None,
            position.x,
            position.y,
            0,
            0,
            SWP_ASYNCWINDOWPOS | SWP_NOACTIVATE | SWP_NOSIZE | SWP_NOZORDER,
        )
        .map_err(|error| format!("Could not move Unity avatar host: {error}"))?;
    }
    Ok(())
}

#[cfg(windows)]
fn set_embedded_avatar_visibility(window: usize, visible: bool) -> Result<(), String> {
    unsafe {
        let hwnd = HWND(window as *mut core::ffi::c_void);
        // ShowWindow returns the previous visibility, not an error code. It is
        // therefore intentionally best-effort while shutdown is in progress.
        let _ = ShowWindow(hwnd, if visible { SW_SHOWNA } else { SW_HIDE });
    }
    Ok(())
}

#[cfg(windows)]
fn unity_window_for_process(process_id: u32) -> Option<HWND> {
    struct Search {
        process_id: u32,
        window: Option<HWND>,
    }
    unsafe extern "system" fn visit(window: HWND, lparam: LPARAM) -> BOOL {
        let search = &mut *(lparam.0 as *mut Search);
        let mut owner = 0_u32;
        GetWindowThreadProcessId(window, Some(&mut owner));
        if owner == search.process_id && is_unity_render_window(window) {
            search.window = Some(window);
            return BOOL(0);
        }
        BOOL(1)
    }

    let mut search = Search {
        process_id,
        window: None,
    };
    unsafe {
        // The player starts as a normal tiny top-level window. Its rendering
        // surface is always a UnityWndClass; helper and splash windows are
        // skipped by the class-name check.
        let _ = EnumWindows(Some(visit), LPARAM((&mut search as *mut Search) as isize));
    }
    search.window
}

#[cfg(windows)]
unsafe fn is_unity_render_window(window: HWND) -> bool {
    let mut class_name = [0_u16; 128];
    let length = GetClassNameW(window, &mut class_name);
    if length <= 0 {
        return false;
    }
    let class_name = String::from_utf16_lossy(&class_name[..length as usize]);
    class_name.contains("UnityWndClass")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn avatar_placement_json_accepts_only_the_embedded_value() {
        assert_eq!(
            avatar_placement_from_json(r#"{"settings":{"avatar_placement":"in_app"}}"#),
            AvatarPlacement::InApp,
        );
        assert_eq!(
            avatar_placement_from_json(r#"{"settings":{"avatar_placement":"desktop_overlay"}}"#),
            AvatarPlacement::DesktopOverlay,
        );
        assert_eq!(
            avatar_placement_from_json("not json"),
            AvatarPlacement::DesktopOverlay
        );
    }

    #[test]
    fn avatar_visibility_defaults_to_enabled_for_existing_settings() {
        assert!(!avatar_overlay_visible_from_json(
            r#"{"settings":{"avatar_overlay_visible":false}}"#
        ));
        assert!(avatar_overlay_visible_from_json(r#"{"settings":{}}"#));
        assert!(!avatar_in_app_visible_from_json(
            r#"{"settings":{"avatar_in_app_visible":false}}"#
        ));
        assert!(avatar_in_app_visible_from_json(r#"{"settings":{}}"#));
    }

    #[test]
    fn avatar_host_revisions_reject_stale_ipc() {
        let state = DesktopState::new();
        assert!(state.accept_in_app_avatar_revision(41).unwrap());
        assert!(state.accept_in_app_avatar_revision(41).unwrap());
        assert!(!state.accept_in_app_avatar_revision(40).unwrap());
        assert!(state.accept_in_app_avatar_revision(42).unwrap());
        assert!(state.accept_in_app_avatar_revision(0).is_err());
    }
}

fn read_api_key() -> Result<Option<String>, String> {
    match keyring_entry()?.get_password() {
        Ok(value) if !value.trim().is_empty() => Ok(Some(value)),
        Ok(_) | Err(keyring::Error::NoEntry) => Ok(None),
        Err(error) => Err(format!(
            "Could not read API key from Windows Credential Manager: {error}"
        )),
    }
}

fn core_command(root: &PathBuf) -> Result<Command, String> {
    if let Some(executable) = env::var_os("NEUROASIST_CORE_EXECUTABLE") {
        return Ok(Command::new(executable));
    }
    let python = root.join(".venv").join("Scripts").join("python.exe");
    let mut command = Command::new(if python.exists() {
        python
    } else {
        PathBuf::from("python")
    });
    command.args(["-m", "apps.backend.desktop_entry"]);
    Ok(command)
}

fn configure_core_command(
    command: &mut Command,
    root: &PathBuf,
    data_root: &PathBuf,
    port: &str,
    token: &str,
    safe_mode: bool,
    avatar_enabled: bool,
    api_key: Option<&str>,
) {
    command
        .current_dir(root)
        .env("NEUROASIST_PORT", port)
        .env("NEUROASIST_DESKTOP_TOKEN", token)
        .env("NEUROASIST_APP_DATA_DIR", data_root)
        .env(
            "SQLITE_PATH",
            data_root.join("data").join("neuroasist.sqlite3"),
        )
        .env("VOICE_AUDIO_DIR", data_root.join("data").join("audio"))
        .env("LOG_TO_FILE", "true")
        .env("LOG_FILE_PATH", data_root.join("logs").join("app.log"))
        .env("NEUROASIST_SAFE_MODE", if safe_mode { "1" } else { "0" })
        .env(
            "AVATAR_ENABLED",
            if avatar_enabled { "true" } else { "false" },
        );
    if let Some(api_key) = api_key {
        command.env("DEEPSEEK_API_KEY", api_key);
    }
}

fn core_health_is_ready(runtime: &DesktopRuntime) -> bool {
    core_request(runtime, "GET", "/health").is_ok()
}

fn core_shutdown_request(runtime: &DesktopRuntime) -> Result<(), String> {
    core_request(runtime, "POST", "/internal/shutdown")
}

fn core_request(runtime: &DesktopRuntime, method: &str, path: &str) -> Result<(), String> {
    let address = runtime.api_base_url.trim_start_matches("http://");
    let mut stream = TcpStream::connect(address).map_err(|error| error.to_string())?;
    stream
        .set_read_timeout(Some(Duration::from_secs(1)))
        .map_err(|error| error.to_string())?;
    let request = format!("{method} {path} HTTP/1.1\r\nHost: {address}\r\nX-NeuroAsist-Token: {}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n", runtime.api_token);
    stream
        .write_all(request.as_bytes())
        .map_err(|error| error.to_string())?;
    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|error| error.to_string())?;
    if response.starts_with("HTTP/1.1 2") {
        Ok(())
    } else {
        Err(response.lines().next().unwrap_or("No HTTP response").into())
    }
}

fn avatar_overlay_visibility_request(
    runtime: &DesktopRuntime,
    visible: bool,
) -> Result<(), String> {
    let address = runtime.api_base_url.trim_start_matches("http://");
    let mut stream = TcpStream::connect(address).map_err(|error| error.to_string())?;
    stream
        .set_read_timeout(Some(Duration::from_secs(1)))
        .map_err(|error| error.to_string())?;
    let body = format!(r#"{{"visible":{visible}}}"#);
    let request = format!("PUT /avatar/overlay HTTP/1.1\r\nHost: {address}\r\nX-NeuroAsist-Token: {}\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: {}\r\n\r\n{body}", runtime.api_token, body.len());
    stream
        .write_all(request.as_bytes())
        .map_err(|error| error.to_string())?;
    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|error| error.to_string())?;
    if response.starts_with("HTTP/1.1 2") {
        Ok(())
    } else {
        Err(response.lines().next().unwrap_or("No HTTP response").into())
    }
}

fn avatar_in_app_visibility_request(runtime: &DesktopRuntime, visible: bool) -> Result<(), String> {
    let address = runtime.api_base_url.trim_start_matches("http://");
    let mut stream = TcpStream::connect(address).map_err(|error| error.to_string())?;
    stream
        .set_read_timeout(Some(Duration::from_secs(1)))
        .map_err(|error| error.to_string())?;
    let body = format!(r#"{{"avatar_in_app_visible":{visible}}}"#);
    let request = format!("PATCH /settings/runtime HTTP/1.1\r\nHost: {address}\r\nX-NeuroAsist-Token: {}\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: {}\r\n\r\n{body}", runtime.api_token, body.len());
    stream
        .write_all(request.as_bytes())
        .map_err(|error| error.to_string())?;
    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|error| error.to_string())?;
    if response.starts_with("HTTP/1.1 2") {
        Ok(())
    } else {
        Err(response.lines().next().unwrap_or("No HTTP response").into())
    }
}

// Trigger rebuild
