import type { CSSProperties } from 'react';
import type { MediaKind, MediaSource } from '../content/media';

interface MediaImageProps {
  media: MediaSource;
  className?: string;
  style?: CSSProperties;
  /** The hero and the first story frame load eagerly; everything else waits. */
  priority?: boolean;
  /** Overrides the registry `sizes` hint. */
  sizes?: string;
}

/**
 * The single image primitive. Intrinsic width/height are always emitted so the
 * browser reserves space and nothing shifts while the file loads. A `<picture>`
 * is only introduced when the entry declares a fallback format.
 */
export function MediaImage({ media, className, style, priority = false, sizes }: MediaImageProps) {
  const resolved = sizes ?? media.sizes;

  const img = (
    <img
      className={className}
      style={style}
      src={media.fallback ? media.fallback.src : media.src}
      srcSet={media.fallback ? media.fallback.srcSet : media.srcSet}
      sizes={resolved}
      width={media.width}
      height={media.height}
      alt={media.alt}
      loading={priority ? 'eager' : 'lazy'}
      decoding={priority ? 'sync' : 'async'}
      {...(priority ? { fetchPriority: 'high' as const } : {})}
      draggable={false}
    />
  );

  if (!media.fallback) return img;

  return (
    <picture>
      <source type="image/webp" srcSet={media.srcSet ?? media.src} sizes={resolved} />
      {img}
    </picture>
  );
}

/** Human-readable badge for the kind of asset shown. */
export const kindLabel: Record<MediaKind, string> = {
  photograph: 'Photograph',
  cad: 'CAD',
  interface: 'Interface',
};
