#!/usr/bin/env node
"use strict";
// Sends one self-contained brief to an external model through the Command Code
// CLI and prints its single answer. The CLI is an agent that attaches local
// context on its own, so this runner removes what it can and reports the rest:
//  - it runs in a new empty directory, so no repository, Git state or project
//    instruction file exists to attach;
//  - it allows one model turn, so a file the model reads is never sent back;
//  - it passes a minimal environment and loads no skills or saved session.
// The CLI still sends its own system prompt, the temporary directory path, the
// operating system, the date and the user's global Command Code taste profile.
// This is a data boundary for accidental context, not a sandbox.
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const MAX_BRIEF_BYTES = 20 * 1024;
const MAX_OUTPUT_BYTES = 8 * 1024 * 1024;
const NAMES = ["commandcode", "command-code", "cmdc"];
const PREAMBLE = "Answer from the brief below alone, in one reply. Do not call any tool: a tool call ends this run without an answer. " +
  "If the brief lacks something you need, say what is missing instead.\n\n";
// A brief is text for another provider; refuse the obvious credential shapes.
const SECRETS = [/-----BEGIN [A-Z ]*PRIVATE KEY-----/, /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/,
  /\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b/,
  /\bBearer\s+[A-Za-z0-9._~+\/-]{24,}/i];
const ENVIRONMENT = ["PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
  "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "XDG_CONFIG_HOME", "XDG_DATA_HOME"];

class Refusal extends Error {}

function resolveCli(explicit) {
  if (explicit) return /\.[cm]?js$/.test(explicit) ? [process.execPath, explicit] : [explicit];
  const extensions = process.platform === "win32" ? [".cmd", ""] : [""];
  for (const directory of (process.env.PATH || "").split(path.delimiter).filter(Boolean)) {
    for (const name of NAMES) {
      for (const extension of extensions) {
        const shim = path.join(directory, name + extension);
        if (!fs.existsSync(shim)) continue;
        // An npm shim only forwards to the package entry; run that with this Node.
        const root = path.join(directory, "node_modules", "command-code");
        try {
          const bin = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8")).bin;
          const entry = typeof bin === "string" ? bin : bin[name] || Object.values(bin)[0];
          return [process.execPath, path.join(root, entry)];
        } catch { /* not an npm layout */ }
        if (!extension) {
          const real = fs.realpathSync(shim);
          return /\.[cm]?js$/.test(real) ? [process.execPath, real] : [real];
        }
      }
    }
  }
  throw new Refusal("Command Code CLI not found. Install it separately; nothing was sent.");
}

function options(argv) {
  const result = { timeout: 180 };
  for (let index = 0; index < argv.length; index += 1) {
    const [flag, value] = [argv[index], argv[index + 1]];
    if (flag === "--check") { result.check = true; continue; }
    if (!["--brief-file", "--model", "--effort", "--timeout", "--cli"].includes(flag) || value === undefined) {
      throw new Refusal("Usage: external-specialist.cjs --brief-file <file> [--model <id>] [--effort low|medium|high] [--timeout <seconds>] | --check");
    }
    result[flag.slice(2).replace("-file", "File")] = value;
    index += 1;
  }
  if (result.model !== undefined && !/^[A-Za-z0-9][A-Za-z0-9._\/-]{0,80}$/.test(result.model)) throw new Refusal("Invalid model id.");
  if (result.effort !== undefined && !["low", "medium", "high"].includes(result.effort)) throw new Refusal("Effort must be low, medium or high.");
  result.timeout = Number(result.timeout);
  if (!Number.isFinite(result.timeout) || result.timeout < 10 || result.timeout > 600) throw new Refusal("Timeout must be 10 to 600 seconds.");
  return result;
}

function readBrief(file) {
  if (!file) throw new Refusal("A brief file is required. Write the self-contained assignment to a file and pass --brief-file.");
  const info = fs.statSync(file);
  if (!info.isFile() || info.size > MAX_BRIEF_BYTES) throw new Refusal(`The brief must be a file of at most ${MAX_BRIEF_BYTES} bytes.`);
  const brief = fs.readFileSync(file, "utf8").trim();
  if (!brief) throw new Refusal("The brief is empty.");
  if (SECRETS.some(pattern => pattern.test(brief))) throw new Refusal("The brief contains credential-shaped text; nothing was sent. Remove it or use a redacted value.");
  return brief;
}

function tasteProfilePresent() {
  try { return fs.statSync(path.join(os.homedir(), ".commandcode", "taste", "taste.md")).size > 0; } catch { return false; }
}

function disclosure(briefBytes) {
  return { briefBytes, workingDirectory: "new empty temporary directory (its path is sent)", repositoryFiles: false, gitState: false,
    projectInstructions: false, environmentVariables: false, operatingSystemAndDate: true, commandCodeTasteProfile: tasteProfilePresent() };
}

function run(argv) {
  const selected = options(argv);
  const cli = resolveCli(selected.cli);
  if (selected.check) return { status: "available", sent: disclosure(0) };
  const brief = readBrief(selected.briefFile);
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "ultra-hook-external-"));
  try {
    const args = ["-p", PREAMBLE + brief, "--output-format", "json", "--max-turns", "1", "--no-session", "--no-skills",
      "--skip-onboarding", "--no-auto-update"];
    if (selected.model) args.push("--model", selected.model);
    if (selected.effort) args.push("--effort", selected.effort);
    const env = { COMMANDCODE_SKIP_UPDATES: "1" };
    for (const [key, value] of Object.entries(process.env)) if (ENVIRONMENT.includes(key.toUpperCase())) env[key] = value;
    const child = spawnSync(cli[0], [...cli.slice(1), ...args], { cwd: workspace, env, encoding: "utf8", shell: false,
      windowsHide: true, timeout: selected.timeout * 1000, maxBuffer: MAX_OUTPUT_BYTES, stdio: ["ignore", "pipe", "pipe"] });
    if (child.error) throw new Refusal(child.error.code === "ETIMEDOUT" ? "The external specialist timed out." : "The external specialist could not be started or exceeded its output limit.");
    let result = null, model = null;
    for (const line of child.stdout.split("\n")) {
      if (!line.startsWith("{")) continue;
      let event;
      try { event = JSON.parse(line); } catch { continue; }
      if (event.type === "result") result = event;
      if (event.event?.type === "model_request_start" && typeof event.event.model === "string") model = event.event.model;
    }
    if (!result) throw new Refusal("The external specialist returned no result. Check that Command Code is signed in.");
    if (result.stopReason === "max_turns") throw new Refusal("The external specialist tried to use a tool, which this runner does not allow. Make the brief self-contained and retry once.");
    if (result.subtype !== "success" || typeof result.finalText !== "string") throw new Refusal("The external specialist did not complete the request.");
    return { status: "answered", model, text: result.finalText, usage: result.usage || null, sent: disclosure(Buffer.byteLength(brief)) };
  } finally {
    // Only the directory this run created, and only when it is still a direct child of the temp directory.
    if (path.dirname(path.resolve(workspace)) === path.resolve(os.tmpdir())) fs.rmSync(workspace, { recursive: true, force: true });
  }
}

if (require.main === module) {
  try {
    process.stdout.write(JSON.stringify(run(process.argv.slice(2)), null, 2) + "\n");
  } catch (error) {
    // Only fixed messages leave the runner; a brief or provider text never reaches an error.
    const message = error instanceof Refusal ? error.message : "The external specialist run failed; private diagnostics withheld.";
    process.stdout.write(JSON.stringify({ status: "error", message }) + "\n");
    process.exitCode = 1;
  }
} else {
  module.exports = { run, resolveCli, readBrief, NAMES, MAX_BRIEF_BYTES };
}
