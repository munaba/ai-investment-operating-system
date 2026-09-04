"use client";

import { useMotionValue } from "framer-motion";
import { motion } from "motion/react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

export const Skiper102 = () => {
  const mouseX = useMotionValue(0);
  const mouseY = useMotionValue(0);

  const [count, setCount] = useState(0);

  const [keyPressed, setKeyPressed] = useState("");

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      setKeyPressed(e.key);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div
      onMouseMove={(e) => {
        mouseX.set(e.clientX);
        mouseY.set(e.clientY);
      }}
      onClick={() => setCount((prev) => prev + 1)}
      className="flex size-full flex-col items-center justify-center"
    >
      <div className="-mt-36 mb-36 grid content-start justify-items-center gap-6 text-center">
        <span className="after:to-foreground relative max-w-[14ch] text-xs uppercase leading-tight opacity-40 after:absolute after:left-1/2 after:top-full after:h-16 after:w-px after:bg-gradient-to-b after:from-transparent after:content-['']">
          Debug Pannel
        </span>
      </div>
      <DebugPanel
        className=""
        count={count}
        mouseX={mouseX}
        mouseY={mouseY}
        keyPressed={keyPressed}
      />
    </div>
  );
};

export const DebugPanel = ({
  className,
  ...props
}: Record<string, any> & { className?: string }) => {
  return (
    <div
      className={cn(
        "z-99 left-4 top-4 font-mono text-sm text-red-500",
        className,
      )}
    >
      {"{"}

      {Object.entries(props).map(([key, value]) => (
        <div key={key} className="ml-4">
          {key}:{" "}
          {value && typeof value === "object" && "get" in value ? (
            <motion.span>{value}</motion.span>
          ) : typeof value === "boolean" ? (
            value ? (
              "true"
            ) : (
              "false"
            )
          ) : (
            String(value)
          )}
          ;
        </div>
      ))}
      {"}"}
    </div>
  );
};
