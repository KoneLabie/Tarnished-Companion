'use strict';
const { configuration, recipientFromFile } = require('./config');
const { acquireLock, ReceiptStore } = require('./storage');
const { PackageError } = require('./package');
const { FormatError } = require('./strict-json');
const { downloadAttachment, submit } = require('./submission');
const { renderText, summary } = require('./report');
const { ReportMenus } = require('./presentation');
const { PublishedRecords, CATEGORIES } = require('./published-records');
const { peerComparison } = require('./peer-comparison');
const { readTrust } = require('./storage');

function attachRegistration(client, events, config, { register = require('../commands').register, logger = console, onFatal = async () => {} } = {}) {
  let ready = false, registered = false, pending = null, guildRetryUsed = false, retryQueued = false, stopped = false;
  function attempt() {
    if (!config.registerCommandsOnStart || registered || stopped) return Promise.resolve();
    if (pending) return pending;
    pending = (async () => {
      try {
        await register(config);
        if (stopped) return;
        registered = true;
        logger.log('Tarnished Companion /submit command registered for the configured Discord scope.');
      } catch (error) {
        if (stopped) return;
        const code = Number(error.code), status = Number(error.status);
        if (status === 401 || error.code === 'TokenInvalid' || code === 50014) {
          stopped = true;
          logger.error('Discord authentication failed during command registration. Check the private bot token; the verifier is stopping.');
          await onFatal();
        } else if (code === 50001 || code === 50013 || status === 403) {
          logger.error('Discord installation pending: /submit is not registered because this application cannot access the configured server. Authorize the bot with bot and applications.commands scopes and confirm its server permissions. The bot stays connected and retries when it joins that server; restart it after changing permissions on an existing installation.');
        } else {
          logger.error('Discord command registration did not complete. The bot stays connected; it will retry when it joins the configured server. Restart after checking Discord availability and the configured application/server IDs.');
        }
      } finally { pending = null; }
      if (retryQueued && !registered && !stopped) { retryQueued = false; await attempt(); }
    })();
    return pending;
  }
  client.once(events.ClientReady, () => { ready = true; void attempt(); });
  client.on(events.GuildCreate, guild => {
    if (!ready || !config.guildId || guild.id !== config.guildId || guildRetryUsed || registered || stopped) return;
    guildRetryUsed = true;
    if (pending) retryQueued = true;
    else void attempt();
  });
  return { whenIdle: async () => { while (pending) await pending; }, stop: () => { stopped = true; retryQueued = false; } };
}

async function main({ refreshComparison = null } = {}) {
  const { Client, Events, GatewayIntentBits, MessageFlags } = require('discord.js');
  const config = configuration({ discord: true }), recipient = recipientFromFile(config.recipientKeyFile);
  const unlock = acquireLock(config.dataDir), store = new ReceiptStore(config.dataDir);
  const records = new PublishedRecords(config.dataDir);
  if (!refreshComparison) refreshComparison = async (report, { force = false } = {}) => {
    await records.refresh(report.category.id, { force });
    let owner;
    try { owner = readTrust(config.dataDir).signers[report.verification.signingFingerprint]?.discordUserId; } catch {}
    const peers = owner ? await peerComparison(config.dataDir, report, owner)
      : { status: 'unavailable', sampleCount: 0, bosses: [], notice: 'The enrolled submitter could not be matched for community comparisons.' };
    return { published: records.snapshot(report.category.id), peers };
  };
  const client = new Client({ intents: [GatewayIntentBits.Guilds], allowedMentions: { parse: [] } });
  const menus = new ReportMenus({ refreshComparison });
  let active = 0, stopping = false;
  let recordTimer = null, recordUpdate = null;
  const recordStatus = new Map();
  function refreshRecords() {
    if (stopping || recordUpdate) return recordUpdate;
    recordUpdate = (async () => {
      for (const category of Object.keys(CATEGORIES)) {
        if (stopping) break;
        await records.refresh(category);
        const snapshot = records.snapshot(category);
        const stamp = `${snapshot.status}:${snapshot.checkedAt || ''}`;
        if (recordStatus.get(category) !== stamp) {
          recordStatus.set(category, stamp);
          console.log(`Published records: ${snapshot.categoryName} — ${snapshot.status}, ${snapshot.sampleCount} results.`);
        }
      }
      if (!stopping) await menus.refreshPublishedSnapshots(report => records.snapshot(report.category.id));
    })().catch(() => console.error('Published record refresh is unavailable; report verification remains online.'))
      .finally(() => { recordUpdate = null; });
    return recordUpdate;
  }
  const users = new Set(), recent = new Map(), operations = new Set();
  async function handle(interaction) {
    if (await menus.handle(interaction)) return;
    if (!interaction.isChatInputCommand() || interaction.commandName !== 'submit') return;
    if (config.guildId && interaction.guildId !== config.guildId) {
      await interaction.reply({ content: 'This verifier is configured for a different server.', flags: MessageFlags.Ephemeral }); return;
    }
    const userId = interaction.user.id, now = Date.now();
    for (const [id, at] of recent) if (now - at > 60000) recent.delete(id);
    if (stopping || active >= 2 || users.has(userId) || now - (recent.get(userId) || 0) < 15000) {
      await interaction.reply({ content: 'The verifier is busy or you submitted recently. Please try again shortly.', flags: MessageFlags.Ephemeral }); return;
    }
    active++; users.add(userId); recent.set(userId, now);
    let committed = false;
    try {
      await interaction.deferReply({ flags: MessageFlags.Ephemeral });
      const bytes = await downloadAttachment(interaction.options.getAttachment('report', true));
      const result = await submit(bytes, userId, recipient, store); committed = true;
      if (refreshComparison) {
        try { result.report.comparison = await refreshComparison(result.report); }
        catch { result.report.comparison = { published: { status: 'unavailable', notice: 'Published records could not be retrieved. The submitted report remains saved.' } }; }
      }
      const json = Buffer.from(JSON.stringify(result.report, null, 2) + '\n'), txt = Buffer.from(renderText(result.report));
      // Discord limits apply to attachments separately. If a very large
      // normalized timeline expands beyond that cap, the durable full report
      // remains in private bot storage and the user receives a bounded receipt.
      const files = [];
      if (txt.length <= 8 * 1024 * 1024) files.push({ attachment: txt, name: 'verified-run.txt' });
      if (json.length <= 8 * 1024 * 1024) files.push({ attachment: json, name: 'verified-run.json' });
      const menu = menus.create(result.report, userId, interaction.guildId);
      const receiptNote = files.length < 2 ? 'A full attachment exceeded the display limit; the administrator can retrieve it from private report storage.' : null;
      const message = await interaction.editReply({ ...(menu ? menu.message : { content: summary(result.report), allowedMentions: { parse: [] } }),
        ...(receiptNote ? { content: receiptNote } : {}), files });
      if (menu) menus.bind(menu.token, message.id, { edit: payload => interaction.editReply(payload) });
    } catch (error) {
      const publicMessage = committed ? 'Your report was saved, but Discord could not deliver its receipt. Ask the administrator to retrieve it; do not submit it again.' : error instanceof PackageError || error instanceof FormatError ? error.message : 'The verifier could not complete this request. No result should be assumed; ask the administrator to check storage and service health.';
      if (!(error instanceof PackageError) && !(error instanceof FormatError)) console.error(`Submission failure (${error.code || error.name || 'unknown'}); inspect service health.`);
      try {
        const reply = { content: publicMessage, allowedMentions: { parse: [] } };
        if (interaction.deferred || interaction.replied) await interaction.editReply(reply);
        else await interaction.reply({ ...reply, flags: MessageFlags.Ephemeral });
      } catch { console.error('Could not deliver a private interaction response.'); }
    } finally { active--; users.delete(userId); }
  }
  client.on(Events.InteractionCreate, interaction => {
    const operation = handle(interaction).catch(() => console.error('Interaction could not be acknowledged.'));
    operations.add(operation); operation.finally(() => operations.delete(operation));
  });
  client.once(Events.ClientReady, ready => {
    console.log(`Tarnished Companion connected to Discord as ${ready.user.tag}.`);
    void refreshRecords();
    recordTimer = setInterval(() => void refreshRecords(), 60000);
    recordTimer.unref();
  });
  client.on(Events.Error, () => console.error('Discord client error; connection retry is handled by discord.js.'));
  async function shutdown() {
    if (stopping) return; stopping = true;
    if (recordTimer) clearInterval(recordTimer);
    registration.stop();
    await Promise.allSettled([...operations]);
    if (recordUpdate) await recordUpdate;
    client.destroy(); recipient.fill(0); unlock();
  }
  const registration = attachRegistration(client, Events, config, { onFatal: async () => { process.exitCode = 1; await shutdown(); } });
  process.once('SIGINT', shutdown); process.once('SIGTERM', shutdown);
  try {
    await client.login(config.token);
  }
  catch (error) { await shutdown(); throw error; }
}
if (require.main === module) main().catch(error => {
  console.error(`Bot startup failed: ${error instanceof PackageError || error instanceof FormatError ? error.message : 'Check installed dependencies, Discord credentials, network access, and private storage.'}`);
  process.exitCode = 1;
});
module.exports = { main, attachRegistration };
