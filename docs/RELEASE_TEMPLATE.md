# Ultra Hook __VERSION__

## Download Ultra Hook

- [Plugin ZIP](https://github.com/jonmedev/Ultra_Hook/releases/download/v__VERSION__/ultra-hook-__VERSION__.zip)
- [SHA-256 checksum](https://github.com/jonmedev/Ultra_Hook/releases/download/v__VERSION__/ultra-hook-__VERSION__.sha256)
- [Verify the download and provenance](https://github.com/jonmedev/Ultra_Hook/blob/v__VERSION__/SECURITY.md#verify-a-download)
- [Installation, activation and usage](https://github.com/jonmedev/Ultra_Hook/blob/v__VERSION__/docs/GETTING_STARTED.md)

Extract the verified ZIP into a directory you will keep. From that root, run
`python -B scripts/install.py --dry-run`, then `python -B scripts/install.py`.
Review and approve hooks in Codex `/hooks`, run `python -B scripts/doctor.py`,
and start a new session. On macOS/Linux use `python3`.

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

Follow the [upgrade instructions](https://github.com/jonmedev/Ultra_Hook/blob/v__VERSION__/docs/GETTING_STARTED.md#upgrade-or-remove).
Remove the owned older installation using its original source/profile, retain
backups, then install the new version from its own extracted directory. Scripts
provide readable output by default; add `--json` for automation.

The release workflow runs portable checks on Windows and Linux before publishing
and signs the archive's build provenance. These checks do not establish universal
security or measured savings. See [credits and licenses](https://github.com/jonmedev/Ultra_Hook/blob/v__VERSION__/NOTICE).
