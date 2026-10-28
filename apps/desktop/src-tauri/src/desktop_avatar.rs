//! Independent desktop host. Only this controller writes the Unity HWND bounds.
use crate::DesktopState;
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex,
    },
    thread,
    time::{Duration, Instant},
};
use tauri::{
    AppHandle, Emitter, Manager, PhysicalPosition, PhysicalSize, WebviewUrl, WebviewWindowBuilder,
};

#[derive(Clone, Copy, Debug, Default, Deserialize, Serialize, PartialEq)]
pub struct Rect {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}
impl Rect {
    fn contains(&self, x: f64, y: f64) -> bool {
        x >= self.x && y >= self.y && x < self.x + self.width && y < self.y + self.height
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct Layout {
    pub monitor: String,
    pub x_ratio: f64,
    pub y_ratio: f64,
    pub height_dip: f64,
}
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct Monitor {
    pub id: String,
    pub name: String,
    pub area: Rect,
    pub scale: f64,
    pub primary: bool,
}

#[derive(Clone, Deserialize)]
#[serde(default)]
pub struct Config {
    pub visible: bool,
    pub always_on_top: bool,
    pub locked: bool,
    pub desktop_mode: String,
    pub layouts: HashMap<String, Layout>,
    pub monitor: String,
    pub x: f64,
    pub y: f64,
    pub height: f64,
}
impl Default for Config {
    fn default() -> Self {
        Self {
            visible: true,
            always_on_top: true,
            locked: true,
            desktop_mode: "waist".into(),
            layouts: HashMap::new(),
            monitor: "primary".into(),
            x: 80.,
            y: 80.,
            height: 720.,
        }
    }
}

#[derive(Clone, Serialize, PartialEq)]
pub struct Geometry {
    pub desktop_mode: String,
    pub monitor: Monitor,
    pub rect: Rect,
    pub layout: Layout,
    pub transforming: bool,
    pub commit: bool,
}
#[derive(Clone)]
struct Gesture {
    kind: String,
    cursor: (f64, f64),
    rect: Rect,
}
#[derive(Default)]
struct Inner {
    config: Config,
    geometry: Option<Geometry>,
    regions: Vec<Rect>,
    gesture: Option<Gesture>,
    window: Option<usize>,
    active: bool,
    click_through: Option<bool>,
    hovered: Option<bool>,
    topology: Vec<Monitor>,
    last_topology_check: Option<Instant>,
}
#[derive(Default)]
pub struct DesktopAvatarState {
    inner: Mutex<Inner>,
    polling: AtomicBool,
}

#[cfg(windows)]
fn monitor_identity(device: &str) -> (String, String) {
    use windows::{
        core::PCWSTR,
        Win32::{
            Graphics::Gdi::{EnumDisplayDevicesW, DISPLAY_DEVICEW},
            UI::WindowsAndMessaging::EDD_GET_DEVICE_INTERFACE_NAME,
        },
    };
    let wide: Vec<u16> = device.encode_utf16().chain(Some(0)).collect();
    let mut display = DISPLAY_DEVICEW::default();
    display.cb = std::mem::size_of::<DISPLAY_DEVICEW>() as u32;
    if unsafe {
        EnumDisplayDevicesW(
            PCWSTR(wide.as_ptr()),
            0,
            &mut display,
            EDD_GET_DEVICE_INTERFACE_NAME,
        )
    }
    .as_bool()
    {
        let read = |chars: &[u16]| {
            String::from_utf16_lossy(
                &chars[..chars.iter().position(|&c| c == 0).unwrap_or(chars.len())],
            )
        };
        let id = read(&display.DeviceID);
        let label = read(&display.DeviceString);
        if !id.is_empty() {
            return (
                id,
                if label.is_empty() {
                    device.into()
                } else {
                    label
                },
            );
        }
    }
    (device.into(), device.into())
}
#[cfg(not(windows))]
fn monitor_identity(device: &str) -> (String, String) {
    (device.into(), device.into())
}

pub fn monitors(app: &AppHandle) -> Result<Vec<Monitor>, String> {
    let primary = app
        .primary_monitor()
        .map_err(|e| e.to_string())?
        .map(|m| m.position().to_owned());
    Ok(app
        .available_monitors()
        .map_err(|e| e.to_string())?
        .into_iter()
        .map(|m| {
            let a = m.work_area();
            let name = m
                .name()
                .cloned()
                .unwrap_or_else(|| format!("{}:{}", a.position.x, a.position.y));
            let (id, name) = monitor_identity(&name);
            Monitor {
                id,
                name,
                scale: m.scale_factor(),
                primary: primary.as_ref() == Some(m.position()),
                area: Rect {
                    x: a.position.x as f64,
                    y: a.position.y as f64,
                    width: a.size.width as f64,
                    height: a.size.height as f64,
                },
            }
        })
        .collect())
}

fn ratio(value: f64, available: f64) -> f64 {
    if available > 0. {
        (value / available).clamp(0., 1.)
    } else {
        0.
    }
}
fn aspect(mode: &str) -> f64 {
    if mode == "full_body" {
        0.58
    } else {
        0.88
    }
}

pub fn resolve(config: &Config, monitors: &[Monitor]) -> Option<Geometry> {
    let saved = config.layouts.get(&config.desktop_mode);
    let requested = saved.map(|s| s.monitor.as_str()).unwrap_or(&config.monitor);
    let monitor = monitors
        .iter()
        .find(|m| m.id == requested)
        .or_else(|| monitors.iter().find(|m| m.primary))
        .or_else(|| monitors.first())?
        .clone();
    let a = monitor.area;
    let default_height = if config.desktop_mode == "full_body" {
        a.height * 0.7 / monitor.scale
    } else {
        config.height / monitor.scale
    };
    let mut layout = saved.cloned().unwrap_or_else(|| Layout {
        monitor: monitor.id.clone(),
        x_ratio: ratio(
            config.x - a.x,
            a.width - default_height * monitor.scale * aspect(&config.desktop_mode),
        ),
        y_ratio: 1.,
        height_dip: default_height,
    });
    layout.monitor = monitor.id.clone();
    layout.height_dip = layout
        .height_dip
        .clamp(160., (a.height / monitor.scale).max(160.));
    let height = (layout.height_dip * monitor.scale).min(a.height);
    let width = (height * aspect(&config.desktop_mode)).min(a.width);
    let rect = Rect {
        x: a.x + layout.x_ratio.clamp(0., 1.) * (a.width - width),
        y: a.y
            + if config.desktop_mode == "waist" {
                a.height - height
            } else {
                layout.y_ratio.clamp(0., 1.) * (a.height - height)
            },
        width,
        height,
    };
    Some(Geometry {
        desktop_mode: config.desktop_mode.clone(),
        monitor,
        rect,
        layout,
        transforming: false,
        commit: false,
    })
}

pub fn create_host(app: &AppHandle) -> Result<(), String> {
    if app.get_webview_window("desktop_avatar").is_none() {
        let bootstrap = format!("window.__NEUROASIST_DESKTOP_CONFIG__ = {}; window.__IRIS_VIEW__ = 'desktop-avatar'; document.addEventListener('DOMContentLoaded', () => document.body.classList.add('desktop-avatar-body'));",
            serde_json::to_string(&app.state::<DesktopState>().runtime()).map_err(|e| e.to_string())?);
        WebviewWindowBuilder::new(app, "desktop_avatar", WebviewUrl::App("index.html".into()))
            .title("Iris")
            .decorations(false)
            .transparent(true)
            .background_color(tauri::window::Color(0, 0, 0, 0))
            .shadow(false)
            .skip_taskbar(true)
            .resizable(false)
            .zoom_hotkeys_enabled(false)
            .visible(false)
            .focused(false)
            .always_on_top(true)
            .initialization_script(&bootstrap)
            .build()
            .map_err(|e| e.to_string())?;
    }
    let state = app.state::<DesktopAvatarState>();
    state.inner.lock().unwrap().active = true;
    if !state.polling.swap(true, Ordering::SeqCst) {
        let app = app.clone();
        thread::spawn(move || loop {
            let state = app.state::<DesktopAvatarState>();
            if app.get_webview_window("desktop_avatar").is_none() {
                state.polling.store(false, Ordering::SeqCst);
                break;
            }
            tick(&app);
            let delay = {
                let inner = state.inner.lock().unwrap();
                if !inner.active || !inner.config.visible {
                    250
                } else if inner.gesture.is_some() {
                    16
                } else {
                    50
                }
            };
            thread::sleep(Duration::from_millis(delay));
        });
    }
    Ok(())
}

pub fn detach(app: &AppHandle) {
    let state = app.state::<DesktopAvatarState>();
    let mut inner = state.inner.lock().unwrap();
    inner.active = false;
    inner.window = None;
    inner.gesture = None;
    inner.regions.clear();
    inner.click_through = None;
    inner.hovered = None;
    if let Some(host) = app.get_webview_window("desktop_avatar") {
        let _ = host.hide();
    }
}

pub fn attach(app: &AppHandle, window: usize) -> Result<(), String> {
    crate::attach_native_avatar_window(app, window, "desktop_avatar")?;
    app.state::<DesktopAvatarState>()
        .inner
        .lock()
        .unwrap()
        .window = Some(window);
    apply(app)
}

fn apply(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<DesktopAvatarState>();
    // Native Tauri operations can wait for the UI thread. Never hold the
    // controller mutex while dispatching: an IPC handler may need that mutex.
    let (config, geometry, window, active) = {
        let inner = state.inner.lock().unwrap();
        (
            inner.config.clone(),
            inner.geometry.clone(),
            inner.window,
            inner.active,
        )
    };
    if !active {
        return Ok(());
    }
    let Some(g) = geometry.as_ref() else {
        return Ok(());
    };
    let Some(host) = app.get_webview_window("desktop_avatar") else {
        return Ok(());
    };
    let a = g.monitor.area;
    // Host coordinates are physical; React receives only monitor-local DIPs.
    if host.outer_position().ok() != Some(PhysicalPosition::new(a.x as i32, a.y as i32)) {
        host.set_position(PhysicalPosition::new(a.x as i32, a.y as i32))
            .map_err(|e| e.to_string())?;
    }
    if host.inner_size().ok() != Some(PhysicalSize::new(a.width as u32, a.height as u32)) {
        host.set_size(PhysicalSize::new(a.width as u32, a.height as u32))
            .map_err(|e| e.to_string())?;
    }
    if host.is_always_on_top().ok() != Some(config.always_on_top) {
        host.set_always_on_top(config.always_on_top)
            .map_err(|e| e.to_string())?;
    }
    let show = config.visible && window.is_some();
    if host.is_visible().ok() != Some(show) {
        // Keep the native window and WebView2 visibility lifecycle aligned.
        if show {
            let _ = host.show();
        } else {
            let _ = host.hide();
        }
    }
    #[cfg(windows)]
    if let Some(window) = window {
        use windows::Win32::{Foundation::HWND, UI::WindowsAndMessaging::*};
        let r = g.rect;
        unsafe {
            SetWindowPos(
                HWND(window as *mut _),
                Some(if config.always_on_top {
                    HWND_TOPMOST
                } else {
                    HWND_NOTOPMOST
                }),
                r.x.round() as i32,
                r.y.round() as i32,
                r.width.round() as i32,
                r.height.round() as i32,
                SWP_NOACTIVATE,
            )
            .map_err(|e| e.to_string())?;
            let _ = ShowWindow(
                HWND(window as *mut _),
                if show { SW_SHOWNA } else { SW_HIDE },
            );
        }
    }
    app.emit_to("desktop_avatar", "desktop-avatar-geometry", g)
        .map_err(|e| e.to_string())?;
    Ok(())
}

fn tick(app: &AppHandle) {
    #[cfg(windows)]
    {
        use windows::Win32::{
            Foundation::POINT,
            UI::{
                Input::KeyboardAndMouse::{GetAsyncKeyState, VK_LBUTTON},
                WindowsAndMessaging::GetCursorPos,
            },
        };
        let state = app.state::<DesktopAvatarState>();
        // Monitor enumeration may dispatch to the event loop too.
        let (active, check_topology, moving) = {
            let inner = state.inner.lock().unwrap();
            (
                inner.active && inner.config.visible,
                inner
                    .last_topology_check
                    .map_or(true, |last| last.elapsed() > Duration::from_secs(2)),
                inner.gesture.is_some(),
            )
        };
        if !active {
            return;
        }
        let mut point = POINT::default();
        if unsafe { GetCursorPos(&mut point) }.is_err() {
            return;
        }
        // Display enumeration can dispatch to the UI thread. Use the cached
        // topology during gestures instead of doing this for every frame.
        let displays = if check_topology && !moving {
            monitors(app).ok()
        } else {
            None
        };
        let mut inner = state.inner.lock().unwrap();
        if !inner.active {
            return;
        }
        let pressed = unsafe { GetAsyncKeyState(VK_LBUTTON.0 as i32) } < 0;
        let mut changed = false;
        if inner.gesture.is_none()
            && inner
                .last_topology_check
                .map_or(true, |last| last.elapsed() > Duration::from_secs(2))
        {
            inner.last_topology_check = Some(Instant::now());
            if let Some(displays) = displays.as_ref() {
                if inner.topology != *displays {
                    inner.geometry = resolve(&inner.config, displays);
                    inner.topology = displays.clone();
                    changed = true;
                }
            }
        }
        let gesture_displays = inner.topology.clone();
        if let (Some(gesture), Some(mut g)) = (inner.gesture.clone(), inner.geometry.clone()) {
            let dx = point.x as f64 - gesture.cursor.0;
            let dy = point.y as f64 - gesture.cursor.1;
            if gesture.kind == "resize" {
                let a = aspect(&g.desktop_mode);
                let desired =
                    (gesture.rect.height + (dx * a - dy) / (a * a + 1.)) / g.monitor.scale;
                g.layout.height_dip = desired.clamp(160., g.monitor.area.height / g.monitor.scale);
                // Keep the bottom centre still during proportional resizing.
                let h = g.layout.height_dip * g.monitor.scale;
                let w = h * aspect(&g.desktop_mode);
                g.layout.x_ratio = ratio(
                    gesture.rect.x + gesture.rect.width / 2. - w / 2. - g.monitor.area.x,
                    g.monitor.area.width - w,
                );
                g.layout.y_ratio = ratio(
                    gesture.rect.y + gesture.rect.height - h - g.monitor.area.y,
                    g.monitor.area.height - h,
                );
            } else {
                let x = gesture.rect.x + dx;
                let y = gesture.rect.y + dy;
                if g.desktop_mode == "full_body" {
                    if let Some(next) = gesture_displays
                        .iter()
                        .find(|m| m.area.contains(point.x as f64, point.y as f64))
                    {
                        g.monitor = next.clone();
                    }
                }
                let h = (g.layout.height_dip * g.monitor.scale).min(g.monitor.area.height);
                let w = h * aspect(&g.desktop_mode);
                g.layout.x_ratio = ratio(x - g.monitor.area.x, g.monitor.area.width - w);
                g.layout.y_ratio = if g.desktop_mode == "waist" {
                    1.
                } else {
                    ratio(y - g.monitor.area.y, g.monitor.area.height - h)
                };
            }
            g.layout.monitor = g.monitor.id.clone();
            inner
                .config
                .layouts
                .insert(g.desktop_mode.clone(), g.layout);
            if let Some(mut next) = resolve(&inner.config, &[g.monitor]) {
                next.transforming = pressed;
                next.commit = !pressed;
                if inner.geometry.as_ref() != Some(&next) {
                    inner.geometry = Some(next);
                    changed = true;
                }
            }
            if !pressed {
                inner.gesture = None;
            }
        }
        let mut hover_event = None;
        let mut click_through_event = None;
        if let Some(g) = inner.geometry.as_ref() {
            let x = (point.x as f64 - g.monitor.area.x) / g.monitor.scale;
            let y = (point.y as f64 - g.monitor.area.y) / g.monitor.scale;
            let interactive =
                inner.gesture.is_some() || inner.regions.iter().any(|r| r.contains(x, y));
            let hovered = interactive || g.rect.contains(point.x as f64, point.y as f64);
            if inner.hovered != Some(hovered) {
                inner.hovered = Some(hovered);
                hover_event = Some(hovered);
            }
            // This is independent from the geometry lock: hover/buttons must still work.
            if inner.click_through != Some(!interactive) {
                inner.click_through = Some(!interactive);
                click_through_event = Some(!interactive);
            }
        }
        drop(inner);
        if let Some(hovered) = hover_event {
            let _ = app.emit_to("desktop_avatar", "desktop-avatar-hover", hovered);
        }
        if let (Some(ignore), Some(host)) = (
            click_through_event,
            app.get_webview_window("desktop_avatar"),
        ) {
            if host.set_ignore_cursor_events(ignore).is_err() {
                state.inner.lock().unwrap().click_through = None;
            }
        }
        if changed {
            let _ = apply(app);
        }
    }
}

#[tauri::command]
pub fn get_desktop_avatar_monitors(app: AppHandle) -> Result<Vec<Monitor>, String> {
    monitors(&app)
}

#[tauri::command]
pub fn configure_desktop_avatar(
    app: AppHandle,
    config: Config,
) -> Result<Option<Geometry>, String> {
    let visible = config.visible;
    if !matches!(config.desktop_mode.as_str(), "waist" | "full_body") {
        return Err("Unknown desktop avatar mode".into());
    }
    for layout in config.layouts.values() {
        if !layout.height_dip.is_finite()
            || !layout.x_ratio.is_finite()
            || !layout.y_ratio.is_finite()
        {
            return Err("Invalid avatar geometry".into());
        }
    }
    let displays = monitors(&app)?;
    let geometry = resolve(&config, &displays);
    {
        let state = app.state::<DesktopAvatarState>();
        let mut inner = state.inner.lock().unwrap();
        inner.gesture = None;
        inner.config = config;
        inner.geometry = geometry.clone();
        inner.topology = displays;
        inner.last_topology_check = Some(Instant::now());
    }
    let desktop = app.state::<DesktopState>();
    let active = desktop
        .avatar
        .lock()
        .map_err(|_| "avatar mutex poisoned")?
        .as_ref()
        .is_some_and(|process| process.placement == crate::AvatarPlacement::DesktopOverlay);
    if active {
        let changed = {
            let mut current = desktop
                .avatar_visible
                .lock()
                .map_err(|_| "avatar visibility mutex poisoned")?;
            let changed = *current != visible;
            *current = visible;
            changed
        };
        if changed {
            desktop.emit_avatar_status(&app);
        }
    }
    apply(&app)?;
    Ok(geometry)
}

#[tauri::command]
pub fn set_desktop_avatar_regions(app: AppHandle, regions: Vec<Rect>) -> Result<(), String> {
    if regions.len() > 24
        || regions
            .iter()
            .any(|r| ![r.x, r.y, r.width, r.height].iter().all(|v| v.is_finite()))
    {
        return Err("Invalid interactive regions".into());
    }
    app.state::<DesktopAvatarState>()
        .inner
        .lock()
        .unwrap()
        .regions = regions;
    Ok(())
}

#[tauri::command]
pub fn begin_desktop_avatar_transform(app: AppHandle, kind: String) -> Result<(), String> {
    #[cfg(windows)]
    {
        use windows::Win32::{Foundation::POINT, UI::WindowsAndMessaging::GetCursorPos};
        let mut p = POINT::default();
        unsafe { GetCursorPos(&mut p) }.map_err(|e| e.to_string())?;
        let state = app.state::<DesktopAvatarState>();
        let mut inner = state.inner.lock().unwrap();
        if inner.config.locked {
            return Err("Avatar placement is locked".into());
        }
        if !matches!(kind.as_str(), "move" | "resize") {
            return Err("Unknown transform".into());
        }
        if let Some(g) = &inner.geometry {
            inner.gesture = Some(Gesture {
                kind,
                cursor: (p.x as f64, p.y as f64),
                rect: g.rect,
            });
        }
        Ok(())
    }
    #[cfg(not(windows))]
    {
        let _ = (app, kind);
        Err("Desktop avatar is supported on Windows".into())
    }
}

#[tauri::command]
pub fn desktop_avatar_command(app: AppHandle, command: serde_json::Value) -> Result<(), String> {
    app.emit_to("main", "desktop-avatar-command", command)
        .map_err(|e| e.to_string())
}
#[tauri::command]
pub fn desktop_avatar_snapshot(app: AppHandle, snapshot: serde_json::Value) -> Result<(), String> {
    app.emit_to("desktop_avatar", "desktop-avatar-conversation", snapshot)
        .map_err(|e| e.to_string())
}
#[tauri::command]
pub fn open_main_from_avatar(app: AppHandle) {
    crate::show_main_window(&app);
    let _ = app.emit_to("main", "desktop-avatar-open-chat", ());
}

#[cfg(test)]
mod tests {
    use super::*;
    fn display() -> Monitor {
        Monitor {
            id: "left".into(),
            name: "Left".into(),
            area: Rect {
                x: -1920.,
                y: 0.,
                width: 1920.,
                height: 1040.,
            },
            scale: 1.5,
            primary: true,
        }
    }
    #[test]
    fn waist_always_uses_work_area_bottom() {
        let c = Config::default();
        let g = resolve(&c, &[display()]).unwrap();
        assert_eq!(g.rect.y + g.rect.height, 1040.);
        assert!(g.rect.x >= -1920.);
    }
    #[test]
    fn mode_layouts_are_independent_and_dpi_is_applied_once() {
        let mut c = Config::default();
        c.desktop_mode = "full_body".into();
        c.layouts.insert(
            "full_body".into(),
            Layout {
                monitor: "left".into(),
                x_ratio: 0.25,
                y_ratio: 0.3,
                height_dip: 400.,
            },
        );
        let g = resolve(&c, &[display()]).unwrap();
        assert_eq!(g.rect.height, 600.);
        assert_eq!(g.rect.y, 132.);
        assert_eq!(g.layout.height_dip, 400.);
    }
    #[test]
    fn missing_monitor_falls_back_and_large_avatar_fits() {
        let mut c = Config::default();
        c.layouts.insert(
            "waist".into(),
            Layout {
                monitor: "unplugged".into(),
                x_ratio: 1.,
                y_ratio: 0.,
                height_dip: 2000.,
            },
        );
        let g = resolve(&c, &[display()]).unwrap();
        assert_eq!(g.layout.monitor, "left");
        assert!(g.rect.height <= 1040.);
        assert!(g.rect.x + g.rect.width <= 0.);
    }
}
