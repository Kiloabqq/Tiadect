#!/usr/bin/env python3
"""Tiadect 2 local bridge: GitHub Issues <-> local Codex CLI.

Standard-library only. GitHub authentication is delegated to the official gh CLI;
Codex authentication is delegated to the local codex CLI.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from dataclasses import dataclass

READY = "tiadect:ready"
RUNNING = "tiadect:running"
DONE = "tiadect:done"
FAILED = "tiadect:failed"
TASK_RE = re.compile(r"\`\`\`tiadect\s*\n(.*?)\n\`\`\`", re.S | re.I)

@dataclass
class Config:
    mailbox_repo: str
    poll_seconds: int
    allowed_roots: list[pathlib.Path]
    default_repo: pathlib.Path
    codex_bin: str
    gh_bin: str
    max_output_chars: int

def load_config(path: pathlib.Path) -> Config:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    bridge = raw.get("bridge", {})
    security = raw.get("security", {})
    mailbox_repo = str(bridge.get("mailbox_repo", "")).strip()
    if not mailbox_repo or "/" not in mailbox_repo:
        raise SystemExit("bridge.mailbox_repo must be owner/repo")
    roots = [pathlib.Path(p).expanduser().resolve() for p in security.get("allowed_roots", [])]
    if not roots:
        raise SystemExit("security.allowed_roots must contain at least one local directory")
    default_repo = pathlib.Path(bridge.get("default_repo", roots[0])).expanduser().resolve()
    return Config(
        mailbox_repo=mailbox_repo,
        poll_seconds=max(5, int(bridge.get("poll_seconds", 30))),
        allowed_roots=roots,
        default_repo=default_repo,
        codex_bin=str(bridge.get("codex_bin", "codex")),
        gh_bin=str(bridge.get("gh_bin", "gh")),
        max_output_chars=max(2000, int(bridge.get("max_output_chars", 50000))),
    )

def run(cmd: list[str], *, cwd: pathlib.Path | None = None, stdin: str | None = None,
        check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, input=stdin, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check,
        encoding="utf-8", errors="replace",
    )

def gh(cfg: Config, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run([cfg.gh_bin, *args], check=check)

def ensure_tools(cfg: Config) -> None:
    for binary in (cfg.gh_bin, cfg.codex_bin):
        if shutil.which(binary) is None:
            raise SystemExit(f"Required executable not found on PATH: {binary}")
    auth = gh(cfg, ["auth", "status"], check=False)
    if auth.returncode:
        raise SystemExit("GitHub CLI is not authenticated. Run: gh auth login")
    codex = run([cfg.codex_bin, "--version"], check=False)
    if codex.returncode:
        raise SystemExit("Codex CLI did not start. Run codex once and complete login.")

def ensure_labels(cfg: Config) -> None:
    labels = {
        READY: "0E8A16", RUNNING: "FBCA04", DONE: "1D76DB", FAILED: "D93F0B"
    }
    for name, color in labels.items():
        gh(cfg, ["label", "create", name, "--repo", cfg.mailbox_repo,
                 "--color", color, "--force"], check=False)

def parse_task(body: str) -> dict:
    m = TASK_RE.search(body or "")
    if not m:
        return {"prompt": (body or "").strip()}
    block = m.group(1).strip()
    # The protocol block is JSON. Keeping it JSON avoids adding YAML dependencies.
    try:
        obj = json.loads(block)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid tiadect JSON block: {e}") from e
    if not isinstance(obj, dict):
        raise ValueError("tiadect block must be a JSON object")
    return obj

def resolve_repo(cfg: Config, requested: str | None) -> pathlib.Path:
    p = pathlib.Path(requested).expanduser().resolve() if requested else cfg.default_repo
    allowed = False
    for root in cfg.allowed_roots:
        try:
            p.relative_to(root)
            allowed = True
            break
        except ValueError:
            pass
    if not allowed:
        raise ValueError(f"repo_path is outside allowed_roots: {p}")
    if not (p / ".git").exists():
        raise ValueError(f"repo_path is not a Git checkout: {p}")
    return p

def labels_of(issue: dict) -> set[str]:
    out = set()
    for x in issue.get("labels", []):
        out.add(x["name"] if isinstance(x, dict) else str(x))
    return out

def list_ready(cfg: Config) -> list[dict]:
    p = gh(cfg, ["issue", "list", "--repo", cfg.mailbox_repo, "--state", "open",
                 "--label", READY, "--limit", "20",
                 "--json", "number,title,body,labels,url"])
    return json.loads(p.stdout or "[]")

def comment(cfg: Config, number: int, body: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as f:
        f.write(body)
        name = f.name
    try:
        gh(cfg, ["issue", "comment", str(number), "--repo", cfg.mailbox_repo,
                 "--body-file", name])
    finally:
        pathlib.Path(name).unlink(missing_ok=True)

def set_state(cfg: Config, number: int, add: str, remove: str | None = None) -> None:
    args = ["issue", "edit", str(number), "--repo", cfg.mailbox_repo, "--add-label", add]
    if remove:
        args += ["--remove-label", remove]
    gh(cfg, args)

def codex_exec(cfg: Config, repo: pathlib.Path, prompt: str, mode: str) -> tuple[int, str, str]:
    if mode not in {"read-only", "workspace-write"}:
        raise ValueError("mode must be read-only or workspace-write")
    with tempfile.TemporaryDirectory(prefix="tiadect-") as td:
        last = pathlib.Path(td) / "last-message.md"
        cmd = [
            cfg.codex_bin, "exec",
            "--sandbox", mode,
            "--ask-for-approval", "never",
            "--json",
            "-o", str(last),
            "-",
        ]
        proc = run(cmd, cwd=repo, stdin=prompt, check=False)
        final = last.read_text(encoding="utf-8", errors="replace") if last.exists() else ""
        return proc.returncode, final.strip(), proc.stdout.strip()

def process_issue(cfg: Config, issue: dict) -> None:
    number = int(issue["number"])
    if RUNNING in labels_of(issue):
        return
    set_state(cfg, number, RUNNING, READY)
    try:
        task = parse_task(issue.get("body", ""))
        prompt = str(task.get("prompt", "")).strip()
        if not prompt:
            raise ValueError("Task has no prompt")
        repo = resolve_repo(cfg, task.get("repo_path"))
        mode = str(task.get("mode", "read-only"))
        comment(cfg, number,
                f"🤖 **Tiadect claimed this task**\n\n"
                f"- Local repo: \`{repo}\`\n- Codex sandbox: \`{mode}\`\n"
                f"- Bridge PID: \`{os.getpid()}\`")
        code, final, events = codex_exec(cfg, repo, prompt, mode)
        if code:
            tail = events[-8000:] if events else "(no JSONL output)"
            raise RuntimeError(f"codex exec exited {code}\n\n{tail}")
        if not final:
            final = "(Codex completed without a final text message.)"
        if len(final) > cfg.max_output_chars:
            final = final[:cfg.max_output_chars] + "\n\n[truncated by Tiadect]"
        comment(cfg, number, "## Codex response\n\n" + final)
        set_state(cfg, number, DONE, RUNNING)
    except Exception as e:
        comment(cfg, number, f"## Tiadect bridge failure\n\n\`\`\`text\n{e}\n\`\`\`")
        set_state(cfg, number, FAILED, RUNNING)

def doctor(cfg: Config) -> None:
    ensure_tools(cfg)
    ensure_labels(cfg)
    resolve_repo(cfg, None)
    print("Tiadect doctor: OK")
    print(f"Mailbox: {cfg.mailbox_repo}")
    print(f"Default repo: {cfg.default_repo}")
    print(f"Poll interval: {cfg.poll_seconds}s")

def main() -> int:
    ap = argparse.ArgumentParser(description="Tiadect GitHub <-> local Codex bridge")
    ap.add_argument("--config", default="tiadect.toml")
    ap.add_argument("--once", action="store_true", help="Process available tasks once and exit")
    ap.add_argument("--doctor", action="store_true", help="Validate local prerequisites and exit")
    ns = ap.parse_args()
    cfg = load_config(pathlib.Path(ns.config))
    if ns.doctor:
        doctor(cfg)
        return 0
    ensure_tools(cfg)
    ensure_labels(cfg)
    print(f"Tiadect online: {cfg.mailbox_repo} -> {cfg.default_repo}")
    while True:
        try:
            for issue in list_ready(cfg):
                process_issue(cfg, issue)
        except KeyboardInterrupt:
            print("\nTiadect stopped.")
            return 0
        except Exception as e:
            print(f"[bridge error] {e}", file=sys.stderr)
        if ns.once:
            return 0
        time.sleep(cfg.poll_seconds)

if __name__ == "__main__":
    raise SystemExit(main())
