'use strict';
const path = require('node:path'), fs = require('node:fs'), { spawn } = require('node:child_process');
function supported(version) { const major = Number(version.split('.')[0]); return Number.isInteger(major) && major >= 22 && major % 2 === 0; }
function ensureRuntime(entry, options = {}) {
  const proc = options.process || process, launch = options.spawn || spawn, exists = options.exists || fs.existsSync;
  if (supported(proc.versions.node)) return false;
  const executable = path.resolve(__dirname, '..', 'node_modules', 'node', 'bin', proc.platform === 'win32' ? 'node.exe' : 'node');
  if (proc.env.TARNISHED_RUNTIME_CHILD === '1' || !exists(executable)) {
    console.error('A supported Node runtime is missing. Run npm install with install scripts enabled, or select Node 22/24 LTS in the host panel.');
    proc.exitCode = 1; return true;
  }
  console.log('Starting the verifier with its pinned local Node 24 runtime.');
  const child = launch(executable, [entry, ...proc.argv.slice(2)], { stdio: 'inherit', shell: false, windowsHide: true, env: { ...proc.env, TARNISHED_RUNTIME_CHILD: '1' } });
  const onInt = () => child.kill('SIGINT'), onTerm = () => child.kill('SIGTERM');
  proc.on('SIGINT', onInt); proc.on('SIGTERM', onTerm);
  function detach() { proc.removeListener('SIGINT', onInt); proc.removeListener('SIGTERM', onTerm); }
  child.once('error', () => { detach(); console.error('Could not start the local Node runtime. Reinstall dependencies for this host architecture.'); proc.exitCode = 1; });
  child.once('exit', (code, signal) => { detach(); proc.exitCode = Number.isInteger(code) ? code : signal === 'SIGINT' ? 130 : signal === 'SIGTERM' ? 143 : 1; });
  return true;
}
module.exports = { supported, ensureRuntime };
