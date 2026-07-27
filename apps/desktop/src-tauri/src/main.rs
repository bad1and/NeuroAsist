use std::{
    env,
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::PathBuf,
    process::{Child, Command},
    sync::{atomic::{AtomicU64, Ordering}, Mutex},
    thread,
    time::Duration,
};

use serde::Serialize;
use keyring::Entry;
use tauri_plugin_shell::{process::{CommandChild, CommandEvent}, ShellExt};
use tauri::{
    menu::{MenuBuilder, MenuItemBuilder},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder,
};
use tauri_plugin_global_shortcut::ShortcutState;

const CORE_STARTUP_ATTEMPTS: u8 = 60;
const CORE_STARTUP_DELAY: Duration = Duration::from_millis(250);
const KEYRING_SERVICE: &str = "NeuroAsist";
const KEYRING_ACCOUNT: &str = "deepseek_api_key";

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
    avatar: Mutex<Option<Child>>,
    avatar_visible: Mutex<bool>,
    crash_restarts: Mutex<u8>,
    core_generation: AtomicU64,
}

enum CoreProcess {
    Native(Child),
    Sidecar(CommandChild),
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
            avatar_visible: Mutex::new(true),
            crash_restarts: Mutex::new(0),
            core_generation: AtomicU64::new(0),
        }
    }

    fn runtime(&self) -> DesktopRuntime {
        self.runtime.lock().expect("runtime mutex poisoned").clone()
    }

    fn set_core_status(&self, app: &AppHandle, value: &str) {
        self.runtime.lock().expect("runtime mutex poisoned").core_status = value.into();
        let _ = app.emit("desktop-core-status", value);
    }

    fn start_core(&self, app: &AppHandle) -> Result<(), String> {
        if self.core.lock().map_err(|_| "core mutex poisoned")?.is_some() {
            return Ok(());
        }
        self.set_core_status(app, "starting");
        let generation = self.core_generation.fetch_add(1, Ordering::SeqCst) + 1;
        let runtime = self.runtime();
        let data_root = desktop_data_root(&self.root);
        std::fs::create_dir_all(&data_root).map_err(|error| format!("Could not create Iris data directory: {error}"))?;
        let port = runtime.api_base_url.rsplit(':').next().unwrap_or("8000");
        let api_key = read_api_key()?;
        let avatar_enabled = self.avatar_executable(app).is_some() && !self.safe_mode;
        let mut sidecar_events = None;
        let process = if cfg!(debug_assertions) || env::var_os("NEUROASIST_CORE_EXECUTABLE").is_some() {
            let mut command = core_command(&self.root)?;
            configure_core_command(&mut command, &self.root, &data_root, port, &runtime.api_token, self.safe_mode, avatar_enabled, api_key.as_deref());
            CoreProcess::Native(command.spawn().map_err(|error| format!("Could not start Neuro Core: {error}"))?)
        } else {
            let mut command = app.shell().sidecar("neuroasist-core")
                .map_err(|error| format!("Could not locate bundled Neuro Core: {error}"))?
                .current_dir(&data_root)
                .env("NEUROASIST_PORT", port)
                .env("NEUROASIST_DESKTOP_TOKEN", &runtime.api_token)
                .env("NEUROASIST_APP_DATA_DIR", &data_root)
                .env("SQLITE_PATH", data_root.join("data").join("neuroasist.sqlite3"))
                .env("VOICE_AUDIO_DIR", data_root.join("data").join("audio"))
                .env("LOG_TO_FILE", "true")
                .env("LOG_FILE_PATH", data_root.join("logs").join("app.log"))
                .env("NEUROASIST_SAFE_MODE", if self.safe_mode { "1" } else { "0" });
            command = command.env("AVATAR_ENABLED", if avatar_enabled { "true" } else { "false" });
            if let Some(api_key) = api_key.as_deref() {
                command = command.env("DEEPSEEK_API_KEY", api_key);
            }
            let (events, child) = command.spawn().map_err(|error| format!("Could not start bundled Neuro Core: {error}"))?;
            sidecar_events = Some(events);
            CoreProcess::Sidecar(child)
        };
        *self.core.lock().map_err(|_| "core mutex poisoned")? = Some(process);
        if let Some(mut events) = sidecar_events {
            let app = app.clone();
            tauri::async_runtime::spawn(async move {
                while let Some(event) = events.recv().await {
                    if matches!(event, CommandEvent::Terminated(_)) {
                        let state = app.state::<DesktopState>();
                        if state.core_generation.load(Ordering::SeqCst) == generation {
                            if let Ok(mut core) = state.core.lock() {
                                *core = None;
                            }
                        }
                        break;
                    }
                }
            });
        }

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
        let Some(child) = core.as_mut() else { return Ok(true) };
        if let CoreProcess::Native(child) = child {
            if child.try_wait().map_err(|error| error.to_string())?.is_some() {
                *core = None;
                return Ok(true);
            }
        }
        Ok(false)
    }

    fn restart_core(&self, app: &AppHandle) -> Result<DesktopRuntime, String> {
        self.stop_core();
        *self.crash_restarts.lock().map_err(|_| "restart mutex poisoned")? = 0;
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
                CoreProcess::Sidecar(child) => { let _ = child.kill(); }
            }
        }
    }

    fn avatar_executable(&self, app: &AppHandle) -> Option<PathBuf> {
        if let Some(path) = env::var_os("NEUROASIST_AVATAR_EXECUTABLE") {
            let path = PathBuf::from(path);
            return path.exists().then_some(path);
        }
        let development = self.root.join("apps").join("avatar-unity").join("Builds").join("NeuroAsistAvatar").join("NeuroAsistAvatar.exe");
        if development.exists() {
            return Some(development);
        }
        app.path().resource_dir().ok()
            .map(|path| path.join("avatar").join("NeuroAsistAvatar.exe"))
            .filter(|path| path.exists())
    }

    fn start_avatar(&self, app: &AppHandle) -> Result<bool, String> {
        if self.safe_mode || self.avatar.lock().map_err(|_| "avatar mutex poisoned")?.is_some() {
            return Ok(false);
        }
        let Some(path) = self.avatar_executable(app) else {
            let _ = app.emit("desktop-avatar-status", "not-configured");
            return Ok(false);
        };
        let runtime = self.runtime();
        let child = Command::new(path)
            .current_dir(&self.root)
            .env("NEUROASIST_BACKEND_URL", &runtime.api_base_url)
            .env("NEUROASIST_BACKEND_TOKEN", &runtime.api_token)
            .spawn()
            .map_err(|error| format!("Could not start avatar process: {error}"))?;
        *self.avatar.lock().map_err(|_| "avatar mutex poisoned")? = Some(child);
        *self.avatar_visible.lock().map_err(|_| "avatar visibility mutex poisoned")? = true;
        let _ = app.emit("desktop-avatar-status", "connecting");
        Ok(true)
    }

    fn stop_avatar(&self) {
        let child = self.avatar.lock().ok().and_then(|mut avatar| avatar.take());
        if let Some(mut child) = child {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    fn toggle_avatar(&self, app: &AppHandle) -> Result<bool, String> {
        if self.avatar.lock().map_err(|_| "avatar mutex poisoned")?.is_some() {
            let next = {
                let mut visible = self.avatar_visible.lock().map_err(|_| "avatar visibility mutex poisoned")?;
                *visible = !*visible;
                *visible
            };
            avatar_overlay_visibility_request(&self.runtime(), next)?;
            let _ = app.emit("desktop-avatar-status", if next { "visible" } else { "hidden" });
            Ok(next)
        } else {
            self.start_avatar(app)
        }
    }

    fn shutdown(&self) {
        self.stop_avatar();
        self.stop_core();
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

#[tauri::command]
fn toggle_avatar(app: AppHandle) -> Result<bool, String> {
    app.state::<DesktopState>().toggle_avatar(&app)
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
    keyring_entry()?.set_password(api_key).map_err(|error| format!("Could not save API key in Windows Credential Manager: {error}"))?;
    app.state::<DesktopState>().restart_core(&app)
}

#[tauri::command]
fn remove_api_key(app: AppHandle) -> Result<DesktopRuntime, String> {
    let entry = keyring_entry()?;
    match entry.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => {}
        Err(error) => return Err(format!("Could not remove API key from Windows Credential Manager: {error}")),
    }
    app.state::<DesktopState>().restart_core(&app)
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| show_main_window(app)))
        .plugin(tauri_plugin_shell::init())
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
            }).map_err(std::io::Error::other)?;
            let state = app.state::<DesktopState>();
            create_main_window(&app.handle(), state.runtime())?;
            setup_tray(app)?;
            let startup_handle = app.handle().clone();
            thread::spawn(move || {
                let state = startup_handle.state::<DesktopState>();
                if state.start_core(&startup_handle).is_ok() {
                    let _ = state.start_avatar(&startup_handle);
                }
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
        .invoke_handler(tauri::generate_handler![desktop_runtime, restart_core, quit_app, toggle_avatar, api_key_configured, save_api_key, remove_api_key])
        .build(tauri::generate_context!())
        .expect("error while building Iris desktop shell");

    app.run(|app, event| {
            if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
                app.state::<DesktopState>().shutdown();
            }
        });
}

fn create_main_window(app: &AppHandle, runtime: DesktopRuntime) -> tauri::Result<()> {
    let bootstrap = format!("window.__NEUROASIST_DESKTOP_CONFIG__ = {};", serde_json::to_string(&runtime).expect("desktop config serializes"));
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
    let show = MenuItemBuilder::with_id("show", "Show Iris").build(app)?;
    let avatar = MenuItemBuilder::with_id("avatar", "Show / hide avatar").build(app)?;
    let safe_mode = MenuItemBuilder::with_id("safe-mode", "Restart in Safe Mode").build(app)?;
    let quit = MenuItemBuilder::with_id("quit", "Quit").build(app)?;
    let menu = MenuBuilder::new(app).items(&[&show, &avatar, &safe_mode, &quit]).build()?;
    TrayIconBuilder::with_id("companion")
        .icon(tauri::include_image!("./icons/32x32.png"))
        .tooltip("Iris companion")
        .menu(&menu)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "show" => show_main_window(app),
            "avatar" => { let _ = app.state::<DesktopState>().toggle_avatar(app); }
            "safe-mode" => restart_in_safe_mode(app),
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if matches!(event, TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. }) {
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
    let executable = match env::current_exe() { Ok(path) => path, Err(_) => return };
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
    Entry::new(KEYRING_SERVICE, KEYRING_ACCOUNT).map_err(|error| format!("Windows Credential Manager is unavailable: {error}"))
}

fn desktop_data_root(root: &PathBuf) -> PathBuf {
    env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .map(|path| path.join("NeuroAsist"))
        .unwrap_or_else(|| root.join("data"))
}

fn read_api_key() -> Result<Option<String>, String> {
    match keyring_entry()?.get_password() {
        Ok(value) if !value.trim().is_empty() => Ok(Some(value)),
        Ok(_) | Err(keyring::Error::NoEntry) => Ok(None),
        Err(error) => Err(format!("Could not read API key from Windows Credential Manager: {error}")),
    }
}

fn core_command(root: &PathBuf) -> Result<Command, String> {
    if let Some(executable) = env::var_os("NEUROASIST_CORE_EXECUTABLE") {
        return Ok(Command::new(executable));
    }
    let python = root.join(".venv").join("Scripts").join("python.exe");
    let mut command = Command::new(if python.exists() { python } else { PathBuf::from("python") });
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
        .env("SQLITE_PATH", data_root.join("data").join("neuroasist.sqlite3"))
        .env("VOICE_AUDIO_DIR", data_root.join("data").join("audio"))
        .env("LOG_TO_FILE", "true")
        .env("LOG_FILE_PATH", data_root.join("logs").join("app.log"))
        .env("NEUROASIST_SAFE_MODE", if safe_mode { "1" } else { "0" })
        .env("AVATAR_ENABLED", if avatar_enabled { "true" } else { "false" });
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
    stream.set_read_timeout(Some(Duration::from_secs(1))).map_err(|error| error.to_string())?;
    let request = format!("{method} {path} HTTP/1.1\r\nHost: {address}\r\nX-NeuroAsist-Token: {}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n", runtime.api_token);
    stream.write_all(request.as_bytes()).map_err(|error| error.to_string())?;
    let mut response = String::new();
    stream.read_to_string(&mut response).map_err(|error| error.to_string())?;
    if response.starts_with("HTTP/1.1 2") { Ok(()) } else { Err(response.lines().next().unwrap_or("No HTTP response").into()) }
}

fn avatar_overlay_visibility_request(runtime: &DesktopRuntime, visible: bool) -> Result<(), String> {
    let address = runtime.api_base_url.trim_start_matches("http://");
    let mut stream = TcpStream::connect(address).map_err(|error| error.to_string())?;
    stream.set_read_timeout(Some(Duration::from_secs(1))).map_err(|error| error.to_string())?;
    let body = format!(r#"{{"visible":{visible}}}"#);
    let request = format!("PUT /avatar/overlay HTTP/1.1\r\nHost: {address}\r\nX-NeuroAsist-Token: {}\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: {}\r\n\r\n{body}", runtime.api_token, body.len());
    stream.write_all(request.as_bytes()).map_err(|error| error.to_string())?;
    let mut response = String::new();
    stream.read_to_string(&mut response).map_err(|error| error.to_string())?;
    if response.starts_with("HTTP/1.1 2") { Ok(()) } else { Err(response.lines().next().unwrap_or("No HTTP response").into()) }
}
