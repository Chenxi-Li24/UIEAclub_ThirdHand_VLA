import { forwardRef } from 'react';
import { MediaImage } from './Media';
import type { MediaSource } from '../content/media';

export interface HeroVideoSource {
  /** Muted, looping, 16:9. Poster is required so nothing shifts on load. */
  src: string;
  type?: string;
  poster: MediaSource;
}

interface HeroMediaProps {
  image: MediaSource;
  /** When supplied, a silent looping video replaces the still frame. */
  video?: HeroVideoSource;
  className?: string;
}

/**
 * Reusable hero media surface.
 * -----------------------------------------------------------------------------
 * Today it renders a still frame. To swap in the future 16:9 task video, pass a
 * `video` prop from `src/content/media.ts` — no other component changes. Audio
 * is never played: the element is muted and carries no controls.
 */
export const HeroMedia = forwardRef<HTMLDivElement, HeroMediaProps>(function HeroMedia(
  { image, video, className },
  ref
) {
  return (
    <div className={className} ref={ref}>
      {video ? (
        <video
          className="hero__media-el"
          poster={video.poster.src}
          width={image.width}
          height={image.height}
          autoPlay
          muted
          loop
          playsInline
          preload="metadata"
          aria-label={image.alt}
        >
          <source src={video.src} type={video.type ?? 'video/mp4'} />
        </video>
      ) : (
        <MediaImage className="hero__media-el" media={image} priority sizes="100vw" />
      )}
    </div>
  );
});
