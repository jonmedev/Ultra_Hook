#!/usr/bin/env node
"use strict";

const fs = require("fs");
const { expandedSegments, executableName, gitSubcommand } = require("./safety-command-parser.cjs");

function gitOperation(words, start) {
  const operation = gitSubcommand(words, start)?.name;
  return new Set(["commit", "commit-tree", "push"]).has(operation) ? `git ${operation}` : null;
}

function inspectCommand(command) {
  if (typeof command !== "string") return null;
  for (const words of expandedSegments(command)) {
    const executable = executableName(words[0]);
    if (["rm", "remove-item", "ri", "del", "erase", "rmdir", "rd"].includes(executable)) return executable;
    if (executable === "git") {
      const operation = gitOperation(words, 1);
      if (operation) return operation;
    }
  }
  return null;
}

function check(payload) {
  const tool = String(payload?.tool_name || "").split(".").at(-1);
  if (payload?.hook_event_name !== "PreToolUse" || !["Bash", "exec_command"].includes(tool)) return null;
  const command = payload?.tool_input?.command ?? payload?.tool_input?.cmd;
  return inspectCommand(command);
}

function main() {
  let payload;
  try { payload = JSON.parse(fs.readFileSync(0, "utf8")); }
  catch { return; }
  const operation = check(payload);
  if (!operation) return;
  // Only a known operation label enters the response. Commands can include
  // credentials in arguments, environment assignments, or commit messages.
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "ask",
      permissionDecisionReason: `Running ${operation} always requires your approval.`
    }
  }) + "\n");
}

if (require.main === module) main();
else module.exports = { inspectCommand, gitOperation, check };
