"use client";

import React, { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

// Constants for wave animation behavior
const WAVE_THRESH = 3;
const CHAR_MULT = 3;
const ANIM_STEP = 40;
const WAVE_BUF = 5;

export interface AsciiGlitchRippleProps extends React.AnchorHTMLAttributes<HTMLAnchorElement> {
  /**
   * The text to display and animate.
   */
  children: string;
  /**
   * The HTML element or component to render as.
   * @default "a"
   */
  as?: any;
  /**
   * Additional CSS classes.
   */
  className?: string;
  /**
   * Duration of each ripple wave in milliseconds.
   * @default 1000
   */
  dur?: number;
  /**
   * Character set to scramble through during the ripple wave.
   * @default '.,·-─~+:;=*π""┐┌┘┴┬╗╔╝╚╬╠╣╩╦║░▒▓█▄▀▌▐■!?&#$@0123456789*'
   */
  chars?: string;
  /**
   * Whether to preserve space characters or scramble them too.
   * @default true
   */
  preserveSpaces?: boolean;
  /**
   * The spread of the ripple wave. Larger numbers mean wider waves.
   * @default 1.0
   */
  spread?: number;
  [key: string]: any;
}

export function AsciiGlitchRipple({
  children,
  as = "a",
  className,
  dur = 1000,
  chars = '.,·-─~+:;=*π""┐┌┘┴┬╗╔╝╚╬╠╣╩╦║░▒▓█▄▀▌▐■!?&#$@0123456789*',
  preserveSpaces = true,
  spread = 1.0,
  ...props
}: AsciiGlitchRippleProps) {
  const Component = as;
  const elRef = useRef<any>(null);

  // Use a mutable ref to store animation state, preventing unnecessary React renders
  const stateRef = useRef({
    origTxt: children,
    origChars: children.split(""),
    isAnim: false,
    cursorPos: 0,
    waves: [] as Array<{ startPos: number; startTime: number; id: number }>,
    animId: null as number | null,
    isHover: false,
    origW: null as number | null,
    dur,
    chars,
    preserveSpaces,
    spread,
  });

  // Keep internal mutable state updated when props change
  useEffect(() => {
    stateRef.current.origTxt = children;
    stateRef.current.origChars = children.split("");
    stateRef.current.dur = dur;
    stateRef.current.chars = chars;
    stateRef.current.preserveSpaces = preserveSpaces;
    stateRef.current.spread = spread;

    // Reset layout widths if text changes dynamically
    if (stateRef.current.origW !== null && elRef.current) {
      elRef.current.style.width = "";
      stateRef.current.origW = null;
    }

    if (!stateRef.current.isAnim && elRef.current) {
      elRef.current.textContent = children;
    }
  }, [children, dur, chars, preserveSpaces, spread]);

  useEffect(() => {
    const el = elRef.current;
    if (!el) return;

    // Initialize content
    el.textContent = children;

    const updateCursorPos = (e: MouseEvent) => {
      const rect = el.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const len = stateRef.current.origTxt.length;
      const pos = Math.round((x / rect.width) * len);
      stateRef.current.cursorPos = Math.max(0, Math.min(pos, len - 1));
    };

    const stop = () => {
      el.textContent = stateRef.current.origTxt;
      el.classList.remove("as");

      // Restore natural width layout
      if (stateRef.current.origW !== null) {
        el.style.width = "";
        stateRef.current.origW = null;
      }
      stateRef.current.isAnim = false;
      if (stateRef.current.animId) {
        cancelAnimationFrame(stateRef.current.animId);
        stateRef.current.animId = null;
      }
    };

    const start = () => {
      if (stateRef.current.isAnim) return;

      // Lock current width to prevent layout shifts during ASCII scrambling
      if (stateRef.current.origW === null) {
        stateRef.current.origW = el.getBoundingClientRect().width;
        el.style.width = `${stateRef.current.origW}px`;
      }

      stateRef.current.isAnim = true;
      el.classList.add("as");

      const animate = () => {
        const t = Date.now();

        // Evict finished waves
        stateRef.current.waves = stateRef.current.waves.filter(
          (w) => t - w.startTime < stateRef.current.dur
        );

        if (stateRef.current.waves.length === 0) {
          stop();
          return;
        }

        // Apply visual scramble
        el.textContent = genScrambledTxt(t);
        stateRef.current.animId = requestAnimationFrame(animate);
      };

      stateRef.current.animId = requestAnimationFrame(animate);
    };

    const startWave = () => {
      stateRef.current.waves.push({
        startPos: stateRef.current.cursorPos,
        startTime: Date.now(),
        id: Math.random(),
      });

      if (!stateRef.current.isAnim) start();
    };

    const calcWaveEffect = (charIdx: number, t: number) => {
      let shouldAnim = false;
      let resultChar = stateRef.current.origChars[charIdx];

      for (const w of stateRef.current.waves) {
        const age = t - w.startTime;
        const prog = Math.min(age / stateRef.current.dur, 1);
        const dist = Math.abs(charIdx - w.startPos);
        const maxDist = Math.max(w.startPos, stateRef.current.origChars.length - w.startPos - 1);
        const rad = (prog * (maxDist + WAVE_BUF)) / stateRef.current.spread;

        if (dist <= rad) {
          shouldAnim = true;
          const intens = Math.max(0, rad - dist);

          // Wave distortion characters
          if (intens <= WAVE_THRESH && intens > 0) {
            const index =
              (dist * CHAR_MULT + Math.floor(age / ANIM_STEP)) % stateRef.current.chars.length;
            resultChar = stateRef.current.chars[index];
          }
        }
      }

      return { shouldAnim, char: resultChar };
    };

    const genScrambledTxt = (t: number) =>
      stateRef.current.origChars
        .map((char, i) => {
          if (stateRef.current.preserveSpaces && char === " ") return " ";
          const res = calcWaveEffect(i, t);
          return res.shouldAnim ? res.char : char;
        })
        .join("");

    const handleEnter = (e: MouseEvent) => {
      stateRef.current.isHover = true;
      updateCursorPos(e);
      startWave();
    };

    const handleMove = (e: MouseEvent) => {
      if (!stateRef.current.isHover) return;
      const old = stateRef.current.cursorPos;
      updateCursorPos(e);
      if (stateRef.current.cursorPos !== old) startWave();
    };

    const handleLeave = () => {
      stateRef.current.isHover = false;
    };

    el.addEventListener("mouseenter", handleEnter);
    el.addEventListener("mousemove", handleMove);
    el.addEventListener("mouseleave", handleLeave);

    return () => {
      el.removeEventListener("mouseenter", handleEnter);
      el.removeEventListener("mousemove", handleMove);
      el.removeEventListener("mouseleave", handleLeave);
      if (stateRef.current.animId) {
        cancelAnimationFrame(stateRef.current.animId);
      }
    };
  }, [children]);

  return (
    <Component
      ref={elRef}
      className={cn(
        "cursor-pointer select-none relative inline-block transition-colors duration-200",
        className
      )}
      {...props}
    />
  );
}

export default AsciiGlitchRipple;
