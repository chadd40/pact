from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = _ROOT / ".claude" / "skills" / "pact" / "SKILL.md"
AGENTS_SKILL_PATH = _ROOT / ".agents" / "skills" / "pact" / "SKILL.md"


def _read_skill() -> str:
    assert SKILL_PATH.exists(), f"missing skill file: {SKILL_PATH}"
    return SKILL_PATH.read_text(encoding="utf-8")


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse a leading `---` YAML frontmatter block into a flat str->str dict.

    Only supports the simple `key: value` lines this skill uses; no nesting.
    Returns (frontmatter, body).
    """
    assert text.startswith("---\n"), "SKILL.md must open with a '---' frontmatter fence"
    end = text.find("\n---", 4)
    assert end != -1, "SKILL.md frontmatter block is not closed with '---'"
    raw = text[4:end]
    body = text[end:].lstrip("-\n")
    fm: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        assert ":" in line, f"frontmatter line is not key: value -> {line!r}"
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip()
    return fm, body


def test_skill_file_exists():
    assert SKILL_PATH.exists()
    assert SKILL_PATH.is_file()


def test_claude_and_agents_skill_copies_stay_identical():
    # The .claude/ and .agents/ skill files are the same agent-brain contract. They
    # are hand-maintained copies, so guard against silent drift (edit one, forget the
    # other) — both must be byte-identical.
    assert AGENTS_SKILL_PATH.exists(), f"missing skill file: {AGENTS_SKILL_PATH}"
    assert (
        AGENTS_SKILL_PATH.read_text(encoding="utf-8")
        == SKILL_PATH.read_text(encoding="utf-8")
    ), ".claude and .agents pact SKILL.md copies have drifted — keep them in sync"


def test_frontmatter_has_name_pact():
    fm, _ = _split_frontmatter(_read_skill())
    assert fm.get("name") == "pact"


def test_frontmatter_has_nonempty_description():
    fm, _ = _split_frontmatter(_read_skill())
    desc = fm.get("description", "")
    assert desc, "frontmatter description must be present and non-empty"
    assert len(desc) >= 20, "description should be a real sentence, not a stub"


@pytest.mark.parametrize(
    "command",
    [
        "/pact create",
        "/pact status",
        "/pact submit",
        "/pact coach",
        "/pact check",
        "/pact verdict",
        "/pact freeze",
        "/pact dispute",
        "/pact renew",
        "/pact me",
        "/pact serve",
    ],
)
def test_body_documents_each_command(command: str):
    _, body = _split_frontmatter(_read_skill())
    assert command in body, f"SKILL.md body must document {command!r}"


def test_body_documents_brain_inline_contract():
    _, body = _split_frontmatter(_read_skill())
    lowered = body.lower()
    # The skill is the brain on the skill path: it reasons inline and posts results.
    assert "inline" in lowered
    assert "brain" in lowered
    # Worker/serve path for website-created tasks.
    assert "broker" in lowered


def test_body_lists_base_url_and_key_endpoints():
    _, body = _split_frontmatter(_read_skill())
    assert "http://127.0.0.1:8000" in body
    for endpoint in [
        "POST /api/pacts/draft",
        "POST /api/pacts/{id}/proofs",
        "POST /api/pacts/{id}/coach",
        "POST /api/pacts/{id}/settle",
        "POST /api/pacts/{id}/dispute",
        "GET /api/reasoning-tasks",
        "POST /api/reasoning-tasks/{tid}/claim",
        "POST /api/reasoning-tasks/{tid}/result",
    ]:
        assert endpoint in body, f"SKILL.md must list endpoint {endpoint!r}"
