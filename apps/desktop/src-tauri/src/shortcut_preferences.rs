use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    fs,
    path::PathBuf,
    str::FromStr,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
};
use tauri::{AppHandle, Manager};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

const ACTIONS: [&str; 2] = ["showWindow", "toggleAvatar"];
type Bindings = BTreeMap<String, Option<String>>;

#[derive(Clone, Serialize)]
pub struct ShortcutStatus {
    bindings: Bindings,
    errors: BTreeMap<String, String>,
}

struct Inner {
    status: ShortcutStatus,
    active: Bindings,
    recording: bool,
}

pub struct ShortcutPreferences {
    path: PathBuf,
    inner: Mutex<Inner>,
}

#[derive(Deserialize, Serialize)]
struct Saved {
    bindings: Bindings,
}

fn defaults() -> Bindings {
    ACTIONS
        .into_iter()
        .map(|id| (id.to_owned(), None))
        .collect()
}

fn validate(bindings: &Bindings) -> Result<(), String> {
    if bindings.len() != ACTIONS.len() || ACTIONS.iter().any(|id| !bindings.contains_key(*id)) {
        return Err("Неизвестная команда сочетания клавиш.".into());
    }
    let mut used = std::collections::HashSet::new();
    for chord in bindings.values().flatten() {
        let parts: Vec<_> = chord.split('+').collect();
        if parts.first() != Some(&"Ctrl") || parts.len() < 2 || parts.len() > 4 {
            return Err("Используйте Ctrl и клавишу.".into());
        }
        let modifiers = &parts[..parts.len() - 1];
        let canonical: Vec<_> = ["Ctrl", "Shift", "Alt"]
            .into_iter()
            .filter(|key| modifiers.contains(key))
            .collect();
        if canonical != modifiers || (modifiers.contains(&"Alt") && !modifiers.contains(&"Shift")) {
            return Err("Для Ctrl+Alt добавьте Shift, чтобы не мешать AltGr.".into());
        }
        let key = parts[parts.len() - 1];
        let supported = (key.len() == 4
            && key.starts_with("Key")
            && key.as_bytes()[3].is_ascii_uppercase())
            || (key.len() == 6 && key.starts_with("Digit") && key.as_bytes()[5].is_ascii_digit())
            || key
                .strip_prefix('F')
                .and_then(|n| n.parse::<u8>().ok())
                .is_some_and(|n| (1..=12).contains(&n))
            || [
                "Comma",
                "Period",
                "Slash",
                "Semicolon",
                "Quote",
                "BracketLeft",
                "BracketRight",
                "Backslash",
                "Minus",
                "Equal",
                "Space",
            ]
            .contains(&key);
        if !supported {
            return Err("Неподдерживаемая клавиша.".into());
        }
        if [
            "Ctrl+KeyA",
            "Ctrl+KeyC",
            "Ctrl+KeyV",
            "Ctrl+KeyX",
            "Ctrl+KeyZ",
            "Ctrl+KeyY",
            "Ctrl+KeyS",
            "Ctrl+KeyF",
            "Ctrl+KeyP",
            "Ctrl+KeyO",
            "Ctrl+KeyN",
            "Ctrl+KeyW",
            "Ctrl+KeyT",
            "Ctrl+KeyR",
            "Ctrl+KeyL",
            "Ctrl+KeyU",
            "Ctrl+Shift+KeyZ",
            "Ctrl+Shift+KeyV",
            "Ctrl+Shift+KeyT",
            "Ctrl+Shift+KeyW",
            "Ctrl+Shift+KeyN",
            "Ctrl+Shift+KeyR",
            "Ctrl+Shift+KeyI",
            "Ctrl+Shift+KeyJ",
            "Ctrl+Shift+KeyC",
            "Ctrl+Shift+KeyO",
            "Ctrl+F4",
            "Ctrl+Shift+F4",
        ]
        .contains(&chord.as_str())
        {
            return Err("Это стандартное сочетание для текста, браузера или окна.".into());
        }
        Shortcut::from_str(chord).map_err(|error| error.to_string())?;
        if !used.insert(chord) {
            return Err("Это сочетание уже назначено другой команде.".into());
        }
    }
    Ok(())
}

impl ShortcutPreferences {
    pub fn load(path: PathBuf) -> Self {
        let mut errors = BTreeMap::new();
        let bindings = match fs::read(&path) {
            Ok(bytes) => match serde_json::from_slice::<Saved>(&bytes) {
                Ok(saved) if validate(&saved.bindings).is_ok() => saved.bindings,
                _ => {
                    errors.insert(
                        "showWindow".into(),
                        "Не удалось прочитать сохранённые сочетания. Назначьте их заново.".into(),
                    );
                    defaults()
                }
            },
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => defaults(),
            Err(error) => {
                errors.insert(
                    "showWindow".into(),
                    format!("Не удалось прочитать сочетания: {error}"),
                );
                defaults()
            }
        };
        Self {
            path,
            inner: Mutex::new(Inner {
                status: ShortcutStatus { bindings, errors },
                active: defaults(),
                recording: false,
            }),
        }
    }

    fn unregister(app: &AppHandle, inner: &mut Inner) -> Result<(), String> {
        for id in ACTIONS {
            if let Some(chord) = inner.active.get(id).and_then(Clone::clone) {
                app.global_shortcut()
                    .unregister(chord.as_str())
                    .map_err(|error| error.to_string())?;
                inner.active.insert(id.into(), None);
            }
        }
        Ok(())
    }

    fn register(app: &AppHandle, inner: &mut Inner) {
        for id in ACTIONS {
            if let Some(active) = inner.active.get(id).and_then(|value| value.as_ref()) {
                if inner
                    .status
                    .bindings
                    .get(id)
                    .and_then(|value| value.as_ref())
                    != Some(active)
                {
                    inner.status.errors.insert(
                        id.into(),
                        "Не удалось снять предыдущую системную привязку. Повторите подключение."
                            .into(),
                    );
                    continue;
                }
            }
            let Some(chord) = inner.status.bindings.get(id).and_then(Clone::clone) else {
                continue;
            };
            if inner.active.get(id).and_then(|value| value.as_ref()) == Some(&chord) {
                continue;
            }
            let pressed = Arc::new(AtomicBool::new(false));
            let result = app
                .global_shortcut()
                .on_shortcut(chord.as_str(), move |app, _, event| {
                    if event.state == ShortcutState::Released {
                        pressed.store(false, Ordering::Relaxed);
                        return;
                    }
                    if pressed.swap(true, Ordering::Relaxed) {
                        return;
                    }
                    if id == "toggleAvatar" {
                        let _ = app.state::<crate::DesktopState>().toggle_avatar(app);
                    } else {
                        crate::show_main_window(app);
                    }
                });
            match result {
                Ok(()) => {
                    inner.active.insert(id.into(), Some(chord));
                    inner.status.errors.remove(id);
                }
                Err(error) => {
                    inner.status.errors.insert(
                        id.into(),
                        format!("Сочетание занято или недоступно в Windows: {error}"),
                    );
                }
            }
        }
    }

    pub fn start(&self, app: &AppHandle) {
        if let Ok(mut inner) = self.inner.lock() {
            Self::register(app, &mut inner);
        }
    }

    pub fn restore_after_focus_loss(&self, app: &AppHandle) {
        if let Ok(mut inner) = self.inner.try_lock() {
            if inner.recording {
                inner.recording = false;
                Self::register(app, &mut inner);
            }
        }
    }

    fn save(&self, bindings: &Bindings) -> Result<(), String> {
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        let temp = self.path.with_extension("json.tmp");
        fs::write(
            &temp,
            serde_json::to_vec(&Saved {
                bindings: bindings.clone(),
            })
            .map_err(|error| error.to_string())?,
        )
        .map_err(|error| error.to_string())?;
        fs::rename(temp, &self.path).map_err(|error| error.to_string())
    }
}

#[tauri::command]
pub fn get_shortcut_preferences(app: AppHandle) -> Result<ShortcutStatus, String> {
    let state = app.state::<ShortcutPreferences>();
    let inner = state.inner.lock().map_err(|error| error.to_string())?;
    Ok(inner.status.clone())
}

#[tauri::command]
pub fn set_shortcut_preferences(
    app: AppHandle,
    bindings: Bindings,
) -> Result<ShortcutStatus, String> {
    validate(&bindings)?;
    let state = app.state::<ShortcutPreferences>();
    let mut inner = state.inner.lock().map_err(|error| error.to_string())?;
    let previous = inner.status.clone();
    if let Err(error) = ShortcutPreferences::unregister(&app, &mut inner) {
        if !inner.recording {
            ShortcutPreferences::register(&app, &mut inner);
        }
        return Err(error);
    }
    inner.status = ShortcutStatus {
        bindings,
        errors: BTreeMap::new(),
    };
    // Registration is tested even while the recorder is open, before persistence.
    ShortcutPreferences::register(&app, &mut inner);
    let registration_error = inner.status.errors.values().next().cloned();
    let result = registration_error.map_or_else(|| state.save(&inner.status.bindings), Err);
    if let Err(error) = result {
        let cleanup = ShortcutPreferences::unregister(&app, &mut inner);
        inner.status = previous;
        if !inner.recording {
            ShortcutPreferences::register(&app, &mut inner);
        }
        if let Err(cleanup_error) = cleanup {
            inner.status.errors.insert("showWindow".into(), format!("Не удалось снять предыдущую системную привязку. Повторите подключение. {cleanup_error}"));
            return Err(format!("{error}. {cleanup_error}"));
        }
        return Err(error);
    }
    inner.recording = false;
    Ok(inner.status.clone())
}

#[tauri::command]
pub fn set_shortcut_recording(app: AppHandle, recording: bool) -> Result<ShortcutStatus, String> {
    let state = app.state::<ShortcutPreferences>();
    let mut inner = state.inner.lock().map_err(|error| error.to_string())?;
    if recording {
        if let Err(error) = ShortcutPreferences::unregister(&app, &mut inner) {
            if !inner.recording {
                ShortcutPreferences::register(&app, &mut inner);
            }
            return Err(error);
        }
    }
    inner.recording = recording;
    if !recording {
        ShortcutPreferences::register(&app, &mut inner);
    }
    Ok(inner.status.clone())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn accepts_disabled_and_physical_keys() {
        assert!(validate(&defaults()).is_ok());
        let mut bindings = defaults();
        bindings.insert("showWindow".into(), Some("Ctrl+Shift+KeyK".into()));
        bindings.insert("toggleAvatar".into(), Some("Ctrl+Shift+Alt+F9".into()));
        assert!(validate(&bindings).is_ok());
    }
    #[test]
    fn rejects_text_system_altgr_and_duplicates() {
        for invalid in [
            "KeyM",
            "Ctrl+Alt+KeyA",
            "Alt+F4",
            "Ctrl+KeyC",
            "Ctrl+Shift+KeyZ",
            "Ctrl+Shift+Shift+KeyK",
        ] {
            let mut bindings = defaults();
            bindings.insert("showWindow".into(), Some(invalid.into()));
            assert!(validate(&bindings).is_err(), "{invalid}");
        }
        let mut bindings = defaults();
        bindings.insert("showWindow".into(), Some("Ctrl+Shift+KeyK".into()));
        bindings.insert("toggleAvatar".into(), Some("Ctrl+Shift+KeyK".into()));
        assert!(validate(&bindings).is_err());
    }

    #[test]
    fn preferences_survive_replacement_and_corruption_does_not_block_startup() {
        let directory = std::env::temp_dir().join(format!(
            "iris-shortcuts-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let path = directory.join("shortcuts.json");
        let state = ShortcutPreferences::load(path.clone());
        assert!(state
            .inner
            .lock()
            .unwrap()
            .status
            .bindings
            .values()
            .all(Option::is_none));
        let mut bindings = defaults();
        bindings.insert("showWindow".into(), Some("Ctrl+Shift+F9".into()));
        state.save(&bindings).unwrap();
        assert_eq!(
            ShortcutPreferences::load(path.clone())
                .inner
                .lock()
                .unwrap()
                .status
                .bindings,
            bindings
        );
        state.save(&defaults()).unwrap();
        assert_eq!(
            ShortcutPreferences::load(path.clone())
                .inner
                .lock()
                .unwrap()
                .status
                .bindings,
            defaults()
        );
        fs::write(&path, b"broken json").unwrap();
        let recovered = ShortcutPreferences::load(path.clone());
        let inner = recovered.inner.lock().unwrap();
        assert_eq!(inner.status.bindings, defaults());
        assert!(!inner.status.errors.is_empty());
        fs::remove_file(path).unwrap();
        fs::remove_dir(directory).unwrap();
    }
}
