#!/usr/bin/env node
"use strict";

const { readEvent, deny, ask, runtime } = require("./hook-io.cjs");
const { expandedSegments, executableName, gitSubcommand } = require("./safety-command-parser.cjs");
const { recordSpawn } = require("./session-mode.cjs");
const { capText } = require("./model-routing.cjs");

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

// Command Code is an agent CLI that attaches local context for an external
// provider. "runner" is this plugin's bounded wrapper; "raw" is a direct call
// that would send a model request. Subcommands that only report state pass.
const EXTERNAL_CLI = ["commandcode", "command-code", "cmdc"];
const EXTERNAL_LOCAL = new Set(["--version", "-v", "--help", "-h", "--list-models", "status", "whoami", "info", "help", "update"]);
function externalCall(command) {
  for (const words of expandedSegments(command)) {
    const executable = executableName(words[0]);
    if (executable === "node" && words.some(word => /(?:^|[\\/])external-specialist\.cjs$/.test(word))) {
      return words.includes("--check") ? null : "runner";
    }
    const index = ["npx", "pnpx", "bunx"].includes(executable) ? words.findIndex((word, position) => position > 0 && !word.startsWith("-")) : 0;
    if (index >= 0 && EXTERNAL_CLI.includes(executableName(words[index])) && !words.slice(index + 1).some(word => EXTERNAL_LOCAL.has(word))) return "raw";
  }
  return null;
}

function context(text) {
  process.stdout.write(JSON.stringify({ hookSpecificOutput: { hookEventName: "PreToolUse", additionalContext: text } }) + "\n");
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
  const external = externalCall(command);
  if (external === "raw") {
    if (runtime() === "claude") return ask("Ultra Hook: a direct Command Code call sends this directory's listing, Git state and project instructions to an external provider. Approve only if that is intended; the external-specialist runner sends a brief alone.");
    return deny("Ultra Hook blocks a direct Command Code call: the CLI attaches the working directory listing, Git state and project instructions for an external provider. Use the external-specialist runner with a self-contained brief; do not evade the hook through another tool.");
  }
  if (external === "runner") {
    // An external specialist is a worker like any other: it takes a slot of the prompt's cap.
    const slot = recordSpawn(payload.session_id);
    if (slot && slot.index > slot.cap) return runtime() === "claude" ? ask(capText(slot, "claude")) : deny(capText(slot, "codex"));
    return context(`Ultra Hook external specialist${slot ? ` ${slot.index}/${slot.cap} (${slot.mode})` : ""}: only the brief file leaves this machine as task content; ` +
      "keep it self-contained and free of credentials, private data and repository text the user has not cleared for an external provider. Verify its answer before using it.");
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
else module.exports = { inspectCommand, gitOperation, destructiveOperation, externalCall, check };
