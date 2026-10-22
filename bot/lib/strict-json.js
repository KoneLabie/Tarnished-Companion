'use strict';

// JSON.parse cannot reject duplicate keys. Parse bounded input before trusting
// signed fields, including escaped spellings of the same property name.
const utf8 = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });
class FormatError extends Error { constructor(message) { super(message); this.name = 'FormatError'; this.code = 'FORMAT'; } }
function parseJson(bytes, maximum, label = 'JSON', { maxNodes = 200000 } = {}) {
  if (!Buffer.isBuffer(bytes) || !bytes.length || bytes.length > maximum) throw new FormatError(`${label} exceeds its size limit or is empty.`);
  let text;
  try { text = utf8.decode(bytes); } catch { throw new FormatError(`${label} is not valid UTF-8.`); }
  let at = 0, nodes = 0;
  function fail() { throw new FormatError(`${label} is malformed, duplicated, or exceeds its structural limits.`); }
  function whitespace() { while (' \r\n\t'.includes(text[at]) && at < text.length) at++; }
  function string() {
    const start = at++;
    while (at < text.length) {
      const c = text[at++];
      if (c === '"') {
        try { return JSON.parse(text.slice(start, at)); } catch { fail(); }
      }
      if (c === '\\') at++;
      else if (c.charCodeAt(0) < 32) fail();
    }
    fail();
  }
  function value(depth) {
    if (++nodes > maxNodes || depth > 32) fail();
    whitespace();
    if (text[at] === '"') return string();
    if (text[at] === '{') {
      at++;
      const object = Object.create(null), keys = new Set();
      whitespace();
      if (text[at] === '}') { at++; return object; }
      while (at < text.length) {
        whitespace();
        if (text[at] !== '"') fail();
        const key = string();
        if (keys.has(key)) fail();
        keys.add(key); whitespace();
        if (text[at++] !== ':') fail();
        object[key] = value(depth + 1); whitespace();
        const sep = text[at++];
        if (sep === '}') return object;
        if (sep !== ',') fail();
      }
      fail();
    }
    if (text[at] === '[') {
      at++; const array = []; whitespace();
      if (text[at] === ']') { at++; return array; }
      while (at < text.length) {
        array.push(value(depth + 1)); whitespace();
        const sep = text[at++];
        if (sep === ']') return array;
        if (sep !== ',') fail();
      }
      fail();
    }
    for (const [word, result] of [['true', true], ['false', false], ['null', null]]) {
      if (text.startsWith(word, at)) { at += word.length; return result; }
    }
    const match = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(text.slice(at));
    if (!match) fail();
    at += match[0].length;
    const number = Number(match[0]);
    if (!Number.isFinite(number) || Math.abs(number) > Number.MAX_SAFE_INTEGER) fail();
    return number;
  }
  const parsed = value(0); whitespace();
  if (at !== text.length) fail();
  return parsed;
}
function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
function exactFields(value, fields) {
  return object(value) && Object.keys(value).length === fields.length && fields.every(key => Object.hasOwn(value, key));
}
function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (object(value)) return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
  return JSON.stringify(value);
}
module.exports = { parseJson, FormatError, object, exactFields, canonical };
