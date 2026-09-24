#!/usr/bin/env python3
"""Tiadect 2 local bridge: GitHub Issues <-> local Codex CLI.

Standard-library only. GitHub authentication is delegated to the official gh CLI;
Codex authentication is delegated to the local codex CLI.
"""
from __future__ import annotations

import argparse
import json
import logging
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

LOG = logging.getLogger("tiadect")

def configure_logging(verbose=False, quiet=False):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING if quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s", force=True,
    )

READY = "tiadect:ready"
RUNNING = "tiadect:running"
DONE = "tiadect:done"
FAILED = "tiadect:failed"
TASK_RE = re.compile(r"\`\`\`tiadect\s*\n(.*?)\n\`\`\`", re.S | re.I)


# Only these internally selected codes may contribute text to failure reports.
FAILURES = {
    "envelope": "Invalid task envelope. Supply a valid JSON object in the tiadect block.",
    "prompt": "Missing prompt. Supply a non-empty prompt.",
    "outside_root": "Repository outside allowed roots. Select an approved checkout.",
    "checkout": "Repository is not a Git checkout. Select an existing approved checkout.",
    "sandbox": "Invalid sandbox. Use read-only or explicitly request workspace-write.",
    "codex": "Codex execution failed. Check local Codex authentication and prerequisites before retrying.",
}

class TaskValidationError(ValueError):
    pass

def safe_failure(error: Exception) -> str:
    # Never format the exception, its command/output, or arbitrary class name.
    if type(error) is TaskValidationError and len(error.args) == 1:
        code = error.args[0]
        if type(code) is str and code in FAILURES:
            return f"Task failure [{code}]: {FAILURES[code]}"
    if isinstance(error, subprocess.SubprocessError):
        return "Subprocess failure: check GitHub/Codex authentication, permissions and tool availability locally."
    if isinstance(error, OSError):
        return "Local I/O failure: check executable availability, filesystem permissions and disk space."
    if isinstance(error, ValueError):
        return "Validation failure: review task format and approved repository settings."
    return "Internal task failure: ask the local operator to investigate before retrying."

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
    started = time.monotonic()
    try:
        result = subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, input=stdin, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check,
        encoding="utf-8", errors="replace",
        )
        LOG.debug("Subprocess completed exit=%d elapsed=%.3fs", result.returncode, time.monotonic() - started)
        return result
    except Exception:
        LOG.debug("Subprocess failed elapsed=%.3fs", time.monotonic() - started)
        raise

def gh(cfg: Config, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    # Only fixed operation identifiers; never arguments, bodies, or output.
    operation = tuple(args[:2])
    if operation in {("auth", "status"), ("label", "create"), ("issue", "list"),
                     ("issue", "comment"), ("issue", "edit")}:
        LOG.debug("GitHub operation: %s %s", *operation)
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
    LOG.debug("Parsing task envelope (contents omitted)")
    m = TASK_RE.search(body or "")
    if not m:
        return {"prompt": (body or "").strip()}
    block = m.group(1).strip()
    # The protocol block is JSON. Keeping it JSON avoids adding YAML dependencies.
    try:
        obj = json.loads(block)
    except json.JSONDecodeError as e:
        raise TaskValidationError("envelope") from e
    if not isinstance(obj, dict):
        raise TaskValidationError("envelope")
    return obj

def resolve_repo(cfg: Config, requested: str | None) -> pathlib.Path:
    LOG.debug("Validating repository against allowed roots")
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
        raise TaskValidationError("outside_root")
    if not (p / ".git").exists():
        raise TaskValidationError("checkout")
    LOG.debug("Repository validation passed")
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
    LOG.debug("Issue #%d state transition requested", number)
    args = ["issue", "edit", str(number), "--repo", cfg.mailbox_repo, "--add-label", add]
    if remove:
        args += ["--remove-label", remove]
    gh(cfg, args)

def codex_exec(cfg: Config, repo: pathlib.Path, prompt: str, mode: str) -> tuple[int, str, str]:
    if mode not in {"read-only", "workspace-write"}:
        raise TaskValidationError("sandbox")
    with tempfile.TemporaryDirectory(prefix="tiadect-") as td:
        last = pathlib.Path(td) / "last-message.md"
        cmd = [
            cfg.codex_bin, "exec",
            "--sandbox", mode,
            "--json",
            "-o", str(last),
            "-",
        ]
        LOG.debug("Codex metadata: sandbox=%s json=true prompt=stdin", mode)
        started = time.monotonic()
        LOG.info("Codex launch")
        try:
            proc = run(cmd, cwd=repo, stdin=prompt, check=False)
        except Exception:
            LOG.error("Codex launch/execution failed elapsed=%.3fs", time.monotonic() - started)
            raise
        LOG.info("Codex completion exit=%d elapsed=%.3fs", proc.returncode, time.monotonic() - started)
        final = last.read_text(encoding="utf-8", errors="replace") if last.exists() else ""
        return proc.returncode, final.strip(), proc.stdout.strip()

def process_issue(cfg: Config, issue: dict) -> None:
    number = int(issue["number"])
    if RUNNING in labels_of(issue):
        return
    LOG.info("Task discovered Issue #%d", number)
    try:
        set_state(cfg, number, RUNNING, READY)
        LOG.info("Task claimed Issue #%d", number)
        task = parse_task(issue.get("body", ""))
        prompt = str(task.get("prompt", "")).strip()
        if not prompt:
            raise TaskValidationError("prompt")
        repo = resolve_repo(cfg, task.get("repo_path"))
        mode = str(task.get("mode", "read-only"))
        if mode not in {"read-only", "workspace-write"}:
            raise TaskValidationError("sandbox")
        LOG.info("Issue #%d repository=%s sandbox=%s", number, repo, mode)
        comment(cfg, number,
                f"🤖 **Tiadect claimed this task**\n\n"
                f"- Local repo: \`{repo}\`\n- Codex sandbox: \`{mode}\`\n"
                f"- Bridge PID: \`{os.getpid()}\`")
        code, final, events = codex_exec(cfg, repo, prompt, mode)
        if code:
            raise TaskValidationError("codex")
        if not final:
            final = "(Codex completed without a final text message.)"
        if len(final) > cfg.max_output_chars:
            final = final[:cfg.max_output_chars] + "\n\n[truncated by Tiadect]"
        comment(cfg, number, "## Codex response\n\n" + final)
        LOG.info("Issue #%d response posted", number)
        set_state(cfg, number, DONE, RUNNING)
        LOG.info("Issue #%d done", number)
    except Exception as e:
        failure = safe_failure(e)
        LOG.error("Issue #%d task failed: %s", number, failure)
        comment(cfg, number, "## Tiadect bridge failure\n\n" + failure)
        set_state(cfg, number, FAILED, RUNNING)
        LOG.error("Issue #%d failed state posted", number)

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
    modes = ap.add_mutually_exclusive_group()
    modes.add_argument("--verbose", action="store_true", help="Safe diagnostic logging")
    modes.add_argument("--quiet", action="store_true", help="Only errors and failures")
    ns = ap.parse_args()
    configure_logging(ns.verbose, ns.quiet)
    cfg = load_config(pathlib.Path(ns.config))
    if ns.doctor:
        doctor(cfg)
        return 0
    ensure_tools(cfg)
    ensure_labels(cfg)
    LOG.info("Daemon online mailbox=%s poll_interval=%ds", cfg.mailbox_repo, cfg.poll_seconds)
    while True:
        try:
            LOG.debug("Polling cycle started")
            for issue in list_ready(cfg):
                process_issue(cfg, issue)
        except KeyboardInterrupt:
            LOG.info("Tiadect stopped")
            return 0
        except Exception as e:
            LOG.error("Polling/task dispatch failed: %s", safe_failure(e))
        if ns.once:
            return 0
        time.sleep(cfg.poll_seconds)

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        LOG.error("Startup-critical failure: %s", safe_failure(e))
        raise SystemExit(1) from None
