import { useEffect, useRef } from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { HeroMedia } from './HeroMedia';
import { Field, Reticle } from './Instruments';
import { heroMedia } from '../content/media';
import { controlEntry, hero } from '../content/site';
import { usePointerParallax, useReducedMotion } from '../hooks/useMotionPreference';
import './Hero.css';

gsap.registerPlugin(ScrollTrigger);

export function Hero() {
  const rootRef = useRef<HTMLElement>(null);
  const mediaRef = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const parallax = usePointerParallax();

  /* Load-in: a slow settle, a single light sweep, then the camera reticle. */
  useEffect(() => {
    const root = rootRef.current;
    if (!root || reduced) return;

    const ctx = gsap.context(() => {
      gsap
        .timeline({ defaults: { ease: 'power3.out' } })
        .fromTo(
          '.hero__media-el',
          { scale: 1.08, xPercent: 2.5, opacity: 0 },
          { scale: 1, xPercent: 0, opacity: 1, duration: 1.8 }
        )
        .fromTo('.hero__sweep', { xPercent: -140 }, { xPercent: 160, duration: 1.7 }, 0.35)
        .fromTo(
          '.hero__line',
          { yPercent: 110, opacity: 0 },
          { yPercent: 0, opacity: 1, duration: 0.9, stagger: 0.08 },
          0.45
        )
        .fromTo(
          '.hero__actions > *, .hero__scroll',
          { y: 16, opacity: 0 },
          { y: 0, opacity: 1, duration: 0.7, stagger: 0.08 },
          1.0
        )
        .fromTo(
          '.hero .reticle',
          { scale: 1.5, opacity: 0, transformOrigin: 'center' },
          { scale: 1, opacity: 1, duration: 0.9, ease: 'power4.out' },
          0.95
        )
        .fromTo(
          '.hero .reticle__ring',
          { rotate: -35, transformOrigin: 'center' },
          { rotate: 0, duration: 1.4, ease: 'power2.out' },
          0.95
        );

      /* Slow camera drift as the hero leaves — restrained, never bouncy. */
      gsap.to('.hero__media', {
        yPercent: 8,
        scale: 1.06,
        ease: 'none',
        scrollTrigger: { trigger: root, start: 'top top', end: 'bottom top', scrub: true },
      });
      gsap.to('.hero__content', {
        yPercent: -14,
        opacity: 0.15,
        ease: 'none',
        scrollTrigger: { trigger: root, start: 'top top', end: 'bottom top', scrub: true },
      });
    }, root);

    return () => ctx.revert();
  }, [reduced]);

  /* Very small pointer parallax — fine pointers only, never under reduced motion. */
  useEffect(() => {
    const media = mediaRef.current;
    if (!media || !parallax) return;

    const xTo = gsap.quickTo(media, 'x', { duration: 0.9, ease: 'power3' });
    const yTo = gsap.quickTo(media, 'y', { duration: 0.9, ease: 'power3' });

    const onMove = (e: PointerEvent) => {
      xTo((e.clientX / window.innerWidth - 0.5) * -14);
      yTo((e.clientY / window.innerHeight - 0.5) * -10);
    };

    window.addEventListener('pointermove', onMove, { passive: true });
    return () => {
      window.removeEventListener('pointermove', onMove);
      gsap.set(media, { x: 0, y: 0 });
    };
  }, [parallax]);

  return (
    <section className="hero" id="top" ref={rootRef}>
      <div className="hero__frame">
        <HeroMedia className="hero__media" image={heroMedia} ref={mediaRef} />
        <div className="hero__sweep" aria-hidden="true" />
        <div className="hero__scrim" aria-hidden="true" />
        {/* The reticle registers with the robot only when the frame is wide
            enough; narrow screens get a frame mark that never crosses copy. */}
        <Field className="hero__field">
          <Reticle x={1010} y={330} size={200} />
        </Field>
        <div className="hero__brackets" aria-hidden="true">
          <span />
          <span />
          <span />
          <span />
        </div>
      </div>

      <div className="hero__content page">
        <p className="hero__eyebrow label">
          <span className="hero__line">{hero.eyebrow}</span>
        </p>

        <h1 className="hero__headline display">
          {hero.headlineLines.map((line) => (
            <span className="hero__line-wrap" key={line}>
              <span className="hero__line">{line}</span>
            </span>
          ))}
        </h1>

        <p className="hero__support lede">
          <span className="hero__line">{hero.support}</span>
        </p>

        <div className="hero__actions">
          <a className="btn btn--primary" href={controlEntry.href}>
            {controlEntry.label}
            <span className="btn__arrow" aria-hidden="true">↗</span>
          </a>
          <a className="btn btn--ghost" href={hero.cta.href}>
            {hero.cta.heroLabel}
            <span aria-hidden="true">↓</span>
          </a>
          <a className="btn btn--ghost" href={hero.demoCta.href}>
            {hero.demoCta.label}
            <span className="btn__arrow" aria-hidden="true">
              ↓
            </span>
          </a>
        </div>
      </div>

      <a className="hero__scroll" href={hero.cta.href}>
        <span className="label">{hero.scrollHint}</span>
        <span className="hero__scroll-track" aria-hidden="true">
          <span className="hero__scroll-dot" />
        </span>
      </a>
    </section>
  );
}
