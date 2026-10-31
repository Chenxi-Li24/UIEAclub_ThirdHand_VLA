import { useEffect, useState } from 'react';

function subscribe(query: string, onChange: (matches: boolean) => void) {
  if (typeof window === 'undefined' || !window.matchMedia) return () => {};
  const mql = window.matchMedia(query);
  const handler = (e: MediaQueryListEvent) => onChange(e.matches);
  onChange(mql.matches);
  mql.addEventListener('change', handler);
  return () => mql.removeEventListener('change', handler);
}

export function useMediaQuery(query: string, initial = false): boolean {
  const [matches, setMatches] = useState(initial);
  useEffect(() => subscribe(query, setMatches), [query]);
  return matches;
}

/** True when the visitor has asked for reduced motion. */
export function useReducedMotion(): boolean {
  return useMediaQuery('(prefers-reduced-motion: reduce)');
}

/**
 * True when the scroll-driven, pinned presentation is appropriate: enough
 * viewport height and width, a real pointer or not, but never under reduced
 * motion. Everything else falls back to a stacked story that reads identically.
 */
export function useCinematicMode(): boolean {
  const reduced = useReducedMotion();
  const roomy = useMediaQuery('(min-width: 62rem) and (min-height: 34rem)');
  return roomy && !reduced;
}

/** Desktop pointer parallax is opt-in: fine pointer, hover capable, no reduced motion. */
export function usePointerParallax(): boolean {
  const reduced = useReducedMotion();
  const finePointer = useMediaQuery('(hover: hover) and (pointer: fine)');
  return finePointer && !reduced;
}
