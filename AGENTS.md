# Ultra Hook development

Keep this distributable independent of the maintainer's workstation. Never copy
user profiles, credentials, transcripts, model caches, local screenshots or build
outputs into the repository. Use synthetic fixtures and temporary external paths.

Install through supported Codex commands. Preserve model, effort, permissions and
unrelated plugins. Do not write trust hashes or bypass native hook trust. Keep
AgentController optional to installation and required for validating UI work;
unavailable targets remain unvalidated. CLI/library changes use their actual tests.

Keep skills concise and role-based; no fixed teams or implicit maximum-effort loops.
Any change to packaging must pass the release audit and isolated installation tests.
Test with `python -B -m unittest discover -s tests` and the Node tests under
`plugins/ultra-hook/hooks/tests`. Build only allowlisted release inputs.

Publishing, tagging or deploying is a separate user-authorized action. No secrets
are needed for local tests or release packaging.
