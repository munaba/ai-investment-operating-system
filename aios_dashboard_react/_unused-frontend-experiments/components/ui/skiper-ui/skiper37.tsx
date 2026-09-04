"use client";

import NumberFlow from "@number-flow/react";
import { AnimatePresence, motion, useSpring } from "framer-motion";
import { animate, useMotionValue } from "framer-motion";
import { Plus } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import { useInView } from "react-intersection-observer";

const Skiper37 = () => {
  return (
    <section className="relative h-[calc(100vh-1rem)] w-full snap-y snap-mandatory overflow-y-scroll bg-[#f5f4f3]">
      <div className="snap-start">
        <AnimatedNumber_001 />
      </div>
      <div className="snap-start">
        <AnimatedNumber_002 />
      </div>
      <div className="snap-start">
        <AnimatedNumber_003 />
      </div>
      <div className="snap-start">
        <AnimatedNumber_004 />
      </div>
    </section>
  );
};

const AnimatedNumber_001 = () => {
  const [isPaused, setIsPaused] = useState(false);
  const [resetTrigger, setResetTrigger] = useState(0);

  const [count, setCount] = useState(60);

  useEffect(() => {
    if (isPaused) return;

    const id = setInterval(() => {
      setCount((c) => {
        if (c === 0) {
          return 60;
        }
        return c - 1;
      });
    }, 1000);

    return () => {
      clearInterval(id);
    };
  }, [isPaused]);

  // Reset timer when resetTrigger changes
  useEffect(() => {
    setCount(60);
  }, [resetTrigger]);

  const handleReset = () => {
    setResetTrigger((prev) => prev + 1);
  };

  return (
    <div className="relative flex h-screen w-full flex-col items-center justify-center bg-[#f5f4f3] text-black">
      <div className="top-22 absolute left-1/2 grid -translate-x-1/2 content-start justify-items-center gap-6 text-center text-black">
        <span className="relative max-w-[12ch] text-xs uppercase leading-tight opacity-40 after:absolute after:left-1/2 after:top-full after:h-16 after:w-px after:bg-gradient-to-b after:from-[#f5f4f3] after:to-black after:content-['']">
          Countdown with Number Flow
        </span>
      </div>
      <div className="font-bebas-neue text-[20vw] tracking-tight">
        <NumberFlow value={count} prefix="0:" />
      </div>
      <div className="flex w-fit items-center gap-2">
        <motion.button
          aria-label="Pause timer"
          onClick={() => setIsPaused((p) => !p)}
          whileTap={{ scale: 0.9 }}
          className="hover:bg-[#ff3828 flex h-10 w-10 items-center justify-center rounded-full bg-[#ff3828] transition-colors"
        >
          <AnimatePresence initial={false} mode="wait">
            {isPaused ? (
              <motion.svg
                key="play"
                initial={{ opacity: 0, scale: 0.5, filter: "blur(4px)" }}
                animate={{ opacity: 1, scale: 1, filter: "blur(0px)" }}
                exit={{ opacity: 0, scale: 0.5, filter: "blur(4px)" }}
                transition={{ duration: 0.1 }}
                viewBox="0 0 12 14"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
                className="h-4 w-4 fill-current text-[#f5f4f3]"
              >
                <path d="M0.9375 13.2422C1.25 13.2422 1.51562 13.1172 1.82812 12.9375L10.9375 7.67188C11.5859 7.28906 11.8125 7.03906 11.8125 6.625C11.8125 6.21094 11.5859 5.96094 10.9375 5.58594L1.82812 0.3125C1.51562 0.132812 1.25 0.015625 0.9375 0.015625C0.359375 0.015625 0 0.453125 0 1.13281V12.1172C0 12.7969 0.359375 13.2422 0.9375 13.2422Z" />
              </motion.svg>
            ) : (
              <motion.svg
                key="pause"
                initial={{ opacity: 0, scale: 0.5, filter: "blur(4px)" }}
                animate={{ opacity: 1, scale: 1, filter: "blur(0px)" }}
                exit={{ opacity: 0, scale: 0.5, filter: "blur(4px)" }}
                transition={{ duration: 0.1 }}
                viewBox="0 0 10 13"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
                className="h-4 w-4 fill-current text-[#f5f4f3]"
              >
                <path d="M1.03906 12.7266H2.82031C3.5 12.7266 3.85938 12.3672 3.85938 11.6797V1.03906C3.85938 0.328125 3.5 0 2.82031 0H1.03906C0.359375 0 0 0.359375 0 1.03906V11.6797C0 12.3672 0.359375 12.7266 1.03906 12.7266ZM6.71875 12.7266H8.49219C9.17969 12.7266 9.53125 12.3672 9.53125 11.6797V1.03906C9.53125 0.328125 9.17969 0 8.49219 0H6.71875C6.03125 0 5.67188 0.359375 5.67188 1.03906V11.6797C5.67188 12.3672 6.03125 12.7266 6.71875 12.7266Z" />
              </motion.svg>
            )}
          </AnimatePresence>
        </motion.button>
        <button
          aria-label="Reset timer"
          onClick={handleReset}
          className="flex h-10 w-10 items-center justify-center rounded-full bg-white/45 text-[#ff3828] shadow-2xl transition-colors hover:bg-white/70"
        >
          <Plus className="rotate-45" />
        </button>
      </div>
    </div>
  );
};

export { Skiper37 };

export const AnimatedNumber_002 = () => {
  const finalCount = 500;
  const [displaySubs, setDisplaySubs] = useState(0);

  // Animating sub count from 0 to subscriberCount prop
  const springSubCount = useSpring(0, {
    bounce: 0,
    duration: 1000,
  });

  springSubCount.on("change", (value) => {
    setDisplaySubs(Math.round(value));
  });

  const animate = () => {
    springSubCount.set(finalCount);
  };

  return (
    <div className="relative flex h-screen w-full flex-col items-center justify-center bg-[#f5f4f3] text-black">
      <div className="top-22 absolute left-1/2 grid -translate-x-1/2 content-start justify-items-center gap-6 text-center text-black">
        <span className="relative max-w-[12ch] text-xs uppercase leading-tight opacity-40 after:absolute after:left-1/2 after:top-full after:h-16 after:w-px after:bg-gradient-to-b after:from-[#f5f4f3] after:to-black after:content-['']">
          random numbers from x to y in view
        </span>
      </div>
      <motion.div
        onViewportEnter={animate}
        onViewportLeave={() => {
          springSubCount.set(0);
        }}
        className="font-bebas-neue text-[20vw] tracking-tight"
      >
        {displaySubs}
      </motion.div>
    </div>
  );
};

export const AnimatedNumber_003 = () => {
  const [displayNumber, setDisplayNumber] = useState(1000000);
  const [isAnimating, setIsAnimating] = useState(false);
  const hasAnimated = useRef(false);

  const formatNumber = (num: any) => {
    return new Intl.NumberFormat("en-US").format(num);
  };

  const animate = () => {
    if (hasAnimated.current || isAnimating) return;

    setIsAnimating(true);
    hasAnimated.current = true;

    const steps = 12;
    let currentStep = 0;

    const interval = setInterval(() => {
      currentStep++;

      if (currentStep <= steps) {
        const min = 1000000 + currentStep * (1000000 / steps);
        const max = 2200000;
        const randomNum = Math.floor(min + Math.random() * (max - min));
        setDisplayNumber(randomNum);
      } else {
        setDisplayNumber(2146000);
        setIsAnimating(false);
        clearInterval(interval);
      }
    }, 80);
  };
  return (
    <div className="relative flex h-screen w-full flex-col items-center justify-center bg-[#f5f4f3] text-black">
      <div className="top-22 absolute left-1/2 grid -translate-x-1/2 content-start justify-items-center gap-6 text-center text-black">
        <span className="relative max-w-[12ch] text-xs uppercase leading-tight opacity-40 after:absolute after:left-1/2 after:top-full after:h-16 after:w-px after:bg-gradient-to-b after:from-[#f5f4f3] after:to-black after:content-['']">
          random numbers from x to y in view
        </span>
      </div>
      <div className="font-bebas-neue text-[20vw] tracking-tight">
        <motion.div
          onViewportEnter={animate}
          onViewportLeave={() => {
            setDisplayNumber(1000000);
            hasAnimated.current = false;
            setIsAnimating(false);
          }}
        >
          ${formatNumber(displayNumber)}
        </motion.div>
      </div>
    </div>
  );
};

function AnimatedNumber_004() {
  const [displayValue, setDisplayValue] = useState(0);
  const count = useMotionValue(3);
  const { ref, inView } = useInView({ triggerOnce: false });

  useEffect(() => {
    if (inView) {
      animate(count, 100, {
        duration: 1,
        ease: "easeInOut",
        onUpdate: (latest) => setDisplayValue(Math.round(latest)),
        onComplete: () => {
          console.log("complete");
        },
      });
    } else {
      setDisplayValue(3);
    }
  }, [inView, count]);

  return (
    <div className="relative flex h-screen w-full flex-col items-center justify-center bg-[#f5f4f3] text-black">
      <div className="top-22 absolute left-1/2 grid -translate-x-1/2 content-start justify-items-center gap-6 text-center text-black">
        <span className="relative max-w-[12ch] text-xs uppercase leading-tight opacity-40 after:absolute after:left-1/2 after:top-full after:h-16 after:w-px after:bg-gradient-to-b after:from-[#f5f4f3] after:to-black after:content-['']">
          from x to y value in view [number-flow]
        </span>
      </div>
      <div ref={ref} className="font-bebas-neue text-[20vw] tracking-tight">
        <NumberFlow value={displayValue} prefix="$" suffix="K USD" />
      </div>
    </div>
  );
}

/**
 * Skiper 37 AnimatedNumber — React + Number Flow + Framer Motion
 * Design Inspired by https://number-flow.barvian.me/
 * Code Inspired by https://number-flow.barvian.me/
 * We respect the original creators. This is an inspired rebuild with our own taste and does not claim any ownership.
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
