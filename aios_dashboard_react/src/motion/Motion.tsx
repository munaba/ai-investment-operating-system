import { motion, type Variants } from 'framer-motion';
import type { CSSProperties, ReactNode } from 'react';

// Senior-designer micro-motion scale: subtle, ease-out, <=300ms.
// Reduced motion is enforced globally via <MotionConfig reducedMotion="user">
// in main.tsx, so these primitives never need manual guards.
export const EASE_OUT: [number, number, number, number] = [0.22, 1, 0.36, 1];

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.28, ease: EASE_OUT } },
};

export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { duration: 0.22 } },
};

/** Page root: fades up once on mount. */
export function PageReveal({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div className={className} initial="hidden" animate="show" variants={fadeUp}>
      {children}
    </motion.div>
  );
}

/** Stagger container — give children `variants={fadeUp}` (or use <StaggerItem>). */
export function Stagger({
  children,
  className,
  style,
  gap = 0.05,
}: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  gap?: number;
}) {
  return (
    <motion.div
      className={className}
      style={style}
      initial="hidden"
      animate="show"
      variants={{ hidden: {}, show: { transition: { staggerChildren: gap } } }}
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({ children, className }: { children: ReactNode; className?: string }) {
  return <motion.div className={className} variants={fadeUp}>{children}</motion.div>;
}
