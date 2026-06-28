use std::collections::HashMap;

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // Preserve debug log plugin registration from the generated scaffold.
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            let handle = app.handle().clone();

            // On-disk home for the local DB + proof artifacts.
            let data_dir = app
                .path()
                .app_data_dir()
                .expect("could not resolve app data dir");
            std::fs::create_dir_all(&data_dir).ok();
            let db_path = data_dir.join("pact.db");
            let artifacts_dir = data_dir.join("artifacts");

            let mut envs: HashMap<String, String> = HashMap::new();
            envs.insert("PACT_PORT".into(), "8000".into());
            envs.insert("PACT_CLOCK_MODE".into(), "real".into());
            envs.insert("PACT_EMIT_READY".into(), "1".into());
            envs.insert("PACT_DB_PATH".into(), db_path.to_string_lossy().into_owned());
            envs.insert(
                "PACT_ARTIFACTS_DIR".into(),
                artifacts_dir.to_string_lossy().into_owned(),
            );

            let sidecar = app
                .shell()
                .sidecar("pact-sidecar")
                .expect("pact-sidecar not bundled")
                .envs(envs);
            let (mut rx, _child) = sidecar.spawn().expect("failed to spawn sidecar");

            // Open the window only once the API is up, so the SPA's first fetch
            // succeeds. The base URL is injected before any page script runs.
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    if let CommandEvent::Stdout(bytes) = event {
                        if String::from_utf8_lossy(&bytes).contains("PACT_SIDECAR_READY") {
                            WebviewWindowBuilder::new(
                                &handle,
                                "main",
                                WebviewUrl::default(),
                            )
                            .title("Pact")
                            .inner_size(1100.0, 760.0)
                            .initialization_script(
                                "window.__PACT_API_BASE__='http://127.0.0.1:8000';",
                            )
                            .build()
                            .expect("failed to build main window");
                            break;
                        }
                    }
                }
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
