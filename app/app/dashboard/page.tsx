"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import Loader from "@/components/Loader";

function Stat({ label, value, hint, empty }: { label: string; value: string; hint?: string; empty?: boolean }) {
  return (
    <div className="stat-tile">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${empty ? "empty" : ""}`}>{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export default function Dashboard() {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api("/dashboard").then(setD).catch((e) => setErr(e.message));
  }, []);

  if (err) return <p className="error">{err}</p>;
  if (!d) return <Loader label="Loading the dashboard" />;
  const pct = (v: number | null) => (v === null ? "—" : `${v}%`);

  return (
    <>
      <h1>Dashboard</h1>
      <div className="stat-grid">
        <Stat label="Flags in the database" value={String(d.flags_total)} hint="all runs, all companies" />
        <Stat label="Flags with a complete citation" value={d.flags_with_citation_pct === null ? "n/a" : `${d.flags_with_citation_pct}%`} hint="target: 100%" />
        <Stat label="Flags decided by reviewers" value={String(d.flags_decided)} hint={`${d.accepted} accepted, ${d.rejected} rejected`} />
        <Stat label="Acceptance rate" value={pct(d.acceptance_rate_pct)} hint={d.acceptance_rate_pct === null ? "Shown after the first review" : "Flags judged worth investigating"} empty={d.acceptance_rate_pct === null} />
        <Stat label="False-alarm rate" value={pct(d.false_alarm_rate_pct)} hint={d.false_alarm_rate_pct === null ? "Shown after the first review" : "Flags rejected; used later to tune limits"} empty={d.false_alarm_rate_pct === null} />
      </div>
      <p className="muted small">{d.note} Time per screen is not tracked yet.</p>
    </>
  );
}
