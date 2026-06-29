from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sidecar_spec_collects_nemoguardrails_runtime():
    spec = (ROOT / "packaging" / "pact-sidecar.spec").read_text(encoding="utf-8")

    assert '"nemoguardrails"' in spec
