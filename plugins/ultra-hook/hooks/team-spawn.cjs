#!/usr/bin/env node
"use strict";
// Advisory on native team creation in Codex and Claude Code. It does not deny,
// select or rewrite tools.
const { readEvent, runtime } = require("./hook-io.cjs");
const { emitContext, contextFor } = require("./model-routing.cjs");
async function main() { try {
  const input = await readEvent();
  if (input.hook_event_name === "PreToolUse" &&
      ["spawn_agent", "Agent", "Task", "Workflow", "collaboration.spawn_agent"].includes(input.tool_name)) {
    emitContext("PreToolUse", contextFor("PreToolUse", "team", runtime()));
  }
} catch { /* No approval or model changes on errors. */ } }
main();
