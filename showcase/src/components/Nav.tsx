import { useCallback, useEffect, useRef, useState } from 'react';
import { brandMarks } from '../content/media';
import { controlEntry, nav, site } from '../content/site';
import './Nav.css';

export function Nav() {
  const [solid, setSolid] = useState(false);
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const onScroll = () => setSolid(window.scrollY > 24);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const close = useCallback(() => {
    setOpen(false);
    toggleRef.current?.focus();
  }, []);

  /* Menu is a focus trap while open, and Escape always returns to the toggle. */
  useEffect(() => {
    if (!open) return;

    const panel = panelRef.current;
    panel?.querySelector<HTMLElement>('a, button')?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        close();
        return;
      }
      if (e.key !== 'Tab' || !panel) return;

      const focusables = panel.querySelectorAll<HTMLElement>('a[href], button:not([disabled])');
      if (!focusables.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [open, close]);

  return (
    <header className={`nav${solid ? ' is-solid' : ''}`}>
      <div className="nav__inner page">
        <a className="nav__brand" href="#top" aria-label={`${site.name} — back to top`}>
          <img
            src={brandMarks.wordmark.src}
            width={brandMarks.wordmark.width}
            height={brandMarks.wordmark.height}
            alt={brandMarks.wordmark.alt}
          />
        </a>

        <nav className="nav__links" aria-label="Sections">
          {nav.map((item) => (
            <a key={item.id} href={`#${item.id}`}>
              {item.label}
            </a>
          ))}
        </nav>

        <a className="nav__cta btn btn--ghost" href={controlEntry.href}>
          {controlEntry.label}
          <span className="btn__arrow" aria-hidden="true">
            →
          </span>
        </a>

        <button
          ref={toggleRef}
          className="nav__toggle"
          type="button"
          aria-expanded={open}
          aria-controls="nav-menu"
          onClick={() => setOpen((v) => !v)}
        >
          <span className="nav__toggle-label">{open ? 'Close' : 'Menu'}</span>
          <span className={`nav__toggle-icon${open ? ' is-open' : ''}`} aria-hidden="true">
            <span />
            <span />
          </span>
        </button>
      </div>

      <div
        ref={panelRef}
        id="nav-menu"
        className={`nav__panel${open ? ' is-open' : ''}`}
        hidden={!open}
      >
        <nav aria-label="Sections">
          <a href={controlEntry.href} onClick={close}>
            <span className="nav__panel-index num" aria-hidden="true">↗</span>
            {controlEntry.label}
          </a>
          {nav.map((item) => (
            <a key={item.id} href={`#${item.id}`} onClick={close}>
              <span className="nav__panel-index num">
                {String(nav.indexOf(item) + 1).padStart(2, '0')}
              </span>
              {item.label}
            </a>
          ))}
        </nav>
      </div>
    </header>
  );
}
