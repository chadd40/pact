from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sidecar_spec_does_not_bundle_nemoguardrails():
    # The spend gate is a deterministic policy (pact.spend_policy); the heavy
    # nemoguardrails dependency was dropped, so the packaged sidecar must not try
    # to collect it (NVIDIA integration is Nemotron via NIM in pact.reasoning).
    spec = (ROOT / "packaging" / "pact-sidecar.spec").read_text(encoding="utf-8")

    assert "nemoguardrails" not in spec
