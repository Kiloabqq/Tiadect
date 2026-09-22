# Tiadect 2

**Tiadect** is now a practical duplex bridge between a GitHub mailbox and a
local Codex CLI process.

The original browser prototype proved the routing idea. Tiadect 2 adds the
missing execution adapter: a small, standard-library Python daemon on Windows
polls trusted GitHub Issues, runs the task through local `codex exec`, and
posts Codex's final response back to the same issue.

## Architecture

```text
ChatGPT / GitHub client
        |
        v
GitHub Issue mailbox
        |
        v
Tiadect bridge.py (Windows)
        |
        v
codex exec
        |
        v
local approved Git checkout
```

## Safety defaults

- Codex tasks default to `read-only`.
- Write-capable tasks must explicitly request `workspace-write`.
- The bridge rejects repositories outside configured `allowed_roots`.
- The target must be a Git checkout.
- Tiadect does not store GitHub or Codex credentials.
- There is deliberately no Tiadect option for Codex `--yolo` /
  `danger-full-access`.

## Windows quick start

Requirements: Python 3.11+, GitHub CLI (`gh`), Codex CLI, and existing
authentication for both CLIs.

```powershell
git clone https://github.com/Kiloabqq/Tiadect.git
cd Tiadect
git switch tiadect-2-codex-bridge

Copy-Item .\tiadect.toml.example .\tiadect.toml
notepad .\tiadect.toml
```

Set `default_repo` to the canonical local BARS checkout and make
`allowed_roots` as narrow as possible. Then:

```powershell
.\start-tiadect.ps1
```

The startup script runs a doctor check before starting the polling daemon.

## Sending a task

Create a GitHub Issue in the configured mailbox repository and add
`tiadect:ready`. Plain issue text becomes a read-only Codex prompt against the
configured default checkout.

For explicit routing, use the JSON envelope documented in
[PROTOCOL.md](PROTOCOL.md).

## Why GitHub Issues?

They provide a durable, inspectable message bus with IDs, timestamps,
attribution, comments, labels, and access control. The local bridge is the only
component that needs access to the Windows filesystem.

## Current status

This branch contains the first functional Tiadect 2 bridge implementation.
The local Windows half still needs to be installed and smoke-tested on the
machine that owns the BARS checkout.

The original browser relay files remain in the repository as the Tiadect
prototype/history.

## License

MIT
