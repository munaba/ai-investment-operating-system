import { useReducedMotion } from 'framer-motion';

// Thin wrapper so components read the user's motion preference in one place.
// Framer Motion's useReducedMotion() already respects the
// prefers-reduced-motion media query (unlike the old CSS-only approach).
export function useReducedMotionSafe(): boolean {
  return useReducedMotion() ?? false;
}
