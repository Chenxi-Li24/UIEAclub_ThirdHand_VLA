import { MediaImage } from './Media';
import { teamPhoto } from '../content/media';
import { team } from '../content/site';
import './Team.css';

/**
 * One title, one sentence, one photograph.
 * -----------------------------------------------------------------------------
 * The picture carries the section, so it is shown whole at its natural 4:3 and
 * nothing is laid over it: the copy sits above the image, never across anyone's
 * face. No individual is named anywhere on this page.
 */
export function Team() {
  return (
    <section className="team section" id="team" aria-labelledby="team-heading">
      <div className="page">
        <div className="team__body">
          <div className="chapter reveal">
            <span className="chapter__num num">{team.chapter}</span>
            <span className="chapter__name">{team.name}</span>
            <span className="chapter__line" />
          </div>

          <h2 className="h2 reveal" id="team-heading">
            {team.headline}
          </h2>
          <p className="lede reveal">{team.support}</p>
        </div>

        <figure className="team__photo reveal">
          <MediaImage className="team__photo-img" media={teamPhoto} />
        </figure>
      </div>
    </section>
  );
}
