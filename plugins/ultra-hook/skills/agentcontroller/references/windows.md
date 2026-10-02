# AgentController on Windows

Probe the installed backend and actual target. Cross-platform tool names do not imply
feature parity, and capability discovery does not establish that execution is routed
to a working implementation.

- Readiness fields such as `allGranted` and `uiAutomationAvailable` can be static
  declarations in Windows implementations. Confirm access with a real target snapshot
  or assertion rather than accepting these flags as a permissions test.
- UI Automation patterns can support background actions. Raw keyboard/pointer input
  and some fallbacks require foreground operation and can change focus. Use only the
  supported behavior authorized for the target. A `foreground:false` parameter is
  not proof that an operation preserves focus; URL activation can use the system shell.
- Interactive access can require an unlocked desktop, and UIPI can restrict elevated
  applications. Identify the actual access failure instead of routinely requesting
  elevation or changing system protections.
- `PrintWindow`-based images can be blank for GPU-rendered content. Report the capture
  limitation. Use another supported AgentController capture path only within the
  authorized interaction; do not replace the required backend with another controller.
- Recording, generic app-state reset and `run_app_code` may return unsupported results
  even when their schemas or a CDP/Blender target appear in discovery. Check the concrete
  operation before promising scripting, recording or reset support.
- Accessibility visibility assertions describe resolved elements. Inspect a relevant
  screenshot when the acceptance condition concerns rendered pixels or layout.

These are compatibility checks, not guarantees about every release. Let observed
results and the installed tool contract determine the validated coverage. Keep an
unsupported condition explicit instead of reporting an unexercised flow as passed.
