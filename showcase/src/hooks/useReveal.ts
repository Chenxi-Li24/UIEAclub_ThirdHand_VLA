import { useEffect } from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { useReducedMotion } from './useMotionPreference';

gsap.registerPlugin(ScrollTrigger);

/**
 * Fades `.reveal` elements in as they enter the viewport. Elements are visible
 * by default in CSS; the hidden state only exists once `js-motion` is on the
 * root, so a JavaScript failure leaves the page fully readable.
 */
export function useReveal(root: React.RefObject<HTMLElement | null>) {
  const reduced = useReducedMotion();

  useEffect(() => {
    const el = root.current;
    if (!el || reduced) return;

    const ctx = gsap.context(() => {
      const targets = gsap.utils.toArray<HTMLElement>('.reveal');
      targets.forEach((target) => {
        gsap.to(target, {
          opacity: 1,
          y: 0,
          duration: 0.7,
          ease: 'power2.out',
          scrollTrigger: { trigger: target, start: 'top 88%', once: true },
        });
      });
    }, el);

    return () => ctx.revert();
  }, [root, reduced]);
}
