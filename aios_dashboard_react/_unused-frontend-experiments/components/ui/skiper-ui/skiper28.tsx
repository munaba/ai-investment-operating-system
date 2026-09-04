"use client";

import {
  motion,
  useMotionTemplate,
  useScroll,
  useTransform,
} from "framer-motion";
import ReactLenis from "lenis/react";
import React, { useRef } from "react";

const Skiper28 = () => {
  const targetRef = useRef<HTMLDivElement | null>(null);
  const { scrollYProgress } = useScroll({
    target: targetRef,
  });

  const yMotionValue = useTransform(scrollYProgress, [0, 1], [487, 0]);
  const transform = useMotionTemplate`rotateX(30deg) translateY(${yMotionValue}px) translateZ(10px)`;

  return (
    <ReactLenis root>
      <div
        ref={targetRef}
        className="relative z-0 h-[300vh] w-screen bg-[#f5f4f3] text-black"
      >
        <div className="absolute left-1/2 top-[10%] grid -translate-x-1/2 content-start justify-items-center gap-6 text-center text-black">
          <span className="relative max-w-[12ch] text-xs uppercase leading-tight opacity-40 after:absolute after:left-1/2 after:top-full after:h-16 after:w-px after:bg-gradient-to-b after:from-white after:to-black after:content-['']">
            scroll down to see
          </span>
        </div>
        <div
          className="sticky top-0 mx-auto flex items-center justify-center bg-transparent py-20"
          style={{
            transformStyle: "preserve-3d",
            perspective: "200px",
          }}
        >
          <motion.div
            style={{
              transformStyle: "preserve-3d",
              transform,
            }}
            className="font-geist w-full max-w-4xl text-center text-6xl font-bold tracking-tighter text-[#ff5800]"
          >
            Jatt seeweyan cho langheya chudail takkri jaani badi sohni bhoot
            female takkri .. kehndi jatta .. oye jatta.... kehndi jatta .. metho
            darke ho ja katha .. nai tan aah kar du ... nai tan waah kardu...
            tenu ethe khade khade nu swah kardu ... jatt kehnda hor menu ki
            chahida ... jatt kehnda hor menu ki chahida .. avein gallan-baatan
            vich bohta sama na gva aaja chimbad ja ... mein keha chimbad ja .. .
            aaja chimbad ja ... mein keha chimbad ja .. .
            <div className="absolute bottom-0 left-0 h-[60vh] w-full bg-gradient-to-b from-transparent to-white" />
          </motion.div>
        </div>
      </div>
    </ReactLenis>
  );
};

export { Skiper28 };

/**
 * Skiper 28 PerspectiveTextScroll — React + framer motion + lenis
 *
 * License & Usage:
 * - Free to use and modify in both personal and commercial projects.
 * - Attribution to Skiper UI is required when using the free version.
 * - No attribution required with Skiper UI Pro.
 *
 * Feedback and contributions are welcome.
 *
 * Author: @gurvinder-singh02
 * Website: https://gxuri.me
 * Twitter: https://x.com/Gur__vi
 */
