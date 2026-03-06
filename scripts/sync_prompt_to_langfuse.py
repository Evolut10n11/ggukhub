from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langfuse import Langfuse

ROOT = Path(__file__).resolve().parents[1]


def _run_git(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except Exception:
        return None
    value = result.stdout.strip()
    return value or None


def _repo_meta() -> dict[str, Any]:
    status = _run_git(["status", "--porcelain"]) or ""
    return {
        "repo_branch": _run_git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "repo_commit": _run_git(["rev-parse", "HEAD"]),
        "repo_commit_short": _run_git(["rev-parse", "--short", "HEAD"]),
        "repo_remote": _run_git(["remote", "get-url", "origin"]),
        "repo_dirty": bool(status.strip()),
        "repo_synced_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _default_prompt_file() -> Path:
    dspy = ROOT / "app" / "prompts" / "system.dspy.txt"
    if dspy.exists():
        return dspy
    return ROOT / "app" / "prompts" / "system.txt"


def _read_prompt_text(prompt_file: Path) -> str:
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")
    content = prompt_file.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"Prompt file is empty: {prompt_file}")
    return content


def _resolve_env(name: str, fallback: str | None = None) -> str | None:
    value = (Path.cwd() / ".env")  # touch cwd for clarity in stack traces
    _ = value
    import os

    raw = os.getenv(name)
    if raw is not None and raw.strip():
        return raw.strip()
    return fallback


def main() -> int:
    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(description="Sync repository prompt file to Langfuse prompt version")
    parser.add_argument("--prompt-name", default=None, help="Langfuse prompt name (defaults to LANGFUSE_PROMPT_NAME)")
    parser.add_argument("--label", default=None, help="Label to set (defaults to LANGFUSE_PROMPT_LABEL or production)")
    parser.add_argument(
        "--prompt-file",
        default=None,
        help="Path to prompt text file (defaults to LANGFUSE_PROMPT_FILE or app/prompts/system.dspy.txt if exists)",
    )
    parser.add_argument("--commit-message", default=None, help="Langfuse commit message")
    args = parser.parse_args()

    host = _resolve_env("LANGFUSE_HOST") or _resolve_env("LANGFUSE_BASE_URL")
    public_key = _resolve_env("LANGFUSE_PUBLIC_KEY")
    secret_key = _resolve_env("LANGFUSE_SECRET_KEY")
    environment = _resolve_env("LANGFUSE_ENVIRONMENT", "default")
    prompt_name = args.prompt_name or _resolve_env("LANGFUSE_PROMPT_NAME")
    label = args.label or _resolve_env("LANGFUSE_PROMPT_LABEL", "production")

    if not host or not public_key or not secret_key:
        print("ERROR: LANGFUSE_HOST(or LANGFUSE_BASE_URL), LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY are required.")
        return 2
    if not prompt_name:
        print("ERROR: prompt name is required. Set --prompt-name or LANGFUSE_PROMPT_NAME.")
        return 2

    prompt_file = Path(args.prompt_file) if args.prompt_file else Path(_resolve_env("LANGFUSE_PROMPT_FILE") or _default_prompt_file())
    if not prompt_file.is_absolute():
        prompt_file = (ROOT / prompt_file).resolve()

    try:
        prompt_text = _read_prompt_text(prompt_file)
    except Exception as error:
        print(f"ERROR: {error}")
        return 2

    client = Langfuse(
        base_url=host,
        public_key=public_key,
        secret_key=secret_key,
        environment=environment,
    )
    if not client.auth_check():
        print("ERROR: Langfuse auth check failed.")
        return 3

    repo_meta = _repo_meta()
    config: dict[str, Any] = {
        **repo_meta,
        "prompt_file": str(prompt_file.relative_to(ROOT)),
        "prompt_format": "text",
    }
    commit_message = args.commit_message or (
        f"sync prompt from repo {repo_meta.get('repo_commit_short') or 'unknown'}"
    )

    try:
        current = client.get_prompt(prompt_name, label=label)
    except Exception:
        current = None

    if current is not None:
        current_prompt = str(getattr(current, "prompt", "")).strip()
        current_config = getattr(current, "config", {}) or {}
        current_commit = current_config.get("repo_commit")
        if current_prompt == prompt_text and current_commit == repo_meta.get("repo_commit"):
            print(
                f"No changes: '{prompt_name}' label '{label}' already points to commit {current_commit}."
            )
            return 0

    created = client.create_prompt(
        name=prompt_name,
        prompt=prompt_text,
        labels=[label],
        type="text",
        config=config,
        commit_message=commit_message,
    )
    client.flush()

    print(
        f"Synced prompt '{prompt_name}' version={getattr(created, 'version', 'n/a')} "
        f"label={label} file={prompt_file.relative_to(ROOT)}"
    )
    print(
        f"Repo commit: {repo_meta.get('repo_commit_short') or 'n/a'} "
        f"(dirty={repo_meta.get('repo_dirty')})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
