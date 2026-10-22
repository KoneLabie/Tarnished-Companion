#!/usr/bin/env node
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { configuration, recipientFromFile } = require('./lib/config');
const { generateRecipient, decryptPackage, fingerprint, MAX_PACKAGE } = require('./lib/package');
const { enroll } = require('./lib/storage');
const { normalizeReport, renderText } = require('./lib/report');
function args(argv) {
  const result = { positional: [] };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith('--')) {
      const name = argv[i].slice(2);
      if (Object.hasOwn(result, name) || !argv[i + 1] || argv[i + 1].startsWith('--')) throw new Error(`Missing or repeated --${name}.`);
      result[name] = argv[++i];
    } else result.positional.push(argv[i]);
  }
  return result;
}
function required(options, name) { if (!options[name]) throw new Error(`Supply --${name}.`); return options[name]; }
function writeExclusive(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const fd = fs.openSync(file, 'wx', 0o600);
  try { fs.writeFileSync(fd, JSON.stringify(data, null, 2) + '\n'); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
}
async function main(argv = process.argv.slice(2)) {
  const command = argv.shift(), options = args(argv);
  if (command === 'init-recipient') {
    const privatePath = path.resolve(required(options, 'out')), publicPath = path.resolve(required(options, 'public-out'));
    if (privatePath === publicPath || fs.existsSync(privatePath) || fs.existsSync(publicPath)) throw new Error('Use two distinct, new output files. Existing files are never overwritten.');
    const key = generateRecipient(), { privateKey: secret, ...publicConfig } = key;
    writeExclusive(privatePath, key);
    writeExclusive(publicPath, publicConfig);
    console.log('Recipient key files created. Keep the private file with the bot; distribute only the public file.');
    console.log(`Recipient fingerprint: ${key.fingerprint}`);
    return 0;
  }
  if (command === 'enroll') {
    const config = configuration();
    enroll(config.dataDir, required(options, 'fingerprint'), required(options, 'user-id'));
    console.log('Independent signer fingerprint enrolled to the specified Discord account.'); return 0;
  }
  if (command === 'verify') {
    if (options.positional.length !== 1) throw new Error('Supply exactly one .tlrun path.');
    const config = configuration(), raw = recipientFromFile(options.key || config.recipientKeyFile);
    const file = path.resolve(options.positional[0]);
    if (fs.statSync(file).size > MAX_PACKAGE) throw new Error('Package exceeds 8 MiB.');
    // Read at most the cap plus one byte; crypto checks the actual byte length.
    const fd = fs.openSync(file, 'r'); let data;
    try { const buffer = Buffer.alloc(MAX_PACKAGE + 1); const n = fs.readSync(fd, buffer, 0, buffer.length, 0); data = buffer.subarray(0, n); } finally { fs.closeSync(fd); }
    let opened;
    try { opened = decryptPackage(data, raw, options['trusted-fingerprint'] ? fingerprint(options['trusted-fingerprint']) : undefined); } finally { raw.fill(0); }
    const report = normalizeReport(opened);
    console.log(opened.trusted ? 'SIGNATURE VALID; INDEPENDENT SIGNER PIN MATCHED.' : 'SIGNATURE VALID; SIGNER UNTRUSTED (no independently trusted fingerprint provided).');
    console.log(renderText(report));
    console.log('Offline verification does not enroll a signer or record a Discord submission.');
    return opened.trusted ? 0 : 2;
  }
  if (command === 'register') {
    await require('./commands').register(configuration({ discord: true }));
    console.log('The /submit command was registered for the configured application scope.'); return 0;
  }
  console.log('Usage:\n  node cli.js init-recipient --out PRIVATE.json --public-out PUBLIC.json\n  node cli.js enroll --fingerprint SHA256 --user-id DISCORD_ID\n  node cli.js verify REPORT.tlrun [--key PRIVATE.json] [--trusted-fingerprint SHA256]\n  node cli.js register');
  return command ? 1 : 0;
}
if (require.main === module && !require('./lib/runtime').ensureRuntime(__filename)) main().then(code => { process.exitCode = code; }).catch(error => { console.error(`${error.code || 'ERROR'}: ${error.message}`); process.exitCode = 1; });
module.exports = { main };
