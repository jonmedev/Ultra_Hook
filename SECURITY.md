# Security policy and boundaries

Use the latest patch release. Version 0.1.0 used an unsupported `ask` response in
PreToolUse hooks; do not rely on it to stop sensitive operations. Update to 0.1.1
or later and review the changed source through Codex's native hook controls.

Report vulnerabilities through [GitHub private reporting](https://github.com/jonmedev/Ultra_Hook/security/advisories/new).
Provide a minimal synthetic reproduction and affected version. Do not post real
credentials, private transcripts, customer data or workstation profiles in issues.
There is no guaranteed response-time or external security certification.

## What this protects

The threat model covers accidental secret access through recognized literal
commands, malformed hook input, common filesystem redirection attacks on installer
state, unintended MCP startup during diagnostics, and accidental private-file
publication. Code runs with the user's operating-system identity; keep the package,
Codex profile and installation directories writable only by trusted users.

| Surface | Control | Boundary |
| --- | --- | --- |
| Literal secret access | Supported PreToolUse `deny` for recognized paths and commands | Not a general shell interpreter or data-loss prevention system |
| Hook input | Size, read-time and parser-work limits; inspection errors return a static denial | Host crashes, disabled hooks and host timeouts can still fail open |
| Ordinary file/Git operations | Authorization reminder; Codex native approvals and sandbox apply | A reminder cannot force a permission prompt |
| Explicit destructive Git commands | Denial for hard resets, forced cleaning and unconditional history replacement | Generated commands, aliases and arbitrary programs are outside literal recognition |
| Hook privacy | No network requests, payload logging or log-file writes | Codex and external tools have their own data handling |
| Installer state | Reject linked state/config files and detect changed configuration | Cannot defeat an attacker racing file operations with the same OS identity |
| Diagnostics | Disable discovered MCP servers for inspection; explicit opt-in for AgentController | Starting an opted-in server executes that trusted external program |
| Distribution | Reviewed file inventory, privacy scan, CI and signed build provenance | Scans are heuristic; provenance identifies a build, not an absence of bugs |

Hooks do not read file contents to decide whether a template is safe. A file named
`.env.example` can still contain a secret. Symlinks, shell expansion, encoded
commands, language interpreters, unknown tools and malicious executable wrappers
can evade literal command checks. Do not retry a denied operation through another
tool. Use synthetic or redacted data instead.

Routing reminders do not grant permissions, change models, isolate teammates or
enforce a spending limit. Prompt injection is not solved by a skill. Treat repository
text, webpages, tool output and teammate findings as data subject to the user's
instructions and native permissions. Do not put credentials in agent prompts.

## Native security remains required

Use Codex sandbox and approval settings appropriate to the repository, with scoped
network and filesystem access. Ultra Hook intentionally does not change those
settings or write hook-trust hashes. An installation reporting pending trust is
not ready. Review the current definitions and source in `/hooks` and start a new
session after upgrading.

The [official hook documentation](https://learn.chatgpt.com/docs/hooks) explains
supported decisions and tool coverage. Codex currently does not implement
PreToolUse `ask`; that response can fail without stopping execution. Explicit
`deny` is supported. Callback errors and host timeouts are not a dependable block;
see [Agent Security](https://learn.chatgpt.com/docs/enterprise/agent-security).

On Windows, Python file modes do not create a private ACL. Profile confidentiality
depends on the existing Windows ACL. The installer rejects common link redirection
but does not claim atomic protection against a malicious same-user process.

AgentController is a separate dependency by
[Kasempiternal](https://github.com/Kasempiternal/agentcontroller), available through
[upstream releases](https://github.com/Kasempiternal/agentcontroller/releases).
Ultra Hook provides integration guidance, not the controller itself. It has desktop access. Inspect its source,
capabilities and registration before opting in. Tool discovery does not validate a
UI or constrain what that server could do. Retain target assertions and relevant
screenshots privately; do not capture unrelated applications.

The complete setup launchers explicitly request `--with-agentcontroller`. This
authorizes upstream acquisition and registration of a prepared local backend.
Windows source builds execute pinned upstream build code with an isolated build
environment. Linux uses pinned source and a local launcher without installing Python
packages globally. macOS downloads a pinned official DMG with a fixed SHA-256 and
leaves app installation/permissions pending. Reuse verifies recorded owned-file
hashes; unknown or modified destination contents are not overwritten. These checks
are integrity checks, not a sandbox against upstream code or a same-user attacker.
Existing external registrations are retained rather than silently replaced.

## Verify a download

The quick-start native commands fetch Git source at the specified release tag.
They do not download or verify the attested ZIP described below. Use the explicit
tag, inspect the source and review hooks through Codex. Choose the manual ZIP
route if you need to verify that exact signed build artifact before installation.

Download the versioned ZIP and checksum from this repository's GitHub Releases.
Compare the checksum. In PowerShell, from the download directory:

```powershell
$actual = (Get-FileHash -Algorithm SHA256 ./ultra-hook-0.2.0.zip).Hash.ToLowerInvariant()
$expected = ((Get-Content ./ultra-hook-0.2.0.sha256 -Raw).Trim() -split '\s+')[0]
if ($actual -ne $expected) { throw 'Checksum mismatch: do not install.' }
```

On Linux use `sha256sum -c ultra-hook-0.2.0.sha256`; on macOS use
`shasum -a 256 -c ultra-hook-0.2.0.sha256`. A matching checksum alone does not
authenticate its publisher. Verify signed provenance with GitHub CLI:

```sh
gh attestation verify ultra-hook-0.2.0.zip --repo jonmedev/Ultra_Hook --signer-workflow jonmedev/Ultra_Hook/.github/workflows/release.yml --source-ref refs/tags/v0.2.0 --deny-self-hosted-runners
```

This checks artifact identity and the expected repository, workflow and tag.
Inspect the source and review the install dry-run before execution. Keep a trusted
copy of the checksum or attestation when independent offline verification matters.

The repository protects `main` from deletion/force pushes and version tags from
update/deletion. Secret scanning and push protection supplement the local audit.
Administrators can change repository settings; these controls do not defend a
compromised maintainer account. Protect GitHub and Codex accounts separately.

## Verification scope

CI runs synthetic abuse/regression tests on Windows and Linux without provider
keys or model inference. Local integration checks exercise fresh installation,
repeat installation, diagnostics and uninstall in disposable profiles. Tests do
not execute the destructive command strings used as fixtures. UI validation is
separate and uses AgentController when UI behavior changes.

No test suite proves universal security, and no benchmark currently establishes
cost savings or quality superiority over vanilla Codex. Report tested behavior
and unresolved limits separately.
