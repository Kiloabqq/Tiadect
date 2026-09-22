# Tiadect 2 protocol

Tiadect uses a GitHub Issue as a durable mailbox message. This deliberately
separates transport (GitHub) from execution (the local Codex CLI).

## Task lifecycle

1. A trusted sender creates an issue in the mailbox repository.
2. The issue receives the label `tiadect:ready`.
3. The Windows bridge sees it, replaces that label with `tiadect:running`,
   and posts a claim comment.
4. The bridge invokes `codex exec` in the approved local checkout.
5. The final Codex message is posted back as an issue comment.
6. The issue receives `tiadect:done`, or `tiadect:failed` on error.

The issue remains open so another agent can reply with a follow-up. A new
follow-up task can be represented by a new issue; this keeps task ownership and
retries unambiguous.

## Task body

The simplest task is plain text. It uses the configured default repository and
read-only sandbox.

For explicit routing, include one fenced `tiadect` block containing JSON:

~~~markdown
Investigate the Prisma runtime path mismatch.

```tiadect
{
  "repo_path": "D:\\\\2026BARS\\\\bars-m3-review-engine(latest2026)",
  "mode": "read-only",
  "prompt": "Inspect the deployed pnpm/Prisma topology. Do not modify files. Report the exact path mismatch."
}
```
~~~

Supported `mode` values are:

- `read-only` — default; Codex may inspect but not edit the checkout.
- `workspace-write` — Codex may edit inside the selected checkout.

Tiadect intentionally does **not** expose Codex's unrestricted/yolo mode.

## Trust boundary

The bridge runs on the user's Windows machine. It only accepts repository paths
under `security.allowed_roots` and requires the target to be a Git checkout.

The GitHub CLI owns GitHub credentials. Codex owns Codex credentials. Tiadect
does not read, copy, log, or commit either credential.

Because a mailbox task becomes an AI prompt executed against local source code,
only trusted GitHub users should be allowed to create/label tasks in the mailbox
repository.
