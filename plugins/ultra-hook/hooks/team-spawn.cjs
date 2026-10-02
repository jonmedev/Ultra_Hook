#!/usr/bin/env node
"use strict";
// Codex advisory on native team creation. It does not deny, select or rewrite tools.
const fs = require("node:fs");
const { emitContext } = require("./model-routing.cjs");
try {
  const input = JSON.parse(fs.readFileSync(0, "utf8"));
  if (input.hook_event_name === "PreToolUse" &&
      ["spawn_agent", "Agent", "Task", "Workflow", "collaboration.spawn_agent"].includes(input.tool_name)) {
    emitContext("PreToolUse");
  }
} catch { /* No approval or model changes on errors. */ }
