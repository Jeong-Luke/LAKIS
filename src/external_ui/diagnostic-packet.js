(function (global) {
  'use strict';

  const MAX_RAW_BYTES = 4 * 1024 * 1024;
  const MAX_COMPRESSED_BYTES = 1024 * 1024;
  const MAX_BASE64URL_LENGTH =
    Math.floor(MAX_COMPRESSED_BYTES / 3) * 4 +
    (MAX_COMPRESSED_BYTES % 3 === 0 ? 0 : (MAX_COMPRESSED_BYTES % 3) + 1);

  function validateJsonValue(value, ancestors) {
    if (
      value === null ||
      typeof value === 'string' ||
      typeof value === 'boolean'
    ) {
      return;
    }

    if (typeof value === 'number') {
      if (!Number.isFinite(value)) {
        throw new TypeError('Report contains a non-JSON number');
      }
      return;
    }

    if (typeof value !== 'object') {
      throw new TypeError('Report contains a non-JSON value');
    }
    if (ancestors.has(value)) {
      throw new TypeError('Report contains a cycle');
    }
    ancestors.add(value);

    const isArray = Array.isArray(value);
    const prototype = Object.getPrototypeOf(value);
    if (
      (isArray && prototype !== Array.prototype) ||
      (!isArray && prototype !== Object.prototype && prototype !== null)
    ) {
      throw new TypeError('Report contains a non-JSON object');
    }

    const keys = Reflect.ownKeys(value);
    if (isArray) {
      if (value.length > MAX_RAW_BYTES) {
        throw new RangeError('Report exceeds the raw size limit');
      }
      for (const key of keys) {
        if (typeof key !== 'string') {
          throw new TypeError('Report contains a non-JSON property');
        }
        if (key === 'length') {
          continue;
        }
        const index = Number(key);
        if (
          !Number.isInteger(index) ||
          index < 0 ||
          index >= value.length ||
          String(index) !== key
        ) {
          throw new TypeError('Report contains a non-JSON array property');
        }
        const descriptor = Object.getOwnPropertyDescriptor(value, key);
        if (!descriptor.enumerable || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) {
          throw new TypeError('Report contains a non-JSON array property');
        }
      }
      for (let index = 0; index < value.length; index += 1) {
        if (!Object.prototype.hasOwnProperty.call(value, index)) {
          throw new TypeError('Report contains a sparse array');
        }
        validateJsonValue(value[index], ancestors);
      }
    } else {
      for (const key of keys) {
        if (typeof key !== 'string') {
          throw new TypeError('Report contains a non-JSON property');
        }
        const descriptor = Object.getOwnPropertyDescriptor(value, key);
        if (!descriptor.enumerable || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) {
          throw new TypeError('Report contains a non-JSON property');
        }
        validateJsonValue(descriptor.value, ancestors);
      }
    }

    ancestors.delete(value);
  }

  function validateReport(report) {
    if (report === null || typeof report !== 'object' || Array.isArray(report)) {
      throw new TypeError('Report must be a JSON object');
    }
    validateJsonValue(report, new Set());
    if (report.report_schema !== 1) {
      throw new TypeError('Report schema must be 1');
    }
    if (typeof report.error_code !== 'string' || report.error_code.length === 0) {
      throw new TypeError('Report error_code must be a nonempty string');
    }
  }

  function toBase64Url(bytes) {
    let binary = '';
    for (let offset = 0; offset < bytes.length; offset += 0x8000) {
      const end = Math.min(offset + 0x8000, bytes.length);
      for (let index = offset; index < end; index += 1) {
        binary += String.fromCharCode(bytes[index]);
      }
    }
    return btoa(binary)
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/g, '');
  }

  function fromBase64Url(encoded) {
    if (
      encoded.length === 0 ||
      encoded.length > MAX_BASE64URL_LENGTH ||
      !/^[A-Za-z0-9_-]+$/.test(encoded) ||
      encoded.length % 4 === 1
    ) {
      throw new TypeError('Malformed Base64url payload');
    }

    const base64 = encoded.replace(/-/g, '+').replace(/_/g, '/');
    const binary = atob(base64 + '='.repeat((4 - (base64.length % 4)) % 4));
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    if (bytes.byteLength > MAX_COMPRESSED_BYTES || toBase64Url(bytes) !== encoded) {
      throw new TypeError('Noncanonical or oversized Base64url payload');
    }
    return bytes;
  }

  function joinChunks(chunks, total) {
    const output = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      output.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return output;
  }

  async function transformBytesBounded(input, transform, maxOutputBytes, limitMessage) {
    const writer = transform.writable.getWriter();
    const reader = transform.readable.getReader();
    const writeTask = (async function () {
      await writer.write(input);
      await writer.close();
    })();
    writeTask.catch(function () {});

    const chunks = [];
    let total = 0;
    try {
      while (true) {
        const result = await reader.read();
        if (result.done) {
          break;
        }
        if (result.value.byteLength > maxOutputBytes - total) {
          const error = new RangeError(limitMessage);
          try {
            await reader.cancel(error);
          } catch (_) {}
          try {
            await writer.abort(error);
          } catch (_) {}
          await writeTask.catch(function () {});
          throw error;
        }
        chunks.push(result.value);
        total += result.value.byteLength;
      }
      await writeTask;
    } catch (error) {
      try {
        await reader.cancel(error);
      } catch (_) {}
      try {
        await writer.abort(error);
      } catch (_) {}
      await writeTask.catch(function () {});
      throw error;
    } finally {
      reader.releaseLock();
      writer.releaseLock();
    }
    return joinChunks(chunks, total);
  }

  async function sha256Hex(bytes) {
    const digest = new Uint8Array(await global.crypto.subtle.digest('SHA-256', bytes));
    let hex = '';
    for (const byte of digest) {
      hex += byte.toString(16).padStart(2, '0');
    }
    return hex;
  }

  function extractToken(text) {
    if (typeof text !== 'string') {
      throw new TypeError('Diagnostic input must be text');
    }
    if (text.length > MAX_BASE64URL_LENGTH + 16384) {
      throw new RangeError('Diagnostic input exceeds the text size limit');
    }
    const trimmed = text.trim();
    if (trimmed.startsWith('LKS') && !/\s/u.test(trimmed)) {
      return trimmed;
    }
    const candidates = [];
    const matcher = /(^|[^A-Za-z0-9_])(LKS[0-9]+[A-Za-z]+:[^\s]*)/g;
    let match;
    while ((match = matcher.exec(text)) !== null) {
      candidates.push(match[2].replace(/[.,;)\]}]+$/, ''));
    }
    if (candidates.length !== 1) {
      throw new TypeError('Expected exactly one diagnostic packet token');
    }
    return candidates[0];
  }

  function parseToken(token) {
    const header = token.split(':', 1)[0];
    if (header.startsWith('LKS') && header !== 'LKS1G') {
      throw new TypeError('Unknown diagnostic packet version or codec');
    }
    const fields = token.split(':');
    if (fields.length !== 4 || fields[0] !== 'LKS1G') {
      throw new TypeError('Malformed diagnostic packet');
    }
    if (!/^(0|[1-9][0-9]*)$/.test(fields[1])) {
      throw new TypeError('Malformed diagnostic packet length');
    }
    const rawLength = Number(fields[1]);
    if (!Number.isSafeInteger(rawLength) || rawLength > MAX_RAW_BYTES) {
      throw new RangeError('Diagnostic packet exceeds the raw size limit');
    }
    if (!/^[0-9a-f]{64}$/.test(fields[2])) {
      throw new TypeError('Malformed diagnostic packet hash');
    }
    return {
      rawLength: rawLength,
      hash: fields[2],
      compressed: fromBase64Url(fields[3])
    };
  }

  async function encode(report) {
    validateReport(report);
    const json = JSON.stringify(report);
    const raw = new TextEncoder().encode(json);
    if (raw.byteLength > MAX_RAW_BYTES) {
      throw new RangeError('Report exceeds the raw size limit');
    }

    const compressed = await transformBytesBounded(
      raw,
      new CompressionStream('gzip'),
      MAX_COMPRESSED_BYTES,
      'Report exceeds the compressed size limit'
    );
    const hash = await sha256Hex(raw);
    return 'LKS1G:' + raw.byteLength + ':' + hash + ':' + toBase64Url(compressed);
  }

  async function decode(fullCopiedReportOrToken) {
    const packet = parseToken(extractToken(fullCopiedReportOrToken));
    const raw = await transformBytesBounded(
      packet.compressed,
      new DecompressionStream('gzip'),
      packet.rawLength,
      'Diagnostic packet exceeds its declared or raw size limit'
    );
    if (raw.byteLength !== packet.rawLength) {
      throw new TypeError('Diagnostic packet length mismatch');
    }
    if ((await sha256Hex(raw)) !== packet.hash) {
      throw new TypeError('Diagnostic packet hash mismatch');
    }

    let json;
    try {
      json = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(raw);
    } catch (_) {
      throw new TypeError('Diagnostic packet is not valid UTF-8');
    }

    let report;
    try {
      report = JSON.parse(json);
    } catch (_) {
      throw new TypeError('Diagnostic packet does not contain valid JSON');
    }
    validateReport(report);
    return report;
  }

  global.LAKISDiagnosticPacket = Object.freeze({
    encode: encode,
    decode: decode
  });
})(globalThis);
