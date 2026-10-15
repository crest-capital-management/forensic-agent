"use client";

import { useEffect, useState } from "react";

// Plain-language steps that match what the tool really does, so the wait reads as progress.
const STEPS = [
  "Opening the filings…",
  "Matching figures across sources…",
  "Checking every citation against the page…",
  "Ranking flags by severity…",
  "Remember: these are leads, not proof.",
];

export default function Loader({ label }: { label?: string }) {
  const [i, setI] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setI((n) => (n + 1) % STEPS.length), 2200);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="loader" role="status" aria-live="polite">
      <svg className="loader-art" viewBox="0 0 220 150" aria-hidden="true">
        {/* the ledger page */}
        <rect x="20" y="14" width="150" height="112" rx="8" className="l-page" />
        {[0, 1, 2, 3, 4].map((r) => (
          <g key={r} className="l-row" style={{ animationDelay: `${r * 0.28}s` }}>
            <rect x="34" y={30 + r * 19} width="26" height="7" rx="3" className="l-bar" />
            <rect x="68" y={30 + r * 19} width={62 + ((r * 23) % 34)} height="7" rx="3" className="l-bar" />
          </g>
        ))}
        {/* a flag that gets planted on one row */}
        <g className="l-flag">
          <line x1="150" y1="34" x2="150" y2="70" className="l-pole" />
          <path d="M150 34 L170 41 L150 48 Z" className="l-flag-cloth" />
        </g>
        {/* the magnifier sweeping the page */}
        <g className="l-glass">
          <circle cx="0" cy="0" r="17" className="l-lens" />
          <circle cx="0" cy="0" r="17" className="l-ring" />
          <line x1="12" y1="12" x2="27" y2="27" className="l-handle" />
        </g>
      </svg>
      <p className="loader-title">{label || "Loading"}</p>
      <p className="loader-step" key={i}>{STEPS[i]}</p>
      <div className="loader-dots" aria-hidden="true"><i /><i /><i /></div>
    </div>
  );
}
