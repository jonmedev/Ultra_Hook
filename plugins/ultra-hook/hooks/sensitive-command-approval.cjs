#!/usr/bin/env node
"use strict";

const { readEvent, deny, ask, runtime } = require("./hook-io.cjs");
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

// PowerShell is Claude Code's native Windows shell tool; the parser already
// recognizes its literal cmdlets and nested hosts.
const SHELL_TOOLS = ["Bash", "exec_command", "PowerShell"];

function check(payload) {
  const tool = String(payload?.tool_name || "").split(".").at(-1);
  if (payload?.hook_event_name !== "PreToolUse" || !SHELL_TOOLS.includes(tool)) return null;
  const command = payload?.tool_input?.command ?? payload?.tool_input?.cmd;
  return inspectCommand(command);
}

function destructiveOperation(command) {
  for (const words of expandedSegments(command)) {
    if (executableName(words[0]) !== "git") continue;
    const subcommand = gitSubcommand(words);
    const args = words.slice((subcommand?.index ?? 0) + 1);
    if (subcommand?.name === "reset" && args.includes("--hard")) return "git reset --hard";
    // A dry run only lists candidates, even when combined with --force.
    const dryRun = args.some(arg => /^-[a-z]*n[a-z]*$/.test(arg) || arg === "--dry-run");
    if (subcommand?.name === "clean" && !dryRun && args.some(arg => /^-[a-z]*f[a-z]*$/.test(arg) || arg === "--force")) return "git clean --force";
    if (subcommand?.name === "push" && args.some(arg => /^(?:--force(?:=|$)|--mirror$|-[a-z]*f[a-z]*$|\+)/.test(arg))) return "git push with history replacement";
  }
  return null;
}

async function main() { try {
  const payload = await readEvent();
  const tool = String(payload?.tool_name || "").split(".").at(-1);
  if (payload.hook_event_name !== "PreToolUse" || !SHELL_TOOLS.includes(tool)) return;
  const command = payload.tool_input?.command ?? payload.tool_input?.cmd;
  if (typeof command !== "string" || !command.trim()) return deny();
  const destructive = destructiveOperation(command);
  if (destructive) {
    // Claude Code can put the decision to the user; Codex only supports a denial.
    if (runtime() === "claude") return ask(`Ultra Hook: ${destructive} discards work or replaces history. Approve only if this exact operation was requested.`);
    return deny(`Ultra Hook blocks ${destructive}. Preserve work and use a reversible operation; do not evade the hook through another tool.`);
  }
  const operation = check(payload);
  if (!operation) return;
  // Only a known operation label enters the response. Commands can include
  // credentials in arguments, environment assignments, or commit messages.
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      additionalContext: `Ultra Hook: ${operation} changes files or repository state. Verify the target and existing user authorization; native permissions govern execution. This reminder grants no approval and does not require asking again when already authorized.`
    }
  }) + "\n");
} catch { deny(); } }

if (require.main === module) main();
else module.exports = { inspectCommand, gitOperation, destructiveOperation, check };
