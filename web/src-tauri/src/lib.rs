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
                let mut ready = false;
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(bytes) => {
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
                                ready = true;
                                break;
                            }
                        }
                        CommandEvent::Terminated(payload) => {
                            log::error!("pact sidecar terminated before ready: {:?}", payload);
                            break;
                        }
                        CommandEvent::Error(msg) => {
                            log::error!("pact sidecar error before ready: {}", msg);
                            break;
                        }
                        _ => {}
                    }
                }

                if !ready {
                    log::error!(
                        "pact sidecar never signalled ready — port 8000 may be in use or the binary crashed"
                    );
                    let error_html = "data:text/html,\
                        %3C!DOCTYPE%20html%3E\
                        %3Chtml%3E\
                        %3Chead%3E\
                        %3Cmeta%20charset%3D%22utf-8%22%3E\
                        %3Cstyle%3E\
                        body%7Bfont-family%3Asystem-ui%2Csans-serif%3Bpadding%3A2rem%3Bcolor%3A%23222%3Bbackground%3A%23fafafa%7D\
                        h2%7Bcolor%3A%23c0392b%7D\
                        %3C%2Fstyle%3E\
                        %3C%2Fhead%3E\
                        %3Cbody%3E\
                        %3Ch2%3EPact%20couldn%E2%80%99t%20start%3C%2Fh2%3E\
                        %3Cp%3EPact%E2%80%99s%20local%20engine%20didn%E2%80%99t%20start%20(port%208000%20may%20be%20in%20use).%20Quit%20and%20relaunch.%3C%2Fp%3E\
                        %3C%2Fbody%3E\
                        %3C%2Fhtml%3E";
                    if let Ok(url) = error_html.parse::<tauri::Url>() {
                        if let Err(e) = WebviewWindowBuilder::new(
                            &handle,
                            "error",
                            WebviewUrl::External(url),
                        )
                        .title("Pact \u{2014} startup error")
                        .inner_size(520.0, 300.0)
                        .build()
                        {
                            log::error!("failed to build error window: {e}");
                        }
                    } else {
                        log::error!(
                            "could not parse error page URL — Pact's local engine didn't start"
                        );
                    }
                }
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
