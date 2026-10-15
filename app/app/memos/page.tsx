"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { whenLabel } from "@/lib/time";
import Loader from "@/components/Loader";
import { Tag } from "@/components/Badges";

type Row = {
  id: number; reference: string; case_id: number; company: string; owner_name: string;
  status: string; versions: number; updated_at: string;
};

// Every memo across all cases. New memos are made from a case page (they need accepted flags).
export default function MemosPage() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [filter, setFilter] = useState("all");
  const [err, setErr] = useState("");

  useEffect(() => { api<Row[]>("/memos").then(setRows).catch((e) => setErr(e.message)); }, []);

  if (err) return <p className="error">{err}</p>;
  if (!rows) return <Loader label="Loading memos" />;
  const shown = rows.filter((r) => filter === "all" || r.status === filter);

  return (
    <>
      <h1>Memos</h1>
      <p className="muted small" style={{ marginTop: 0 }}>
        Research memos are drafts for a named person to edit and sign. To start one, open a case and use <b>New memo</b> at the bottom of the case page: a memo needs at least one accepted flag.
      </p>
      <div className="row gap">
        {["all", "draft", "signed"].map((f) => (
          <button key={f} className={`chip ${filter === f ? "on" : ""}`} onClick={() => setFilter(f)}>{f}</button>
        ))}
      </div>
      {shown.length === 0 && <p className="muted" style={{ marginTop: 16 }}>{rows.length === 0 ? "No memos yet." : "No memos match this filter."}</p>}
      <div className="stack" style={{ marginTop: 12 }}>
        {shown.map((r) => (
          <Link key={r.id} href={`/memos/${r.id}`} className="card link">
            <div className="row between wrap">
              <span className="row gap"><strong>{r.reference}</strong><span>{r.company}</span></span>
              <span className="row gap">
                {r.status === "signed" ? <Tag tone="accept">signed</Tag> : <Tag tone="wait">draft</Tag>}
                <span className="muted small">{r.versions} version{r.versions === 1 ? "" : "s"} · {whenLabel(r.updated_at)}</span>
              </span>
            </div>
            <div className="muted small">Case {r.case_id} · owner {r.owner_name}</div>
          </Link>
        ))}
      </div>
    </>
  );
}
