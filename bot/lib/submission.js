'use strict';
const { decryptPackage, PackageError, MAX_PACKAGE } = require('./package');
const { normalizeReport } = require('./report');
const ALLOWED_HOSTS = new Set(['cdn.discordapp.com', 'media.discordapp.net']);
function safeUrl(value) {
  let url;
  try { url = new URL(value); } catch { throw new PackageError('DOWNLOAD', 'Attachment URL is invalid.'); }
  if (url.protocol !== 'https:' || !ALLOWED_HOSTS.has(url.hostname) || url.port || url.username || url.password || !url.pathname.startsWith('/attachments/')) throw new PackageError('DOWNLOAD', 'Only Discord attachment URLs are accepted.');
  return url;
}
async function downloadAttachment(attachment, fetcher = fetch) {
  if (!attachment || typeof attachment.name !== 'string' || !/\.tlrun$/i.test(attachment.name) || !Number.isSafeInteger(attachment.size) || attachment.size < 1 || attachment.size > MAX_PACKAGE) throw new PackageError('DOWNLOAD', 'Attach one .tlrun file no larger than 8 MiB.');
  let url = safeUrl(attachment.url);
  const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 20000);
  let response;
  try {
    for (let redirects = 0; redirects <= 2; redirects++) {
      response = await fetcher(url, { signal: controller.signal, redirect: 'manual' });
      if (![301, 302, 303, 307, 308].includes(response.status)) break;
      await response.body?.cancel();
      if (redirects === 2) throw new PackageError('DOWNLOAD', 'Too many attachment redirects.');
      url = safeUrl(new URL(response.headers.get('location'), url).href);
    }
    if (!response.ok || !response.body) throw new PackageError('DOWNLOAD', 'Discord attachment could not be downloaded.');
    const length = response.headers.get('content-length');
    if (length !== null && (!/^\d+$/.test(length) || Number(length) > MAX_PACKAGE)) throw new PackageError('DOWNLOAD', 'Attachment exceeds the 8 MiB limit.');
    let size = 0; const chunks = [];
    for await (const chunk of response.body) {
      size += chunk.length;
      if (size > MAX_PACKAGE) { controller.abort(); throw new PackageError('DOWNLOAD', 'Attachment exceeds the 8 MiB limit.'); }
      chunks.push(Buffer.from(chunk));
    }
    if (size !== attachment.size) throw new PackageError('DOWNLOAD', 'Downloaded attachment size does not match Discord metadata.');
    return Buffer.concat(chunks, size);
  } catch (error) {
    if (error instanceof PackageError) throw error;
    throw new PackageError('DOWNLOAD', 'Attachment download failed or timed out.');
  } finally { clearTimeout(timeout); }
}
async function submit(bytes, userId, recipient, store) {
  const opened = decryptPackage(bytes, recipient);
  const report = normalizeReport(opened);
  // commit independently checks signer enrollment and the invoking account.
  // A cryptographically valid self-signed report is never auto-enrolled.
  const receipt = await store.commit(opened, report, userId);
  return { report, receipt };
}
module.exports = { safeUrl, downloadAttachment, submit };
