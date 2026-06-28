from pact.config import load_settings


def test_cors_origins_default():
    s = load_settings({})
    assert s.cors_origins == (
        "tauri://localhost",
        "http://tauri.localhost",
        "http://localhost:5173",
    )


def test_cors_origins_from_env():
    s = load_settings({"PACT_CORS_ORIGINS": "tauri://localhost, https://x.test"})
    assert s.cors_origins == ("tauri://localhost", "https://x.test")
