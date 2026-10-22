'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), { EventEmitter } = require('node:events');
const { attachRegistration } = require('../lib/bot');
const events = { ClientReady: 'ready', GuildCreate: 'guildCreate' }, config = { registerCommandsOnStart: true, guildId: '123456789012345678' };
function setup(register, extra = {}) {
  const client = new EventEmitter(), messages = [];
  const state = attachRegistration(client, events, config, { register, logger: { log: m => messages.push(m), error: m => messages.push(m) }, ...extra });
  return { client, messages, state };
}
test('registration waits for Discord login and remains connected while installation is pending', async () => {
  let calls = 0, fatal = 0;
  const f = setup(async () => { calls++; if (calls === 1) throw Object.assign(new Error('SECRET MUST NOT BE LOGGED'), { code: 50001, status: 403 }); }, { onFatal: async () => fatal++ });
  assert.equal(calls, 0);
  f.client.emit(events.ClientReady); await f.state.whenIdle();
  assert.equal(calls, 1); assert.equal(fatal, 0); assert.match(f.messages.join(' '), /stays connected/); assert.doesNotMatch(f.messages.join(' '), /SECRET/);
  f.client.emit(events.GuildCreate, { id: 'different' }); await f.state.whenIdle(); assert.equal(calls, 1);
  f.client.emit(events.GuildCreate, { id: config.guildId }); await f.state.whenIdle(); assert.equal(calls, 2);
  assert.match(f.messages.join(' '), /command registered/);
  f.client.emit(events.GuildCreate, { id: config.guildId }); await f.state.whenIdle(); assert.equal(calls, 2);
});
test('guild join while initial request is in flight queues exactly one bounded retry', async () => {
  let release, calls = 0;
  const f = setup(async () => { calls++; if (calls === 1) await new Promise(resolve => { release = resolve; }); throw { code: 50013 }; });
  f.client.emit(events.ClientReady);
  f.client.emit(events.GuildCreate, { id: config.guildId }); f.client.emit(events.GuildCreate, { id: config.guildId });
  release(); await f.state.whenIdle(); assert.equal(calls, 2);
  f.client.emit(events.GuildCreate, { id: config.guildId }); await f.state.whenIdle(); assert.equal(calls, 2);
});
test('authentication failure is fatal while transient registration failure is safe and bounded', async () => {
  let fatal = 0;
  const bad = setup(async () => { throw { status: 401, message: 'hidden token' }; }, { onFatal: async () => fatal++ });
  bad.client.emit(events.ClientReady); await bad.state.whenIdle(); assert.equal(fatal, 1); assert.doesNotMatch(bad.messages.join(' '), /hidden token/);
  const transient = setup(async () => { throw { status: 503 }; }, { onFatal: async () => fatal++ });
  transient.client.emit(events.ClientReady); await transient.state.whenIdle(); assert.equal(fatal, 1); assert.match(transient.messages.join(' '), /stays connected/);
});
test('disabled registration and stopped lifecycle never issue command writes', async () => {
  const client = new EventEmitter(); let calls = 0;
  const disabled = attachRegistration(client, events, { ...config, registerCommandsOnStart: false }, { register: async () => calls++ });
  client.emit(events.ClientReady); client.emit(events.GuildCreate, { id: config.guildId }); await disabled.whenIdle(); assert.equal(calls, 0);
  const f = setup(async () => calls++); f.state.stop(); f.client.emit(events.ClientReady); await f.state.whenIdle(); assert.equal(calls, 0);
});
