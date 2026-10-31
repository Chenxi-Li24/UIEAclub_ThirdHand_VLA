import { useEffect, useRef } from 'react';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { Nav } from './components/Nav';
import { Hero } from './components/Hero';
import { Actions } from './components/Actions';
import { Demos } from './components/Demos';
import { Lab } from './components/Lab';
import { Platform } from './components/Platform';
import { Team } from './components/Team';
import { Footer } from './components/Footer';
import { useReveal } from './hooks/useReveal';
import { useReducedMotion } from './hooks/useMotionPreference';

export default function App() {
  const mainRef = useRef<HTMLElement>(null);
  const reduced = useReducedMotion();

  useReveal(mainRef);

  /**
   * `js-motion` gates every hidden-until-revealed style. It is only added once
   * React has mounted and motion is allowed, so the page stays fully readable
   * if scripting fails or motion is reduced.
   */
  useEffect(() => {
    const root = document.documentElement;
    if (reduced) {
      root.classList.remove('js-motion');
      return;
    }
    root.classList.add('js-motion');
    return () => root.classList.remove('js-motion');
  }, [reduced]);

  /* Sticky measurements depend on images and fonts having settled. */
  useEffect(() => {
    const refresh = () => ScrollTrigger.refresh();
    const onLoad = () => refresh();

    if (document.readyState === 'complete') refresh();
    else window.addEventListener('load', onLoad);

    document.fonts?.ready.then(refresh).catch(() => {});
    return () => window.removeEventListener('load', onLoad);
  }, []);

  return (
    <>
      <a className="skip-link" href="#actions">
        Skip to content
      </a>
      <Nav />
      <main id="main" ref={mainRef}>
        <Hero />
        <Actions />
        <Demos />
        <Lab />
        <Platform />
        <Team />
      </main>
      <Footer />
    </>
  );
}
