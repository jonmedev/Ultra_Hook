# Ultra Hook __VERSION__

## Install: two commands

With Codex CLI signed in, Node.js LTS and Git installed, open PowerShell or Terminal:

```sh
codex plugin marketplace add jonmedev/Ultra_Hook --ref v__VERSION__
codex plugin add ultra-hook@ultra-hook
```

Codex downloads and installs the plugin. **No ZIP extraction or Python is needed
for this method.** In Codex, review the five hooks in `/hooks`, start a new conversation
and send `$ultra-hook` followed by your task.

[Quick start and examples](https://github.com/jonmedev/Ultra_Hook/blob/v__VERSION__/docs/GETTING_STARTED.md)
explain activation, prerequisites and the separate update paths for existing installations.

## Alternative: manual ZIP download

- [Plugin ZIP](https://github.com/jonmedev/Ultra_Hook/releases/download/v__VERSION__/ultra-hook-__VERSION__.zip)
- [SHA-256 checksum](https://github.com/jonmedev/Ultra_Hook/releases/download/v__VERSION__/ultra-hook-__VERSION__.sha256)
- [Verify the download and provenance](https://github.com/jonmedev/Ultra_Hook/blob/v__VERSION__/SECURITY.md#verify-a-download)
- [Installation, activation and usage](https://github.com/jonmedev/Ultra_Hook/blob/v__VERSION__/docs/GETTING_STARTED.md)

The ZIP route uses Python management scripts. Follow the
[advanced guide](https://github.com/jonmedev/Ultra_Hook/blob/v__VERSION__/docs/ADVANCED_INSTALL.md)
and do not combine both installation methods on the same profile registration.

## AgentController is by Kasempiternal

**[AgentController](https://github.com/Kasempiternal/agentcontroller) is an independent
project developed by Kasempiternal.** Ultra Hook supplies an integration skill and
an optional pinned-source build helper. It does not own or bundle the controller.

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

The release workflow runs portable checks on Windows and Linux before publishing
and signs the archive's build provenance. These checks do not establish universal
security or measured savings. See [credits and licenses](https://github.com/jonmedev/Ultra_Hook/blob/v__VERSION__/NOTICE).
