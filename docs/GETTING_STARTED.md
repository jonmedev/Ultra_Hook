# Start using Ultra Hook

Ultra Hook helps Codex implement, debug, review and research with appropriate
verification and useful native teammates. Small tasks stay direct. It preserves
your chosen leader and permissions. It does not unlock models or guarantee savings.

## Install with two commands

Have [Codex CLI](https://developers.openai.com/codex/cli/) installed and signed in,
plus [Node.js LTS](https://nodejs.org/en/download) and [Git](https://git-scm.com/downloads/).
For an existing Ultra Hook/CAS installation, read [updates](#update-or-remove) first.

Open **PowerShell on Windows** or **Terminal on macOS/Linux**, then run each line:

```sh
codex plugin marketplace add jonmedev/Ultra_Hook --ref v0.1.4
codex plugin add ultra-hook@ultra-hook
```

Codex downloads and installs the versioned plugin. No manual ZIP download, local
checkout or Python installation is needed for this route. These commands use your
current Codex profile (`CODEX_HOME` if set). Use that same profile when opening Codex.

## Activate and use

In Codex, open `/hooks`, inspect and approve the five Ultra Hook hooks, then start
a new conversation. Native hook approval is a separate user step; installation
does not grant it. Send a real task:

```text
$ultra-hook Fix the CSV importer dropping its last row. Reproduce the failure,
preserve the public API and verify the original input after the fix.
```

For a read-only review:

```text
$ultra-hook Review this branch for data loss. Report evidence and affected
locations; do not edit files or publish anything.
```

For direct work, add `without subagents`. For native teamwork, describe the outcome
and allow useful independent work; workers discuss findings with the lead. The
skill does not force a team or maximum reasoning for every request.

Use `$ultra-hook:ultra-hook` if the short name is ambiguous. To inspect installation:

```sh
codex plugin list --marketplace ultra-hook
```

The plugin should be enabled; `/hooks` should show its five reviewed hooks. There
are two skills: `ultra-hook` and `agentcontroller`. The second is guidance for an
external controller, not the controller executable. Installation status alone is
not evidence that a task or UI flow has been tested.

## Optional AgentController

You can program, debug and review code without installing AgentController.
You need it when using Ultra Hook to validate UI behavior, such as clicking a
button and checking what the application displays.

**[AgentController is developed by Kasempiternal](https://github.com/Kasempiternal/agentcontroller),
independently of Ultra Hook. [Download it from its official releases](https://github.com/Kasempiternal/agentcontroller/releases).**
The 2.5.0 release publishes a macOS DMG. Windows/Linux source installation is
documented in the upstream [Windows guide](https://github.com/Kasempiternal/agentcontroller/blob/master/Windows/README.md)
and [Linux guide](https://github.com/Kasempiternal/agentcontroller/blob/master/Linux/README.md).
A source ZIP is not a Windows installer.

Before registering anything, run `codex mcp list` and check whether AgentController
is already configured. Do not overwrite an existing registration.

**macOS:** launch AgentController.app, grant it Accessibility and Screen Recording
permissions, and complete [upstream setup](https://github.com/Kasempiternal/agentcontroller#setup)
so its stdio bridge exists. Register the bridge, not the `.app` bundle:

```sh
codex mcp add agentcontroller -- "$HOME/.agentcontroller/agentcontroller-mcp-bridge.sh"
```

**Windows/Linux:** register the working stdio executable from the upstream
installation. Windows uses `agentcontroller-windows.exe`; Linux can use the
installed `agentcontroller-linux` console script. Replace this example with its
actual absolute path:

```sh
codex mcp add agentcontroller -- "absolute path to AgentController launcher"
```

Start a new Codex session, then ask:

```text
$agentcontroller Check that my local app's search filter returns the expected
result and that clearing it restores the full list. Keep assertions and a
focused screenshot; report unsupported operations or missing access.
```

The integration must reach the real target. A detected tool catalog is not a UI
pass. More platform details and the optional pinned Windows builder are in the
[advanced guide](ADVANCED_INSTALL.md#optional-enable-agentcontroller-for-ui-work).

## Update or remove

**Installed with the two Codex commands above:** to uninstall, run:

```sh
codex plugin remove ultra-hook@ultra-hook
codex plugin marketplace remove ultra-hook
```

To update to a new release, run those two removal commands first, then repeat the
two installation commands with the new tag. A pinned marketplace stays on its tag;
adding the same name with a different tag can be rejected. This removal/reinstall
path is tested and preserves unrelated preferences. Review the new source and hooks,
then start a new session. Do not change hook trust data manually.

**Installed previously with `scripts/install.py` or migrating CAS:** follow the
[script-managed upgrade/removal guide](ADVANCED_INSTALL.md#upgrade-or-remove) or
[CAS migration guide](MIGRATION.md). Do not mix native removal with an active script
receipt; finish removal through the original method before switching methods.
This preserves recorded rollback/ownership information. Native installation does
not create a script receipt or disable another plugin for you.

Removing Ultra Hook does not remove an independently registered AgentController.
Manage that separate MCP registration only if you intend to stop using it elsewhere.

## If something is missing

| Symptom | What to do |
| --- | --- |
| `codex`, `node` or `git` not found | Install that prerequisite from the links above and reopen the terminal |
| Codex does not recognize `plugin` | Update Codex using its official installation method |
| Skill missing after install | Confirm the plugin/profile, start a new conversation and try the qualified skill name |
| Hooks not active | Review them in `/hooks`; restart the session after approval |
| AgentController missing | Continue non-UI work, or install/register the external tool for UI validation |
| Previous ZIP/CAS installation | Follow the matching migration path rather than overlaying another installation |

Prefer manual downloads? [Get the release ZIP](https://github.com/jonmedev/Ultra_Hook/releases/latest)
and follow [advanced installation](ADVANCED_INSTALL.md). That alternative uses
Python 3.11+ for management scripts. Download verification and hook limits are
documented in [SECURITY.md](../SECURITY.md). The native marketplace mechanism is
documented by [OpenAI](https://developers.openai.com/plugins/build/plugins#add-a-marketplace-from-the-cli).
