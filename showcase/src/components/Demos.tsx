import { useCallback, useRef } from 'react';
import { demoVideos } from '../content/media';
import { demos } from '../content/site';
import './Demos.css';

export function Demos() {
  const videosRef = useRef<Array<HTMLVideoElement | null>>([]);

  const pauseOtherVideos = useCallback((activeIndex: number) => {
    videosRef.current.forEach((video, index) => {
      if (index !== activeIndex) video?.pause();
    });
  }, []);

  return (
    <section className="demos section" id="demos" aria-labelledby="demos-heading">
      <div className="page">
        <div className="chapter reveal">
          <span className="chapter__num num">{demos.chapter}</span>
          <span className="chapter__name">{demos.name}</span>
          <span className="chapter__line" />
        </div>

        <div className="demos__intro">
          <h2 className="h2 reveal" id="demos-heading">
            {demos.headline}
          </h2>
          <p className="lede reveal">{demos.support}</p>
        </div>

        <div className="demos__list">
          {demos.items.map((item, index) => {
            const video = demoVideos[index];

            return (
              <article className="demos__item reveal" key={video.src}>
                <div className="demos__meta">
                  <span className="demos__index num">{item.index}</span>
                  <p className="demos__tag label">{item.tag}</p>
                  <h3 className="h3">{item.title}</h3>
                  <p className="body">{item.description}</p>
                </div>

                <div className="demos__video-shell">
                  <video
                    ref={(node) => {
                      videosRef.current[index] = node;
                    }}
                    controls
                    playsInline
                    preload="metadata"
                    aria-label={video.label}
                    onPlay={() => pauseOtherVideos(index)}
                  >
                    <source src={video.src} type="video/mp4" />
                    Your browser does not support video playback.
                  </video>
                </div>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
