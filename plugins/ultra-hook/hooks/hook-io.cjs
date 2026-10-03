"use strict";
// Bounds are below the host hook timeout. No payloads or parser errors are logged.
const fs = require("node:fs");
const MAX_INPUT_BYTES = 1024 * 1024;
const INPUT_TIMEOUT_MS = 1500;

function readEvent() {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0, settled = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      process.stdin.removeAllListeners("data");
      process.stdin.removeAllListeners("end");
      process.stdin.removeAllListeners("error");
      if (error) { process.stdin.destroy(); reject(new Error("Hook input unavailable")); return; }
      try {
        const value = JSON.parse(Buffer.concat(chunks).toString("utf8"));
        if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
        resolve(value);
      } catch { reject(new Error("Invalid hook input")); }
    };
    const timer = setTimeout(() => finish(true), INPUT_TIMEOUT_MS);
    process.stdin.on("data", chunk => {
      size += chunk.length;
      if (size > MAX_INPUT_BYTES) return finish(true);
      chunks.push(chunk);
    });
    process.stdin.on("end", () => finish(false));
    process.stdin.on("error", () => finish(true));
  });
}

// The Claude Code hook file passes --runtime=claude. Anything else is Codex, so an
// unknown host never receives a decision it may not implement.
function runtime(argv = process.argv) {
  return argv.includes("--runtime=claude") ? "claude" : "codex";
}

function decide(permissionDecision, reason) {
  process.stdout.write(JSON.stringify({hookSpecificOutput: {
    hookEventName: "PreToolUse", permissionDecision, permissionDecisionReason: reason
  }}) + "\n");
}

function deny(reason = "Ultra Hook could not safely inspect this input. The tool call is blocked; do not retry through another tool to bypass it.") {
  decide("deny", reason);
}

// Codex does not implement PreToolUse ask; callers use it for Claude Code only.
function ask(reason) { decide("ask", reason); }

function readBoundedFile(filename, maximum = MAX_INPUT_BYTES) {
  const initial = fs.lstatSync(filename);
  if (!initial.isFile() || initial.isSymbolicLink() || initial.nlink !== 1 || initial.size > maximum) throw new Error("Invalid hint file");
  const fd = fs.openSync(filename, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
  try {
    const stat = fs.fstatSync(fd);
    if (!stat.isFile() || stat.nlink !== 1 || stat.size > maximum || stat.ino !== initial.ino || stat.dev !== initial.dev) throw new Error("Changed hint file");
    const buffer = Buffer.alloc(maximum + 1);
    let offset = 0, count;
    while ((count = fs.readSync(fd, buffer, offset, buffer.length - offset, null)) > 0) {
      offset += count;
      if (offset > maximum) throw new Error("Hint file too large");
    }
    return buffer.subarray(0, offset).toString("utf8");
  } finally { fs.closeSync(fd); }
}

module.exports = { readEvent, deny, ask, runtime, readBoundedFile, MAX_INPUT_BYTES };
