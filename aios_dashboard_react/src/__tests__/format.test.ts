// Pure helper tests — no DOM, no mocks. TDD-groomed: real inputs → real outputs.
import { describe, it, expect } from 'vitest';
import { formatDateTime, formatIdr, parseJsonList, toCsv } from '../lib/format';

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
