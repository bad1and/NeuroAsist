use std::{fs, path::PathBuf, sync::Mutex};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, LogicalSize, Manager, PhysicalPosition, WebviewWindow};

// Design dimensions are logical pixels: Windows display scaling must not
// change the amount of space available to the web interface.
pub const REFERENCE_WIDTH: f64 = 1135.0;
pub const REFERENCE_HEIGHT: f64 = 760.0;
pub const MIN_WIDTH: f64 = 900.0;
pub const MIN_HEIGHT: f64 = 620.0;

#[derive(Clone, Copy, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct Preference {
    #[serde(default)]
    locked: bool,
}

pub struct WindowPreferences {
    path: PathBuf,
    preference: Mutex<Preference>,
    monitor_bounds: Mutex<Option<(Dimensions, Dimensions)>>,
}

impl WindowPreferences {
    pub fn load(path: PathBuf) -> Self {
        let preference = match fs::read(&path) {
            Ok(bytes) => serde_json::from_slice(&bytes).unwrap_or_else(|error| {
                eprintln!("Could not read window preferences: {error}");
                Preference::default()
            }),
            Err(error) => {
                if error.kind() != std::io::ErrorKind::NotFound {
                    eprintln!("Could not read window preferences: {error}");
                }
                Preference::default()
            }
        };
        Self {
            path,
            preference: Mutex::new(preference),
            monitor_bounds: Mutex::new(None),
        }
    }

    pub fn locked(&self) -> bool {
        self.preference.lock().unwrap().locked
    }

    fn save(&self, preference: Preference) -> Result<(), String> {
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        let temporary = self.path.with_extension("json.tmp");
        let bytes = serde_json::to_vec(&preference).map_err(|error| error.to_string())?;
        fs::write(&temporary, bytes).map_err(|error| error.to_string())?;
        fs::rename(&temporary, &self.path).map_err(|error| error.to_string())
    }
}

#[derive(Clone, Copy, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Dimensions {
    pub width: f64,
    pub height: f64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WindowPreferenceStatus {
    locked: bool,
    reference: Dimensions,
    minimum: Dimensions,
    effective_reference: Dimensions,
}

// Leave a small margin for native frame edges, including on high-DPI displays.
pub fn fitted_dimensions(work_width: f64, work_height: f64) -> (Dimensions, Dimensions) {
    let width = (work_width - 16.0).max(1.0);
    let height = (work_height - 16.0).max(1.0);
    (
        Dimensions {
            width: REFERENCE_WIDTH.min(width),
            height: REFERENCE_HEIGHT.min(height),
        },
        Dimensions {
            width: MIN_WIDTH.min(width),
            height: MIN_HEIGHT.min(height),
        },
    )
}

fn dimensions(window: &WebviewWindow) -> Result<(Dimensions, Dimensions), String> {
    let monitor = window
        .current_monitor()
        .map_err(|error| error.to_string())?
        .or(window
            .primary_monitor()
            .map_err(|error| error.to_string())?);
    Ok(match monitor {
        Some(monitor) => {
            let area = monitor.work_area();
            fitted_dimensions(
                area.size.width as f64 / monitor.scale_factor(),
                area.size.height as f64 / monitor.scale_factor(),
            )
        }
        None => fitted_dimensions(REFERENCE_WIDTH + 16.0, REFERENCE_HEIGHT + 16.0),
    })
}

fn status(window: &WebviewWindow, locked: bool) -> Result<WindowPreferenceStatus, String> {
    let (effective_reference, _) = dimensions(window)?;
    Ok(WindowPreferenceStatus {
        locked,
        reference: Dimensions {
            width: REFERENCE_WIDTH,
            height: REFERENCE_HEIGHT,
        },
        minimum: Dimensions {
            width: MIN_WIDTH,
            height: MIN_HEIGHT,
        },
        effective_reference,
    })
}

fn main_window(app: &AppHandle) -> Result<WebviewWindow, String> {
    app.get_webview_window("main")
        .ok_or_else(|| "Iris main window is unavailable".into())
}

pub fn apply(window: &WebviewWindow, locked: bool, reset: bool) -> Result<(), String> {
    let (reference, minimum) = dimensions(window)?;
    let result = (|| -> tauri::Result<()> {
        // Clear the previous fixed bounds before resizing or changing monitors.
        window.set_max_size(None::<LogicalSize<f64>>)?;
        window.set_min_size(Some(LogicalSize::new(minimum.width, minimum.height)))?;
        if reset {
            window.set_fullscreen(false)?;
            window.unmaximize()?;
            window.unminimize()?;
            window.set_size(LogicalSize::new(reference.width, reference.height))?;
            // Preserve the user's position where possible; move only enough to
            // keep the whole window in the current monitor's working area.
            if let Some(monitor) = window.current_monitor()? {
                let area = monitor.work_area();
                let position = window.outer_position()?;
                let size = window.outer_size()?;
                let right = area.position.x + area.size.width.saturating_sub(size.width) as i32;
                let bottom = area.position.y + area.size.height.saturating_sub(size.height) as i32;
                window.set_position(PhysicalPosition::new(
                    position.x.clamp(area.position.x, right),
                    position.y.clamp(area.position.y, bottom),
                ))?;
            }
        }
        if locked {
            let fixed = LogicalSize::new(reference.width, reference.height);
            window.set_min_size(Some(fixed))?;
            window.set_max_size(Some(fixed))?;
        }
        window.set_resizable(!locked)?;
        window.set_maximizable(!locked)?;
        Ok(())
    })();
    result.map_err(|error| error.to_string())?;
    *window
        .app_handle()
        .state::<WindowPreferences>()
        .monitor_bounds
        .lock()
        .unwrap() = Some((reference, minimum));
    Ok(())
}

// Moving on the same monitor must not resize the native window: doing so
// competes with Windows' move loop and with the embedded avatar. Reapply only
// when the monitor's logical working area actually changes.
pub fn refresh_for_monitor(window: &WebviewWindow) {
    let state = window.app_handle().state::<WindowPreferences>();
    let Ok(preference) = state.preference.try_lock() else {
        return;
    };
    let Ok(bounds) = dimensions(window) else {
        return;
    };
    if *state.monitor_bounds.lock().unwrap() == Some(bounds) {
        return;
    }
    if let Err(error) = apply(window, preference.locked, preference.locked) {
        eprintln!("Could not update window bounds for this monitor: {error}");
        return;
    }
    if let Ok(status) = status(window, preference.locked) {
        let _ = window.emit("desktop-window-preferences", &status);
    }
}

#[tauri::command]
pub fn get_window_preferences(app: AppHandle) -> Result<WindowPreferenceStatus, String> {
    status(
        &main_window(&app)?,
        app.state::<WindowPreferences>().locked(),
    )
}

#[tauri::command]
pub fn set_reference_window_locked(
    app: AppHandle,
    locked: bool,
) -> Result<WindowPreferenceStatus, String> {
    let state = app.state::<WindowPreferences>();
    let mut preference = state.preference.lock().unwrap();
    let window = main_window(&app)?;
    let previous = *preference;
    let status = match apply(&window, locked, locked)
        .and_then(|()| status(&window, locked))
        .and_then(|status| state.save(Preference { locked }).map(|()| status))
    {
        Ok(status) => status,
        Err(error) => {
            let _ = apply(&window, previous.locked, previous.locked);
            return Err(error);
        }
    };
    *preference = Preference { locked };
    let _ = window.emit("desktop-window-preferences", &status);
    Ok(status)
}

#[tauri::command]
pub fn reset_reference_window(app: AppHandle) -> Result<WindowPreferenceStatus, String> {
    let state = app.state::<WindowPreferences>();
    let preference = state.preference.lock().unwrap();
    let window = main_window(&app)?;
    apply(&window, preference.locked, true)?;
    let status = status(&window, preference.locked)?;
    let _ = window.emit("desktop-window-preferences", &status);
    Ok(status)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reference_and_minimum_fit_small_and_scaled_work_areas() {
        let (reference, minimum) = fitted_dimensions(1920.0, 1040.0);
        assert_eq!((reference.width, reference.height), (1135.0, 760.0));
        assert_eq!((minimum.width, minimum.height), (900.0, 620.0));
        let (reference, minimum) = fitted_dimensions(1366.0 / 1.5, 728.0 / 1.5);
        assert!(reference.width <= 1366.0 / 1.5);
        assert!(reference.height <= 728.0 / 1.5);
        assert!(minimum.width <= reference.width && minimum.height <= reference.height);
    }

    #[test]
    fn lock_survives_restart_and_unlock_replaces_the_saved_file() {
        let directory =
            std::env::temp_dir().join(format!("iris-window-test-{}", std::process::id()));
        let path = directory.join("window-preferences.json");
        let state = WindowPreferences::load(path.clone());
        assert!(!state.locked());
        state.save(Preference { locked: true }).unwrap();
        assert!(WindowPreferences::load(path.clone()).locked());
        state.save(Preference { locked: false }).unwrap();
        assert!(!WindowPreferences::load(path).locked());
        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn corrupt_or_old_preferences_do_not_prevent_startup() {
        assert!(!serde_json::from_str::<Preference>("{}").unwrap().locked);
        assert!(serde_json::from_str::<Preference>(r#"{"locked":"true"}"#).is_err());
    }

    // Opt-in because this test creates a real Windows window. It uses a blank
    // webview and its own preferences file; no core, avatar, or user data starts.
    #[cfg(windows)]
    #[test]
    #[ignore]
    #[allow(deprecated)]
    fn native_window_lock_reset_and_unlock() {
        use windows::Win32::{
            Foundation::{LPARAM, WPARAM},
            UI::WindowsAndMessaging::{SendMessageW, MINMAXINFO, WM_GETMINMAXINFO},
        };
        let directory =
            std::env::temp_dir().join(format!("iris-native-window-test-{}", std::process::id()));
        let path = directory.join("window-preferences.json");
        let mut app = tauri::Builder::default()
            .any_thread()
            .setup(move |app| {
                app.manage(WindowPreferences::load(path));
                tauri::WebviewWindowBuilder::new(
                    app,
                    "main",
                    tauri::WebviewUrl::External("about:blank".parse().unwrap()),
                )
                .decorations(false)
                .visible(false)
                .inner_size(REFERENCE_WIDTH, REFERENCE_HEIGHT)
                .build()?;
                Ok(())
            })
            .build(tauri::generate_context!())
            .unwrap();
        let pump = |app: &mut tauri::App| {
            for _ in 0..12 {
                app.run_iteration(|_, _| {});
                std::thread::sleep(std::time::Duration::from_millis(10));
            }
        };
        pump(&mut app);
        let window = main_window(app.handle()).unwrap();
        apply(&window, false, true).unwrap();
        pump(&mut app);
        let (reference, minimum) = dimensions(&window).unwrap();
        let logical_size = || {
            window
                .inner_size()
                .unwrap()
                .to_logical::<f64>(window.scale_factor().unwrap())
        };
        let tracking_bounds = || {
            let mut info = MINMAXINFO::default();
            unsafe {
                SendMessageW(
                    window.hwnd().unwrap(),
                    WM_GETMINMAXINFO,
                    Some(WPARAM(0)),
                    Some(LPARAM((&mut info as *mut MINMAXINFO) as isize)),
                );
            }
            info
        };
        // Native tracking bounds govern mouse/keyboard resizing. Explicit
        // programmatic set_size calls intentionally bypass these constraints.
        let bounds = tracking_bounds();
        let scale = window.scale_factor().unwrap();
        assert!(bounds.ptMinTrackSize.x as f64 / scale >= minimum.width - 1.0);
        assert!(bounds.ptMinTrackSize.y as f64 / scale >= minimum.height - 1.0);
        window.maximize().unwrap();
        pump(&mut app);
        assert!(window.is_maximized().unwrap());
        reset_reference_window(app.handle().clone()).unwrap();
        pump(&mut app);
        assert!(!window.is_maximized().unwrap());
        assert!((logical_size().width - reference.width).abs() <= 1.0);
        assert!((logical_size().height - reference.height).abs() <= 1.0);
        set_reference_window_locked(app.handle().clone(), true).unwrap();
        pump(&mut app);
        assert!(!window.is_resizable().unwrap());
        assert!(!window.is_maximizable().unwrap());
        assert!(get_window_preferences(app.handle().clone()).unwrap().locked);
        let bounds = tracking_bounds();
        assert_eq!(bounds.ptMinTrackSize.x, bounds.ptMaxTrackSize.x);
        assert_eq!(bounds.ptMinTrackSize.y, bounds.ptMaxTrackSize.y);
        reset_reference_window(app.handle().clone()).unwrap();
        pump(&mut app);
        assert!(get_window_preferences(app.handle().clone()).unwrap().locked);
        set_reference_window_locked(app.handle().clone(), false).unwrap();
        pump(&mut app);
        assert!(window.is_resizable().unwrap());
        assert!(window.is_maximizable().unwrap());
        window
            .set_size(LogicalSize::new(
                reference.width - 50.0,
                reference.height - 30.0,
            ))
            .unwrap();
        pump(&mut app);
        assert!(logical_size().width < reference.width - 1.0);
        // Force an actual atomic-replace failure in this test's isolated file.
        let saved_path = app.state::<WindowPreferences>().path.clone();
        fs::remove_file(&saved_path).unwrap();
        fs::create_dir(&saved_path).unwrap();
        assert!(set_reference_window_locked(app.handle().clone(), true).is_err());
        pump(&mut app);
        assert!(window.is_resizable().unwrap());
        assert!(window.is_maximizable().unwrap());
        assert!(!get_window_preferences(app.handle().clone()).unwrap().locked);
        window.close().unwrap();
        pump(&mut app);
        fs::remove_dir_all(directory).unwrap();
    }
}
