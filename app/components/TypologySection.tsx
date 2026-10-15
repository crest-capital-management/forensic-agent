"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { whenLabel } from "@/lib/time";
import Select from "@/components/Select";
import { Tag } from "@/components/Badges";

type Present = { indicator: string; source: string; check_id?: string; detail: string; what: string };
type Missing = { indicator: string; why: string };
type Evidence = { text: string; public: boolean };
type Ref = { title: string; locator: string; verified: string };
type Match = {
  id: number; scheme_id: string; scheme_name: string; class_label: string; coverage: number;
  present: Present[]; missing: Missing[]; against: string[]; innocent_explanations: string[]; evidence_to_confirm: Evidence[];
  citations: { acfe: Ref[]; fais: Ref[] }; named_individual: boolean; notice: string; created_at: string;
  review: { status: string; by: string | null; note: string | null };
  partner: { status: string; by: string | null; note: string | null };
};
type Preview = { scheme_id: string; scheme_name: string; class_label: string; present: number; total: number; ranked: boolean };
type Rec = { id: number; kind: string; title: string; source_name: string; url: string | null; published_on: string | null; summary: string; tags: string[]; names_individual: boolean; added_by: string };
type Overview = {
  notice: string; min_present: number; counted_flags: number; left_out: { unreviewed: number; rejected: number; not_material: number };
  saved_batch: number | null; stale: boolean; matches: Match[]; preview: Preview[]; records: Rec[]; record_tags: string[];
};

const KINDS = [
  { value: "enforcement_order", label: "Regulator or exchange order" },
  { value: "tribunal", label: "Tribunal or court ruling" },
  { value: "announcement", label: "Exchange announcement" },
  { value: "news", label: "Credible news report" },
  { value: "filing_analysis", label: "Reading of a filing" },
  { value: "other", label: "Other public source" },
];

function statusTag(s: string) {
  if (s === "accepted") return <Tag tone="accept">accepted</Tag>;
  if (s === "rejected") return <Tag tone="reject">rejected</Tag>;
  if (s === "not_needed") return null;
  return <Tag tone="wait">awaiting review</Tag>;
}

// Job 3: which known patterns do the accepted flags resemble? Every result is a hypothesis for the lead to review.
export default function TypologySection({ caseId, companyId, role, closed }: { caseId: number | string; companyId: number; role: string; closed: boolean }) {
  const [ov, setOv] = useState<Overview | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const canRun = ["analyst", "forensic_lead"].includes(role) && !closed;
  const canAdd = ["analyst", "forensic_lead"].includes(role);

  const load = useCallback(() => { api<Overview>(`/cases/${caseId}/typology`).then(setOv).catch((e) => toast.error(e.message)); }, [caseId]);
  useEffect(load, [load]);

  async function run() {
    setBusy(true);
    try {
      const out = await api<Overview & { unchanged: boolean; ranked_now?: number }>(`/cases/${caseId}/typology/run`, { method: "POST" });
      setOv(out);
      toast.success(out.unchanged ? "Nothing changed since the last run" : `${out.ranked_now ?? 0} scheme(s) ranked`);
    } catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  }

  if (!ov) return null;
  const lo = ov.left_out;
  return (
    <>
      <div className="row between wrap" style={{ marginTop: 24 }}>
        <h2>Scheme matches (hypotheses)</h2>
        {canRun && <button className="btn" onClick={run} disabled={busy}>{ov.saved_batch ? "Run matching again" : "Run matching"}</button>}
      </div>
      <p className="muted small" style={{ marginTop: 0 }}>
        {ov.notice} Only flags a reviewer accepted count ({ov.counted_flags} so far; left out: {lo.unreviewed} unreviewed, {lo.rejected} rejected, {lo.not_material} not material).
        A scheme is ranked only when at least {ov.min_present} of its indicators are present.
      </p>
      {ov.stale && <p className="notice">The flag decisions or the public-record items changed since the last run. Run the matching again.</p>}

      <details className="card">
        <summary><strong>Coverage of every scheme</strong> <span className="muted small">(live view, nothing is saved until you run)</span></summary>
        <table className="matrix" style={{ marginTop: 8 }}>
          <thead><tr><th className="mname">Scheme</th><th>Indicators present</th><th>Ranked</th></tr></thead>
          <tbody>
            {ov.preview.map((p) => (
              <tr key={p.scheme_id}>
                <td className="mname"><strong>{p.scheme_id}</strong> {p.scheme_name}<div className="muted small">{p.class_label}</div></td>
                <td>{p.present} of {p.total}</td>
                <td>{p.ranked ? <Tag tone="accept">yes</Tag> : <span className="muted">no</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      {ov.saved_batch && ov.matches.length === 0 && <p className="muted">The last run (batch {ov.saved_batch}) ranked no scheme: fewer than {ov.min_present} indicators are present for each.</p>}
      {!ov.saved_batch && <p className="muted">No matching has been run for this case yet.</p>}

      <div className="stack">
        {ov.matches.map((m) => (
          <MatchCard key={m.id} m={m} role={role} open={open === m.id} onToggle={() => setOpen(open === m.id ? null : m.id)} onChanged={load} />
        ))}
      </div>

      <RecordPanel companyId={companyId} ov={ov} canAdd={canAdd} onChanged={load} />
    </>
  );
}

function MatchCard({ m, role, open, onToggle, onChanged }: { m: Match; role: string; open: boolean; onToggle: () => void; onChanged: () => void }) {
  const [note, setNote] = useState("");
  const [verified, setVerified] = useState(false);
  const [busy, setBusy] = useState(false);
  const total = m.present.length + m.missing.length;

  async function review(path: string, decision: string, body: object) {
    setBusy(true);
    try { await api(path, { method: "POST", body: { decision, note, ...body } }); toast.success("Saved"); setNote(""); onChanged(); }
    catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  }

  return (
    <div className="card">
      <div className="row between wrap" onClick={onToggle} style={{ cursor: "pointer" }}>
        <span className="row gap wrap">
          <strong>{m.scheme_id}</strong><span>{m.scheme_name}</span><Tag>hypothesis</Tag>
          {m.named_individual && <Tag tone="esc">names an individual: partner review</Tag>}
        </span>
        <span className="row gap">
          <span className="muted small">{m.present.length} of {total} indicators ({Math.round(m.coverage * 100)}%)</span>
          {statusTag(m.review.status)}
        </span>
      </div>
      {open && (
        <div className="stack" style={{ marginTop: 10 }}>
          <p className="muted small">{m.class_label}. {m.notice}</p>
          <div><strong>Indicators present</strong>
            <ul>{m.present.map((p, i) => <li key={i}>{p.indicator} <span className="muted small">({p.source === "flag" ? `${p.check_id}: ${p.detail}` : `public record: ${p.detail}`})</span></li>)}</ul></div>
          <details><summary><strong>Indicators missing ({m.missing.length})</strong></summary>
            <ul>{m.missing.map((x, i) => <li key={i}>{x.indicator} <span className="muted small">({x.why})</span></li>)}</ul></details>
          <details><summary><strong>Facts that cut against it ({m.against.length})</strong></summary>
            <ul>{m.against.map((a, i) => <li key={i}>{a}</li>)}</ul></details>
          <details><summary><strong>Common innocent explanations</strong></summary>
            <ul>{m.innocent_explanations.map((a, i) => <li key={i}>{a}</li>)}</ul></details>
          <details><summary><strong>Evidence that would confirm or refute it</strong></summary>
            <ul>{m.evidence_to_confirm.map((e, i) => <li key={i}>{e.text} {e.public ? <Tag tone="accept">public</Tag> : <Tag tone="wait">not public: needs access to the company</Tag>}</li>)}</ul></details>
          <details><summary><strong>References</strong></summary>
            <ul>
              {[...m.citations.acfe, ...m.citations.fais].map((c, i) => <li key={i}>{c.title}: {c.locator} <span className="muted small">({c.verified})</span></li>)}
            </ul></details>

          <div className="muted small">Run by {whenLabel(m.created_at)}. Lead review: {m.review.status}{m.review.by ? ` by ${m.review.by}` : ""}{m.review.note ? `: ${m.review.note}` : ""}
            {m.partner.status !== "not_needed" && ` · Partner review: ${m.partner.status}${m.partner.by ? ` by ${m.partner.by}` : ""}${m.partner.note ? `: ${m.partner.note}` : ""}`}</div>

          {(role === "forensic_lead" || (role === "partner" && m.partner.status === "pending")) && (
            <div className="card form narrowform">
              <strong>{role === "partner" ? "Partner review" : "Review this match"}</strong>
              <label>Reason
                <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why it is or is not worth pursuing" />
              </label>
              {role === "forensic_lead" && (
                <label className="row gap"><input type="checkbox" checked={verified} onChange={(e) => setVerified(e.target.checked)} /> I have checked the ACFE and FAIS references</label>
              )}
              <div className="row gap" style={{ justifyContent: "flex-end" }}>
                <button className="btn" disabled={busy || !note.trim()} onClick={() => review(role === "partner" ? `/typology/${m.id}/partner-review` : `/typology/${m.id}/review`, "rejected", { citations_verified: verified })}>Reject</button>
                <button className="btn primary" disabled={busy || !note.trim() || (role === "forensic_lead" && !verified)} onClick={() => review(role === "partner" ? `/typology/${m.id}/partner-review` : `/typology/${m.id}/review`, "accepted", { citations_verified: verified })}>Accept</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RecordPanel({ companyId, ov, canAdd, onChanged }: { companyId: number; ov: Overview; canAdd: boolean; onChanged: () => void }) {
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ kind: "enforcement_order", title: "", source_name: "", url: "", published_on: "", summary: "", names_individual: false });
  const [tags, setTags] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  async function add() {
    setBusy(true);
    try {
      await api(`/companies/${companyId}/public-records`, { method: "POST", body: { ...f, tags, url: f.url || null, published_on: f.published_on || null } });
      toast.success("Added");
      setAdding(false); setTags([]); setF({ ...f, title: "", url: "", published_on: "", summary: "", names_individual: false });
      onChanged();
    } catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  }

  return (
    <>
      <div className="row between wrap" style={{ marginTop: 16 }}>
        <h3 style={{ margin: 0 }}>Public-record items ({ov.records.length})</h3>
        {canAdd && <button className="btn" onClick={() => setAdding(!adding)}>Add an item</button>}
      </div>
      <p className="muted small" style={{ marginTop: 4 }}>Facts from regulator orders, tribunal rulings, exchange announcements or credible news, added by a person with the source. The tool does not search the web by itself. Describe what the source says, not a conclusion.</p>
      {adding && (
        <div className="card form narrowform">
          <label>Kind<Select value={f.kind} onChange={(v) => setF({ ...f, kind: v })} options={KINDS} /></label>
          <label>Title<input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></label>
          <label>Source (name of the regulator, exchange or publication)<input value={f.source_name} onChange={(e) => setF({ ...f, source_name: e.target.value })} /></label>
          <label>Link (optional)<input value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} /></label>
          <label>Date (optional, YYYY-MM-DD)<input value={f.published_on} onChange={(e) => setF({ ...f, published_on: e.target.value })} /></label>
          <label>What the source says (under 600 characters)<textarea rows={3} value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} /></label>
          <div><strong className="small">Which indicator does it speak to?</strong>
            <div className="stack">{ov.record_tags.map((t) => (
              <label key={t} className="row gap"><input type="checkbox" checked={tags.includes(t)} onChange={(e) => setTags(e.target.checked ? [...tags, t] : tags.filter((x) => x !== t))} /> {t.replace(/_/g, " ")}</label>
            ))}</div></div>
          <label className="row gap"><input type="checkbox" checked={f.names_individual} onChange={(e) => setF({ ...f, names_individual: e.target.checked })} /> The item names an individual (a partner must review any match that uses it)</label>
          <div className="row gap" style={{ justifyContent: "flex-end" }}>
            <button className="btn" onClick={() => setAdding(false)}>Cancel</button>
            <button className="btn primary" disabled={busy || !f.title || !f.source_name || !f.summary || tags.length === 0} onClick={add}>Add item</button>
          </div>
        </div>
      )}
      <div className="stack">
        {ov.records.map((r) => (
          <div key={r.id} className="card">
            <div className="row between wrap"><strong>{r.title}</strong><span className="muted small">{r.source_name}{r.published_on ? ` · ${r.published_on}` : ""} · added by {r.added_by}</span></div>
            <p style={{ margin: "4px 0" }}>{r.summary}</p>
            <div className="row gap wrap">{r.tags.map((t) => <Tag key={t}>{t.replace(/_/g, " ")}</Tag>)}{r.names_individual && <Tag tone="esc">names an individual</Tag>}
              {r.url && <a href={r.url} target="_blank" rel="noopener noreferrer" className="small">source link</a>}</div>
          </div>
        ))}
      </div>
    </>
  );
}
