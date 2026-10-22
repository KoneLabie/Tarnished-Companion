'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), { EventEmitter } = require('node:events');
const { supported, ensureRuntime } = require('../lib/runtime');
function fake(version = '19.9.0') { const p = new EventEmitter(); Object.assign(p, { versions: { node: version }, env: {}, argv: ['/usr/bin/node', '/bot/index.js', '--anything'], platform: 'linux' }); return p; }
test('supported runtime uses the current process and never spawns', () => {
  assert.equal(supported('24.22.1'), true); assert.equal(supported('22.20.0'), true); assert.equal(supported('19.9.0'), false);
  assert.equal(ensureRuntime('/bot/index.js', { process: fake('24.22.1'), spawn: () => assert.fail('spawned') }), false);
});
test('old host starts pinned local runtime without a shell and forwards signals/exit code', () => {
  const p = fake(), child = new EventEmitter(), signals = []; child.kill = signal => signals.push(signal);
  let command;
  assert.equal(ensureRuntime('/bot/index.js', { process: p, exists: () => true, spawn: (...args) => { command = args; return child; } }), true);
  assert.match(command[0], /node_modules[\\/]node[\\/]bin[\\/]node$/); assert.deepEqual(command[1], ['/bot/index.js', '--anything']);
  assert.equal(command[2].shell, false); assert.equal(command[2].env.TARNISHED_RUNTIME_CHILD, '1');
  p.emit('SIGTERM'); assert.deepEqual(signals, ['SIGTERM']); child.emit('exit', 7, null);
  assert.equal(p.exitCode, 7); assert.equal(p.listenerCount('SIGTERM'), 0);
});
test('missing, failed or recursively unsupported runtime fails closed', () => {
  const missing = fake(); ensureRuntime('/bot/index.js', { process: missing, exists: () => false }); assert.equal(missing.exitCode, 1);
  const recursive = fake(); recursive.env.TARNISHED_RUNTIME_CHILD = '1'; ensureRuntime('/bot/index.js', { process: recursive, exists: () => true, spawn: () => assert.fail('loop') }); assert.equal(recursive.exitCode, 1);
  const broken = fake(), child = new EventEmitter(); child.kill = () => {};
  ensureRuntime('/bot/index.js', { process: broken, exists: () => true, spawn: () => child }); child.emit('error', new Error('missing binary'));
  assert.equal(broken.exitCode, 1); assert.equal(broken.listenerCount('SIGINT'), 0);
});
