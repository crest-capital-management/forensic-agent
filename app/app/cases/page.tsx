"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import Loader from "@/components/Loader";
import { Tag } from "@/components/Badges";

type Case = {
  id: number; name: string | null; company: string; years: string[]; reason: string; status: string;
  is_portfolio_company: boolean; created_by: string; duplicate_of: number | null;
  counts: { total: number; unreviewed: number; accepted: number; rejected: number };
};

export default function CasesPage() {
  const [cases, setCases] = useState<Case[] | null>(null);
  const [filter, setFilter] = useState("all");
  const [err, setErr] = useState("");

  useEffect(() => {
    api<Case[]>("/cases").then(setCases).catch((e) => setErr(e.message));
  }, []);

  const shown = (cases || []).filter((c) => filter === "all" || c.status === filter);

  return (
    <>
      <div className="row between">
        <h1>Cases</h1>
        <Link className="btn primary" href="/cases/new">New case</Link>
      </div>
      <div className="row gap">
        {["all", "open", "in_review", "escalated", "closed"].map((f) => (
          <button key={f} className={`chip ${filter === f ? "on" : ""}`} onClick={() => setFilter(f)}>
            {f.replace("_", " ")}
          </button>
        ))}
      </div>
      <p className="muted small" style={{ margin: "8px 0 0" }}>
        <b>Open</b>: no flag has been decided yet. <b>In review</b>: at least one flag has been accepted or rejected.{" "}
        <b>Escalated</b>: a flag has been escalated (for a portfolio company, waiting for the adviser). <b>Closed</b>: finished and kept; nothing new can be added unless it is reopened.
      </p>
      {err && <p className="error">{err}. Is the API running? (python -m crest_forensic.review.api)</p>}
      {cases === null && !err && <Loader label="Loading cases" />}
      {cases && shown.length === 0 && <p className="muted">{filter === "closed" ? "No closed cases." : "No cases here yet. Open one with “New case”."}</p>}
      <div className="stack">
        {shown.map((c) => (
          <Link key={c.id} href={`/cases/${c.id}`} className="card link">
            <div className="row between">
              <span className="row gap"><strong>Case {c.id} · {c.name || c.company}</strong>{c.duplicate_of && <Tag tone="plain">duplicate of case {c.duplicate_of}</Tag>}</span>
              <span className="row gap">
                {c.is_portfolio_company && <Tag tone="wait">portfolio company</Tag>}
                <Tag tone={c.status === "escalated" ? "esc" : c.status === "closed" ? "reject" : "plain"}>{c.status.replace("_", " ")}</Tag>
              </span>
            </div>
            <div className="muted">{c.name ? `${c.company} · ` : ""}{c.years.join(", ")} · opened by {c.created_by}</div>
            <div>{c.reason}</div>
            <div className="muted">
              {c.counts.total} flags · {c.counts.unreviewed} unreviewed · {c.counts.accepted} accepted ·{" "}
              {c.counts.rejected} rejected
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}
