#!/usr/bin/env node
"use strict";
// Prints how often each mode ran and how many agents it spawned, from the local
// session records. Read-only; the records hold counters, not prompts.
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { report, dataDirectory } = require("./session-mode.cjs");

// A hook receives its data directory from the host. Run by hand, look in the
// places each host uses for this plugin.
function candidates() {
  const found = [dataDirectory()];
  const homes = [process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude"),
    process.env.CODEX_HOME || path.join(os.homedir(), ".codex")];
  for (const home of homes) {
    const base = path.join(home, "plugins", "data");
    let names = [];
    try { names = fs.readdirSync(base).slice(0, 500); } catch { continue; }
    for (const name of names) if (name.includes("ultra-hook")) found.push(path.join(base, name, "sessions"));
  }
  return [...new Set(found)];
}

function main(argv) {
  const index = argv.indexOf("--dir");
  const directories = index >= 0 && argv[index + 1] ? [argv[index + 1]] : candidates();
  const results = directories.map(directory => ({ directory, ...report(directory) })).filter(result => result.sessions);
  if (argv.includes("--json")) {
    const result = results[0] || { directory: directories[0], ...report(directories[0]) };
    process.stdout.write(JSON.stringify(results.length > 1 ? results : result, null, 2) + "\n");
    return;
  }
  if (!results.length) {
    process.stdout.write("No Ultra Hook session records found in:\n" + directories.map(directory => "  " + directory).join("\n") + "\n");
    return;
  }
  for (const result of results) {
    process.stdout.write(`${result.directory}\n${result.sessions} session(s), last 30 days\n`);
    process.stdout.write("mode     prompts  agents  over cap  agents/prompt\n");
    for (const [mode, row] of Object.entries(result.totals)) {
      const average = row.prompts ? (row.spawns / row.prompts).toFixed(2) : "-";
      process.stdout.write(`${mode.padEnd(8)} ${String(row.prompts).padStart(7)} ${String(row.spawns).padStart(7)} ${String(row.overCap).padStart(9)}  ${average.padStart(13)}\n`);
    }
    process.stdout.write("\n");
  }
}

main(process.argv.slice(2));
