import { useCallback, useEffect, useRef, useState } from 'react';
import { MediaImage } from './Media';
import { useReducedMotion } from '../hooks/useMotionPreference';
import type { VideoSource } from '../content/media';
import './VideoFrame.css';

interface VideoFrameProps {
  video: VideoSource;
  className?: string;
  /**
   * Whether the act this clip belongs to is the one currently being shown. In
   * the pinned stage every panel is on screen at once, so visibility alone is
   * not enough to decide what should be playing.
   */
  active?: boolean;
  /** Play from the first frame each time the act is entered again. */
  restartOnEnter?: boolean;
}

/**
 * A silent clip that only plays while it is the thing being looked at.
 * -----------------------------------------------------------------------------
 * The `<source>` is attached when the element approaches the viewport, playback
 * stops the moment the clip leaves the viewport or its act stops being the
 * active one, and audio is never present in the file at all.
 *
 * A play/pause control is always available and always reachable from the
 * keyboard: it stays out of the way until the frame is hovered or focused, and
 * shows itself whenever the clip is not running. Under reduced motion nothing
 * moves at all until the visitor asks for it — the poster is shown instead.
 */
export function VideoFrame({ video, className, active = true, restartOnEnter = false }: VideoFrameProps) {
  const reduced = useReducedMotion();
  const wrapRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  const [near, setNear] = useState(false);
  const [onScreen, setOnScreen] = useState(false);
  const [started, setStarted] = useState(false);
  const [paused, setPaused] = useState(true);
  /* Set when the visitor uses the control; automatic playback then stays off. */
  const [held, setHeld] = useState(false);

  /* Motion is allowed once: never under reduced motion until asked for. */
  const allowed = !reduced || started;

  /* Attach the file only when the section is close. */
  useEffect(() => {
    const el = wrapRef.current;
    if (!el || !allowed) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setNear(true);
          io.disconnect();
        }
      },
      { rootMargin: '400px 0px' }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [allowed]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const io = new IntersectionObserver(([entry]) => setOnScreen(entry.isIntersecting), {
      threshold: 0.2,
    });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  /* Rewind when the act is entered again, before anything starts playing. */
  const wasActive = useRef(active);
  useEffect(() => {
    const media = videoRef.current;
    if (media && restartOnEnter && active && !wasActive.current) media.currentTime = 0;
    wasActive.current = active;
  }, [active, restartOnEnter]);

  /* The one place playback is decided. */
  useEffect(() => {
    const media = videoRef.current;
    if (!media) return;

    if (onScreen && active && allowed && !held) media.play().catch(() => {});
    else media.pause();
  }, [onScreen, active, allowed, held, near]);

  useEffect(() => {
    const media = videoRef.current;
    return () => media?.pause();
  }, []);

  const toggle = useCallback(() => {
    const media = videoRef.current;
    if (!media) return;
    if (!started) setStarted(true);

    if (media.paused) {
      setHeld(false);
      // The clip holds on its last frame when it is not looped; play it again.
      if (!video.loop && media.duration && media.currentTime >= media.duration - 0.05) {
        media.currentTime = 0;
      }
      media.play().catch(() => {});
    } else {
      setHeld(true);
      media.pause();
    }
  }, [started, video.loop]);

  const showPoster = reduced && !started;

  return (
    <div
      className={`vframe${className ? ` ${className}` : ''}${paused ? ' is-paused' : ''}`}
      ref={wrapRef}
    >
      <video
        ref={videoRef}
        className={`vframe__video${showPoster ? '' : ' is-live'}`}
        width={video.width}
        height={video.height}
        poster={video.poster.src}
        muted
        loop={video.loop ?? true}
        playsInline
        preload="none"
        aria-label={video.label}
        onPlay={() => setPaused(false)}
        onPause={() => setPaused(true)}
        onEnded={() => setPaused(true)}
      >
        {near && !showPoster && <source src={video.src} type={video.type} />}
      </video>

      {showPoster ? (
        <>
          <MediaImage className="vframe__poster" media={video.poster} />
          <button className="vframe__play" type="button" onClick={toggle}>
            <span className="vframe__play-icon" aria-hidden="true" />
            Play clip
          </button>
        </>
      ) : (
        <button
          className="vframe__toggle"
          type="button"
          onClick={toggle}
          aria-label={paused ? 'Play clip' : 'Pause clip'}
        >
          <span className={`vframe__toggle-icon${paused ? '' : ' is-playing'}`} aria-hidden="true" />
        </button>
      )}
    </div>
  );
}
