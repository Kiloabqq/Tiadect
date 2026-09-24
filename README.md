# Tiadect 2

**Tiadect is a local AI execution bridge.** It lets a trusted remote client place a task in a GitHub Issue, have a daemon on your computer hand that task to the local OpenAI Codex CLI inside an approved Git repository, and post Codex's result back to the same Issue.

It is not a remote-desktop product and it does not give ChatGPT direct filesystem access. GitHub Issues are the durable message bus; the Tiadect daemon is the local executor.

```text
remote client / human / automation
              |
              v
      GitHub Issue mailbox
              |
              v
   Tiadect bridge.py (local)
              |
              v
       OpenAI Codex CLI
              |
              v
     approved local Git repo
              |
              v
 result -> GitHub Issue comment
```

This makes Tiadect useful when an agent or collaborator can reach GitHub but cannot directly reach the machine that owns the working copy. The GitHub Issue becomes an inspectable handoff point between the remote side and local Codex.

## What Tiadect does

1. Polls one configured GitHub repository for open Issues labeled `tiadect:ready`.
2. Claims a task by changing its state to `tiadect:running`.
3. Resolves the requested local repository and checks that it is under an explicit allowlist.
4. Runs `codex exec` in that repository.
5. Posts the final Codex response to the Issue.
6. Marks the task `tiadect:done` or `tiadect:failed`.

Plain Issue bodies run against the configured default repository in `read-only` mode. A JSON envelope can select another approved repository and explicitly request `workspace-write`. See [PROTOCOL.md](PROTOCOL.md).

## Safety model

- Tasks default to `read-only`.
- Write-capable tasks must explicitly request `workspace-write`.
- Repository paths must be inside `security.allowed_roots`.
- The target must be a Git checkout.
- GitHub authentication stays with the official `gh` CLI.
- Codex authentication stays with the Codex CLI.
- Tiadect does not store either credential.
- Tiadect deliberately does not expose Codex unrestricted / `--yolo` / `danger-full-access` execution.
- Anyone able to create and label mailbox tasks can cause prompts to run against approved local source, so mailbox permissions are part of the security boundary.

## Prerequisites

The current bridge targets Windows and requires:

- Windows PowerShell.
- Python 3.11 or newer. Python 3.11 is required because Tiadect uses the standard-library `tomllib` module.
- Git.
- GitHub CLI (`gh`), authenticated to an account with permission to read Issues, create/edit labels, edit Issues, and post comments in the mailbox repository.
- OpenAI Codex CLI, installed and authenticated.
- At least one local Git checkout that Codex is allowed to inspect.
- Network access required by GitHub CLI and Codex.

Tiadect itself currently uses only the Python standard library; there is no `pip install` step.

For detailed installation, verification, first-task testing, and troubleshooting, see [INSTALL.md](INSTALL.md).

## Quick start

```powershell
git clone https://github.com/Kiloabqq/Tiadect.git
cd Tiadect
git switch tiadect-2-codex-bridge

Copy-Item .\tiadect.toml.example .\tiadect.toml
notepad .\tiadect.toml
```

Set:

- `bridge.mailbox_repo` to the GitHub repository that will carry Tiadect tasks.
- `bridge.default_repo` to a real local Git checkout.
- `security.allowed_roots` to the narrowest directories that should ever be reachable by Tiadect.

Then run:

```powershell
.\start-tiadect.ps1
```

The startup script runs the built-in doctor check before starting the polling daemon.

## First task

Create an Issue in the configured mailbox repository:

```text
Title: Tiadect smoke test

Inspect this repository read-only. Report the repository root, current branch,
HEAD commit, and git status. Do not modify files.
```

Add the label:

```text
tiadect:ready
```

A healthy bridge changes the task to `tiadect:running`, posts a claim comment, invokes local Codex, posts the Codex response, and finishes with `tiadect:done`.

## Write tasks

Do not use write mode until the read-only smoke test succeeds. A write task must explicitly use the protocol envelope:

```markdown
```tiadect
{
  "repo_path": "D:\\\\Projects\\\\my-repo",
  "mode": "workspace-write",
  "prompt": "Create docs/example.md containing a short test note. Do not modify any other file."
}
```
```

Afterward, review `git diff` and `git status` locally. Tiadect does not automatically commit or push changes.

## Operating model

Tiadect is intentionally small. It is a transport-and-execution adapter, not an autonomous orchestration platform. GitHub provides durable task state and auditability; Codex performs the local reasoning and coding; Git remains the source-of-truth for code changes.

## Bug #0: Tiadect works so quietly that the operators think Tiadect doesn't work

The first end-to-end acceptance test exposed Tiadect's first operational bug: the bridge completed the task so quietly that the operators initially thought nothing had happened.

On 2026-09-24, a remote client created GitHub Issue #2 with `tiadect:ready`. The local bridge claimed it, invoked Codex against the approved BARS checkout in `read-only` mode, posted the result, and transitioned the Issue to `tiadect:done`. Because the local console did not clearly announce those lifecycle transitions, the successful run was briefly mistaken for a stalled daemon.

**Bug #0:** *Tiadect works so quietly that the operators think Tiadect doesn't work.*

The acceptance test proved the full round trip:

```text
remote client -> GitHub Issue -> Tiadect -> local Codex -> local Git repo
                                                        |
remote client <- GitHub Issue <- Tiadect <- Codex result
```

The test also established an operator-experience requirement: the local daemon should visibly log task claim, repository/mode, Codex launch, completion or failure, response posting, and final lifecycle state.

## Current status

Tiadect 2 is under active validation. The bridge implementation, doctor command, Windows launcher, allowlist, task protocol, and GitHub Issue lifecycle are present. End-to-end smoke testing should be completed on each machine before write mode is trusted.

The original browser relay files remain in the repository as Tiadect prototype/history.

## Documentation

- [INSTALL.md](INSTALL.md) — prerequisites, installation, validation, first run, troubleshooting.
- [PROTOCOL.md](PROTOCOL.md) — task envelope and lifecycle.
- [tiadect.toml.example](tiadect.toml.example) — configuration template.

## License

MIT

## Local logging (Bug #0)

Successful bridge activity is now visible locally. Default logging reports startup,
mailbox/poll interval, issue discovery/claim, validated repository and sandbox,
Codex launch/completion (exit code and elapsed seconds), response posting, and
terminal task state. Logs go immediately to stderr.

Run directly to select a logging mode:

```powershell
python .\bridge.py --config .\tiadect.toml
python .\bridge.py --config .\tiadect.toml --verbose
python .\bridge.py --config .\tiadect.toml --quiet
```

Verbose adds polling, GitHub operation identifiers/state transitions, envelope
parsing, path-validation progress, subprocess timing, and safe Codex metadata.
Quiet suppresses routine activity but retains task failures and startup-critical
errors. The flags are mutually exclusive; explicit doctor results remain visible.
No prompts, issue titles/bodies, response text, subprocess output, environment
values, tokens, or raw exception messages are added to local logs. Repository paths,
mailbox name, issue numbers and sandbox mode are operational metadata.

Read-only remains the default. Workspace-write still requires an explicit request;
allowed roots and delegated CLI authentication are unchanged. No unrestricted
mode is provided. Restart an existing daemon after updating to activate logging.
GitHub failure comments use fixed failure categories and remediation guidance,
never raw exception strings or captured command output. Successful Codex responses
remain the intended result transport and are not sanitized.
