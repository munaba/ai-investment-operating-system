const fs = require('fs');
const orig = fs.readFileSync('src/pages/Phase1.tsx', 'utf8');
// Write a fixer script
const fixer = `
const fs = require('fs');
const p = 'F:/My Son/aios_dashboard_react/src/pages/Phase1.tsx';
let s = fs.readFileSync(p, 'utf8');

// Pattern: anywhere we have 'XXX<' where XXX is broken JSX, fix it.
// Brute force: replace all occurrences of '<element<' (with missing >) by '<element>'.
const fixes = [
  ['s</option>)}', 's</option>)}'],
  ['Loading journal entries</p>', 'Loading journal entries</p>'],
  ['{e.entryId</td>', '{e.entryId</td>'],
  ['{e.symbol</td>', '{e.symbol</td>'],
  ['motion.span</AnimatePresence</td>', 'motion.span</AnimatePresence</td>'],
  ['e.plannedR.toFixed(2) : '&#x2014</td>', "e.plannedR.toFixed(2) : '&#x2014;'</td>"],
  ["e.briefStatus ?? '&#x2014</td>", "{e.briefStatus ?? '&#x2014;'</td>"],
  ["e.note ?? ''</td>", "{e.note ?? ''</td>"],
  ['(entries.length} records</h5>', '(entries.length} records</h5>'],
  ['Journal Entry Details</h5>', 'Journal Entry Details</h5>'],
  ['Decision Brief Details</h5>', 'Decision Brief Details</h5>'],
  ['{journalDetailJson(selected)}</code</pre>', '{journalDetailJson(selected)}</code</pre>'],
  ['{briefDetailJson(selected)}</code</pre>', '{briefDetailJson(selected)}</code</pre>'],
];

for (const [from, to] of fixes) {
  const cnt = (s.match(new RegExp(from.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&'), 'g')) || []).length;
  if (cnt > 0) {
    s = s.replaceAll(from, to);
    console.log('FIXED ' + cnt + ':', from.slice(0, 50));
  }
}

fs.writeFileSync(p, s);
console.log('total length:', s.length);
`;

fs.writeFileSync('_run_fixer.cjs', fixer);
console.log('wrote _run_fixer.cjs');
