"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { parseUtc } from "@/lib/time";
import Loader from "@/components/Loader";
import { EscTag, ReviewTag, Sev, Tag } from "@/components/Badges";

// Source values are stored in rupees; people read them in crore.
function crore(v: unknown) {
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  return Math.abs(n) >= 1e7 ? `₹${(n / 1e7).toLocaleString("en-IN", { maximumFractionDigits: 0 })} cr` : n.toLocaleString("en-IN");
}

function Kv({ data }: { data: Record<string, any> }) {
  const rows = Object.entries(data)
    .filter(([, v]) => v === null || typeof v !== "object" || Array.isArray(v))
    .map(([k, v]) => [k, Array.isArray(v) ? v.join(", ") : v] as [string, any]);
  return (
    <table>
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}><th>{k.replace(/_/g, " ")}</th><td>{String(v)}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

export default function FlagPage() {
  const { id, flagId } = useParams<{ id: string; flagId: string }>();
  const [f, setF] = useState<any>(null);
  const [me, setMe] = useState<any>(null);
  const [err, setErr] = useState("");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(() => {
    api(`/cases/${id}/flags/${flagId}`).then(setF).catch((e) => setErr(e.message));
    api("/me").then(setMe).catch(() => {});
  }, [id, flagId]);
  useEffect(load, [load]);

  async function act(path: string, body?: unknown) {
    setErr("");
    try {
      await api(path, { method: "POST", body });
      setReason("");
      setNote("");
      toast.success(path.includes("/review") ? "Decision saved" : path.includes("/escalate") ? "Escalation requested" : "Escalation approved");
      load();
    } catch (e: any) {
      setErr(e.message);
      toast.error(e.message);
    }
  }

  if (!f) return err ? <p className="error">{err}</p> : <Loader label="Loading this flag" />;
  const cit = f.citation || {};
  const canReview = me && ["analyst", "forensic_lead"].includes(me.role);
  const canApprove = me && me.role === "adviser";

  return (
    <>
      <p><Link href={`/cases/${id}`}>← Back to case</Link></p>
      <div className="row gap wrap">
        <Sev v={f.severity} />
        <h1 style={{ margin: 0 }}>{f.check_id}</h1>
        <span className="muted">{f.financial_year} · {f.basis}</span>
        <ReviewTag review={f.review} />
        <EscTag esc={f.escalation} />
        {f.draft_config && <Tag tone="wait">DRAFT limits</Tag>}
      </div>

      {f.review?.carried_from && (
        <p className="notice">
          This flag is identical to one already reviewed in run {f.review.carried_from.run_id} (flag #{f.review.carried_from.flag_id}): same figures,
          evidence and severity. That decision ({f.review.decision === "accept" ? "accepted" : "rejected"} by {f.review.reviewer}: {f.review.reason}) is shown
          here, but nobody has looked at this run&apos;s flag yet. Accept or reject it below to confirm or change the decision.
        </p>
      )}

      <p className="notice">{f.disclaimer}</p>

      <div className="card">
        <h2>What was observed</h2>
        <p>{f.what_observed}</p>
        <h3>Where</h3>
        <Kv data={f.location} />
        {f.location?.pages && <p className="muted">Pages: {f.location.pages.join(", ")}</p>}
        <h3>Technique</h3>
        <p>{f.technique}</p>
        <h3>Severity</h3>
        <p>
          {f.severity} · rule {f.severity_rule_id} · materiality: {String(f.materiality).replace("_", " ")} · evidence
          confidence: {f.evidence_confidence}
        </p>
        <p className="muted">Severity, materiality and evidence confidence are three separate things.</p>
      </div>

      <div className="card">
        <h2>Figures</h2>
        <Kv data={f.figures} />
        {f.materiality_detail && (<><h3>Materiality</h3><Kv data={f.materiality_detail} /></>)}
      </div>

      <div className="card">
        <h2>Source and citation</h2>
        <p className="muted">{cit.company} · {cit.basis}</p>
        {(cit.evidence || []).map((e: any, i: number) =>
          e.kind === "digit_test" ? (
            <div key={i}>
              <p>
                Leading digits of {Number(e.n).toLocaleString("en-IN")} distinct amounts in the {Object.keys(e.sections).map((k) => k.replace(/_/g, " ")).join(", ")} of{" "}
                {e.file_name} ({e.fy}). Each distinct amount is counted once.
              </p>
              <table>
                <thead><tr><th>First digit</th>{e.counts.map((_: number, d: number) => <th key={d}>{d + 1}</th>)}</tr></thead>
                <tbody>
                  <tr><th>Count</th>{e.counts.map((c: number, d: number) => <td key={d}>{c}</td>)}</tr>
                  <tr><th>Share seen</th>{(f.figures.digit_share || []).map((v: number, d: number) => <td key={d}>{(v * 100).toFixed(1)}%</td>)}</tr>
                  <tr><th>Share expected</th>{(f.figures.expected_share || []).map((v: number, d: number) => <td key={d}>{(v * 100).toFixed(1)}%</td>)}</tr>
                </tbody>
              </table>
              <p className="muted small">
                Pages {Object.entries(e.sections).map(([k, v]: any) => `${k.replace(/_/g, " ")} ${v[0]}–${v[1]}`).join("; ")} · document hash{" "}
                {String(e.document_sha256).slice(0, 12)}. A weak, low-confidence signal: many ordinary figures do not follow the pattern.
              </p>
            </div>
          ) : (
            <blockquote key={i}>
              “{e.quote}”
              <footer>
                {e.file_name} · PDF page {e.page}{e.printed_page ? ` (printed page ${e.printed_page})` : ""} · {e.fy} ·
                document hash {String(e.document_sha256).slice(0, 12)}
              </footer>
            </blockquote>
          ),
        )}
        {(cit.inputs || []).length > 0 && (
          <table>
            <thead><tr><th>Input</th><th>Year</th><th>Value</th><th>Source</th><th>Agreement</th></tr></thead>
            <tbody>
              {cit.inputs.map((x: any, i: number) => (
                <tr key={i}>
                  <td>{x.field}</td><td>{x.fy}</td><td>{crore(x.value)}</td>
                  <td>{(x.providers || [x.provider]).join(", ")}</td><td>{x.resolution}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted">Flag fingerprint {String(f.content_hash).slice(0, 16)} · run #{f.run_id}</p>
      </div>

      <div className="card">
        <h2>Your decision</h2>
        {canReview ? (
          <>
            <label>Reason (required)
              <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} />
            </label>
            <div className="row gap">
              <button className="btn primary" onClick={() => act(`/cases/${id}/flags/${flagId}/review`, { decision: "accept", reason })}>
                Accept: worth investigating
              </button>
              <button className="btn" onClick={() => act(`/cases/${id}/flags/${flagId}/review`, { decision: "reject", reason })}>
                Reject: not worth investigating
              </button>
            </div>
          </>
        ) : (
          <p className="muted">Your role ({me?.role}) cannot accept or reject flags.</p>
        )}
        {err && <p className="error">{err}</p>}

        {f.history.length > 0 && (
          <>
            <h3>Decision history</h3>
            <ul>
              {f.history.map((h: any, i: number) => (
                <li key={i}>
                  <strong>{h.decision}</strong> by {h.reviewer}, {parseUtc(h.decided_at).toLocaleString()}: {h.reason}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      <div className="card">
        <h2>Escalation</h2>
        {f.escalation ? (
          <>
            <p>
              Requested by {f.escalation.requested_by}: {f.escalation.note}
            </p>
            {f.escalation.state === "awaiting_adviser" ? (
              canApprove ? (
                <button className="btn primary" onClick={() => act(`/escalations/${f.escalation.id}/approve`)}>
                  Approve escalation (adviser)
                </button>
              ) : (
                <p className="muted">Portfolio company: waiting for the adviser&apos;s approval.</p>
              )
            ) : (
              <p>Escalated{f.escalation.adviser_approval_by ? `, approved by ${f.escalation.adviser_approval_by}` : ""}.</p>
            )}
          </>
        ) : f.review?.decision === "accept" && canReview ? (
          <>
            <label>Note for escalation (required)
              <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} />
            </label>
            <button className="btn" onClick={() => act(`/cases/${id}/flags/${flagId}/escalate`, { note })}>
              Request escalation
            </button>
          </>
        ) : (
          <p className="muted">Only an accepted flag can be escalated.</p>
        )}
      </div>
    </>
  );
}
