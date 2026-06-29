use std::collections::HashMap;
use std::net::TcpListener;

use serde::Serialize;
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

/// The /pact skill, embedded at compile time so the installer never depends on
/// files outside the bundle. `include_str!` is resolved relative to this source
/// file (web/src-tauri/src/lib.rs); three levels up is the repo root, which is
/// also the checkout root in CI, so the path resolves in both places.
const PACT_SKILL_MD: &str = include_str!("../../../.claude/skills/pact/SKILL.md");
const SIDECAR_HOST: &str = "127.0.0.1";
const SIDECAR_PORT: u16 = 8000;
const SIDECAR_PORT_ATTEMPTS: u16 = 50;

fn select_sidecar_port<F>(preferred: u16, attempts: u16, is_available: F) -> Option<u16>
where
    F: Fn(u16) -> bool,
{
    (0..attempts)
        .filter_map(|offset| preferred.checked_add(offset))
        .find(|port| is_available(*port))
}

fn tcp_port_available(host: &str, port: u16) -> bool {
    TcpListener::bind((host, port)).is_ok()
}

fn sidecar_base_url(host: &str, port: u16) -> String {
    format!("http://{host}:{port}")
}

fn pact_skill_markdown(api_base_url: &str) -> String {
    PACT_SKILL_MD.replace("http://127.0.0.1:8000", api_base_url)
}

#[derive(Clone)]
struct SidecarRuntime {
    api_base_url: String,
}

#[derive(Serialize)]
struct InstallResult {
    /// "installed" (wrote the skill), "builtin" (agent ships it), or "manual"
    /// (we can't auto-install; the UI shows copy-paste instructions).
    status: String,
    /// Absolute path the skill was written to, when status == "installed".
    path: Option<String>,
    /// Human-readable line for the onboarding UI.
    message: String,
}

/// Install the /pact skill for the agent the user picked when sealing their pact.
/// Idempotent: re-running overwrites the file so an updated skill always wins.
///   - "Claude Code" -> write ~/.claude/skills/pact/SKILL.md
///   - "Hermes"      -> built-in, nothing to install
///   - anything else -> manual (custom / bring-your-own MCP agent)
/// The sidecar prefers 127.0.0.1:8000 but can fall forward if that port is busy;
/// installed skills are templated with the actual runtime URL.
#[tauri::command]
fn install_pact_skill(app: tauri::AppHandle, agent_key: String) -> Result<InstallResult, String> {
    let api_base_url = app
        .try_state::<SidecarRuntime>()
        .map(|runtime| runtime.api_base_url.clone())
        .unwrap_or_else(|| sidecar_base_url(SIDECAR_HOST, SIDECAR_PORT));
    match agent_key.trim().to_lowercase().as_str() {
        "claude code" | "claude-code" | "claudecode" => {
            let home = app.path().home_dir().map_err(|e| e.to_string())?;
            let skill_dir = home.join(".claude").join("skills").join("pact");
            std::fs::create_dir_all(&skill_dir).map_err(|e| e.to_string())?;
            let skill_path = skill_dir.join("SKILL.md");
            std::fs::write(&skill_path, pact_skill_markdown(&api_base_url))
                .map_err(|e| e.to_string())?;
            Ok(InstallResult {
                status: "installed".into(),
                path: Some(skill_path.to_string_lossy().into_owned()),
                message: format!("Installed the /pact skill for Claude Code at {api_base_url}."),
            })
        }
        "hermes" => Ok(InstallResult {
            status: "builtin".into(),
            path: None,
            message: "Hermes ships with /pact built in — nothing to install.".into(),
        }),
        _ => Ok(InstallResult {
            status: "manual".into(),
            path: None,
            message: format!(
                "Copy .claude/skills/pact/SKILL.md into your agent and point it at {api_base_url}."
            ),
        }),
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![install_pact_skill])
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

            let sidecar_port = select_sidecar_port(
                SIDECAR_PORT,
                SIDECAR_PORT_ATTEMPTS,
                |port| tcp_port_available(SIDECAR_HOST, port),
            )
            .expect("no available local port for pact sidecar");
            let api_base_url = sidecar_base_url(SIDECAR_HOST, sidecar_port);
            app.manage(SidecarRuntime {
                api_base_url: api_base_url.clone(),
            });

            let mut envs: HashMap<String, String> = HashMap::new();
            envs.insert("PACT_HOST".into(), SIDECAR_HOST.into());
            envs.insert("PACT_PORT".into(), sidecar_port.to_string());
            envs.insert("PACT_BASE_URL".into(), api_base_url.clone());
            envs.insert("PACT_CLOCK_MODE".into(), "real".into());
            envs.insert("PACT_EMIT_READY".into(), "1".into());
            // Desktop builds must not inherit live-money env by accident. Live Link
            // mode is opt-in for local drills only.
            let allow_live_link = std::env::var("PACT_TAURI_ALLOW_LIVE_LINK")
                .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
                .unwrap_or(false);
            if allow_live_link {
                if let Ok(mode) = std::env::var("PACT_PAYMENT_MODE") {
                    envs.insert("PACT_PAYMENT_MODE".into(), mode);
                }
                if let Ok(mode) = std::env::var("PACT_LINK_MODE") {
                    envs.insert("PACT_LINK_MODE".into(), mode);
                }
                if let Ok(method_id) = std::env::var("PACT_LINK_PAYMENT_METHOD_ID") {
                    envs.insert("PACT_LINK_PAYMENT_METHOD_ID".into(), method_id);
                }
            } else {
                envs.insert("PACT_PAYMENT_MODE".into(), "test_link".into());
                envs.insert("PACT_LINK_MODE".into(), "dry_run".into());
            }
            // Give the installed agent (the brain) a real window to judge/draft/coach
            // when it's serving (/pact serve). The hybrid provider only waits when a
            // worker has polled recently, so this never hangs the no-agent case.
            envs.insert("PACT_REASONING_TIMEOUT_POLLS".into(), "20".into());
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
                                .initialization_script(&format!(
                                    "window.__PACT_API_BASE__='{api_base_url}';"
                                ))
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
                        "pact sidecar never signalled ready — local API ports may be unavailable or the binary crashed"
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
                        %3Cp%3EPact%E2%80%99s%20local%20engine%20didn%E2%80%99t%20start%20(local%20API%20ports%20may%20be%20unavailable).%20Quit%20and%20relaunch.%3C%2Fp%3E\
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sidecar_port_selection_skips_occupied_preferred_port() {
        let port = select_sidecar_port(8000, 4, |candidate| candidate != 8000)
            .expect("expected a fallback port");

        assert_eq!(port, 8001);
    }

    #[test]
    fn sidecar_port_selection_reports_exhaustion() {
        let port = select_sidecar_port(8000, 3, |_candidate| false);

        assert_eq!(port, None);
    }

    #[test]
    fn api_base_url_uses_selected_sidecar_port() {
        assert_eq!(
            sidecar_base_url("127.0.0.1", 8042),
            "http://127.0.0.1:8042"
        );
    }

    #[test]
    fn installed_skill_markdown_uses_runtime_base_url() {
        let skill = pact_skill_markdown("http://127.0.0.1:8042");

        assert!(skill.contains("http://127.0.0.1:8042"));
        assert!(!skill.contains("http://127.0.0.1:8000"));
    }
}
