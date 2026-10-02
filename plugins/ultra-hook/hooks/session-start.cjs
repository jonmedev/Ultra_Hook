#!/usr/bin/env node
"use strict";
const fs = require("node:fs");
const { emitContext } = require("./model-routing.cjs");
try {
  const input = JSON.parse(fs.readFileSync(0, "utf8") || "{}");
  if (input.hook_event_name === "SessionStart") emitContext("SessionStart");
} catch { /* Advisory only; never inspect previous sessions or start old work. */ }
