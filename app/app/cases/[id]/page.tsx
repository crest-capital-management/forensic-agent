"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { parseUtc, whenLabel } from "@/lib/time";
import Select from "@/components/Select";
import Loader from "@/components/Loader";
import { EscTag, ReviewTag, Sev, Tag } from "@/components/Badges";
import MemoSection from "@/components/MemoSection";
import TypologySection from "@/components/TypologySection";

export default function CasePage() {
  const { id } = useParams<{ id: string }>();
  const [page, setPage] = useState<any>(null);
  const [err, setErr] = useState("");
  const [sev, setSev] = useState("all");
  const [state, setState] = useState("all");
  const [check, setCheck] = useState("all");

  const [role, setRole] = useState("");
  const [closing, setClosing] = useState(false);
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => api(`/cases/${id}`).then(setPage).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { api("/me").then((m: any) => setRole(m.role)).catch(() => {}); }, []);

  async function change(action: "close" | "reopen") {
    setBusy(true);
    try {
      await api(`/cases/${id}/${action}`, { method: "POST", body: { reason: why } });
      toast.success(action === "close" ? "Case closed" : "Case reopened");
      window.dispatchEvent(new Event("case-changed"));
      setClosing(false); setWhy("");
      await load();
    } catch (e: any) { toast.error(e.message); }
    finally { setBusy(false); }
  }

  if (err) return <p className="error">{err}</p>;
  if (!page) return <Loader label="Loading the case" />;

  const c = page.case;
  const checks: string[] = Array.from(new Set<string>(page.flags.map((f: any) => f.check_id)));
  const flags = page.flags.filter(
    (f: any) =>
      (sev === "all" || f.severity === sev) &&
      (check === "all" || f.check_id === check) &&
      (state === "all" || (state === "unreviewed" ? !f.review : f.review?.decision === state)),
  );
  const draft = page.runs.some((r: any) => !r.config_approved);
  const canClose = ["analyst", "forensic_lead"].includes(role);

  return (
    <>
      <p><Link href="/cases">← Cases</Link></p>
      <div className="row between wrap">
        <h1>Case {c.id} · {c.name || c.company}{c.duplicate_of && <> <Tag tone="plain">duplicate of case {c.duplicate_of}</Tag></>}</h1>
        <span className="row gap">
          <Link className="btn" href={`/analysis/${c.company_id}`}>Multi-year matrix</Link>
          {!c.closure && <Link className="btn primary" href={`/cases/${id}/ask`}>Ask the agent</Link>}
          {canClose && !c.closure && <button className="btn" onClick={() => setClosing(!closing)}>Close case</button>}
        </span>
      </div>

      {closing && !c.closure && (
        <div className="card closeform">
          <strong>Close this case</strong>
          <p className="muted small" style={{ margin: "4px 0 8px" }}>
            A closed case is kept, with its flags, decisions and chats, but no new decisions or questions can be added until it is reopened.
          </p>
          <textarea rows={2} value={why} onChange={(e) => setWhy(e.target.value)} placeholder="Why is this case being closed?" aria-label="Reason for closing" />
          <div className="row gap" style={{ marginTop: 8, justifyContent: "flex-end" }}>
            <button className="btn" onClick={() => { setClosing(false); setWhy(""); }}>Cancel</button>
            <button className="btn primary" disabled={busy || !why.trim()} onClick={() => change("close")}>Close case</button>
          </div>
        </div>
      )}

      {c.closure && (
        <div className="notice closedbar">
          <div>
            <strong>This case is closed.</strong>{" "}
            <span className="muted">{c.closure.by}, {whenLabel(c.closure.at)}: {c.closure.reason}</span>
          </div>
          {canClose && (
            <div className="closedbar-actions">
              {closing ? (
                <>
                  <input type="text" value={why} onChange={(e) => setWhy(e.target.value)} placeholder="Why reopen?" aria-label="Reason for reopening" />
                  <button className="btn primary" disabled={busy || !why.trim()} onClick={() => change("reopen")}>Reopen</button>
                  <button className="btn" onClick={() => { setClosing(false); setWhy(""); }}>Cancel</button>
                </>
              ) : <button className="btn" onClick={() => setClosing(true)}>Reopen case</button>}
            </div>
          )}
        </div>
      )}
      <div className="card">
        <div className="muted">{c.name ? `${c.company} · ` : ""}{c.years.join(", ")} · opened by {c.created_by}</div>
        <p>{c.reason}</p>
        {c.exposure_note && <p className="muted">Exposure: {c.exposure_note}</p>}
        {c.is_portfolio_company && <Tag tone="wait">portfolio company: escalation needs adviser approval</Tag>}
      </div>

      {draft && (
        <p className="notice">
          DRAFT: the limits behind these flags have not been approved by the forensic lead. Treat every flag as a
          lead to look at, not as a result.
        </p>
      )}

      <h2>Flags ({page.counts.total})</h2>
      <p className="muted">
        {page.counts.unreviewed} unreviewed · {page.counts.accepted} accepted · {page.counts.rejected} rejected
      </p>
      <div className="row gap wrap">
        <label className="inline">Severity
          <Select value={sev} onChange={setSev} options={["all", "high", "medium", "low"].map((v) => ({ value: v, label: v }))} />
        </label>
        <label className="inline">Check
          <Select value={check} onChange={setCheck} options={["all", ...checks].map((v) => ({ value: v, label: v }))} />
        </label>
        <label className="inline">Review
          <Select value={state} onChange={setState} options={["all", "unreviewed", "accept", "reject"].map((v) => ({ value: v, label: v }))} />
        </label>
      </div>

      <div className="stack">
        {flags.map((f: any) => (
          <Link key={f.id} href={`/cases/${id}/flags/${f.id}`} className="card link">
            <div className="row between">
              <span className="row gap">
                <Sev v={f.severity} />
                <strong>{f.check_id}</strong>
                <span className="muted">{f.financial_year} · {f.basis}</span>
              </span>
              <span className="row gap"><EscTag esc={f.escalation} /><ReviewTag review={f.review} /></span>
            </div>
            <div>{f.what_observed}</div>
            <div className="muted">
              {f.technique} · materiality: {String(f.materiality).replace("_", " ")} · evidence confidence:{" "}
              {f.evidence_confidence}
            </div>
          </Link>
        ))}
        {flags.length === 0 && <p className="muted">No flags match these filters.</p>}
      </div>

      <TypologySection caseId={id} companyId={c.company_id} role={role} closed={!!c.closure} />

      <MemoSection caseId={id} role={role} accepted={page.counts.accepted} portfolio={c.is_portfolio_company} />

      <h2>Run details</h2>
      <p className="muted">The newest run for each basis. Older runs are kept, never edited. <Link href="/compare">Compare runs →</Link></p>
      <table>
        <thead>
          <tr><th>Run</th><th>Basis</th><th>Years</th><th>Started</th><th>Flags</th><th>Dropped by guardrails</th><th>Config</th></tr>
        </thead>
        <tbody>
          {page.runs.map((r: any) => (
            <tr key={r.id}>
              <td>#{r.id}</td><td>{r.basis}</td><td>{r.years.join(", ")}</td>
              <td>{parseUtc(r.started_at).toLocaleString()}</td>
              <td>{r.flags_created}</td><td>{r.flags_dropped}</td>
              <td>{r.config_approved ? "approved" : "DRAFT"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Data quality notes</h2>
      {page.data_quality_notes.length === 0 ? (
        <p className="muted">No flags were dropped by the guardrails in these runs.</p>
      ) : (
        <ul>
          {page.data_quality_notes.map((n: any, i: number) => (
            <li key={i}>{n.check_id} {n.financial_year || ""}: {n.guardrail} — {n.detail}</li>
          ))}
        </ul>
      )}
    </>
  );
}
