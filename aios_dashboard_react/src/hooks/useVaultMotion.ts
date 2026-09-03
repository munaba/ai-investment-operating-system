import { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { useReducedMotionSafe } from './useReducedMotionSafe';

// registerPlugin() is intentionally NOT called at module scope: ScrollTrigger's
// registration probes window.matchMedia, which jsdom does not implement — a
// top-level call would break any test file that imports this hook at collection
// time. Registering inside the effect keeps it browser-only.
let registered = false;
function ensureRegistered() {
  if (registered) return;
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    gsap.registerPlugin(ScrollTrigger);
    registered = true;
  }
}

/**
 * Vault motion layer — GSAP port of aios_mockup_iterasi11's timeline.
 *
 * Mirrors the mockup's accessibility contract: every tween is gated behind
 * matchMedia('(prefers-reduced-motion: reduce)'), because the CSS media query
 * only kills CSS transitions — it does nothing to JS-driven GSAP tweens.
 * When reduced, elements are set to their static, fully-visible end-state so
 * no information is lost (identical end-state, zero motion).
 */
export function useVaultMotion<T extends HTMLElement>(enabled = true) {
  const scopeRef = useRef<T | null>(null);
  const prefersReduced = useReducedMotionSafe();

  useEffect(() => {
    const root = scopeRef.current;
    if (!root || !enabled) return;

    ensureRegistered();

    // Scope every selector to this component instance — never leak globally.
    const q = gsap.utils.selector(root);

    const targets = {
      frame: q('[data-motion="frame"]'),
      glow: q('[data-motion="glow"]'),
      giant: q('[data-motion="giant"]'),
      kicker: q('[data-motion="kicker"]'),
      headline: q('[data-motion="headline"]'),
      sub: q('[data-motion="sub"]'),
      number: q('[data-motion="number"]'),
      reveals: q('.reveal'),
      heads: q('.section-head'),
      rows: q('tbody tr'),
    };

    const all = Object.values(targets).flat();

    if (prefersReduced) {
      // Static, fully visible end-state — no float/glow/drift/reveal.
      gsap.set(all, { opacity: 1, y: 0, x: 0, scale: 1, rotate: 0 });
      return;
    }

    const ctx = gsap.context(() => {
      // ---- Idle hero motion: floating frame + breathing glow + drifting type ----
      if (targets.frame.length) {
        gsap.to(targets.frame, {
          y: -16,
          rotate: 0.6,
          duration: 4.2,
          ease: 'sine.inOut',
          repeat: -1,
          yoyo: true,
        });
      }
      if (targets.glow.length) {
        gsap.to(targets.glow, {
          scale: 1.12,
          opacity: 0.85,
          duration: 5.5,
          ease: 'sine.inOut',
          repeat: -1,
          yoyo: true,
        });
      }
      if (targets.giant.length) {
        gsap.to(targets.giant, {
          x: -18,
          duration: 9,
          ease: 'sine.inOut',
          repeat: -1,
          yoyo: true,
        });
      }

      // ---- Page-load sequence (same offsets as the mockup tl.from chain) ----
      const tl = gsap.timeline({ defaults: { ease: 'power3.out' } });
      if (targets.giant.length) {
        tl.from(targets.giant, { opacity: 0, scale: 1.06, duration: 1.4, ease: 'power2.out' }, 0.1);
      }
      if (targets.frame.length) {
        tl.from(targets.frame, { opacity: 0, y: 40, scale: 0.94, duration: 1.1 }, 0.35);
      }
      if (targets.kicker.length) {
        tl.from(targets.kicker, { opacity: 0, y: 10, duration: 0.6 }, 0.7);
      }
      if (targets.headline.length) {
        tl.from(targets.headline, { opacity: 0, y: 16, duration: 0.8 }, 0.8);
      }
      if (targets.sub.length) {
        tl.from(targets.sub, { opacity: 0, y: 12, duration: 0.7 }, 0.95);
      }
      if (targets.number.length) {
        tl.from(targets.number, { opacity: 0, y: 12, duration: 0.7 }, 1.05);
      }

      // ---- Scroll reveals: staggered per row / per section head ----
      targets.heads.forEach((el) => {
        gsap.from(el, {
          opacity: 0,
          y: 20,
          duration: 0.9,
          ease: 'power3.out',
          scrollTrigger: { trigger: el, start: 'top 85%' },
        });
      });

      targets.rows.forEach((el, i) => {
        gsap.from(el, {
          opacity: 0,
          y: 10,
          duration: 0.5,
          ease: 'power2.out',
          scrollTrigger: { trigger: el, start: 'top 92%' },
          delay: (i % 8) * 0.04,
        });
      });

      targets.reveals.forEach((el, i) => {
        gsap.to(el, {
          opacity: 1,
          y: 0,
          duration: 0.9,
          ease: 'power3.out',
          scrollTrigger: { trigger: el, start: 'top 88%' },
          delay: (i % 3) * 0.08,
        });
      });
    }, root);

    return () => ctx.revert();
  }, [enabled, prefersReduced]);

  return scopeRef;
}
