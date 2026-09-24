# Tiadect 2 protocol

Tiadect uses a GitHub Issue as a durable mailbox message. This deliberately separates transport (GitHub) from execution (the local Codex CLI).

## Task lifecycle

1. A trusted sender creates an Issue in the configured mailbox repository.
2. The Issue receives the label `tiadect:ready`.
3. The local bridge sees it, replaces that label with `tiadect:running`, and posts a claim comment.
4. The bridge invokes `codex exec` in the approved local checkout.
5. The final Codex message is posted back as an Issue comment.
6. The Issue receives `tiadect:done`, or `tiadect:failed` on error.

The Issue remains open as an audit record. Submit a new Issue for a new task or retry so ownership and task state remain unambiguous.

## Plain-text task

The simplest task is plain text. It uses the configured `default_repo` and the `read-only` Codex sandbox.

Example:

```text
Inspect this repository. Report the current branch, HEAD SHA, and git status.
Do not modify files.
```

## Explicit task envelope

For explicit routing, include one fenced `tiadect` block containing JSON:

~~~markdown
Investigate a local project.

```tiadect
{
  "repo_path": "D:\\\\Projects\\\\my-project",
  "mode": "read-only",
  "prompt": "Inspect the dependency topology. Do not modify files. Report the exact mismatch."
}
```
~~~

The fields are:

- `repo_path` — optional local Git checkout. It must resolve under one of the configured `security.allowed_roots`. If omitted, Tiadect uses `bridge.default_repo`.
- `mode` — optional Codex sandbox mode. Defaults to `read-only`.
- `prompt` — required when using the envelope; this is sent to local `codex exec`.

Supported `mode` values:

- `read-only` — default; Codex may inspect but not edit the checkout.
- `workspace-write` — Codex may edit inside the selected checkout.

Tiadect intentionally does **not** expose Codex unrestricted/yolo execution.

## State labels

Tiadect manages these labels in the mailbox repository:

- `tiadect:ready` — available for pickup.
- `tiadect:running` — claimed by the local bridge.
- `tiadect:done` — completed successfully.
- `tiadect:failed` — bridge or Codex execution failed.

The doctor/startup process attempts to create or normalize these labels.

## Trust boundary

The bridge runs on the user's machine. It only accepts repository paths under `security.allowed_roots` and requires the target to be a Git checkout.

The GitHub CLI owns GitHub credentials. Codex owns Codex credentials. Tiadect does not read, copy, log, or commit either credential.

A mailbox task becomes an AI prompt executed against local source code. Therefore only trusted users should be able to create/label actionable tasks in the mailbox. Do not put credentials or secrets in task bodies.

## Recommended acceptance sequence

1. Run `bridge.py --doctor`.
2. Complete a harmless read-only Issue round trip.
3. Confirm the local repository is unchanged.
4. Use a disposable branch/repository for the first `workspace-write` task.
5. Review `git status` and `git diff` locally before trusting write mode for normal work.

See [INSTALL.md](INSTALL.md) for the complete setup procedure.
