from __future__ import annotations

from pathlib import Path
import os

from pact.clock import Clock
from pact.config import Settings
from pact.models import AgentSession
from pact.repository import Repository


DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def runtime_base_url(env: dict[str, str] | None = None) -> str:
    env = env if env is not None else os.environ
    explicit = env.get("PACT_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    host = env.get("PACT_HOST", "127.0.0.1")
    port = env.get("PACT_PORT", "8000")
    return f"http://{host}:{port}"


def _active_session(session: AgentSession | None, clock: Clock) -> bool:
    return bool(
        session
        and session.revoked_at is None
        and (session.expires_at is None or session.expires_at > clock.now())
    )


def _claude_skill_path() -> Path:
    override = os.environ.get("PACT_CLAUDE_SKILL_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "skills" / "pact" / "SKILL.md"


def mcp_command(base_url: str = DEFAULT_BASE_URL) -> str:
    return f"pact mcp --base-url {base_url} --agent-token <agent-token>"


def build_connector_health(
    repo: Repository,
    owner: str,
    clock: Clock,
    settings: Settings,
    *,
    base_url: str | None = None,
) -> dict:
    """Return the setup/health read-model shown by Settings and Onboarding.

    This intentionally never returns raw bearer tokens. The command/config use a
    placeholder so users know where the once-shown token belongs without leaking
    it from later health checks.
    """
    base_url = base_url or runtime_base_url()
    session = repo.get_agent_session(owner)
    token_ready = _active_session(session, clock)
    worker_online = repo.worker_seen_within(
        clock.now(), settings.worker_presence_seconds
    )
    last_seen = repo.worker_last_seen()
    claude_path = _claude_skill_path()
    claude_installed = claude_path.is_file()

    def token_status(ready_status: str = "ready") -> str:
        return ready_status if token_ready else "needs_token"

    command = mcp_command(base_url)
    mcp_config = {
        "server_name": "pact",
        "command": "pact",
        "args": [
            "mcp",
            "--base-url",
            base_url,
            "--agent-token",
            "<agent-token>",
        ],
    }

    connectors = [
        {
            "key": "hermes",
            "name": "Hermes",
            "kind": "skill",
            "status": token_status("ready"),
            "installed": True,
            "capabilities": ["text", "vision"],
            "detail": "Built in. Generate an agent token, then run /pact serve when you want live agent review.",
            "action": "Run /pact serve with your Pact token.",
        },
        {
            "key": "claude_code",
            "name": "Claude Code",
            "kind": "skill",
            "status": (
                "ready"
                if token_ready and claude_installed
                else "needs_install"
                if token_ready
                else "needs_token"
            ),
            "installed": claude_installed,
            "install_path": str(claude_path),
            "capabilities": ["text", "vision"],
            "detail": "Install the /pact skill, then paste the once-shown token into Claude Code.",
            "action": "Install /pact skill and run pact serve.",
        },
        {
            "key": "mcp",
            "name": "MCP",
            "kind": "mcp",
            "status": token_status("ready"),
            "installed": token_ready,
            "capabilities": ["text"],
            "detail": "Use the Pact MCP server from any MCP-compatible agent.",
            "action": "Add the Pact MCP server command to your agent.",
            "command": command,
            "config": mcp_config,
        },
    ]

    return {
        "owner": owner,
        "runtime": {
            "reasoning_mode": settings.reasoning_mode,
            "auth_mode": settings.auth_mode,
            "base_url": base_url,
        },
        "agent_token": {
            "status": "ready" if token_ready else "missing",
            "token_prefix": session.token_prefix if token_ready and session else None,
            "expires_at": (
                session.expires_at.isoformat()
                if token_ready and session and session.expires_at
                else None
            ),
            "last_used_at": (
                session.last_used_at.isoformat()
                if token_ready and session and session.last_used_at
                else None
            ),
            "scopes": session.scopes if token_ready and session else [],
        },
        "worker": {
            "status": "online" if worker_online else "offline",
            "last_seen_at": last_seen.isoformat() if last_seen else None,
            "presence_window_seconds": settings.worker_presence_seconds,
        },
        "capabilities": {
            "text": worker_online,
            "vision": worker_online,
        },
        "connectors": connectors,
        "mcp": {
            "server_name": "pact",
            "command": command,
            "config": mcp_config,
        },
    }
