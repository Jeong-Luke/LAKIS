import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { createHash, webcrypto } from 'node:crypto';
import { gzipSync, gunzipSync } from 'node:zlib';

Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true });
globalThis.btoa = (value) => Buffer.from(value, 'binary').toString('base64');
globalThis.atob = (value) => Buffer.from(value, 'base64').toString('binary');

const sourcePath = fileURLToPath(
  new URL('../../src/external_ui/diagnostic-packet.js', import.meta.url)
);
const source = await readFile(sourcePath, 'utf8');
vm.runInThisContext(source, { filename: sourcePath });

const codec = globalThis.LAKISDiagnosticPacket;
assert.equal(typeof codec.encode, 'function');
assert.equal(typeof codec.decode, 'function');

const report = {
  report_schema: 1,
  error_code: 'NETWORK_DIAGNOSTIC',
  message: '연결을 확인하세요 🚀',
  details: {
    retries: 0,
    cancelled: false,
    nested: {
      note: '한글과 이모지 😀',
      values: [false, 0, null, { explanation: '상세 진단' }]
    }
  }
};

const token = await codec.encode(report);
assert.match(token, /^LKS1G:(0|[1-9][0-9]*):[0-9a-f]{64}:[A-Za-z0-9_-]+$/);
assert.deepEqual(await codec.decode(token), report);
assert.deepEqual(
  await codec.decode('Copied diagnostic report:\n' + token + '\nEnd of report.'),
  report
);
assert.deepEqual(await codec.decode(`Copied report (${token}).`), report);
assert.deepEqual(await codec.decode(`LAKIS 8.0.1 | LKS-GEN-1012 | 연결 실패\n진단: ${token}`), report);
await assert.rejects(codec.decode(`LAKIS | LKS-GEN-1012\n진단: ${token}=`));
await assert.rejects(codec.decode(`LAKIS | LKS-GEN-1012\n진단: ${token}!`));

const [, rawLength, expectedHash, encoded] = token.split(':');
const compressed = Buffer.from(encoded, 'base64url');
const independentRaw = gunzipSync(compressed);
assert.equal(Number(rawLength), independentRaw.byteLength);
assert.equal(
  expectedHash,
  createHash('sha256').update(independentRaw).digest('hex')
);
assert.deepEqual(JSON.parse(independentRaw.toString('utf8')), report);

function makeToken(
  raw,
  gzipBytes = gzipSync(raw),
  length = raw.byteLength,
  hashInput = raw,
  version = 'LKS1G'
) {
  const hash = createHash('sha256').update(hashInput).digest('hex');
  return `${version}:${length}:${hash}:${gzipBytes.toString('base64url')}`;
}

async function mustReject(input) {
  await assert.rejects(codec.decode(input));
}

const raw = Buffer.from(JSON.stringify(report), 'utf8');
const validCompressed = gzipSync(raw);
const validHash = createHash('sha256').update(raw).digest('hex');
const validPacket = `LKS1G:${raw.length}:${validHash}:${validCompressed.toString('base64url')}`;

const corruptedGzip = Buffer.from(validCompressed);
corruptedGzip[corruptedGzip.length - 1] ^= 0x01;
await mustReject(`LKS1G:${raw.length}:${validHash}:${corruptedGzip.toString('base64url')}`);
await mustReject(`LKS1G:${raw.length}:${validHash}:${validCompressed.subarray(0, -2).toString('base64url')}`);
await mustReject(`LKS1G:${raw.length}:${'0'.repeat(64)}:${validCompressed.toString('base64url')}`);
await mustReject(`LKS1G:${raw.length + 1}:${validHash}:${validCompressed.toString('base64url')}`);
await mustReject(validPacket.replace('LKS1G:', 'LKS2G:'));
await mustReject(validPacket.slice(0, -1) + '!');
await mustReject(validPacket + '=');
await mustReject(`${validPacket}\n${validPacket}`);

const oversizedCompressed = Buffer.alloc(1024 * 1024 + 1).toString('base64url');
await mustReject(`LKS1G:1:${'0'.repeat(64)}:${oversizedCompressed}`);
await mustReject(`LKS1G:${4 * 1024 * 1024 + 1}:${'0'.repeat(64)}:${validCompressed.toString('base64url')}`);

const expansion = Buffer.alloc(4 * 1024 * 1024 + 1, 0x41);
const expansionGzip = gzipSync(expansion);
await mustReject(
  `LKS1G:${4 * 1024 * 1024}:${createHash('sha256').update(expansion).digest('hex')}:${expansionGzip.toString('base64url')}`
);

const noise = Buffer.alloc(2 * 1024 * 1024);
let seed = 0x12345678;
for (let index = 0; index < noise.length; index += 1) {
  seed ^= seed << 13;
  seed ^= seed >>> 17;
  seed ^= seed << 5;
  noise[index] = seed & 0xff;
}
const noisyReport = {
  report_schema: 1,
  error_code: 'SIZE_LIMIT_TEST',
  noise: noise.toString('base64')
};
const noisyRaw = Buffer.from(JSON.stringify(noisyReport), 'utf8');
assert.ok(noisyRaw.byteLength <= 4 * 1024 * 1024);
assert.ok(gzipSync(noisyRaw).byteLength > 1024 * 1024);
await assert.rejects(codec.encode(noisyReport));

const wrongSchema = Buffer.from('{"report_schema":2,"error_code":"X"}', 'utf8');
await mustReject(makeToken(wrongSchema));
const emptyErrorCode = Buffer.from('{"report_schema":1,"error_code":""}', 'utf8');
await mustReject(makeToken(emptyErrorCode));
await mustReject(makeToken(Buffer.from('{"report_schema":1,"error_code":"X","number":1e999}')));
await mustReject(makeToken(raw, Buffer.concat([validCompressed, gzipSync(Buffer.alloc(0))])));
await assert.rejects(
  codec.encode({ report_schema: 1, error_code: 'X', unsupported: undefined })
);

console.log('diagnostic packet browser API tests passed');
