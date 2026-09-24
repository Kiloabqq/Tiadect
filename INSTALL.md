# Installing Tiadect 2 on Windows

This guide sets up Tiadect as a reusable GitHub Issues <-> local OpenAI Codex CLI bridge.

## 1. Install the prerequisites

You need:

- Git
- Python 3.11+
- GitHub CLI (`gh`)
- Node.js/npm if you install Codex through npm
- OpenAI Codex CLI
- a local Git repository that Tiadect may use

Open a new PowerShell window after installing command-line tools so PATH changes are visible.

Verify:

```powershell
git --version
python --version
gh --version
node --version
npm --version
codex --version
```

Python must report 3.11 or newer.

### Install/update Codex CLI

The official Codex package can be installed or updated with:

```powershell
npm install -g @openai/codex@latest
codex --version
```

Then run Codex once and complete the sign-in flow:

```powershell
codex
```

Exit after confirming it can start normally.

### Authenticate GitHub CLI

```powershell
gh auth login
gh auth status
```

The authenticated account must have enough access to the selected mailbox repository to read Issues, create/edit labels, edit Issues, and post comments.

## 2. Choose a mailbox repository

Tiadect uses one GitHub repository's Issues as its task mailbox.

You may use the Tiadect repository itself for a personal setup, or another repository you control. For shared/team use, prefer a dedicated private mailbox repository with tightly controlled Issue/label permissions.

Write down its `owner/repo` name, for example:

```text
YOUR_GITHUB_USER/tiadect-mailbox
```

## 3. Clone Tiadect

Choose a normal local tools directory. Example:

```powershell
Set-Location D:\Tools
git clone https://github.com/Kiloabqq/Tiadect.git
Set-Location .\Tiadect
git switch tiadect-2-codex-bridge
```

## 4. Create the local configuration

```powershell
Copy-Item .\tiadect.toml.example .\tiadect.toml
notepad .\tiadect.toml
```

Example:

```toml
[bridge]
mailbox_repo = "YOUR_GITHUB_USER/tiadect-mailbox"
default_repo = "D:\\Projects\\my-project"
gh_bin = "gh"
codex_bin = "codex"
poll_seconds = 30
max_output_chars = 50000

[security]
allowed_roots = [
  "D:\\Projects\\my-project"
]
```

### Configuration rules

`mailbox_repo`
: GitHub repository used as the durable mailbox.

`default_repo`
: Local Git checkout used when a task does not specify `repo_path`.

`allowed_roots`
: Security allowlist. A requested repository must resolve underneath one of these paths. Keep this list narrow. Pointing it at an entire drive or user profile greatly increases the local source that a mailbox task could reach.

`gh_bin` / `codex_bin`
: Executable names or full paths if the tools are not on PATH.

`poll_seconds`
: Delay between mailbox polls. The bridge enforces a minimum of five seconds.

`max_output_chars`
: Maximum final response length posted back to GitHub.

Do not commit `tiadect.toml`. It is intended to remain machine-local.

## 5. Run the doctor check

Before starting the daemon:

```powershell
python .\bridge.py --config .\tiadect.toml --doctor
```

A healthy setup prints:

```text
Tiadect doctor: OK
Mailbox: ...
Default repo: ...
Poll interval: ...
```

The doctor verifies that `gh` and `codex` can start, GitHub CLI is authenticated, the default repository is under the configured allowlist, and the target has Git metadata. It also ensures the Tiadect lifecycle labels exist in the mailbox.

If doctor fails, fix that error before starting the daemon.

## 6. Start Tiadect

```powershell
.\start-tiadect.ps1
```

Expected final startup line:

```text
Tiadect is online. Ctrl+C stops the bridge.
```

Leave that PowerShell window running. Stop the bridge with Ctrl+C.

For a one-shot polling pass:

```powershell
python .\bridge.py --config .\tiadect.toml --once
```

## 7. Run the read-only acceptance test

Create an Issue in the mailbox:

```text
Title: Tiadect read-only smoke test

Inspect this repository. Report:
1. repository root
2. current branch
3. HEAD SHA
4. git status

Do not modify files.
```

Add the `tiadect:ready` label.

Expected lifecycle:

```text
tiadect:ready
      |
      v
tiadect:running + claim comment
      |
      v
local codex exec --sandbox read-only
      |
      v
Codex response comment
      |
      v
tiadect:done
```

Confirm locally that the repository was not changed:

```powershell
git -C "D:\Projects\my-project" status --short
```

Only proceed to write testing if this round trip succeeds.

## 8. Run a controlled write test

Use a disposable branch or test repository for the first write test.

Create an Issue containing:

```markdown
```tiadect
{
  "repo_path": "D:\\\\Projects\\\\my-project",
  "mode": "workspace-write",
  "prompt": "Create tiadect-smoke-test.txt containing the text 'Tiadect write test'. Do not modify any other file. Report exactly what changed."
}
```
```

Add `tiadect:ready`.

When it completes, inspect:

```powershell
git -C "D:\Projects\my-project" status --short
git -C "D:\Projects\my-project" diff
```

Delete or commit the test file yourself after reviewing it. Tiadect does not automatically commit or push.

## Troubleshooting

### Required executable not found on PATH

Run:

```powershell
Get-Command python
Get-Command gh
Get-Command codex
```

If a command exists elsewhere, either fix PATH or put its full executable path in `tiadect.toml`.

### GitHub CLI is not authenticated

```powershell
gh auth login
gh auth status
```

### Codex CLI did not start

Run `codex` directly and complete authentication, then verify `codex --version`.

### repo_path is outside allowed_roots

Either route the task to an already approved checkout or deliberately add the smallest appropriate parent directory to `security.allowed_roots`. Do not solve this by allowlisting an entire drive unless that is truly intended.

### repo_path is not a Git checkout

The current bridge requires `.git` metadata at the selected path. Use a valid clone/worktree rather than a plain source copy.

### Task remains tiadect:ready

Check that the daemon is running, the configured mailbox is correct, `gh auth status` succeeds, and the Issue is open.

### Task becomes tiadect:failed

Read the failure comment on the Issue and the local Tiadect console. Fix the reported prerequisite, repository, protocol, or Codex error, then submit a new task Issue.

## Security checklist

Before leaving Tiadect running unattended:

- Use a mailbox repository whose writers you trust.
- Keep `allowed_roots` narrow.
- Use read-only mode unless writes are necessary.
- Review local diffs after every write task.
- Do not place secrets in Issue bodies; GitHub Issues are the transport/audit record.
- Protect the local account running Tiadect because Codex inherits that account's environment and filesystem permissions, subject to its sandbox.
- Stop the daemon when remote task execution is not desired.

## Upgrading

```powershell
Set-Location D:\Tools\Tiadect
git fetch origin
git switch tiadect-2-codex-bridge
git pull --ff-only
python .\bridge.py --config .\tiadect.toml --doctor
```

Review release notes and configuration changes before restarting the daemon.
