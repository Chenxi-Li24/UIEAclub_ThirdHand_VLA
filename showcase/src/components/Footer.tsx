import { brandMarks } from '../content/media';
import { footer } from '../content/site';
import './Footer.css';

export function Footer() {
  return (
    <footer className="footer">
      <div className="page footer__inner">
        <img
          className="footer__mark"
          src={brandMarks.lockup.src}
          width={brandMarks.lockup.width}
          height={brandMarks.lockup.height}
          alt={brandMarks.lockup.alt}
          loading="lazy"
        />
        <p className="footer__statement">{footer.statement}</p>
        <p className="footer__rights label">{footer.rights}</p>
      </div>
    </footer>
  );
}
