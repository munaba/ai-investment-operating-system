import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import React from 'react';

// ---------------------------------------------------------------------------
// jsdom environment shims
// ---------------------------------------------------------------------------
// jsdom ships neither `customElements` registration wired to the real
// `esm-env` browser condition, nor `ResizeObserver`. Both are required by
// components we render in tests:
//
//   * @number-flow/react -> registers the <number-flow-react> custom element
//     via `esm-env`'s BROWSER flag, which is `false` under jsdom, so the
//     element is never defined and `this.el?.willUpdate` is undefined.
//   * @visx/responsive (used by EquityChartBklit) -> `new LocalResizeObserver`
//     where LocalResizeObserver = window.ResizeObserver, absent in jsdom.
//
// We stub these globally (not per test file) so every web-component or
// observer-based component behaves consistently under test, now and later.
// ---------------------------------------------------------------------------

// --- ResizeObserver --------------------------------------------------------
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

// --- @number-flow/react ---------------------------------------------------
// Render the formatted number directly. Tests assert on the value and its
// formatting, not on the canvas animation, which jsdom cannot run anyway.
vi.mock('@number-flow/react', () => ({
  default: (props: {
    value: number;
    locales?: string;
    format?: Intl.NumberFormatOptions;
  }) =>
    React.createElement(
      'span',
      { 'data-testid': 'number-flow' },
      new Intl.NumberFormat(props.locales ?? 'id-ID', {
        style: 'currency',
        currency: 'IDR',
        maximumFractionDigits: 0,
        ...props.format,
      }).format(props.value),
    ),
}));

afterEach(() => {
  cleanup();
  localStorage.clear();
});
