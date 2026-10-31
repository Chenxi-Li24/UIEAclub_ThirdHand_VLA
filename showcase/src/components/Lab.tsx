import { useEffect, useRef } from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { MediaImage } from './Media';
import { lab } from '../content/site';
import { labCards, labPanorama } from '../content/media';
import { useCinematicMode } from '../hooks/useMotionPreference';
import './Lab.css';

gsap.registerPlugin(ScrollTrigger);

/**
 * An editorial gallery, not a timeline.
 * -----------------------------------------------------------------------------
 * One panoramic CAD view opens the section at full content width and its own
 * ratio; ten equal 4:5 cards follow. Every image is shown complete — the cards
 * contain their picture rather than cropping it, which is why they carry a
 * neutral ground behind images that are a different shape from the card.
 *
 * On desktop the card grid drifts sideways by a small, fixed amount as the
 * section passes — one controlled movement, tied to scroll position, that
 * reverses when the visitor scrolls back. Everywhere else the grid sits still,
 * and the panorama never moves.
 */
export function Lab() {
  const rootRef = useRef<HTMLElement>(null);
  const cinematic = useCinematicMode();

  useEffect(() => {
    const root = rootRef.current;
    if (!root || !cinematic) return;

    const ctx = gsap.context(() => {
      gsap.fromTo(
        '.lab__grid',
        { x: 40 },
        {
          x: -40,
          ease: 'none',
          scrollTrigger: { trigger: root, start: 'top bottom', end: 'bottom top', scrub: 1 },
        }
      );
    }, root);

    return () => ctx.revert();
  }, [cinematic]);

  return (
    <section className="lab section" id="lab" ref={rootRef} aria-labelledby="lab-heading">
      <div className="page">
        <div className="chapter reveal">
          <span className="chapter__num num">{lab.chapter}</span>
          <span className="chapter__name">{lab.name}</span>
          <span className="chapter__line" />
        </div>

        <div className="lab__intro">
          <h2 className="h2 reveal" id="lab-heading">
            {lab.headline}
          </h2>
          <p className="lede reveal">{lab.support}</p>
        </div>

        {/* Full width, natural height, both ends of the assembly intact. */}
        <figure className="lab__panorama reveal">
          <MediaImage className="lab__panorama-img" media={labPanorama} />
          <figcaption className="lab__caption label">{labPanorama.caption}</figcaption>
        </figure>

        <ul className="lab__grid">
          {labCards.map((item) => (
            <li className="lab__item reveal" key={item.src}>
              <figure>
                <div className="lab__frame">
                  <MediaImage
                    media={item}
                    style={item.focus ? { objectPosition: item.focus } : undefined}
                  />
                </div>
                <figcaption className="lab__caption label">{item.caption}</figcaption>
              </figure>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
