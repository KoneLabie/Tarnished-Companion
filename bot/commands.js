'use strict';
function commands() {
  const { SlashCommandBuilder } = require('discord.js');
  return [new SlashCommandBuilder().setName('submit').setDescription('Verify and submit a completed Tarnished Lineup run for review')
    .setDMPermission(false)
    .addAttachmentOption(option => option.setName('report').setDescription('Encrypted .tlrun export, up to 8 MiB').setRequired(true))
    .toJSON()];
}
async function register(config) {
  const { REST, Routes } = require('discord.js');
  const route = config.guildId ? Routes.applicationGuildCommands(config.applicationId, config.guildId) : Routes.applicationCommands(config.applicationId);
  const rest = new REST({ version: '10' }).setToken(config.token);
  // POST creates or updates this name in place; bulk PUT would replace every
  // command in the scope and could delete unrelated commands.
  for (const command of commands()) await rest.post(route, { body: command });
}
module.exports = { commands, register };
