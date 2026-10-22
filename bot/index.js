'use strict';
// Hosting panels may invoke an old system Node. Load Discord only after the
// pinned, supported local runtime has taken over.
const { ensureRuntime } = require('./lib/runtime');
async function main() { return require('./lib/bot').main(); }
if (require.main === module && !ensureRuntime(__filename)) main().catch(error => {
  console.error(`Bot startup failed (${error.code || error.name || 'error'}): ${['CONFIG', 'KEY', 'FORMAT', 'LOCKED'].includes(error.code) ? error.message : 'Check dependencies, credentials, network access, and private storage.'}`);
  process.exitCode = 1;
});
module.exports = { main };
