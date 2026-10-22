'use strict';
const crypto = require('node:crypto');
const { duration, clean } = require('./report');

const SECTIONS = [
  ['overview', 'Run overview', 'Time, character and observations'],
  ['bosses', 'Boss times', 'Fight duration, attempts and cumulative splits'],
  ['attempts', 'Every attempt', 'Victories, deaths and incomplete observations'],
  ['build', 'Character build', 'Saved attributes, weapons, armor and talismans'],
  ['comparison', 'Record comparison', 'Published records and comparison coverage'],
];
const PAGE_SIZE = 8, GOLD = 0xc6a665, MAX_SESSION_BYTES = 20 * 1024 * 1024, EDIT_WINDOW_MS = 14 * 60 * 1000;
const finite = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const md = (value, limit = 180) => clean(value, limit).replace(/@/g, '@\u200b').replace(/[\\`*_{}\[\]()<>#+.!|~>-]/g, '\\$&');
const field = (name, value, inline = false) => ({ name: String(name).slice(0, 256), value: String(value || 'Unavailable').slice(0, 1024), inline });
function dateLabel(value) {
  const instant = typeof value === 'string' ? new Date(value) : null;
  return instant && Number.isFinite(instant.getTime()) ? instant.toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, ' UTC') : 'Not checked';
}
function safeSource(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && ['www.speedrun.com', 'speedrun.com'].includes(url.hostname)
      && !url.username && !url.password && !url.port && url.href.length < 240 ? url.href : null;
  } catch { return null; }
}
function delta(value, reference) {
  if (!finite(value) || !finite(reference)) return 'Not comparable';
  const difference = value - reference;
  return `${difference > 0 ? '+' : difference < 0 ? '−' : '±'}${duration(Math.abs(difference))}`;
}
function publishedComparable(report) {
  const data = report.comparison?.published || {};
  const checked = Date.parse(data.checkedAt), started = Date.parse(report.startedAt), ended = Date.parse(report.endedAt);
  // normalizeReport accepts only finished, continuously observed runs. Keep
  // explicit timing/bounds guards here so an incomplete view cannot show a
  // final-result difference if this renderer gains another caller later.
  return report.timing?.source === 'Observed LiveSplit Game Time'
    && finite(report.timing.elapsedSeconds) && report.timing.elapsedSeconds > 0
    && Number.isFinite(started) && Number.isFinite(ended) && ended >= started
    && report.journey === 1 && ['fresh', 'stale'].includes(data.status) && data.categoryId === report.category.id
    && data.timingKey === 'pc-soulsplitter-game-time' && finite(data.bestSeconds) && data.bestSeconds > 0
    && Number.isFinite(checked) && checked <= Date.now() + 60000 && Date.now() - checked <= 24 * 60 * 60 * 1000;
}
function paceBar(value, reference) {
  const scale = Math.max(value, reference) * 1.1;
  const bar = seconds => { const filled = Math.max(0, Math.min(20, Math.round(seconds / scale * 20))); return '━'.repeat(filled) + '·'.repeat(20 - filled); };
  return `Published best  \`${bar(reference)}\`\nYour run        \`${bar(value)}\``;
}
function bossRows(report) {
  const rows = new Map();
  for (const split of report.splits) rows.set(String(split.bossId), { name: split.name, bossId: split.bossId, split, attempts: [] });
  for (const attempt of report.attempts) {
    const key = attempt.bossId == null ? `unresolved:${attempt.recordId}` : String(attempt.bossId);
    if (!rows.has(key)) rows.set(key, { name: attempt.name, bossId: attempt.bossId, split: null, attempts: [] });
    rows.get(key).attempts.push(attempt);
  }
  return [...rows.values()];
}
function paged(values, page) {
  const pages = Math.max(1, Math.ceil(values.length / PAGE_SIZE));
  const index = Math.max(0, Math.min(pages - 1, Number.isSafeInteger(page) ? page : 0));
  return { values: values.slice(index * PAGE_SIZE, (index + 1) * PAGE_SIZE), page: index, pages, first: index * PAGE_SIZE };
}
function overview(report) {
  const build = report.build.final || report.build.initial;
  const victories = report.attempts.filter(a => a.outcome === 'victory' && finite(a.elapsedSeconds));
  const observed = report.attempts.filter(a => finite(a.elapsedSeconds));
  const fastest = [...victories].sort((a, b) => a.elapsedSeconds - b.elapsedSeconds)[0];
  const longest = [...observed].sort((a, b) => b.elapsedSeconds - a.elapsedSeconds)[0];
  const points = [];
  if (fastest) points.push(`Fastest observed victory: **${md(fastest.name, 90)}** · ${duration(fastest.elapsedSeconds)}`);
  if (longest) points.push(`Longest observed attempt: **${md(longest.name, 90)}** · ${duration(longest.elapsedSeconds)}`);
  if (!points.length) points.push('No completed live fight measurements were included.');
  return {
    description: `**${md(report.category.name, 220)}**\n${md(report.character, 120)} · Journey ${report.journey}\n\nUse the menu below to explore this run.`,
    fields: [
      field('Observed game time', `**${duration(report.timing.elapsedSeconds)}**`, true),
      field('Real time', duration(report.timing.realTimeSeconds), true),
      field('Deaths', String(report.deaths), true),
      field('Boss defeats', String(report.splits.length), true),
      field('Observed attempts', String(report.attempts.length), true),
      field('Character', build ? `Level ${build.level ?? '?'} · ${md(build.class, 70)}` : 'Build unavailable', true),
      field('Run observations', points.join('\n')),
      field('Report checks', `Signature verified · enrolled account matched\nLocal audit: ${md(report.localAuditStatus, 80)}\n**Review required** · not official leaderboard approval`),
    ], page: 0, pages: 1,
  };
}
function bosses(report, page) {
  const rows = paged(bossRows(report), page);
  return { ...rows,
    description: 'Fight duration measures an encounter. A run split is cumulative game time at the saved defeat. Submitted bests and averages use each unreviewed report’s fastest complete victory in the same category and journey; routes and builds may differ.',
    fields: rows.values.map((row, index) => {
      const victories = row.attempts.filter(a => a.outcome === 'victory' && finite(a.elapsedSeconds));
      const victory = victories.length ? Math.min(...victories.map(a => a.elapsedSeconds)) : null;
      const lines = [`**Fight:** ${finite(victory) ? duration(victory) : 'No measured victory'}`, `**Run split:** ${duration(row.split?.elapsedSeconds)}`,
        `${row.attempts.length} observed ${row.attempts.length === 1 ? 'attempt' : 'attempts'} · ${row.attempts.filter(a => a.outcome === 'death').length} deaths`];
      if (row.bossId == null) lines.push('Arena unresolved · excluded from comparisons');
      const peers = report.comparison?.peers;
      const peer = peers?.status === 'available' && Array.isArray(peers.bosses) && peers.bosses.find(b => b.bossId === row.bossId);
      if (peer && finite(peer.bestFightSeconds)) {
        lines.push(`**Submitted best:** ${duration(peer.bestFightSeconds)}`);
        if (finite(peer.averageFightSeconds)) lines.push(`**Submitted average:** ${duration(peer.averageFightSeconds)}`);
        lines.push(`${peer.sampleCount} submitted ${peer.sampleCount === 1 ? 'report' : 'reports'}`);
        const complete = victories.filter(a => a.eligibleForBenchmark === true);
        if (complete.length) lines.push(`**Difference:** ${delta(Math.min(...complete.map(a => a.elapsedSeconds)), peer.bestFightSeconds)}`);
      }
      return field(`${rows.first + index + 1}. ${md(row.name, 110)}`, lines.join('\n'), true);
    }), empty: 'No boss splits or live attempts were recorded.',
  };
}
function attempts(report, page) {
  const rows = paged(report.attempts, page);
  return { ...rows, description: 'Every observed attempt stays in the report, including deaths and uncertain endings. An unfinished attempt has no final duration.',
    fields: rows.values.map((attempt, index) => field(`${rows.first + index + 1}. ${md(attempt.name, 100)} · #${attempt.attemptNumber ?? '?'}`,
      `**${md(attempt.outcome, 60)}** · ${duration(attempt.elapsedSeconds)}${attempt.note ? `\n${md(attempt.note, 220)}` : ''}`, true)),
    empty: 'No live attempts were recorded.',
  };
}
function build(report, page) {
  const snapshot = report.build.final || report.build.initial;
  if (!snapshot) return { description: 'No saved build snapshot was available. Equipment is never inferred.', fields: [], page: 0, pages: 1 };
  const equipment = [];
  for (const kind of ['weapons', 'armor', 'talismans']) for (const item of snapshot.equipment[kind]) {
    equipment.push(field(`${md(kind, 20)} · ${md(item.slot, 60)}`, `${md(item.name, 240)}${item.upgradeLevel != null ? ` +${item.upgradeLevel}` : ''}${item.affinity ? ` · ${md(item.affinity, 90)}` : ''}${item.active ? '\nEquipped active slot' : ''}`, true));
  }
  const rows = paged(equipment, page);
  return { ...rows, description: `**Level ${snapshot.level ?? '?'} · ${md(snapshot.class, 70)}**\nLast observed saved loadout · ${report.build.observations.length} retained snapshots${report.build.truncated ? ' (history truncated)' : ''}. Rapid unsaved swaps are not guaranteed to appear.`,
    fields: [field('Attributes', Object.entries(snapshot.attributes).map(([name, value]) => `${md(name, 20)} **${value ?? '—'}**`).join(' · ')), ...rows.values],
    empty: 'No resolved equipment entries were included.',
  };
}
function comparison(report, page) {
  const data = report.comparison?.published || {};
  const peers = report.comparison?.peers || {};
  const source = safeSource(data.sourceUrl);
  const description = [data.status === 'stale' ? '**Cached records · latest check unavailable**' : data.status === 'fresh' ? '**Published leaderboard records**' : '**Published comparison unavailable**',
    md(data.notice || 'Published records have not been fetched for this report.', 350),
    `Last successful check: **${dateLabel(data.checkedAt)}**`, source ? `[Open source leaderboard](${source})` : ''].filter(Boolean).join('\n');
  const entries = Array.isArray(data.runs) ? data.runs : [];
  const rows = paged(entries, page), fields = [];
  if (publishedComparable(report)) {
    fields.push(field('Published best', duration(data.bestSeconds), true));
    fields.push(field('Your observed game time', duration(report.timing.elapsedSeconds), true));
    fields.push(field('Difference', delta(report.timing.elapsedSeconds, data.bestSeconds), true));
    fields.push(field('Overall run pace', paceBar(report.timing.elapsedSeconds, data.bestSeconds)));
  }
  for (const entry of rows.values) {
    const link = safeSource(entry.url);
    fields.push(field(`${Number.isSafeInteger(entry.rank) ? `#${entry.rank} · ` : ''}${md(entry.runner || 'Published run', 110)}`,
      `${duration(entry.seconds)}${link ? ` · [Run details](${link})` : ''}`, true));
  }
  if (peers.status === 'available') {
    fields.push(field('Other submitted runs · unreviewed', `${peers.sampleCount} reports\nBest: ${duration(peers.runBestSeconds)} · Average: ${duration(peers.runAverageSeconds)}\n${md(peers.notice || 'Same category and journey; route and build may differ.', 250)}`));
  }
  fields.push(field('Comparison scope', md(data.scope || 'The selected category, timing method and platform must match before a difference can be calculated.', 300)));
  fields.push(field('Boss comparison coverage', 'The published leaderboard supplies complete run times, not individual boss fights. Boss-page comparisons use matching submitted encounters when available and remain unreviewed. Cumulative splits are never converted into fight times.'));
  return { ...rows, description, fields };
}
function renderReport(report, section = 'overview', page = 0, token = 'preview', options = {}) {
  if (!SECTIONS.some(([id]) => id === section)) section = 'overview';
  const details = ({ overview, bosses, attempts, build, comparison })[section](report, page);
  const title = SECTIONS.find(([id]) => id === section)[1];
  const fields = details.fields.length ? details.fields : [field('Details', details.empty || 'No details available.')];
  const embed = { color: GOLD, author: { name: 'TARNISHED LINEUP · RUN REPORT' }, title,
    description: details.description, fields,
    footer: { text: `Page ${details.page + 1}/${details.pages} · Run ${clean(report.recordId, 32)} · Review required` } };
  // Discord counts text across an entire embed. Long legitimate names and
  // adversarial Markdown must not turn a valid report into an API error.
  const fixedSize = embed.title.length + embed.author.name.length + embed.description.length + embed.footer.text.length;
  const namesSize = fields.reduce((n, item) => n + item.name.length, 0);
  if (fixedSize + namesSize + fields.reduce((n, item) => n + item.value.length, 0) > 5800) {
    const valueBudget = Math.max(1, Math.floor((5800 - fixedSize - namesSize) / fields.length));
    for (const item of fields) if (item.value.length > valueBudget) item.value = item.value.slice(0, Math.max(0, valueBudget - 1)) + '…';
  }
  const select = { type: 3, custom_id: `tlrun:${token}:section`, min_values: 1, max_values: 1,
    options: SECTIONS.map(([value, label, description]) => ({ label, value, description, default: value === section })) };
  const buttons = [
    { type: 2, style: 2, custom_id: `tlrun:${token}:previous`, label: 'Previous', disabled: details.page === 0 },
    { type: 2, style: 2, custom_id: `tlrun:${token}:next`, label: 'Next', disabled: details.page + 1 >= details.pages },
  ];
  if (section === 'comparison' && options.canRefresh) buttons.push({ type: 2, style: 2, custom_id: `tlrun:${token}:refresh`, label: 'Refresh records' });
  return { content: null, embeds: [embed], components: [{ type: 1, components: [select] }, { type: 1, components: buttons }], allowedMentions: { parse: [] } };
}

class ReportMenus {
  constructor({ now = Date.now, refreshComparison = null, ttlMs = 30 * 60 * 1000, maxBytes = MAX_SESSION_BYTES, maxSessions = 32 } = {}) {
    this.now = now; this.refreshComparison = refreshComparison; this.ttlMs = ttlMs; this.maxBytes = maxBytes; this.maxSessions = maxSessions;
    this.sessions = new Map(); this.bytes = 0;
  }
  drop(token) { const found = this.sessions.get(token); if (found) { this.bytes -= found.bytes; this.sessions.delete(token); } }
  prune() { for (const [token, s] of this.sessions) if (s.expiresAt <= this.now()) this.drop(token); }
  create(report, userId, guildId) {
    this.prune();
    const bytes = Buffer.byteLength(JSON.stringify(report));
    if (bytes > this.maxBytes) return null;
    while (this.sessions.size && (this.sessions.size >= this.maxSessions || this.bytes + bytes > this.maxBytes)) this.drop(this.sessions.keys().next().value);
    const token = crypto.randomBytes(16).toString('hex');
    this.sessions.set(token, { report, userId, guildId, messageId: null, section: 'overview', page: 0, expiresAt: this.now() + this.ttlMs, bytes, busy: false, lastRefresh: -Infinity, edit: null, editableUntil: 0 });
    this.bytes += bytes;
    return { token, message: renderReport(report, 'overview', 0, token, { canRefresh: !!this.refreshComparison }) };
  }
  bind(token, messageId, { edit = null, editableUntil = this.now() + EDIT_WINDOW_MS } = {}) {
    const s = this.sessions.get(token);
    if (s) {
      s.messageId = messageId; s.edit = typeof edit === 'function' ? edit : null;
      s.editableUntil = Number.isFinite(editableUntil) ? Math.min(editableUntil, this.now() + EDIT_WINDOW_MS) : 0;
    }
  }
  setComparison(token, session, comparison) {
    if (!comparison || typeof comparison !== 'object' || Buffer.byteLength(JSON.stringify(comparison)) > 256 * 1024) throw new Error('Invalid comparison size');
    const nextBytes = Buffer.byteLength(JSON.stringify({ ...session.report, comparison }));
    if (this.sessions.get(token) !== session || this.bytes - session.bytes + nextBytes > this.maxBytes) throw new Error('Report cache capacity');
    this.bytes += nextBytes - session.bytes; session.bytes = nextBytes;
    session.report.comparison = comparison;
  }
  async refreshPublishedSnapshots(snapshotFn) {
    this.prune();
    let updated = 0;
    if (typeof snapshotFn !== 'function') return updated;
    for (const [token, session] of this.sessions) {
      if (this.now() >= session.editableUntil) { session.edit = null; continue; }
      if (session.section !== 'comparison' || session.busy || typeof session.edit !== 'function') continue;
      session.busy = true;
      try {
        const published = await snapshotFn(session.report);
        if (!published || typeof published !== 'object' || Array.isArray(published) || published.categoryId !== session.report.category.id) continue;
        const identity = value => JSON.stringify([value?.checkedAt, value?.status, value?.bestSeconds]);
        if (identity(published) === identity(session.report.comparison?.published)) continue;
        if (this.now() >= session.editableUntil || this.sessions.get(token) !== session) continue;
        this.setComparison(token, session, { ...(session.report.comparison || {}), published });
        try {
          await session.edit(renderReport(session.report, session.section, session.page, token, { canRefresh: !!this.refreshComparison }));
          updated++;
        } catch {
          // Interaction webhooks expire. Stop automatic edits without posting
          // a new message; the next owner interaction supplies a fresh token.
          session.edit = null; session.editableUntil = 0;
        }
      } catch {
        // The cache and a valid receipt survive an unavailable snapshot.
      } finally { session.busy = false; }
    }
    return updated;
  }
  async handle(interaction) {
    if (!(interaction.isButton?.() || interaction.isStringSelectMenu?.()) || typeof interaction.customId !== 'string' || !interaction.customId.startsWith('tlrun:')) return false;
    const match = /^tlrun:([a-f0-9]{32}):(section|previous|next|refresh)$/.exec(interaction.customId);
    this.prune(); const session = match && this.sessions.get(match[1]);
    const reject = async content => { await interaction.reply({ content, flags: 64, allowedMentions: { parse: [] } }); return true; };
    if (!session) return reject('This report menu has expired. Your attached receipts and the administrator’s saved report remain available; do not re-submit the same run.');
    if (interaction.user?.id !== session.userId || interaction.guildId !== session.guildId || !session.messageId || interaction.message?.id !== session.messageId) return reject('This private report menu belongs to its original submitter and message.');
    if (session.busy) return reject('This report view is updating. Please try again in a moment.');
    const action = match[2];
    if (action === 'section' && (!interaction.isStringSelectMenu() || interaction.values?.length !== 1 || !SECTIONS.some(([id]) => id === interaction.values[0]))) return reject('Choose one of this report’s sections.');
    if (action !== 'section' && !interaction.isButton()) return reject('Use this report’s navigation buttons.');
    if (action === 'refresh' && (!this.refreshComparison || session.section !== 'comparison')) return reject('Record refresh is unavailable in this view.');
    if (action === 'refresh' && this.now() - session.lastRefresh < 15000) return reject('Records were checked recently. Please wait a few seconds before refreshing again.');
    session.busy = true;
    try {
      await interaction.deferUpdate();
      if (action === 'section') { session.section = interaction.values[0]; session.page = 0; }
      if (action === 'previous') session.page = Math.max(0, session.page - 1);
      if (action === 'next') session.page++;
      if (session.section === 'comparison' && this.refreshComparison && (action === 'refresh' || this.now() - session.lastRefresh >= 15000)) {
        session.lastRefresh = this.now();
        try {
          const refreshed = await this.refreshComparison(session.report, { force: action === 'refresh' });
          this.setComparison(match[1], session, refreshed);
        } catch {
          try { this.setComparison(match[1], session, { ...(session.report.comparison || {}), published: { ...(session.report.comparison?.published || {}), status: 'stale', notice: 'The latest record check failed. Previously retrieved records may be out of date.' } }); } catch {}
        }
      }
      const message = renderReport(session.report, session.section, session.page, match[1], { canRefresh: !!this.refreshComparison });
      // Rendering clamps requested pages; storing that index prevents unlimited
      // stale-button clicks from moving the cursor beyond the actual report.
      session.page = Number(message.embeds[0].footer.text.match(/^Page (\d+)/)[1]) - 1;
      await interaction.editReply(message);
      this.bind(match[1], session.messageId, { edit: payload => interaction.editReply(payload) });
      return true;
    } finally { session.busy = false; }
  }
}
module.exports = { ReportMenus, renderReport, bossRows, safeSource, delta, publishedComparable, paceBar, SECTIONS, PAGE_SIZE };
