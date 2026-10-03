# Ultra Hook development

Keep this distributable independent of the maintainer's workstation. Never copy
user profiles, credentials, transcripts, model caches, local screenshots or build
outputs into the repository. Use synthetic fixtures and temporary external paths.

Install through supported Codex commands. Preserve model, effort, permissions and
unrelated plugins. Do not write trust hashes or bypass native hook trust. Keep
AgentController optional to installation and required for validating UI work;
unavailable targets remain unvalidated. CLI/library changes use their actual tests.

Claude Code loads the repository root as the plugin through `.claude-plugin`, with
`claude-hooks.json` running the same scripts under `--runtime=claude`. Keep both
hook files on the same script set and never add a root `hooks/` directory.

Keep skills concise and role-based; no fixed teams or implicit maximum-effort loops.
The external specialist runner sends a brief alone; never add options that give
the external CLI tools, extra directories or more than one turn, and re-measure what
it attaches before changing its flags. Modes cap agents per prompt and must fail open: a state error leaves advice, never a
blocked spawn. Session state holds counters only, never prompt or tool text.
Any change to packaging must pass the release audit and isolated installation tests.
Test with `python -B -m unittest discover -s tests` and the Node tests under
`plugins/ultra-hook/hooks/tests`. Build only allowlisted release inputs.

Publishing, tagging or deploying is a separate user-authorized action. No secrets
are needed for local tests or release packaging.
