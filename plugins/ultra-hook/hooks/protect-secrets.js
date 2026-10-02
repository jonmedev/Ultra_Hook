#!/usr/bin/env node
/**
 * Protect Secrets - CAS Codex adaptation for literal file paths and commands
 * Denies recognized access to sensitive files using Codex's supported contract.
 * Based on karanb192/claude-code-hooks; native permissions remain authoritative.
 *
 * SAFETY_LEVEL: 'critical' | 'high' | 'strict'
 *   critical - SSH keys, AWS creds, .env files only
 *   high     - + secrets files, env dumps, exfiltration attempts
 *   strict   - + database configs, any config that might contain secrets
 *
 * Installed through this plugin's hook configuration. Supported inputs include
 * Read/Edit/Write file_path, Bash command, exec_command cmd and apply_patch
 * command headers. This literal recognizer does not interpret arbitrary shell
 * scripts and is not a security boundary.
 */

const { readEvent, deny } = require('./hook-io.cjs');
const { expandedSegments, executableName, nestedCommands, gitSubcommand, REDIRECTION } = require('./safety-command-parser.cjs');

const SAFETY_LEVEL = 'high';

// Files explicitly safe to access (templates, examples)
const ALLOWLIST = [
  /(?:^|\/)\.env\.example$/i, /(?:^|\/)\.env\.sample$/i, /(?:^|\/)\.env\.template$/i,
  /(?:^|\/)\.env\.schema$/i, /(?:^|\/)\.env\.defaults$/i, /(?:^|\/)env\.example$/i, /(?:^|\/)example\.env$/i,
];

// Sensitive file patterns for Read, Edit, Write tools
const SENSITIVE_FILES = [
  { level: 'critical', id: 'auth-json', regex: /(?:^|\/)auth\.json$/, reason: 'Authentication state contains credentials' },
  { level: 'critical', id: 'git-credentials', regex: /(?:^|\/)\.git-credentials$/, reason: 'Git credential store' },
  { level: 'critical', id: 'gh-auth', regex: /(?:^|\/)(?:gh|github-cli)\/hosts\.ya?ml$/, reason: 'GitHub CLI credential store' },
  { level: 'critical', id: 'gcloud-adc', regex: /(?:^|\/)application_default_credentials\.json$/, reason: 'Cloud application credentials' },
  // CRITICAL
  { level: 'critical', id: 'env-file',           regex: /(?:^|\/)\.env(?:\.[^/]*)?$/,                    reason: '.env file contains secrets' },
  { level: 'critical', id: 'envrc',              regex: /(?:^|\/)\.envrc$/,                              reason: '.envrc (direnv) contains secrets' },
  { level: 'critical', id: 'ssh-private-key',    regex: /(?:^|\/)\.ssh\/id_[^/]+$/,                      reason: 'SSH private key' },
  { level: 'critical', id: 'ssh-private-key-2',  regex: /(?:^|\/)(id_rsa|id_ed25519|id_ecdsa|id_dsa)$/,  reason: 'SSH private key' },
  { level: 'critical', id: 'ssh-authorized',     regex: /(?:^|\/)\.ssh\/authorized_keys$/,               reason: 'SSH authorized_keys' },
  { level: 'critical', id: 'aws-credentials',    regex: /(?:^|\/)\.aws\/credentials$/,                   reason: 'AWS credentials file' },
  { level: 'critical', id: 'aws-config',         regex: /(?:^|\/)\.aws\/config$/,                        reason: 'AWS config may contain secrets' },
  { level: 'critical', id: 'kube-config',        regex: /(?:^|\/)\.kube\/config$/,                       reason: 'Kubernetes config contains credentials' },
  { level: 'critical', id: 'pem-key',            regex: /\.pem$/i,                                       reason: 'PEM key file' },
  { level: 'critical', id: 'key-file',           regex: /\.key$/i,                                       reason: 'Key file' },
  { level: 'critical', id: 'p12-key',            regex: /\.(p12|pfx)$/i,                                 reason: 'PKCS12 key file' },

  // HIGH
  { level: 'high', id: 'credentials-json',       regex: /(?:^|\/)credentials\.json$/i,                   reason: 'Credentials file' },
  { level: 'high', id: 'secrets-file',           regex: /(?:^|\/)(secrets?|credentials?)\.(json|ya?ml|toml)$/i, reason: 'Secrets configuration file' },
  { level: 'high', id: 'service-account',        regex: /service[_-]?account.*\.json$/i,                 reason: 'GCP service account key' },
  { level: 'high', id: 'gcloud-creds',           regex: /(?:^|\/)\.config\/gcloud\/.*(credentials|tokens)/i, reason: 'GCloud credentials' },
  { level: 'high', id: 'azure-creds',            regex: /(?:^|\/)\.azure\/(credentials|accessTokens)/i,  reason: 'Azure credentials' },
  { level: 'high', id: 'docker-config',          regex: /(?:^|\/)\.docker\/config\.json$/,               reason: 'Docker config may contain registry auth' },
  { level: 'high', id: 'netrc',                  regex: /(?:^|\/)\.netrc$/,                              reason: '.netrc contains credentials' },
  { level: 'high', id: 'npmrc',                  regex: /(?:^|\/)\.npmrc$/,                              reason: '.npmrc may contain auth tokens' },
  { level: 'high', id: 'pypirc',                 regex: /(?:^|\/)\.pypirc$/,                             reason: '.pypirc contains PyPI credentials' },
  { level: 'high', id: 'gem-creds',              regex: /(?:^|\/)\.gem\/credentials$/,                   reason: 'RubyGems credentials' },
  { level: 'high', id: 'vault-token',            regex: /(?:^|\/)(\.vault-token|vault-token)$/,          reason: 'Vault token file' },
  { level: 'high', id: 'keystore',               regex: /\.(keystore|jks)$/i,                            reason: 'Java keystore' },
  { level: 'high', id: 'htpasswd',               regex: /(?:^|\/)\.?htpasswd$/,                          reason: 'htpasswd contains hashed passwords' },
  { level: 'high', id: 'pgpass',                 regex: /(?:^|\/)\.pgpass$/,                             reason: 'PostgreSQL password file' },
  { level: 'high', id: 'my-cnf',                 regex: /(?:^|\/)\.my\.cnf$/,                            reason: 'MySQL config may contain password' },

  // STRICT
  { level: 'strict', id: 'database-config',      regex: /(?:^|\/)(?:config\/)?database\.(json|ya?ml)$/i, reason: 'Database config may contain passwords' },
  { level: 'strict', id: 'ssh-known-hosts',      regex: /(?:^|\/)\.ssh\/known_hosts$/,                   reason: 'SSH known_hosts reveals infrastructure' },
  { level: 'strict', id: 'gitconfig',            regex: /(?:^|\/)\.gitconfig$/,                          reason: '.gitconfig may contain credentials' },
  { level: 'strict', id: 'curlrc',               regex: /(?:^|\/)\.curlrc$/,                             reason: '.curlrc may contain auth' },
];

// Bash patterns that expose or exfiltrate secrets
const BASH_PATTERNS = [
  // CRITICAL
  { level: 'critical', id: 'cat-env',            regex: /\b(cat|less|head|tail|more|bat|view)\s+[^|;]*\.env\b/i,           reason: 'Reading .env file exposes secrets' },
  { level: 'critical', id: 'cat-ssh-key',        regex: /\b(cat|less|head|tail|more|bat)\s+[^|;]*(id_rsa|id_ed25519|id_ecdsa|id_dsa|\.pem|\.key)\b/i, reason: 'Reading private key' },
  { level: 'critical', id: 'cat-aws-creds',      regex: /\b(cat|less|head|tail|more)\s+[^|;]*\.aws\/credentials/i,         reason: 'Reading AWS credentials' },

  // HIGH - Environment exposure
  { level: 'high', id: 'env-dump',               regex: /\bprintenv\b|(?:^|[;&|]\s*)env\s*(?:$|[;&|])/,                    reason: 'Environment dump may expose secrets' },
  { level: 'high', id: 'echo-secret-var',        regex: /\becho\b[^;|&]*\$\{?[A-Za-z_]*(?:SECRET|KEY|TOKEN|PASSWORD|PASSW|CREDENTIAL|API_KEY|AUTH|PRIVATE)[A-Za-z_]*\}?/i, reason: 'Echoing secret variable' },
  { level: 'high', id: 'printf-secret-var',      regex: /\bprintf\b[^;|&]*\$\{?[A-Za-z_]*(?:SECRET|KEY|TOKEN|PASSWORD|CREDENTIAL|API_KEY|AUTH|PRIVATE)[A-Za-z_]*\}?/i, reason: 'Printing secret variable' },
  { level: 'high', id: 'cat-secrets-file',       regex: /\b(cat|less|head|tail|more)\s+[^|;]*(credentials?|secrets?)\.(json|ya?ml|toml)/i, reason: 'Reading secrets file' },
  { level: 'high', id: 'cat-netrc',              regex: /\b(cat|less|head|tail|more)\s+[^|;]*\.netrc/i,                    reason: 'Reading .netrc credentials' },
  { level: 'high', id: 'source-env',             regex: /\bsource\s+[^|;]*\.env\b|(?:^|[;&|]\s*)\.\s+[^|;]*\.env\b|^\.\s+[^|;]*\.env\b/i, reason: 'Sourcing .env loads secrets' },
  { level: 'high', id: 'export-cat-env',         regex: /export\s+.*\$\(cat\s+[^)]*\.env/i,                                reason: 'Exporting secrets from .env' },

  // HIGH - Exfiltration
  { level: 'high', id: 'curl-upload-env',        regex: /\bcurl\b[^;|&]*(-d\s*@|-F\s*[^=]+=@|--data[^=]*=@)[^;|&]*(\.env|credentials|secrets|id_rsa|\.pem|\.key)/i, reason: 'Uploading secrets via curl' },
  { level: 'high', id: 'curl-post-secrets',      regex: /\bcurl\b[^;|&]*-X\s*POST[^;|&]*(\.env|credentials|secrets)/i, reason: 'POSTing secrets via curl' },
  { level: 'high', id: 'wget-post-secrets',      regex: /\bwget\b[^;|&]*--post-file[^;|&]*(\.env|credentials|secrets)/i,  reason: 'POSTing secrets via wget' },
  { level: 'high', id: 'scp-secrets',            regex: /\bscp\b[^;|&]*(\.env|credentials|secrets|id_rsa|\.pem|\.key)[^;|&]+:/i, reason: 'Copying secrets via scp' },
  { level: 'high', id: 'rsync-secrets',          regex: /\brsync\b[^;|&]*(\.env|credentials|secrets|id_rsa)[^;|&]+:/i,    reason: 'Syncing secrets via rsync' },
  { level: 'high', id: 'nc-secrets',             regex: /\bnc\b[^;|&]*<[^;|&]*(\.env|credentials|secrets|id_rsa)/i,       reason: 'Exfiltrating secrets via netcat' },

  // HIGH - Copy/move/stage secrets. Deletion is handled once by the dedicated
  // rm approval hook so a sensitive rm command cannot generate two prompts.
  { level: 'high', id: 'cp-env',                 regex: /\bcp\b[^;|&]*\.env\b/i,                                           reason: 'Copying .env file' },
  { level: 'high', id: 'cp-ssh-key',             regex: /\bcp\b[^;|&]*(id_rsa|id_ed25519|\.pem|\.key)\b/i,                 reason: 'Copying private key' },
  { level: 'high', id: 'mv-env',                 regex: /\bmv\b[^;|&]*\.env\b/i,                                           reason: 'Moving .env file' },
  { level: 'high', id: 'git-add-env',            regex: /\bgit\b[^;|&]*\badd\b[^;|&]*\.env\b/i,                         reason: 'Staging .env data in Git' },
  { level: 'high', id: 'git-add-private-key',    regex: /\bgit\b[^;|&]*\badd\b[^;|&]*(id_rsa|id_ed25519|id_ecdsa|\.pem|\.key)\b/i, reason: 'Staging a private key in Git' },
  { level: 'high', id: 'git-add-secrets',        regex: /\bgit\b[^;|&]*\badd\b[^;|&]*(credentials?|secrets?)\.(json|ya?ml|toml)/i, reason: 'Staging a secrets file in Git' },
  { level: 'high', id: 'truncate-secrets',       regex: /\btruncate\b.*\.(env|pem|key)\b|(?:^|[;&|]\s*)>\s*\.env\b/i,      reason: 'Truncating secrets file' },

  // HIGH - Process environ
  { level: 'high', id: 'proc-environ',           regex: /\/proc\/[^/]*\/environ/,                                          reason: 'Reading process environment' },

  // STRICT
  { level: 'strict', id: 'grep-password',        regex: /\bgrep\b[^|;]*(-r|--recursive)[^|;]*(password|secret|api.?key|token|credential)/i, reason: 'Grep for secrets may expose them' },
  { level: 'strict', id: 'base64-secrets',       regex: /\bbase64\b[^|;]*(\.env|credentials|secrets|id_rsa|\.pem)/i,       reason: 'Base64 encoding secrets' },
];

const LEVELS = { critical: 1, high: 2, strict: 3 };
const EMOJIS = { critical: '!!!', high: '!!', strict: '!' };
function normalizeFilePath(filePath) {
  if (typeof filePath !== 'string') return '';
  return filePath.trim().replace(/^(['"])(.*)\1$/, '$2')
    .replace(/^Microsoft\.PowerShell\.Core\\FileSystem::/i, '')
    .replace(/^FileSystem::/i, '').replace(/\\/g, '/').toLowerCase()
    .split('/').map(part => /^[a-z]:$/.test(part) ? part : part.split(':')[0].replace(/[. ]+$/, '')).join('/');
}

function isAllowlisted(filePath) {
  const normalized = normalizeFilePath(filePath);
  return Boolean(normalized && ALLOWLIST.some(p => p.test(normalized)));
}

function checkFilePath(filePath, safetyLevel = SAFETY_LEVEL) {
  filePath = normalizeFilePath(filePath);
  if (!filePath || isAllowlisted(filePath)) return { blocked: false, pattern: null };
  const threshold = LEVELS[safetyLevel] || 2;
  for (const p of SENSITIVE_FILES) {
    if (LEVELS[p.level] <= threshold && p.regex.test(filePath)) {
      return { blocked: true, pattern: p };
    }
  }
  return { blocked: false, pattern: null };
}

function checkEnvProvider(words, threshold) {
  if (threshold < LEVELS.high) return null;
  const readers = new Set(['get-childitem', 'gci', 'dir', 'ls', 'get-item', 'gi', 'get-content', 'gc', 'cat', 'type']);
  if (!readers.has(executableName(words[0]))) return null;
  for (const token of words.slice(1)) {
    for (const candidate of token.split(',')) {
      const provider = /^env:[\\/]*([^\\/]*)[\\/]*$/i.exec(candidate.replace(/^-(?:literalpath|path):/i, ''));
      if (!provider) continue;
      const name = provider[1];
      // An empty provider path or a wildcard selector may enumerate secrets.
      // Inspect only the literal name; never resolve environment variable values.
      if (!name || /[*?\[\]]/.test(name)) return BASH_PATTERNS.find(pattern => pattern.id === 'env-dump');
      if (/(?:SECRET|KEY|TOKEN|PASSWORD|PASSW|CREDENTIAL|AUTH|PRIVATE)/i.test(name)) {
        return { level: 'high', id: 'env-secret-variable', reason: 'Reading a sensitive environment variable' };
      }
    }
  }
  return null;
}

function searchFileOperands(words, executable) {
  const args = words.slice(1);
  if (!['rg', 'grep', 'select-string', 'sls'].includes(executable)) return args;
  const powershell = ['select-string', 'sls'].includes(executable);
  const paths = [];
  let explicitPattern = args.some(word => powershell ? /^-pattern(?::|$)/i.test(word) :
    /^(?:-e|-f|--regexp(?:=|$)|--file(?:=|$))/.test(word));
  let positionalPattern = explicitPattern || args.includes('--files');
  const nonFileOptions = new Set(['--max-count', '--max-depth', '--max-columns', '--encoding', '--color', '--colors',
    '--context', '--before-context', '--after-context', '-m', '-A', '-B', '-C', '-j', '--threads', '-g', '--glob',
    '--iglob', '-t', '--type', '-T', '--type-not', '-Pattern', '-pattern', '-Encoding', '-encoding', '-Context', '-context']);
  for (let index = 0; index < args.length; index++) {
    const word = args[index];
    if ((powershell && /^-pattern$/i.test(word)) || (!powershell && ['-e', '--regexp'].includes(word))) { index++; continue; }
    if ((powershell && /^-pattern:/i.test(word)) || (!powershell && /^(?:-e.+|--regexp=)/.test(word))) continue;
    if (!powershell && ['-f', '--file'].includes(word)) { if (index + 1 < args.length) paths.push(args[++index]); continue; }
    if (!powershell && /^-f.+/.test(word)) { paths.push(word.slice(2)); continue; }
    if (nonFileOptions.has(word)) { index++; continue; }
    if (word.startsWith('-')) { paths.push(word); continue; }
    // PowerShell named -Pattern was handled above; positional syntax stays
    // conservative because aliases and parameter binding are not interpreted.
    if (!powershell && !positionalPattern) { positionalPattern = true; continue; }
    paths.push(word);
  }
  return paths;
}

function checkBashCommand(cmd, safetyLevel = SAFETY_LEVEL) {
  if (typeof cmd !== 'string' || !cmd) return { blocked: false, pattern: null };
  const threshold = LEVELS[safetyLevel] || 2;
  const segments = expandedSegments(cmd);
  // These legacy regexes matched file suffixes in arbitrary argument text.
  // File operations now inspect individual paths, including template exceptions.
  const pathPatternIds = new Set(['cat-env', 'cat-ssh-key', 'cat-aws-creds', 'cat-secrets-file', 'cat-netrc',
    'source-env', 'export-cat-env', 'cp-env', 'cp-ssh-key', 'mv-env', 'git-add-env', 'git-add-private-key', 'git-add-secrets', 'truncate-secrets', 'base64-secrets']);
  const readers = new Set(['cat', 'less', 'head', 'tail', 'more', 'bat', 'view', 'get-content', 'gc', 'type', 'source', '.',
    'rg', 'grep', 'sed', 'awk', 'select-string', 'sls', 'base64', 'certutil', 'zip', 'tar']);
  const fileOperations = new Set(['cp', 'mv', 'copy', 'copy-item', 'cpi', 'move', 'move-item', 'mi', 'truncate', 'set-content', 'sc', 'add-content', 'ac', 'out-file']);
  for (const words of segments) {
    const executable = executableName(words[0]);
    const environmentPattern = checkEnvProvider(words, threshold);
    if (environmentPattern) return { blocked: true, pattern: environmentPattern };
    if (executable === 'env' && !nestedCommands(words, 0).length && threshold >= LEVELS.high) {
      return { blocked: true, pattern: BASH_PATTERNS.find(pattern => pattern.id === 'env-dump') };
    }
    const gitCommand = executable === 'git' ? gitSubcommand(words) : null;
    const readsPaths = readers.has(executable) || fileOperations.has(executable) ||
      gitCommand?.name === 'add' ||
      ['curl', 'wget', 'scp', 'rsync'].includes(executable);
    if (readsPaths) {
      const operands = gitCommand ? words.slice(gitCommand.index + 1) : searchFileOperands(words, executable);
      for (const token of operands) {
        for (let candidate of token.split(',')) {
          candidate = candidate.replace(/^-(?:literalpath|path):/i, '').replace(/^--[a-z-]+=/i, '').replace(/^@/, '');
          const result = checkFilePath(candidate, safetyLevel);
          if (result.blocked) return result;
        }
      }
    }
    // An explicit sensitive selector combined with xargs/find readers needs
    // checking even though the reader's actual path is supplied at runtime.
    if ((executable === 'find' || (['printf', 'echo', 'get-childitem', 'gci'].includes(executable) && /\bxargs\b/i.test(cmd))) &&
        segments.some(segment => readers.has(executableName(segment[0])))) {
      for (const token of words.slice(1)) {
        const result = checkFilePath(token, safetyLevel);
        if (result.blocked) return result;
      }
    }
    for (let index = 0; index + 1 < words.length; index += 1) {
      if (words[index] === REDIRECTION) {
        const result = checkFilePath(words[index + 1], safetyLevel);
        if (result.blocked) return result;
      }
    }
    // Mask only individual known template paths. Never exempt a whole command
    // because its last token happens to name a safe example file.
    const sanitized = words.map(word => isAllowlisted(word.replace(/^--[a-z-]+=/i, '').replace(/^@/, '')) ? 'SAFE_TEMPLATE' : word).join(' ');
    for (const p of BASH_PATTERNS) {
      if (!pathPatternIds.has(p.id) && LEVELS[p.level] <= threshold && p.regex.test(sanitized)) {
        return { blocked: true, pattern: p };
      }
    }
  }
  return { blocked: false, pattern: null };
}

function patchPaths(patch) {
  if (typeof patch !== 'string') return [];
  // Inspect only protocol headers; do not inspect added/deleted file contents.
  return patch.split(/\r?\n/).flatMap(line => {
    const header = /^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$/.exec(line);
    return header ? [header[1]] : [];
  });
}

function check(toolName, toolInput, safetyLevel = SAFETY_LEVEL) {
  toolName = String(toolName || '').split('.').at(-1);
  if (['Read', 'Edit', 'Write'].includes(toolName)) {
    return checkFilePath(toolInput?.file_path, safetyLevel);
  }
  if (['Bash', 'exec_command'].includes(toolName)) {
    return checkBashCommand(toolInput?.command ?? toolInput?.cmd, safetyLevel);
  }
  if (toolName === 'apply_patch') {
    for (const filePath of patchPaths(typeof toolInput === 'string' ? toolInput : toolInput?.command ?? toolInput?.patch)) {
      const result = checkFilePath(filePath, safetyLevel);
      if (result.blocked) return result;
    }
  }
  return { blocked: false, pattern: null };
}

async function main() {
  try {
    const data = await readEvent();
    const { tool_name, tool_input } = data;
    if (data.hook_event_name !== 'PreToolUse') return console.log('{}');
    const tool = String(tool_name || '').split('.').at(-1);
    if (!['Read', 'Edit', 'Write', 'Bash', 'exec_command', 'apply_patch'].includes(tool)) {
      return console.log('{}');
    }

    const value = ['Read', 'Edit', 'Write'].includes(tool) ? tool_input?.file_path :
      typeof tool_input === 'string' ? tool_input : tool_input?.command ?? tool_input?.cmd ?? tool_input?.patch;
    if (typeof value !== 'string' || !value.trim()) return deny();
    const result = check(tool_name, tool_input);

    if (result.blocked) {
      const p = result.pattern;
      const action = { Read: 'read', Edit: 'modify', Write: 'write to', Bash: 'execute', exec_command: 'execute', apply_patch: 'modify' }[tool];
      return deny(`${EMOJIS[p.level]} [${p.id}] Cannot ${action}: ${p.reason}. Use a redacted fixture; do not bypass this denial through another tool.`);
    }
    console.log('{}');
  } catch {
    deny();
  }
}

if (require.main === module) {
  main();
} else {
  module.exports = {
    SENSITIVE_FILES, BASH_PATTERNS, ALLOWLIST, LEVELS, SAFETY_LEVEL,
    check, checkFilePath, checkBashCommand, isAllowlisted, normalizeFilePath, patchPaths, checkEnvProvider, searchFileOperands,
  };
}
