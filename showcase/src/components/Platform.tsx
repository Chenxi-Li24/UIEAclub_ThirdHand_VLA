import { platform } from '../content/site';
import './Platform.css';

export function Platform() {
  return (
    <section
      className="platform section"
      id="platform"
      aria-labelledby="platform-heading"
    >
      <div className="page">
        <div className="chapter reveal">
          <span className="chapter__num num">{platform.chapter}</span>
          <span className="chapter__name">{platform.name}</span>
          <span className="chapter__line" />
        </div>

        <div className="platform__intro">
          <h2 className="h2 reveal" id="platform-heading">
            {platform.headline}
          </h2>
          <p className="lede reveal">{platform.support}</p>
        </div>

        <div className="platform__system reveal" aria-label="ThirdHand capability flow">
          <p className="platform__system-label label">Reusable capability stack</p>
          <ol className="platform__flow">
            {platform.flow.map((step) => (
              <li className="platform__module" key={step.label}>
                <span className="platform__module-index num">{step.index}</span>
                <strong className="platform__module-name">{step.label}</strong>
                <span className="platform__module-detail">{step.detail}</span>
              </li>
            ))}
          </ol>
        </div>

        <ul className="platform__principles">
          {platform.principles.map((principle, index) => (
            <li className="platform__principle reveal" key={principle.label}>
              <span className="platform__principle-index num">
                {String(index + 1).padStart(2, '0')}
              </span>
              <h3 className="h4">{principle.label}</h3>
              <p className="body">{principle.copy}</p>
            </li>
          ))}
        </ul>

        <p className="platform__vision lede reveal">{platform.vision}</p>
      </div>
    </section>
  );
}
