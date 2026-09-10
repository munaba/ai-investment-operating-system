// Pure helper tests — no DOM, no mocks. TDD-groomed: real inputs → real outputs.
import { describe, it, expect } from 'vitest';
import { formatDateTime, formatIdr, parseJsonList, toCsv, escapeCsvCell } from '../lib/format';

describe('format helpers', () => {
  it('formatDateTime renders ISO-ish strings in id-ID style', () => {
    expect(formatDateTime('2026-08-24T03:58:27.943292+00:00')).toMatch(/2026-08-24 03:58:27/);
  });
  it('formatDateTime returns — for null/empty', () => {
    expect(formatDateTime(null)).toBe('—');
    expect(formatDateTime('')).toBe('—');
  });
  it('formatDateTime returns the raw string for unparseable input', () => {
    expect(formatDateTime('not-a-date')).toBe('not-a-date');
  });
  it('formatIdr formats IDR with no fraction digits', () => {
    expect(formatIdr(100000)).toBe('Rp 100.000');
  });
  it('parseJsonList parses a JSON array', () => {
    expect(parseJsonList('["a","b"]')).toEqual(['a', 'b']);
  });
  it('parseJsonList falls back to single element on bad json', () => {
    expect(parseJsonList('garbage')).toEqual(['garbage']);
    expect(parseJsonList(null)).toEqual([]);
  });
  it('toCsv escapes commas and quotes', () => {
    expect(toCsv([{ a: 'x', b: 'y,z' }, { a: 'p"q', b: '2' }])).toBe('a,b\nx,"y,z"\n"p""q",2');
  });
});

describe('escapeCsvCell — CSV formula injection guard (CWE-1236)', () => {
  it('neutralises the four dangerous leading characters', () => {
    expect(escapeCsvCell('=SUM(A1)')).toBe("'=SUM(A1)");
    expect(escapeCsvCell('+123')).toBe("'+123");
    expect(escapeCsvCell('-456')).toBe("'-456");
    expect(escapeCsvCell('@import')).toBe("'@import");
  });
  it('neutralises TAB / CR prefixed cells (Excel strips them, then evaluates)', () => {
    expect(escapeCsvCell('\t=SUM(A1)')).toBe("'\t=SUM(A1)");
    // CR also forces quoting (it is in the quote-trigger set), so the cell is
    // both guarded (apostrophe) and wrapped in double quotes.
    expect(escapeCsvCell('\r=SUM(A1)')).toBe('"\'\r=SUM(A1)"');
  });
  it('leaves ordinary values untouched', () => {
    expect(escapeCsvCell('BBCA')).toBe('BBCA');
    expect(escapeCsvCell('Rp 10.000')).toBe('Rp 10.000');
    expect(escapeCsvCell('')).toBe('');
    expect(escapeCsvCell(null)).toBe('');
    expect(escapeCsvCell(undefined)).toBe('');
    expect(escapeCsvCell(42)).toBe('42');
    // negative number in the middle of a word is not a lead character
    expect(escapeCsvCell('a-1')).toBe('a-1');
  });
  it('guards AND quotes when the cell also needs quoting', () => {
    expect(escapeCsvCell('=A1,B1')).toBe('"\'=A1,B1"');
    expect(escapeCsvCell('=say "hi"')).toBe('"\'=say ""hi"""');
  });
  it('toCsv applies the guard to every data cell', () => {
    const csv = toCsv([{ symbol: '=cmd|1', note: '+x' }]);
    expect(csv).toBe("symbol,note\n'=cmd|1,'+x");
  });
});
