'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { readJson, ID } = require('./storage');
const { PackageError, validateRecipient } = require('./package');
function configuration({ discord = false } = {}) {
  const configPath = path.resolve(process.env.TARNISHED_BOT_CONFIG || path.join(__dirname, '..', 'config.json'));
  if (process.platform !== 'win32' && fs.existsSync(configPath)) fs.chmodSync(configPath, 0o600);
  const file = readJson(configPath, 65536, {}), base = path.dirname(configPath);
  const resolvePath = value => typeof value === 'string' && value ? path.resolve(base, value) : null;
  const c = {
    token: process.env.DISCORD_TOKEN || file.token,
    applicationId: process.env.DISCORD_APPLICATION_ID || file.applicationId,
    guildId: process.env.DISCORD_GUILD_ID || file.guildId,
    recipientKeyFile: resolvePath(process.env.TARNISHED_RECIPIENT_KEY_FILE || file.recipientKeyFile),
    dataDir: resolvePath(process.env.TARNISHED_BOT_DATA_DIR || file.dataDir),
    registerCommandsOnStart: file.registerCommandsOnStart === true,
  };
  if (!c.dataDir) throw new PackageError('CONFIG', 'Set TARNISHED_BOT_DATA_DIR or config.json dataDir to persistent private storage.');
  if (discord && (!c.token || typeof c.token !== 'string' || !ID.test(c.applicationId) || (c.guildId && !ID.test(c.guildId)))) throw new PackageError('CONFIG', 'Configure Discord token, application ID, and optional guild ID.');
  return c;
}
function recipientFromFile(file) {
  if (!file) throw new PackageError('CONFIG', 'Configure the private recipient key file.');
  if (process.platform !== 'win32') fs.chmodSync(file, 0o600);
  if (process.platform !== 'win32' && (fs.statSync(file).mode & 0o077)) throw new PackageError('CONFIG', 'Private recipient key file is accessible to other users. Run chmod 600 on it.');
  return validateRecipient(readJson(file, 4096));
}
module.exports = { configuration, recipientFromFile };
