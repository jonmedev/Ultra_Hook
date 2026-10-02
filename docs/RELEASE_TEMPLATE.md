# Ultra Hook __VERSION__

## Install Ultra Hook with AgentController

1. [Download the setup ZIP](https://github.com/jonmedev/Ultra_Hook/releases/download/v__VERSION__/ultra-hook-__VERSION__.zip)
   and extract it into a permanent folder.
2. On Windows, double-click `Install.cmd`. On macOS/Linux, run `sh install.sh` there.
3. Review the result, approve Ultra Hook's hooks in Codex `/hooks`, and start a new session.

The launcher runs `python -B scripts/install.py --with-agentcontroller`. It acquires
Kasempiternal's controller and registers ready Windows/Linux launchers. macOS gets
the verified official DMG, with app installation/permissions/bridge steps still
explicitly pending. It does not overwrite existing controller registrations.

Prerequisites: Codex CLI signed in, Node.js LTS, Python 3.11+ and Git. Windows source
builds additionally need the .NET 9 SDK. See the
[quick start](https://github.com/jonmedev/Ultra_Hook/blob/v__VERSION__/docs/GETTING_STARTED.md)
for platform details and existing installations.

## Plugin only: two commands

With Codex CLI signed in, Node.js LTS and Git installed, open PowerShell or Terminal:

```sh
codex plugin marketplace add jonmedev/Ultra_Hook --ref v__VERSION__
codex plugin add ultra-hook@ultra-hook
```

Codex downloads and installs only the plugin. **No ZIP extraction or Python is needed
for this method; AgentController is not acquired.** In Codex, review the five hooks in `/hooks`, start a new conversation
and send `$ultra-hook` followed by your task.

[Quick start and examples](https://github.com/jonmedev/Ultra_Hook/blob/v__VERSION__/docs/GETTING_STARTED.md)
explain activation, prerequisites and the separate update paths for existing installations.

## Downloads and verification

- [Plugin ZIP](https://github.com/jonmedev/Ultra_Hook/releases/download/v__VERSION__/ultra-hook-__VERSION__.zip)
- [SHA-256 checksum](https://github.com/jonmedev/Ultra_Hook/releases/download/v__VERSION__/ultra-hook-__VERSION__.sha256)
- [Verify the download and provenance](https://github.com/jonmedev/Ultra_Hook/blob/v__VERSION__/SECURITY.md#verify-a-download)
- [Installation, activation and usage](https://github.com/jonmedev/Ultra_Hook/blob/v__VERSION__/docs/GETTING_STARTED.md)

The ZIP launchers use Python management scripts. Follow the
[advanced guide](https://github.com/jonmedev/Ultra_Hook/blob/v__VERSION__/docs/ADVANCED_INSTALL.md)
and do not combine both installation methods on the same profile registration.

## AgentController is by Kasempiternal

**[AgentController](https://github.com/Kasempiternal/agentcontroller) is an independent
project developed by Kasempiternal.** Ultra Hook supplies an integration skill and
an optional acquisition helper. It does not own the controller or rehost its macOS
binary. Downloads go directly to upstream; Windows/Linux use pinned upstream source.

- [Official AgentController downloads](https://github.com/Kasempiternal/agentcontroller/releases)
- [macOS setup](https://github.com/Kasempiternal/agentcontroller#installation)
- [Windows source build and setup](https://github.com/Kasempiternal/agentcontroller/blob/master/Windows/README.md)
- [Linux installation](https://github.com/Kasempiternal/agentcontroller/blob/master/Linux/README.md)

Use the upstream asset appropriate to your platform. A source ZIP is not a Windows
executable. AgentController is optional for installation and required for Ultra
Hook's UI validation workflow. Discovery of its tools is not a completed UI test.

## Existing installations

Follow the [upgrade instructions](https://github.com/jonmedev/Ultra_Hook/blob/v__VERSION__/docs/GETTING_STARTED.md#update-or-remove)
for your original installation method. Native installs update through Codex;
script-managed ZIP installs retain their owned removal/backup procedure.

The release workflow runs portable checks on Windows and Linux, acquires the upstream
controller on Windows/Linux/macOS, probes Windows/Linux MCP, and signs the archive's
build provenance. macOS desktop setup remains manual; headless CI does not prove UI
behavior. These checks do not establish universal
security or measured savings. See [credits and licenses](https://github.com/jonmedev/Ultra_Hook/blob/v__VERSION__/NOTICE).
