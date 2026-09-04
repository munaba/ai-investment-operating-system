"use client";

import * as React from "react";
import { useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { List, X } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

/**
 * Awwwards Nav
 *
 * A glassmorphic bottom navigation pill with inline links and a "More" button.
 * Tapping "More" expands the bar upward with a smooth `power4.inOut` motion:
 * the inline links fade out, the button grows to full width, its icon flips to
 * an X, and a multi-column mega-menu reveals inside the expanded panel.
 *
 * Ported from the vanilla "CodeGrid Awwwards Nav" (GSAP) into a single,
 * self-contained, prop-driven React component. Positioning is left to the
 * consumer via `className`, so it works fixed to the viewport or absolutely
 * inside a positioned container.
 */

export interface AwwwardsNavLink {
  label: string;
  href: string;
}

export interface AwwwardsNavColumn {
  /** Column heading shown above its links. */
  title: string;
  /** Links listed under the heading. */
  links: AwwwardsNavLink[];
}

export interface AwwwardsNavProps {
  /** Inline links shown in the collapsed bar. Defaults to a sample set. */
  items?: AwwwardsNavLink[];
  /** Columns revealed in the expanded mega-menu. Defaults to a sample set. */
  columns?: AwwwardsNavColumn[];
  /** Label on the expand/collapse button. Defaults to "More". */
  moreLabel?: string;
  /** Called whenever the panel opens (true) or closes (false). */
  onOpenChange?: (open: boolean) => void;
  /**
   * Extra class names for the root nav. Use this to position it —
   * e.g. `fixed bottom-6 left-1/2 -translate-x-1/2` (default) or
   * `absolute` inside a positioned parent.
   */
  className?: string;
}

const DEFAULT_ITEMS: AwwwardsNavLink[] = [
  { label: "Home", href: "#" },
  { label: "Nominees", href: "#" },
  { label: "Directory", href: "#" },
  { label: "Collections", href: "#" },
];

const DEFAULT_COLUMNS: AwwwardsNavColumn[] = [
  {
    title: "Awards",
    links: [
      { label: "Winners", href: "#" },
      { label: "Site of the Day", href: "#" },
      { label: "Nominees", href: "#" },
    ],
  },
  {
    title: "Inspiration",
    links: [
      { label: "Collections", href: "#" },
      { label: "Elements", href: "#" },
      { label: "Resources", href: "#" },
    ],
  },
  {
    title: "Directory",
    links: [
      { label: "Professionals", href: "#" },
      { label: "Agencies", href: "#" },
      { label: "Freelancers", href: "#" },
    ],
  },
  {
    title: "Market",
    links: [
      { label: "Jobs", href: "#" },
      { label: "New Events", href: "#" },
      { label: "Products", href: "#" },
    ],
  },
];

const COLLAPSED_HEIGHT = 60;
const EXPANDED_HEIGHT = 370;

export function AwwwardsNav({
  items = DEFAULT_ITEMS,
  columns = DEFAULT_COLUMNS,
  moreLabel = "More",
  onOpenChange,
  className,
}: AwwwardsNavProps) {
  const navRef = useRef<HTMLElement>(null);
  const navTopRef = useRef<HTMLDivElement>(null);
  const navItemsRef = useRef<HTMLDivElement>(null);
  const navHomeRef = useRef<HTMLDivElement>(null);

  const openRef = useRef(false);
  const animatingRef = useRef(false);
  const [showClose, setShowClose] = useState(false);

  const onOpenChangeRef = useRef(onOpenChange);
  useEffect(() => {
    onOpenChangeRef.current = onOpenChange;
  }, [onOpenChange]);

  // Establish the collapsed baseline imperatively (matches the source's gsap.set).
  useEffect(() => {
    const nav = navRef.current;
    const navTop = navTopRef.current;
    const navItems = navItemsRef.current;
    const navHome = navHomeRef.current;
    if (!nav || !navTop || !navItems || !navHome) return;

    gsap.set(nav, { height: COLLAPSED_HEIGHT });
    gsap.set(navTop, { opacity: 0, scale: 0.9, display: "none" });
    gsap.set(navItems, { opacity: 1, display: "flex" });
    gsap.set(navHome, { flexGrow: 0 });

    return () => {
      gsap.killTweensOf([nav, navTop, navItems, navHome]);
    };
  }, []);

  const toggle = () => {
    const nav = navRef.current;
    const navTop = navTopRef.current;
    const navItems = navItemsRef.current;
    const navHome = navHomeRef.current;
    if (!nav || !navTop || !navItems || !navHome || animatingRef.current) return;

    animatingRef.current = true;
    const opening = !openRef.current;
    openRef.current = opening;
    onOpenChangeRef.current?.(opening);

    if (opening) {
      gsap.to(nav, { height: EXPANDED_HEIGHT, duration: 0.75, ease: "power4.inOut" });
      gsap.to(navItems, {
        opacity: 0,
        duration: 0.1,
        onComplete: () => gsap.set(navItems, { display: "none" }),
      });
      gsap.to(navHome, {
        flexGrow: 1,
        duration: 0.2,
        ease: "power4.inOut",
        onComplete: () => setShowClose(true),
      });
      gsap.to(navTop, {
        opacity: 1,
        scale: 1,
        duration: 0.3,
        delay: 0.5,
        onStart: () => gsap.set(navTop, { display: "block" }),
        onComplete: () => {
          animatingRef.current = false;
        },
      });
    } else {
      gsap.to(nav, { height: COLLAPSED_HEIGHT, duration: 0.75, ease: "power4.inOut", delay: 0.2 });
      gsap.to(navTop, {
        opacity: 0,
        scale: 0.9,
        duration: 0.2,
        onComplete: () => gsap.set(navTop, { display: "none" }),
      });
      gsap.to(navHome, {
        flexGrow: 0,
        duration: 0.2,
        ease: "power4.inOut",
        onComplete: () => setShowClose(false),
      });
      gsap.to(navItems, {
        opacity: 1,
        duration: 0.2,
        delay: 0.5,
        onStart: () => gsap.set(navItems, { display: "flex" }),
        onComplete: () => {
          animatingRef.current = false;
        },
      });
    }
  };

  return (
    <nav
      ref={navRef}
      className={cn(
        "fixed bottom-6 left-1/2 z-50 -translate-x-1/2",
        "h-[60px] w-[min(680px,92vw)] overflow-hidden rounded-xl border backdrop-blur-xl",
        "border-black/10 bg-white/70 dark:border-white/25 dark:bg-black/75",
        className,
      )}
    >
      {/* Expanded mega-menu, fills the space above the bottom row */}
      <div ref={navTopRef} className="absolute inset-x-0 top-0 bottom-[60px] hidden p-2.5">
        <div className="flex h-full w-full gap-0 rounded-[10px] border border-black/[0.06] bg-black/[0.03] p-5 dark:border-white/[0.06] dark:bg-white/[0.04]">
          {columns.map((col, ci) => (
            <div
              key={col.title}
              className={cn(
                "flex flex-1 flex-col gap-1",
                ci > 0 && "border-l border-dashed border-black/15 pl-4 dark:border-white/20",
              )}
            >
              <div className="mb-3 flex items-center gap-2">
                <span className="h-1 w-1 shrink-0 rounded-full bg-black dark:bg-white" />
                <p className="text-sm text-black/70 dark:text-white/75">{col.title}</p>
              </div>
              {col.links.map((link) => (
                <a
                  key={link.label}
                  href={link.href}
                  className="block py-2 text-sm text-black transition-colors hover:text-black/50 dark:text-white dark:hover:text-white/60"
                >
                  {link.label}
                </a>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Collapsed bottom row: More button + inline items */}
      <div className="absolute inset-x-0 bottom-0 flex h-[60px] gap-1.5 p-2.5">
        <div
          ref={navHomeRef}
          role="button"
          tabIndex={0}
          aria-expanded={showClose}
          aria-label={showClose ? "Close menu" : "Open menu"}
          onClick={toggle}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              toggle();
            }
          }}
          className={cn(
            "flex shrink-0 cursor-pointer select-none items-center justify-center gap-2.5 rounded-[10px] border px-5 text-sm transition-colors",
            "border-black/10 bg-black/[0.04] text-neutral-600 hover:bg-black/[0.08] hover:text-black",
            "dark:border-white/10 dark:bg-white/[0.06] dark:text-neutral-300 dark:hover:bg-white/[0.12] dark:hover:text-white",
            showClose && "bg-black/[0.08] text-black dark:bg-white/[0.12] dark:text-white",
          )}
        >
          {showClose ? (
            <X weight="light" className="h-4 w-4 text-black dark:text-white" />
          ) : (
            <List weight="light" className="h-4 w-4 text-black dark:text-white" />
          )}
          <span>{moreLabel}</span>
        </div>

        <div ref={navItemsRef} className="flex min-w-0 flex-[4] items-center gap-1.5">
          {items.map((item) => (
            <div
              key={item.label}
              className="flex h-full flex-1 items-center justify-center rounded-[10px] border border-black/15 transition-colors hover:border-black/40 dark:border-white/20 dark:hover:border-white/50"
            >
              <a
                href={item.href}
                className="px-2 text-center text-sm text-neutral-600 transition-colors hover:text-black dark:text-neutral-400 dark:hover:text-white"
              >
                {item.label}
              </a>
            </div>
          ))}
        </div>
      </div>
    </nav>
  );
}

export default AwwwardsNav;
