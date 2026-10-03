#!/usr/bin/env node
"use strict";
// Counts agent spawns against the current mode's cap and adds routing advice.
// Over the cap, Claude Code asks the user and Codex denies. It never selects a
// model or rewrites the call, and without session state it only advises.
const { readEvent, runtime, ask, deny } = require("./hook-io.cjs");
const { emitContext, spawnText, capText } = require("./model-routing.cjs");
const { recordSpawn } = require("./session-mode.cjs");
async function main() { try {
  const input = await readEvent();
  if (input.hook_event_name === "PreToolUse" &&
      ["spawn_agent", "Agent", "Task", "Workflow", "collaboration.spawn_agent"].includes(input.tool_name)) {
    const host = runtime();
    const slot = recordSpawn(input.session_id);
    if (slot && slot.index > slot.cap) return host === "claude" ? ask(capText(slot, host)) : deny(capText(slot, host));
    emitContext("PreToolUse", spawnText(slot, host));
  }
} catch { /* No approval or model changes on errors. */ } }
main();
