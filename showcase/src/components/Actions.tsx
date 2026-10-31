import { useEffect, useRef, useState, type ReactNode } from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { MediaImage } from './Media';
import { VideoFrame } from './VideoFrame';
import { Field, Reticle } from './Instruments';
import { actions } from '../content/site';
import {
  graspSupport,
  graspVideo,
  motionVideo,
  visionStill,
  visionVideo,
} from '../content/media';
import { useCinematicMode } from '../hooks/useMotionPreference';
import './Actions.css';

gsap.registerPlugin(ScrollTrigger);

const acts = actions.acts;

/** Where each act sits on the 0..1 scrub, leaving a lead-in and a dwell. */
const AT = [0.08, 0.5, 0.88];

/** Scrub position at which one act hands over to the next. */
const HANDOVER = AT.slice(1).map((at, i) => (AT[i] + at) / 2);

const actAt = (progress: number) => HANDOVER.filter((edge) => progress >= edge).length;

/* -------------------------------------------------------------------------- */
/* Media panels — one per act, in narrative order                              */
/* -------------------------------------------------------------------------- */

function SeePanel({ active }: { active: boolean }) {
  return (
    <div className="act__composite">
      <VideoFrame className="act__composite-main" video={visionVideo} active={active} />
      <figure className="act__composite-inset">
        <MediaImage media={visionStill} />
        <Field className="act__inset-field">
          <Reticle x={800} y={430} size={230} />
        </Field>
      </figure>
    </div>
  );
}

/** The arm working, as one continuous clip rather than a set of still frames. */
function MovePanel({ active }: { active: boolean }) {
  return (
    <div className="act__composite act__composite--move">
      <VideoFrame
        className="act__composite-main"
        video={motionVideo}
        active={active}
        restartOnEnter
      />
    </div>
  );
}

/**
 * The task clip leads; the calibration photograph supports it. The inset hangs
 * off the bottom-right corner, clear of the bottle and the gripper, which work
 * through the middle and left of the frame.
 */
function GraspPanel({ active }: { active: boolean }) {
  return (
    <div className="act__composite act__composite--grasp">
      <VideoFrame className="act__composite-main act__composite-clip" video={graspVideo} active={active} />
      <figure className="act__composite-inset act__composite-support">
        <MediaImage media={graspSupport} />
      </figure>
    </div>
  );
}

const panel = (i: number, active: boolean): ReactNode => {
  switch (i) {
    case 0:
      return <SeePanel active={active} />;
    case 1:
      return <MovePanel active={active} />;
    default:
      return <GraspPanel active={active} />;
  }
};

/* -------------------------------------------------------------------------- */
/* Section                                                                     */
/* -------------------------------------------------------------------------- */

export function Actions() {
  const cinematic = useCinematicMode();

  return (
    <section className="acts section" id="actions" aria-labelledby="acts-heading">
      <div className="page">
        <div className="chapter reveal">
          <span className="chapter__num num">{actions.chapter}</span>
          <span className="chapter__name">{actions.name}</span>
          <span className="chapter__line" />
        </div>
        <div className="acts__intro">
          <h2 className="h2 reveal" id="acts-heading">
            {actions.headline}
          </h2>
          <p className="lede reveal">{actions.support}</p>
        </div>
      </div>

      {cinematic ? <PinnedActs /> : <StackedActs />}
    </section>
  );
}

/**
 * Scroll-driven presentation.
 * -----------------------------------------------------------------------------
 * A single scrubbed timeline is the only clock: scroll position is the
 * animation time, stopping the scroll stops the transition, and scrolling back
 * up plays it in reverse. The stage is a sticky element inside a taller track,
 * so the page keeps its own native scrolling throughout — nothing is hijacked.
 *
 * The same timeline says which act is current, so only that act's clip plays;
 * all three panels are on screen at once and visibility alone cannot tell them
 * apart.
 */
function PinnedActs() {
  const trackRef = useRef<HTMLDivElement>(null);
  const [current, setCurrent] = useState(0);

  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;

    const ctx = gsap.context(() => {
      const tl = gsap.timeline({
        defaults: { ease: 'none' },
        scrollTrigger: {
          trigger: track,
          start: 'top top',
          end: 'bottom bottom',
          scrub: 0.5,
          onUpdate: (self) => setCurrent((prev) => {
            const next = actAt(self.progress);
            return next === prev ? prev : next;
          }),
        },
      });

      acts.forEach((_, i) => {
        const panelSel = `.act__panel[data-act="${i}"]`;
        const copy = `.act__copy[data-act="${i}"]`;

        if (i > 0) {
          tl.fromTo(panelSel, { opacity: 0, scale: 1.04 }, { opacity: 1, scale: 1, duration: 0.1 }, AT[i] - 0.09)
            .fromTo(copy, { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 0.07 }, AT[i] - 0.07);
        }
        if (i < acts.length - 1) {
          tl.to(copy, { opacity: 0, y: -20, duration: 0.05 }, AT[i + 1] - 0.12);
          // Panels overlap in size and shape, so the outgoing one is faded out
          // rather than left underneath — otherwise its inset stays on screen.
          tl.to(panelSel, { opacity: 0, duration: 0.08 }, AT[i + 1] - 0.1);
          // Only the act on screen can be interacted with.
          tl.set(panelSel, { pointerEvents: 'none' }, AT[i + 1] - 0.09);
          tl.set(panelSel, { pointerEvents: 'auto' }, AT[i] - 0.09);
        }

        const from = i === 0 ? 0 : (AT[i - 1] + AT[i]) / 2;
        const to = i === acts.length - 1 ? 1 : (AT[i] + AT[i + 1]) / 2;
        tl.fromTo(`.acts__rail-fill[data-rail="${i}"]`, { scaleX: 0 }, { scaleX: 1, duration: to - from }, from)
          .to(`.acts__rail-item[data-rail="${i}"]`, { '--tick': 1, duration: 0.03 }, from);
      });
    }, trackRef);

    return () => ctx.revert();
  }, []);

  return (
    <div className="acts__track" ref={trackRef}>
      <div className="acts__viewport">
        <div className="acts__stage page">
          <div className="acts__copy-col">
            {acts.map((act, i) => (
              <article className="act__copy" data-act={i} key={act.id} style={{ opacity: i === 0 ? 1 : 0 }}>
                <p className="act__index num">{act.index}</p>
                <h3 className="h3 act__label">{act.label}</h3>
                <p className="body act__sentence">{act.copy}</p>
              </article>
            ))}

            <ol className="acts__rail" aria-hidden="true">
              {acts.map((act, i) => (
                <li className="acts__rail-item" data-rail={i} key={act.id}>
                  <span className="acts__rail-track">
                    <span className="acts__rail-fill" data-rail={i} />
                  </span>
                  <span className="acts__rail-tick num">{act.index}</span>
                </li>
              ))}
            </ol>
          </div>

          <div className="acts__media-col">
            {acts.map((act, i) => (
              <div
                className="act__panel"
                data-act={i}
                data-current={current === i ? 'true' : 'false'}
                key={act.id}
                style={{ opacity: i === 0 ? 1 : 0, pointerEvents: i === 0 ? 'auto' : 'none' }}
              >
                {panel(i, current === i)}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Short screens, coarse pointers and reduced motion get the same three acts, stacked. */
function StackedActs() {
  return (
    <div className="acts__stack page">
      {acts.map((act, i) => (
        <article className="act__card reveal" key={act.id}>
          <div className="act__card-media">{panel(i, true)}</div>
          <div className="act__card-body">
            <p className="act__index num">{act.index}</p>
            <h3 className="h3 act__label">{act.label}</h3>
            <p className="body act__sentence">{act.copy}</p>
          </div>
        </article>
      ))}
    </div>
  );
}
