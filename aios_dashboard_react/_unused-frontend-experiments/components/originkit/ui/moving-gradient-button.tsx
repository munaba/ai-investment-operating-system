"use client";

import * as React from "react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { motion, useAnimate, type Transition } from "framer-motion";

const radiusFromPercent = (w: number, h: number, pct: number) =>
  (Math.min(w, h) / 2) * (Math.max(0, Math.min(100, pct)) / 100);

const useIsoLayoutEffect =
  typeof window !== "undefined" ? useLayoutEffect : useEffect;

type BandWidths = { top: number; right: number; bottom: number; left: number };

const MAX_BAND_WIDTH = 30;

const num = (v: any) => {
  const parsed = parseFloat(String(v ?? ""));
  return Number.isFinite(parsed) && parsed > 0
    ? Math.min(parsed, MAX_BAND_WIDTH)
    : 0;
};

const bandWidthsOf = (b: any): BandWidths => {
  const fused = num(b?.borderWidth);
  return {
    top: b?.borderTopWidth !== undefined ? num(b.borderTopWidth) : fused,
    right:
      b?.borderRightWidth !== undefined ? num(b.borderRightWidth) : fused,
    bottom:
      b?.borderBottomWidth !== undefined
        ? num(b.borderBottomWidth)
        : fused,
    left: b?.borderLeftWidth !== undefined ? num(b.borderLeftWidth) : fused,
  };
};

const borderColorOf = (b: any): string => b?.borderColor ?? "transparent";

const BAND_MASK: React.CSSProperties = {
  maskImage: "linear-gradient(#000 0 0), linear-gradient(#000 0 0)",
  maskClip: "border-box, content-box",
  maskComposite: "exclude",
  WebkitMaskImage: "linear-gradient(#000 0 0), linear-gradient(#000 0 0)",
  WebkitMaskClip: "border-box, content-box",
  WebkitMaskComposite: "xor",
} as React.CSSProperties;

const DEG_PER_UNIT = 36;
const PX_PER_UNIT = 60;

const TRAIL_LAYERS = 6;

const perimeterOf = (w: number, h: number, r: number) => {
  const rr = Math.max(0, Math.min(r, w / 2, h / 2));
  return 2 * (w - 2 * rr) + 2 * (h - 2 * rr) + 2 * Math.PI * rr;
};

const outlinePath = (w: number, h: number, r: number) => {
  const rr = Math.max(0, Math.min(r, w / 2, h / 2));
  return (
    `M ${rr} 0 H ${w - rr} A ${rr} ${rr} 0 0 1 ${w} ${rr}` +
    ` V ${h - rr} A ${rr} ${rr} 0 0 1 ${w - rr} ${h}` +
    ` H ${rr} A ${rr} ${rr} 0 0 1 0 ${h - rr}` +
    ` V ${rr} A ${rr} ${rr} 0 0 1 ${rr} 0 Z`
  );
};

export type IconConfig = {
  type?: "symbol" | "image";
  symbol?: string;
  image?: string | { src?: string; srcSet?: string; alt?: string };
  color?: string;
  hoverColor?: string;
  size?: number;
  padding?: number;
  rounded?: number;
  side?: "left" | "right";
};

const DEFAULT_TRANSITION: Transition = {
  type: "tween",
  ease: "easeInOut",
  duration: 0.25,
};

type Colors = {
  fill?: string;
  textColor?: string;
  hoverFill?: string;
  hoverTextColor?: string;
};

type Props = {
  colors?: Colors;
  label?: string;
  font?: Record<string, any>;
  showText?: boolean;
  padding?: string;
  rounded?: number;
  fill?: string;
  textColor?: string;
  addIcon?: boolean;
  icon?: IconConfig;
  gap?: number;
  border?: any;
  hover?: {
    fill?: string;
    textColor?: string;
  };
  stroke?: {
    headColor?: string;
    color?: string;
    direction?: "cw" | "ccw";
    movement?: "step" | "continuous";
    count?: number;
    trail?: number;
    speed?: number;
  };
  link?: string;
  transition?: Transition;
  newTab?: boolean;
  style?: React.CSSProperties;
};

export default function MovingGradientButton(props: Props) {
  const {
    label = "MOVING GRADIENT",
    font = {
      fontFamily: "Inter",
      variant: "Regular",
      fontWeight: 500,
      fontSize: 40,
      lineHeight: "1.5em",
      letterSpacing: "0em",
      textAlign: "left",
    },
    showText = true,
    padding = "40px 64px 40px 64px",
    rounded = 100,
    fill: fillProp,
    textColor: textColorProp,
    colors = {
      fill: "#000000",
      hoverFill: "#000000",
      textColor: "#FFFFFF",
      hoverTextColor: "#FFFFFF",
    },
    addIcon = false,
    icon = {
      side: "left",
      size: 24,
      type: "symbol",
      color: "#FFFFFF",
      image: "",
      symbol: "\u2192",
      padding: 0,
      rounded: 0,
      hoverColor: "#CCC30E",
    },
    gap = 12,
    border = {
      borderWidth: 6,
      borderStyle: "solid",
      borderColor: "#FFFFFF",
      borderTopWidth: 6,
      borderLeftWidth: 6,
      borderRightWidth: 6,
      borderBottomWidth: 6,
    },
    hover = {},
    stroke = {
      color: "#3600FF",
      count: 2,
      speed: 22,
      trail: 100,
      movement: "step",
      direction: "cw",
      headColor: "#00FF94",
    },
    link = "",
    transition = {
      type: "tween",
      stiffness: 800,
      damping: 60,
      mass: 1,
      ease: "easeInOut",
      duration: 0.25,
    },
    newTab = true,
    style,
  } = props;

  const fill = colors?.fill ?? fillProp ?? "#000000";
  const textColor = colors?.textColor ?? textColorProp ?? "#FFFFFF";
  const {
    fill: hoverFill = colors?.hoverFill ?? "#1A1A1A",
    textColor: hoverTextColor = colors?.hoverTextColor ?? "#CCC30E",
  } = hover;

  const {
    headColor: strokeHeadColor = "#CCC30E",
    color: strokeColor = "#FC731C",
    direction = "cw",
    movement = "step",
    count = 4,
    trail = 66,
    speed: speedPct = 50,
  } = stroke;

  const speed = 2 * (Math.max(0, Math.min(100, Math.round(speedPct))) / 50);

  const [scope, animate] = useAnimate();

  const [radiusBox, setRadiusBox] = useState({ w: 0, h: 0 });
  useIsoLayoutEffect(() => {
    const el = scope.current as HTMLElement | null;
    if (!el) return;
    const read = () =>
      setRadiusBox((prev) =>
        prev.w === el.offsetWidth && prev.h === el.offsetHeight
          ? prev
          : { w: el.offsetWidth, h: el.offsetHeight }
      );
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, [scope]);
  const radiusPx = radiusFromPercent(radiusBox.w, radiusBox.h, rounded);
  const glowRef = useRef<HTMLDivElement | null>(null);
  const coverRef = useRef<HTMLDivElement | null>(null);
  const labelRef = useRef<HTMLSpanElement | null>(null);
  const iconRef = useRef<HTMLSpanElement | null>(null);
  const [side, setSide] = useState(0);
  const [box, setBox] = useState({ w: 0, h: 0 });
  const dashRefs = useRef<Array<SVGPathElement | null>>([]);

  const hovered = useRef(false);
  const focused = useRef(false);
  const lit = useRef(false);

  const live = useRef({
    degPerSec: 0,
    pxPerSec: 0,
    sign: 1,
    movement,
    lens: [] as number[],
  });
  live.current.movement = movement;
  const sign = direction === "ccw" ? -1 : 1;
  live.current.sign = sign;
  live.current.degPerSec = Math.max(0, speed) * DEG_PER_UNIT * sign;
  live.current.pxPerSec = Math.max(0, speed) * PX_PER_UNIT * sign;

  useEffect(() => {
    const el = scope.current as HTMLElement | null;
    if (!el) return;
    const measure = () => {
      const w = el.offsetWidth;
      const h = el.offsetHeight;
      setSide(Math.ceil(Math.hypot(w, h) * 1.02));
      setBox((prev) => (prev.w === w && prev.h === h ? prev : { w, h }));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [scope]);

  useEffect(() => {
    let raf = 0;
    let last = 0;
    let angle = 0;
    let head = 0;
    const tick = (t: number) => {
      if (!last) last = t;
      const dt = (t - last) / 1000;
      last = t;
      const l = live.current;

      if (l.movement === "continuous") {
        head += l.pxPerSec * dt;
        for (let i = 0; i < dashRefs.current.length; i++) {
          const el = dashRefs.current[i];
          const len = l.lens[i];
          if (el && len !== undefined)
            el.style.strokeDashoffset = String(
              l.sign >= 0 ? len - head : -head
            );
        }
      } else {
        angle = (angle + l.degPerSec * dt) % 360;
        const g = glowRef.current;
        if (g) g.style.transform = `rotate(${angle}deg)`;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  const {
    type: iconKind = "symbol",
    symbol: iconSymbol = "\u2192",
    image,
    color: iconColor = "#FFFFFF",
    hoverColor: iconHoverColor = "#CCC30E",
    side: iconSide = "left",
    size: iconSize = 24,
    padding: iconPaddingProp = 0,
    rounded: iconRounded = 0,
  } = icon;
  const iconSrc =
    typeof image === "string" ? image : image && image.src ? image.src : "";
  const iconMode = iconKind === "image" && iconSrc ? "image" : "symbol";
  const iconPx = Math.max(1, Math.round(iconSize));
  const iconPadPx = Math.max(0, Math.round(iconPaddingProp));
  const iconRadius = radiusFromPercent(iconPx, iconPx, iconRounded);
  const gapPx = Math.max(0, Math.round(gap));
  const hasIcon = addIcon;

  const paint = useCallback(
    (want: boolean, instant: boolean) => {
      const t: any = instant ? { duration: 0 } : transition;
      if (scope.current)
        animate(
          scope.current,
          { backgroundColor: want ? hoverFill : fill } as any,
          t
        );
      if (coverRef.current)
        animate(coverRef.current, { opacity: want ? 1 : 0 } as any, t);
      if (labelRef.current)
        animate(
          labelRef.current,
          { color: want ? hoverTextColor : textColor } as any,
          t
        );
      if (iconRef.current)
        animate(
          iconRef.current,
          { color: want ? iconHoverColor : iconColor } as any,
          t
        );
    },
    [
      animate,
      scope,
      transition,
      fill,
      hoverFill,
      textColor,
      hoverTextColor,
      iconColor,
      iconHoverColor,
    ]
  );

  const sync = useCallback(() => {
    const want = hovered.current || focused.current;
    if (want === lit.current) return;
    lit.current = want;
    paint(want, false);
  }, [paint]);

  useEffect(() => {
    paint(lit.current, true);
  }, [paint]);

  const onPointerEnter = useCallback(() => {
    hovered.current = true;
    sync();
  }, [sync]);

  const onPointerLeave = useCallback(() => {
    hovered.current = false;
    sync();
  }, [sync]);

  const onFocus = useCallback(
    (e: React.FocusEvent<HTMLElement>) => {
      let visible = true;
      try {
        visible = e.currentTarget.matches(":focus-visible");
      } catch {
        // :focus-visible unsupported — treat it as a real focus
      }
      if (!visible) return;
      focused.current = true;
      sync();
    },
    [sync]
  );

  const onBlur = useCallback(() => {
    focused.current = false;
    sync();
  }, [sync]);

  const n = Math.max(1, Math.round(count));
  const period = 360 / n;
  const tailDeg = Math.max(
    0.5,
    (period * Math.max(0, Math.min(100, trail))) / 100
  );
  const knee = (tailDeg * 0.45).toFixed(2);
  const gradient =
    direction === "cw"
      ? `repeating-conic-gradient(from 0deg, transparent 0deg, transparent ${(period - tailDeg).toFixed(2)}deg, ${strokeColor} ${(period - tailDeg * 0.45).toFixed(2)}deg, ${strokeHeadColor} ${period.toFixed(2)}deg)`
      : `repeating-conic-gradient(from 0deg, ${strokeHeadColor} 0deg, ${strokeColor} ${knee}deg, transparent ${tailDeg.toFixed(2)}deg, transparent ${period.toFixed(2)}deg)`;

  const perimeter = perimeterOf(box.w, box.h, radiusPx);
  const slice = perimeter > 0 ? perimeter / n : 0;
  const trailLen = Math.max(1, (slice * Math.max(0, Math.min(100, trail))) / 100);
  const dashLayers = React.useMemo(() => {
    const out: Array<{ len: number; color: string; opacity: number }> = [];
    for (let i = 0; i < TRAIL_LAYERS; i++) {
      const len = (trailLen * (TRAIL_LAYERS - i)) / TRAIL_LAYERS;
      out.push({
        len,
        color: i === TRAIL_LAYERS - 1 ? strokeHeadColor : strokeColor,
        opacity: (i + 1) / TRAIL_LAYERS,
      });
    }
    return out;
  }, [trailLen, strokeColor, strokeHeadColor]);
  live.current.lens = dashLayers.map((d) => d.len);

  const coverGradient = `conic-gradient(from 0deg, ${strokeColor}, ${strokeHeadColor}, ${strokeColor}, ${strokeHeadColor}, ${strokeColor})`;

  const band = bandWidthsOf(border);
  const bandPadding = `${band.top}px ${band.right}px ${band.bottom}px ${band.left}px`;
  const fontStyles = (font ?? {}) as React.CSSProperties;
  const isLink = typeof link === "string" && link.length > 0;
  const Root: any = isLink ? motion.a : motion.button;
  const rootProps = {
    "aria-label": showText ? undefined : label || undefined,
    ...(isLink
      ? {
          href: link,
          target: newTab ? "_blank" : undefined,
          rel: newTab ? "noopener noreferrer" : undefined,
        }
      : { type: "button" }),
  };

  return (
    <Root
      ref={scope}
      {...rootProps}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
      onFocus={onFocus}
      onBlur={onBlur}
      style={{
        position: "relative",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: hasIcon && showText ? gapPx : 0,
        flexDirection: iconSide === "right" ? "row-reverse" : "row",
        minWidth: 80,
        minHeight: 40,
        padding,
        borderRadius: radiusPx,
        border: "none",
        backgroundColor: fill,
        cursor: "pointer",
        textDecoration: "none",
        WebkitTapHighlightColor: "transparent",
        ...style,
      }}
    >
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          inset: 0,
          boxSizing: "border-box",
          padding: bandPadding,
          borderRadius: radiusPx,
          zIndex: 0,
          pointerEvents: "none",
          ...BAND_MASK,
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: borderColorOf(border),
          }}
        />

        {movement !== "continuous" && (
          <div
            ref={glowRef}
            style={{
              position: "absolute",
              top: "50%",
              left: "50%",
              width: side,
              height: side,
              marginTop: -side / 2,
              marginLeft: -side / 2,
              background: gradient,
            }}
          />
        )}

        {movement === "continuous" && box.w > 0 && box.h > 0 && (
          <svg
            width="100%"
            height="100%"
            viewBox={`0 0 ${box.w} ${box.h}`}
            preserveAspectRatio="none"
            style={{ position: "absolute", inset: 0, overflow: "visible" }}
          >
            {dashLayers.map((d, i) => (
              <path
                key={i}
                ref={(el) => {
                  dashRefs.current[i] = el;
                }}
                d={outlinePath(box.w, box.h, radiusPx)}
                fill="none"
                stroke={d.color}
                strokeOpacity={d.opacity}
                strokeWidth={
                  2 * Math.max(band.top, band.right, band.bottom, band.left) +
                  2
                }
                strokeDasharray={`${d.len} ${Math.max(0.01, slice - d.len)}`}
                strokeLinecap="butt"
              />
            ))}
          </svg>
        )}

        <div
          ref={coverRef}
          style={{
            position: "absolute",
            inset: 0,
            background: coverGradient,
            opacity: 0,
          }}
        />
      </div>

      {hasIcon &&
        (iconMode === "image" ? (
          <img
            src={iconSrc}
            alt=""
            aria-hidden
            draggable={false}
            style={{
              position: "relative",
              zIndex: 1,
              width: iconPx,
              height: iconPx,
              margin: iconPadPx,
              objectFit: iconRadius > 0 ? "cover" : "contain",
              borderRadius: Math.min(iconRadius, iconPx / 2),
              display: "block",
              flex: "none",
              pointerEvents: "none",
            }}
          />
        ) : (
          <span
            ref={iconRef}
            aria-hidden
            style={{
              position: "relative",
              zIndex: 1,
              fontSize: iconPx,
              margin: iconPadPx,
              lineHeight: 1,
              color: iconColor,
              flex: "none",
              pointerEvents: "none",
            }}
          >
            {iconSymbol}
          </span>
        ))}

      {showText && (
        <span
          ref={labelRef}
          style={{
            position: "relative",
            zIndex: 1,
            color: textColor,
            whiteSpace: "nowrap",
            ...fontStyles,
          }}
        >
          {label}
        </span>
      )}
    </Root>
  );
}