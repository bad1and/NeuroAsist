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
use tauri::{
    menu::{MenuBuilder, MenuItemBuilder},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder,
};
use tauri_plugin_global_shortcut::ShortcutState;

const CORE_STARTUP_ATTEMPTS: u8 = 60;
const CORE_STARTUP_DELAY: Duration = Duration::from_millis(250);

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
    core: Mutex<Option<Child>>,
    avatar: Mutex<Option<Child>>,
    crash_restarts: Mutex<u8>,
    core_generation: AtomicU64,
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
        let mut command = core_command(&self.root)?;
        command
            .current_dir(&self.root)
            .env("NEUROASIST_PORT", runtime.api_base_url.rsplit(':').next().unwrap_or("8000"))
            .env("NEUROASIST_DESKTOP_TOKEN", &runtime.api_token)
            .env("NEUROASIST_SAFE_MODE", if self.safe_mode { "1" } else { "0" });
        let child = command.spawn().map_err(|error| format!("Could not start Neuro Core: {error}"))?;
        *self.core.lock().map_err(|_| "core mutex poisoned")? = Some(child);

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
        if child.try_wait().map_err(|error| error.to_string())?.is_some() {
            *core = None;
            return Ok(true);
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
        if let Some(mut child) = child {
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

    fn start_avatar(&self) -> Result<bool, String> {
        if self.safe_mode || self.avatar.lock().map_err(|_| "avatar mutex poisoned")?.is_some() {
            return Ok(false);
        }
        let Some(path) = env::var_os("NEUROASIST_AVATAR_EXECUTABLE") else { return Ok(false) };
        let runtime = self.runtime();
        let child = Command::new(path)
            .current_dir(&self.root)
            .env("NEUROASIST_BACKEND_URL", &runtime.api_base_url)
            .env("NEUROASIST_BACKEND_TOKEN", &runtime.api_token)
            .spawn()
            .map_err(|error| format!("Could not start avatar process: {error}"))?;
        *self.avatar.lock().map_err(|_| "avatar mutex poisoned")? = Some(child);
        Ok(true)
    }

    fn stop_avatar(&self) {
        let child = self.avatar.lock().ok().and_then(|mut avatar| avatar.take());
        if let Some(mut child) = child {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    fn toggle_avatar(&self) -> Result<bool, String> {
        if self.avatar.lock().map_err(|_| "avatar mutex poisoned")?.is_some() {
            self.stop_avatar();
            Ok(false)
        } else {
            self.start_avatar()
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
fn toggle_avatar(app: AppHandle) -> Result<bool, String> {
    app.state::<DesktopState>().toggle_avatar()
}

#[tauri::command]
fn desktop_runtime(app: AppHandle) -> DesktopRuntime {
    app.state::<DesktopState>().runtime()
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| show_main_window(app)))
        .setup(|app| {
            let state = DesktopState::new();
            app.manage(state);
            let state = app.state::<DesktopState>();
            state.start_core(&app.handle()).map_err(std::io::Error::other)?;
            let _ = state.start_avatar();
            create_main_window(&app.handle(), state.runtime())?;
            setup_tray(app)?;
            #[cfg(desktop)]
            app.handle().plugin(
                tauri_plugin_global_shortcut::Builder::new()
                    .with_shortcuts(["CommandOrControl+Shift+N"])?
                    .with_handler(|app, _, event| {
                        if event.state == ShortcutState::Pressed {
                            show_main_window(app);
                        }
                    })
                    .build(),
            )?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![desktop_runtime, restart_core, toggle_avatar])
        .build(tauri::generate_context!())
        .expect("error while building NeuroAsist desktop shell");

    app.run(|app, event| {
            if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
                app.state::<DesktopState>().shutdown();
            }
        });
}

fn create_main_window(app: &AppHandle, runtime: DesktopRuntime) -> tauri::Result<()> {
    let bootstrap = format!("window.__NEUROASIST_DESKTOP_CONFIG__ = {};", serde_json::to_string(&runtime).expect("desktop config serializes"));
    WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("NeuroAsist")
        .inner_size(1120.0, 760.0)
        .min_inner_size(760.0, 540.0)
        .initialization_script(&bootstrap)
        .build()?;
    Ok(())
}

fn setup_tray(app: &tauri::App) -> tauri::Result<()> {
    let show = MenuItemBuilder::with_id("show", "Show NeuroAsist").build(app)?;
    let avatar = MenuItemBuilder::with_id("avatar", "Show / hide avatar").build(app)?;
    let safe_mode = MenuItemBuilder::with_id("safe-mode", "Restart in Safe Mode").build(app)?;
    let quit = MenuItemBuilder::with_id("quit", "Quit").build(app)?;
    let menu = MenuBuilder::new(app).items(&[&show, &avatar, &safe_mode, &quit]).build()?;
    TrayIconBuilder::with_id("companion")
        .tooltip("NeuroAsist companion")
        .menu(&menu)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "show" => show_main_window(app),
            "avatar" => { let _ = app.state::<DesktopState>().toggle_avatar(); }
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

fn core_command(root: &PathBuf) -> Result<Command, String> {
    if let Some(executable) = env::var_os("NEUROASIST_CORE_EXECUTABLE") {
        return Ok(Command::new(executable));
    }
    let python = root.join(".venv").join("Scripts").join("python.exe");
    let mut command = Command::new(if python.exists() { python } else { PathBuf::from("python") });
    command.args(["-m", "apps.backend.desktop_entry"]);
    Ok(command)
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
