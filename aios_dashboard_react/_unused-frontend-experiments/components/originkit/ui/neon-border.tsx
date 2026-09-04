"use client";

import * as React from "react";
import { useEffect, useRef, useState } from "react";

type Movement = "continuous" | "step";

type Props = {
    color?: string;
    rounded?: number;
    thickness?: number;
    borderSize?: number;
    glow?: number;
    movement?: Movement;
    speed?: number;
    style?: React.CSSProperties;
};

const DEFAULTS = {
    color: "#CC9149",
    rounded: 24,
    thickness: 6,
    borderSize: 50,
    glow: 100,
    movement: "continuous" as const,
    speed: 16,
};

const EDGE_COPIES = 2;
const GLOW_LAYERS = [
    { blur: 8, opacity: 0.5, reach: 0.3 },
    { blur: 15, opacity: 0.3, reach: 0.6 },
    { blur: 57, opacity: 0.18, reach: 1 },
];
const MAX_GLOW_BLUR = Math.max(...GLOW_LAYERS.map((l) => l.blur));
const MAX_GLOW_REACH = 36;

function withAlpha(input: string, alpha: number) {
    const a = Math.max(0, Math.min(1, alpha));
    if (typeof input !== "string") return `rgba(0,0,0,${a})`;
    const s = input.trim();

    const hex = s.match(/^#([0-9a-f]{3,8})$/i);
    if (hex) {
        let h = hex[1];
        if (h.length === 3 || h.length === 4) {
            h = h
                .split("")
                .map((c) => c + c)
                .join("");
        }
        const n = parseInt(h.slice(0, 6), 16);
        if (!Number.isFinite(n)) return `rgba(0,0,0,${a})`;
        return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
    }

    const rgb = s.match(/^rgba?\(([^)]+)\)/i);
    if (rgb) {
        const parts = rgb[1].split(",").map((v) => parseFloat(v));
        if (parts.length >= 3 && parts.slice(0, 3).every(Number.isFinite)) {
            return `rgba(${parts[0]},${parts[1]},${parts[2]},${a})`;
        }
    }
    return `rgba(0,0,0,${a})`;
}

function perimeterPoint(u: number, w: number, h: number): [number, number] {
    const d = (((u % 1) + 1) % 1) * 2 * (w + h);
    if (d < w) return [d, 0];
    if (d < w + h) return [w, d - w];
    if (d < w * 2 + h) return [w - (d - w - h), h];
    return [0, h - (d - w * 2 - h)];
}

function cornerLap(k: number, w: number, h: number) {
    const p = 2 * (w + h);
    const at = [0, w / p, (w + h) / p, (w * 2 + h) / p];
    return Math.floor(k / 4) + at[((k % 4) + 4) % 4];
}

function perimeterAngle(u: number, w: number, h: number) {
    const [x, y] = perimeterPoint(u, w, h);
    return (Math.atan2(x - w / 2, h / 2 - y) * 180) / Math.PI;
}

const ARC_SAMPLES = 24;
const MIN_ARC = 0.015;

function buildArc(
    lap: number,
    lengthPct: number,
    w: number,
    h: number,
    color: string
) {
    const fw = w > 0 ? w : 100;
    const fh = h > 0 ? h : 100;

    const len = Math.max(0, Math.min(100, lengthPct));
    const span = Math.max(MIN_ARC, (len / 100) * 0.5);
    const solidT = len / 100;

    const stops: string[] = [];
    let base = 0;
    let prev = 0;
    let acc = 0;

    for (let i = 0; i <= ARC_SAMPLES; i++) {
        const f = i / ARC_SAMPLES;
        const angle = perimeterAngle(lap + (f - 0.5) * span, fw, fh);
        if (i === 0) {
            base = angle;
        } else {
            let d = angle - prev;
            while (d > 180) d -= 360;
            while (d < -180) d += 360;
            acc += d;
        }
        prev = angle;

        const t = Math.abs(f - 0.5) * 2;
        const k =
            solidT >= 1 ? 1 : t <= solidT ? 1 : 1 - (t - solidT) / (1 - solidT);
        stops.push(
            `${withAlpha(color, k * k * (3 - 2 * k))} ${acc.toFixed(2)}deg`
        );
    }

    const end = acc.toFixed(2);
    stops.push(`${withAlpha(color, 0)} ${end}deg`);
    stops.push(`${withAlpha(color, 0)} 360deg`);

    return `conic-gradient(from ${base.toFixed(2)}deg at 50% 50%, ${stops.join(
        ", "
    )})`;
}

const SLOWEST_CYCLE = 30;
const FASTEST_CYCLE = 4;
const SLOWEST_STEP = 3;
const FASTEST_STEP = 0.35;
const STEP_EASE = [0.72, 0.16, 0.18, 1.05];
const GLIDE_EASE = [0.65, 0, 0.35, 1];

function makeEaseFn(pts: number[]) {
    const [x1, y1, x2, y2] = pts;
    if (x1 === y1 && x2 === y2) return (t: number) => t;
    const bez = (a: number, b: number, t: number) => {
        const u = 1 - t;
        return 3 * u * u * t * a + 3 * u * t * t * b + t * t * t;
    };
    return (t: number) => {
        const x = Math.max(0, Math.min(1, t));
        let s = x;
        for (let i = 0; i < 8; i++) {
            const cx = bez(x1, x2, s) - x;
            const u = 1 - s;
            const dx =
                3 * u * u * x1 + 6 * u * s * (x2 - x1) + 3 * s * s * (1 - x2);
            if (Math.abs(dx) < 1e-6) break;
            s -= cx / dx;
            s = Math.max(0, Math.min(1, s));
        }
        return bez(y1, y2, s);
    };
}

const stepEase = makeEaseFn(STEP_EASE);
const glideEase = makeEaseFn(GLIDE_EASE);

const BAND_MASK: React.CSSProperties = {
    WebkitMaskImage: "linear-gradient(#fff 0 0), linear-gradient(#fff 0 0)",
    WebkitMaskClip: "content-box, border-box",
    WebkitMaskComposite: "xor",
    maskImage: "linear-gradient(#fff 0 0), linear-gradient(#fff 0 0)",
    maskClip: "content-box, border-box",
    maskComposite: "exclude",
};

export default function NeonBorder(props: Props) {
    const {
        color = DEFAULTS.color,
        rounded = DEFAULTS.rounded,
        thickness = DEFAULTS.thickness,
        borderSize = DEFAULTS.borderSize,
        glow = DEFAULTS.glow,
        movement = DEFAULTS.movement,
        speed = DEFAULTS.speed,
        style,
    } = props;

    const groupARef = useRef<HTMLDivElement>(null);
    const groupBRef = useRef<HTMLDivElement>(null);

    const live = useRef({ speed, movement, borderSize, color });
    live.current = { speed, movement, borderSize, color };

    const rootRef = useRef<HTMLDivElement>(null);
    const sizeRef = useRef({ w: 0, h: 0 });
    const [size, setSize] = useState({ w: 0, h: 0 });

    useEffect(() => {
        const el = rootRef.current;
        if (!el || typeof ResizeObserver === "undefined") return;
        const ro = new ResizeObserver(() => {
            const r = el.getBoundingClientRect();
            if (r.width === sizeRef.current.w && r.height === sizeRef.current.h)
                return;
            sizeRef.current = { w: r.width, h: r.height };
            setSize(sizeRef.current);
        });
        ro.observe(el);
        return () => ro.disconnect();
    }, []);

    useEffect(() => {
        let raf = 0;
        let last = performance.now();
        let lap = 0;
        let corner = 0;
        let stepT = 0;

        const frame = (now: number) => {
            const dt = Math.min(0.05, Math.max(0, (now - last) / 1000));
            last = now;
            const p = live.current;
            const s = Math.max(0, Math.min(20, p.speed));

            if (s > 0) {
                const step = p.movement === "step";
                const beat = step
                    ? SLOWEST_STEP +
                      ((FASTEST_STEP - SLOWEST_STEP) * (s - 1)) / 19
                    : (SLOWEST_CYCLE +
                          ((FASTEST_CYCLE - SLOWEST_CYCLE) * (s - 1)) / 19) /
                      4;

                stepT += dt / beat;
                while (stepT >= 1) {
                    stepT -= 1;
                    corner += 1;
                }
                const eased = step
                    ? stepEase(Math.min(1, stepT * 2))
                    : glideEase(stepT);

                const { w, h } = sizeRef.current;
                const fw = w > 0 ? w : 100;
                const fh = h > 0 ? h : 100;
                const from = cornerLap(corner, fw, fh);
                const to = cornerLap(corner + 1, fw, fh);
                lap = from + (to - from) * eased;

                const a = groupARef.current;
                if (a) {
                    a.style.setProperty(
                        "--arc",
                        buildArc(lap, p.borderSize, w, h, p.color)
                    );
                }
                const b = groupBRef.current;
                if (b) {
                    b.style.setProperty(
                        "--arc",
                        buildArc(lap + 0.5, p.borderSize, w, h, p.color)
                    );
                }
            }

            raf = requestAnimationFrame(frame);
        };
        raf = requestAnimationFrame(frame);

        return () => cancelAnimationFrame(raf);
    }, []);

    const thick = Math.max(1, Math.min(10, thickness));

    const radius =
        (Math.max(0, Math.min(100, rounded)) / 100) *
        (Math.min(size.w, size.h) / 2);

    const amount = Math.max(0, Math.min(100, glow)) / 100;

    const ringAt = (share: number) => thick + amount * MAX_GLOW_REACH * share;
    const glowOuter = 10 + MAX_GLOW_REACH + MAX_GLOW_BLUR * 2;

    const band = (r: number, offset = 0) => (
        <div
            style={{
                position: "absolute",
                inset: offset - r,
                boxSizing: "border-box",
                padding: r,
                borderRadius: radius > 0 ? radius + r : 0,
                background: "var(--arc)",
                ...BAND_MASK,
            }}
        />
    );

    const glowLayer = (
        key: string,
        r: number,
        blurPx: number,
        opacity: number
    ) => (
        <div
            key={key}
            style={{
                position: "absolute",
                inset: -glowOuter,
                boxSizing: "border-box",
                padding: glowOuter,
                borderRadius: radius > 0 ? radius + glowOuter : 0,
                opacity,
                mixBlendMode: "plus-lighter",
                filter: blurPx ? `blur(${blurPx.toFixed(1)}px)` : "none",
                WebkitFilter: blurPx ? `blur(${blurPx.toFixed(1)}px)` : "none",
                ...BAND_MASK,
            }}
        >
            {band(r, glowOuter)}
        </div>
    );

    const glowGroup = (start: number, ref: React.Ref<HTMLDivElement>) => (
        <div
            ref={ref}
            style={
                {
                    position: "absolute",
                    inset: 0,
                    overflow: "visible",
                    pointerEvents: "none",
                    "--arc": buildArc(start, borderSize, size.w, size.h, color),
                } as React.CSSProperties
            }
        >
            {amount > 0 &&
                GLOW_LAYERS.map((l, i) =>
                    glowLayer(`glow-${i}`, ringAt(l.reach), l.blur, l.opacity)
                )}
            {Array.from({ length: EDGE_COPIES }).map((_, i) => (
                <div
                    key={`edge-${i}`}
                    style={{
                        position: "absolute",
                        inset: 0,
                        mixBlendMode: "plus-lighter",
                    }}
                >
                    {band(thick)}
                </div>
            ))}
        </div>
    );

    return (
        <div
            ref={rootRef}
            style={{
                position: "relative",
                width: "100%",
                height: "100%",
                flexShrink: 0,
                borderRadius: radius,
                ...style,
            }}
        >
            {glowGroup(0, groupARef)}
            {glowGroup(0.5, groupBRef)}
        </div>
    );
}