"use strict";

// A small literal-command recognizer, not a shell interpreter. Keep Windows
// backslashes intact; only consume shell escapes where they have meaning.
const REDIRECTION = "\u0000REDIRECTION\u0000";
function commandSegments(source) {
  if (typeof source !== "string") return [];
  const segments = [];
  let words = [], word = "", quote = null;
  const flushWord = () => { if (word.length) words.push(word); word = ""; };
  const flushSegment = () => { flushWord(); if (words.length) segments.push(words); words = []; };
  const windowsWord = () => /^[A-Za-z]:\\|^\\\\/.test(word);
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index], next = source[index + 1];
    if (quote === "'") {
      if (char === "'" && next === "'") { word += "'"; index += 1; }
      else if (char === "'") quote = null;
      else word += char;
      continue;
    }
    if (quote === '"') {
      if (char === '"') quote = null;
      else if (char === "`" && next && /["`$]/.test(next)) word += source[++index];
      else if (char === "\\" && !windowsWord() && next && /["$`\\\n]/.test(next)) word += source[++index];
      else word += char;
      continue;
    }
    if (char === "'" || char === '"') { quote = char; continue; }
    if ((char === "\\" && !windowsWord() && next && /[\s'";&|(){}$`]/.test(next)) ||
        (char === "`" && next && /[\s'"]/.test(next))) { word += source[++index]; continue; }
    if (/\s/.test(char)) { if (char === "\n" || char === "\r") flushSegment(); else flushWord(); continue; }
    if (";&|(){}".includes(char)) { flushSegment(); continue; }
    if (char === "<" || char === ">") {
      flushWord();
      if (/^[0-9]+$/.test(words.at(-1) || "")) words.pop();
      words.push(REDIRECTION);
      while (source[index + 1] === char || source[index + 1] === "&") index += 1;
      continue;
    }
    word += char;
  }
  flushSegment();
  return segments;
}

function executableName(value) {
  return String(value || "").replace(/\\/g, "/").split("/").at(-1).toLowerCase().replace(/\.(?:exe|com|cmd|bat)$/i, "");
}

const assignment = /^[A-Za-z_][A-Za-z0-9_]*=/;
const optionTakesValue = new Map([
  ["sudo", new Set(["-C", "-D", "-g", "-h", "-p", "-R", "-r", "-t", "-T", "-u", "-U", "--chdir", "--chroot", "--close-from", "--group", "--host", "--other-user", "--prompt", "--role", "--type", "--user"])],
  ["doas", new Set(["-C", "-u"])],
  ["nice", new Set(["-n", "--adjustment"])],
  ["time", new Set(["-f", "--format", "-o", "--output"])],
  ["env", new Set(["-a", "--argv0", "-C", "--chdir", "-S", "--split-string", "-u", "--unset"])],
  ["xargs", new Set(["-a", "--arg-file", "-d", "--delimiter", "-E", "-e", "--eof", "-I", "-i", "--replace", "-L", "-l", "--max-lines", "-n", "--max-args", "-P", "--max-procs", "-s", "--max-chars"])],
]);
function skipOptions(words, start, executable) {
  const valueOptions = optionTakesValue.get(executable) || new Set();
  let index = start;
  while (index < words.length) {
    const token = words[index];
    if (executable === "env" && assignment.test(token)) { index += 1; continue; }
    if (token === "--") return index + 1;
    if (!token.startsWith("-") || token === "-") return index;
    index += valueOptions.has(token) && !token.includes("=") ? 2 : 1;
  }
  return index;
}
function commandStart(words) {
  let index = 0;
  while (index < words.length) {
    if (assignment.test(words[index])) { index += 1; continue; }
    if (words[index] === REDIRECTION) { index += 2; continue; }
    if (["!", "if", "then", "elif", "else", "while", "until", "do"].includes(words[index].toLowerCase())) { index += 1; continue; }
    break;
  }
  return index;
}
function nestedCommands(words, start = commandStart(words)) {
  const name = executableName(words[start]), nested = [];
  if (["bash", "dash", "ksh", "sh", "zsh"].includes(name)) {
    for (let index = start + 1; index + 1 < words.length; index += 1) {
      if (/^-[A-Za-z]*c[A-Za-z]*$/.test(words[index])) { nested.push(words[index + 1]); break; }
    }
  }
  if (["powershell", "pwsh"].includes(name)) {
    for (let index = start + 1; index < words.length; index += 1) {
      if (/^-(?:command|c)$/i.test(words[index])) { nested.push(words.slice(index + 1).join(" ")); break; }
      const inline = /^-command:(.*)$/i.exec(words[index]);
      if (inline) { nested.push([inline[1], ...words.slice(index + 1)].join(" ")); break; }
    }
  }
  if (name === "cmd") {
    const index = words.findIndex((word, i) => i > start && /^\/(?:c|k)$/i.test(word));
    if (index >= 0) nested.push(words.slice(index + 1).join(" "));
  }
  if (name === "eval") nested.push(words.slice(start + 1).join(" "));
  if (name === "env") {
    for (let index = start + 1; index < words.length; index += 1) {
      if (["-S", "--split-string"].includes(words[index]) && index + 1 < words.length) { nested.push(words[index + 1]); break; }
      const inline = /^--split-string=(.*)$/.exec(words[index]);
      if (inline) { nested.push(inline[1]); break; }
    }
  }
  return nested;
}
function unwrapWords(words) {
  let start = commandStart(words);
  for (let depth = 0; depth < 8; depth += 1) {
    const name = executableName(words[start]);
    if (!["command", "builtin", "exec", "nohup", "env", "sudo", "doas", "nice", "time", "xargs"].includes(name)) break;
    if (name === "env" && words.slice(start + 1).some(word => word === '-S' || word === '--split-string' || word.startsWith('--split-string='))) break;
    const next = skipOptions(words, start + 1, name);
    if (next >= words.length) break;
    start = next;
  }
  return words.slice(start);
}

// Return literal commands inside common wrappers and find -exec expressions.
// Variables, aliases defined by scripts and generated command text are not evaluated.
function expandedSegments(source, depth = 0, budget = { characters: 262144, segments: 4096 }) {
  if (typeof source !== "string") return [];
  if (depth > 8 || source.length > 65536 || (budget.characters -= source.length) < 0) throw new RangeError("Command inspection limit");
  const result = [];
  for (const original of commandSegments(source)) {
    if (--budget.segments < 0) throw new RangeError("Command inspection limit");
    const words = unwrapWords(original);
    result.push(words);
    for (const nested of nestedCommands(words, 0)) result.push(...expandedSegments(nested, depth + 1, budget));
    if (executableName(words[0]) === "find") {
      for (let index = 1; index + 1 < words.length; index += 1) {
        if (["-exec", "-execdir"].includes(words[index])) result.push(words.slice(index + 1));
      }
    }
  }
  for (const pattern of [/\$\(([^()]*)\)/gs, /`([^`]*)`/gs]) {
    for (const match of source.matchAll(pattern)) result.push(...expandedSegments(match[1], depth + 1, budget));
  }
  return result;
}

function gitSubcommand(words, start = 1) {
  const valueOptions = new Set(["-C", "-c", "--exec-path", "--git-dir", "--work-tree", "--namespace", "--config-env", "--super-prefix"]);
  let index = start;
  while (index < words.length) {
    const token = words[index];
    if (token === "--") { index += 1; continue; }
    if (valueOptions.has(token)) { index += 2; continue; }
    if (/^-C.+/.test(token) || /^-c.+/.test(token) || /^--(?:exec-path|git-dir|work-tree|namespace|config-env|super-prefix)=/.test(token)) { index += 1; continue; }
    if (token.startsWith("-")) { index += 1; continue; }
    return { name: token.toLowerCase(), index };
  }
  return null;
}

module.exports = { REDIRECTION, assignment, commandSegments, executableName, skipOptions, commandStart, nestedCommands, unwrapWords, expandedSegments, gitSubcommand };
