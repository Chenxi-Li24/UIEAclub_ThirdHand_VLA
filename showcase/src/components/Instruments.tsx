/**
 * The interface language, kept deliberately small: a camera reticle drawn on a
 * fixed 1600x900 field so it registers with the frame behind it (both use
 * `slice` / `cover` with the same focal point). Nothing here reports a value
 * the system does not actually produce.
 */

import './Instruments.css';

export const FIELD = { w: 1600, h: 900 };

interface FieldProps {
  className?: string;
  children: React.ReactNode;
}

/** Overlay canvas that tracks the frame behind it. */
export function Field({ className, children }: FieldProps) {
  return (
    <svg
      className={`field${className ? ` ${className}` : ''}`}
      viewBox={`0 0 ${FIELD.w} ${FIELD.h}`}
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

interface ReticleProps {
  x: number;
  y: number;
  size?: number;
  className?: string;
  /** Draws the corner brackets of a locked selection. */
  locked?: boolean;
}

/** Camera targeting reticle. */
export function Reticle({ x, y, size = 130, className, locked = true }: ReticleProps) {
  const h = size / 2;
  const arm = size * 0.26;
  return (
    <g className={`reticle${className ? ` ${className}` : ''}`} transform={`translate(${x} ${y})`}>
      <circle className="reticle__ring" r={h} />
      <circle className="reticle__ring reticle__ring--inner" r={h * 0.42} />
      <g className="reticle__cross">
        <line x1={-h * 1.5} y1="0" x2={-h * 0.62} y2="0" />
        <line x1={h * 0.62} y1="0" x2={h * 1.5} y2="0" />
        <line x1="0" y1={-h * 1.5} x2="0" y2={-h * 0.62} />
        <line x1="0" y1={h * 0.62} x2="0" y2={h * 1.5} />
      </g>
      {locked && (
        <g className="reticle__brackets">
          <path d={`M${-h} ${-h + arm} L${-h} ${-h} L${-h + arm} ${-h}`} />
          <path d={`M${h - arm} ${-h} L${h} ${-h} L${h} ${-h + arm}`} />
          <path d={`M${h} ${h - arm} L${h} ${h} L${h - arm} ${h}`} />
          <path d={`M${-h + arm} ${h} L${-h} ${h} L${-h} ${h - arm}`} />
        </g>
      )}
    </g>
  );
}
