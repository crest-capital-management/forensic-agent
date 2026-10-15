"use client";

import { Download, Plus, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { whenLabel } from "@/lib/time";
import Loader from "@/components/Loader";
import Select from "@/components/Select";
import { Sev, Tag } from "@/components/Badges";

const PUBLIC_WORDS: Record<string, string> = { yes: "public data can close this", partly: "public data can partly close this", no: "public data cannot close this" };
const lines = (t: string) => t.split("\n").map((x) => x.trim()).filter(Boolean);

type Q = { text: string; public_data: string; how: string; check_id: string | null };

export default function MemoPage() {
  const { id } = useParams<{ id: string }>();
  const [m, setM] = useState<any>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState("");
  const [scope, setScope] = useState("");
  const [background, setBackground] = useState("");
  const [findings, setFindings] = useState<Record<string, string>>({});
  const [questions, setQuestions] = useState<Q[]>([]);
  const [pub, setPub] = useState("");
  const [eng, setEng] = useState("");
  const [annexD, setAnnexD] = useState("");
  const [signing, setSigning] = useState(false);

  const load = (version?: number) =>
    api(`/memos/${id}${version ? `?version=${version}` : ""}`).then(setM).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (err) return <p className="error">{err}</p>;
  if (!m) return <Loader label="Loading the memo" />;

  const c = m.content;
  const h = c.header;
  const isLatest = m.shown_version_no === m.latest_version_no;

  function startEdit() {
    setScope(c.scope.join("\n")); setBackground(c.background.join("\n"));
    setFindings(Object.fromEntries(c.findings.map((f: any) => [String(f.flag_id), f.text])));
    setQuestions(c.open_questions.map((q: Q) => ({ ...q })));
    setPub(c.next_steps.public.join("\n")); setEng(c.next_steps.engagement.join("\n"));
    setAnnexD(c.annex_d.supplied ? c.annex_d.text : ""); setNote(""); setEditing(true);
  }

  async function run(fn: () => Promise<any>, ok: string) {
    setBusy(true);
    try { const out = await fn(); setM(out); toast.success(ok); return true; }
    catch (e: any) { toast.error(e.message); return false; }
    finally { setBusy(false); }
  }

  async function save() {
    const changes = { scope: lines(scope), background: lines(background), findings, open_questions: questions,
                      next_steps: { public: lines(pub), engagement: lines(eng) }, annex_d: annexD };
    if (await run(() => api(`/memos/${id}`, { method: "PUT", body: { changes, note } }), "Saved as a new version")) setEditing(false);
  }

  const versionOptions = m.versions.map((v: any) => ({ value: v.version_no, label: `Version ${v.version_no}${v.version_no === m.latest_version_no ? " (latest)" : ""}` }));

  return (
    <>
      <p><Link href={`/cases/${m.case_id}`}>← Case {m.case_id}</Link></p>
      <div className="row between wrap">
        <div>
          <h1 style={{ marginBottom: 2 }}>Research assessment memo</h1>
          <span className="muted">{m.reference} · {h.company} ({h.symbol}) · owner {m.owner_name}</span>
        </div>
        <span className="row gap wrap">
          <Select value={m.shown_version_no} onChange={(v) => { setEditing(false); load(Number(v)); }} options={versionOptions} ariaLabel="Version" />
          <a className="btn" href={`/api/memos/${id}/export.docx?version=${m.shown_version_no}`}><Download size={15} /> Word file</a>
          <a className="btn" href={`/api/memos/${id}/export.pdf?version=${m.shown_version_no}`}><Download size={15} /> PDF file</a>
        </span>
      </div>

      <p className="notice" style={{ marginTop: 12 }}><strong>{m.banner}</strong>{m.status === "draft" ? ". Not final: a named person must review, edit and sign it. It stays inside CREST." : ". This memo is locked."}</p>
      <p className={h.limits_approved ? "muted small" : "notice small"}>{h.limits_line}</p>
      {c.notices.map((n: string) => <p key={n} className="notice small">{n}</p>)}
      {m.out_of_date && (
        <div className="notice closedbar">
          <div><strong>Out of date.</strong> A flag decision, the scope or the limits changed since this draft was made. Regenerate it and review it again before signing.</div>
          {m.can_edit && <div className="closedbar-actions"><button className="btn primary" disabled={busy} onClick={() => run(() => api(`/memos/${id}/regenerate`, { method: "POST", body: { note: "" } }), "Regenerated as a new version")}>Regenerate</button></div>}
        </div>
      )}
      {m.left_out.length > 0 && (
        <p className="muted small">Left out for now: {m.left_out.map((l: any) => `${l.check_id} ${l.financial_year} (${l.reason})`).join("; ")}.</p>
      )}
      {!isLatest && <p className="muted small">You are reading an older version. Switch to the latest to edit.</p>}

      {m.can_edit && isLatest && !editing && (
        <div className="row gap wrap" style={{ margin: "8px 0" }}>
          <button className="btn" onClick={startEdit}>Edit</button>
          {!m.out_of_date && <button className="btn" disabled={busy} onClick={() => run(() => api(`/memos/${id}/regenerate`, { method: "POST", body: { note: "" } }), "Regenerated as a new version")}>Regenerate from current flags</button>}
          {m.can_sign && <button className="btn primary" disabled={busy || m.out_of_date} onClick={() => setSigning(true)}>Sign</button>}
        </div>
      )}
      {signing && (
        <div className="card closeform">
          <strong>Sign this memo</strong>
          <p className="muted small" style={{ margin: "4px 0 8px" }}>You sign version {m.latest_version_no} as its named owner. Signing locks the memo; to change it afterwards you start a new one. Signing does not send it anywhere.</p>
          <div className="row gap" style={{ justifyContent: "flex-end" }}>
            <button className="btn" onClick={() => setSigning(false)}>Cancel</button>
            <button className="btn primary" disabled={busy} onClick={async () => { if (await run(() => api(`/memos/${id}/sign`, { method: "POST" }), "Memo signed")) setSigning(false); }}>Sign memo</button>
          </div>
        </div>
      )}

      <div className="card">
        <table className="assets"><tbody>
          <tr><td>Reference</td><td>{m.reference}</td></tr>
          <tr><td>Case</td><td>#{m.case_id}</td></tr>
          <tr><td>Years in scope</td><td>{h.years.join(", ")}</td></tr>
          <tr><td>Basis</td><td>{h.bases.join(", ")}</td></tr>
          <tr><td>Version</td><td>{m.shown_version_no} of {m.latest_version_no}</td></tr>
          <tr><td>Data as of</td><td>{h.data_as_of}</td></tr>
        </tbody></table>
      </div>

      <h2>1. Assessment scope and objective</h2>
      {editing ? <textarea rows={5} value={scope} onChange={(e) => setScope(e.target.value)} aria-label="Scope" /> : c.scope.map((t: string, i: number) => <p key={i}>{t}</p>)}

      <h2>2. Background and trigger</h2>
      {editing ? <textarea rows={4} value={background} onChange={(e) => setBackground(e.target.value)} aria-label="Background" /> : c.background.map((t: string, i: number) => <p key={i}>{t}</p>)}

      <h2>3. Findings summary ({c.findings.length})</h2>
      <div className="stack">
        {c.findings.map((f: any, i: number) => (
          <div key={f.flag_id} className="card">
            <div className="row gap wrap">
              <strong>Finding {i + 1}</strong><Sev v={f.severity} /><span className="muted">{f.check_id} · {f.financial_year} · {f.basis} · materiality {String(f.materiality).replace("_", " ")}</span>
              <Link className="small" href={`/cases/${m.case_id}/flags/${f.flag_id}`}>flag {f.flag_id} →</Link>
            </div>
            {editing
              ? <textarea rows={3} value={findings[String(f.flag_id)] ?? ""} onChange={(e) => setFindings({ ...findings, [String(f.flag_id)]: e.target.value })} aria-label={`Finding ${i + 1} text`} />
              : <p>{f.text}</p>}
            <p className="muted small">{f.limit_line}</p>
            <p className="small">Accepted by <strong>{f.reviewer.by_name || f.reviewer.by}</strong> on {whenLabel(f.reviewer.at)}: &ldquo;{f.reviewer.reason}&rdquo;{f.reviewer.carried_from_earlier_run ? " (decision carried over from an earlier identical flag)" : ""}</p>
            <ul className="small">
              {f.sources.map((s: any) => <li key={s.ref}><code>{s.ref}</code> {s.label}{s.quote ? <> — &ldquo;{s.quote}&rdquo;</> : null}</li>)}
            </ul>
            <p className="muted small"><em>{f.standing_line}</em></p>
          </div>
        ))}
      </div>

      <h2>4. Open questions and gaps</h2>
      {editing ? (
        <div className="stack">
          {questions.map((q, i) => (
            <div key={i} className="card form">
              <input type="text" value={q.text} onChange={(e) => setQuestions(questions.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} placeholder="Question" aria-label={`Question ${i + 1}`} />
              <div className="row gap wrap">
                <Select value={q.public_data} onChange={(v) => setQuestions(questions.map((x, j) => (j === i ? { ...x, public_data: v } : x)))}
                        options={Object.entries(PUBLIC_WORDS).map(([value, label]) => ({ value, label }))} />
                <input type="text" value={q.how} onChange={(e) => setQuestions(questions.map((x, j) => (j === i ? { ...x, how: e.target.value } : x)))} placeholder="How, or what would be needed" aria-label={`How for question ${i + 1}`} style={{ flex: 1, minWidth: 220 }} />
                <button className="icon-btn" aria-label="Remove question" onClick={() => setQuestions(questions.filter((_, j) => j !== i))}><X size={16} /></button>
              </div>
            </div>
          ))}
          <button className="btn" onClick={() => setQuestions([...questions, { text: "", public_data: "no", how: "", check_id: null }])}><Plus size={15} /> Add a question</button>
        </div>
      ) : (
        <ul>{c.open_questions.map((q: Q, i: number) => <li key={i}>{q.text} <span className="muted">({PUBLIC_WORDS[q.public_data]}: {q.how})</span></li>)}</ul>
      )}

      <h2>5. Recommended next steps</h2>
      <h3>Possible on public data</h3>
      {editing ? <textarea rows={4} value={pub} onChange={(e) => setPub(e.target.value)} aria-label="Next steps on public data (one per line)" /> : <ul>{c.next_steps.public.map((s: string, i: number) => <li key={i}>{s}</li>)}</ul>}
      <h3>What a formal engagement with data access would need</h3>
      {editing ? <textarea rows={4} value={eng} onChange={(e) => setEng(e.target.value)} aria-label="Next steps needing an engagement (one per line)" /> : <ul>{c.next_steps.engagement.map((s: string, i: number) => <li key={i}>{s}</li>)}</ul>}
      {editing && <p className="muted small">One step per line.</p>}

      <h2>6. Ownership and sign-off</h2>
      <p>Owner: <strong>{m.owner_name}</strong></p>
      <p>{c.ownership.note}</p>
      <p>{m.status === "signed" ? `Signed by ${m.owner_name} on ${m.signed_at.slice(0, 10)} (version ${m.signed_version_no}).` : "Signature: not yet signed."}</p>

      <h2>Annexes</h2>
      <h3>A. Method and limits</h3>
      <ul className="small">
        <li>Checks used: {c.annex_a.checks.map((x: any) => `${x.check_id} ${x.name}`).join(", ")}</li>
        {c.annex_a.runs.map((r: any) => <li key={r.run_id}>Run {r.run_id} ({r.basis}), years {r.years.join(", ")}, limits approved: {r.config_approved ? "yes" : "no"}, code {r.code_version}</li>)}
        <li>Source precedence: {c.annex_a.source_rule}.</li>
        <li>{c.annex_a.library_line}</li>
      </ul>
      <h3>B. Citations</h3>
      <ul className="small">{Array.from(new Map<string, any>(c.annex_b.map((s: any) => [s.ref, s])).values()).map((s: any) => <li key={s.ref}><code>{s.ref}</code> {s.label}</li>)}</ul>
      <h3>C. Change log</h3>
      <ul className="small">{m.versions.map((v: any) => <li key={v.version_no}>Version {v.version_no} ({v.kind}), {whenLabel(v.created_at)}, by {v.created_by_name || v.created_by}: {v.change_note}</li>)}</ul>
      <h3>D. Documentation references (ICAI FAIS, SEBI RIA)</h3>
      {editing ? <textarea rows={3} value={annexD} onChange={(e) => setAnnexD(e.target.value)} placeholder="Paste the ICAI FAIS references and the SEBI RIA record-keeping note" aria-label="Annex D" /> : <p>{c.annex_d.text}</p>}
      {c.annex_e && (
        <>
          <h3>E. Scheme hypotheses (Job 3)</h3>
          <p className="small">{c.annex_e.line}</p>
          {c.annex_e.matches.map((h: any) => (
            <div key={h.match_id} className="card">
              <strong>{h.scheme_id} {h.scheme_name}</strong> <span className="muted small">{h.class_label} · hypothesis · {h.coverage_pct}% of indicators present · accepted by {h.lead}{h.partner ? ` and ${h.partner}` : ""}</span>
              <ul className="small">
                {h.present.map((p: any, i: number) => <li key={i}>Present: {p.indicator} ({p.detail})</li>)}
                <li>Missing: {h.missing.join("; ") || "none"}</li>
                <li>Facts that cut against it: {h.against.join("; ")}</li>
                <li>Common innocent explanations: {h.innocent.join("; ")}</li>
                <li>Evidence that would confirm or refute it: {h.evidence.map((x: any) => `${x.text} (${x.public ? "public" : "not public"})`).join("; ")}</li>
                <li>References: {(c.annex_e.references[h.scheme_id] || []).join("; ")}</li>
              </ul>
            </div>
          ))}
        </>
      )}

      {editing && (
        <div className="card closeform">
          <strong>Save as a new version</strong>
          <p className="muted small" style={{ margin: "4px 0 8px" }}>The earlier version is kept. Sources, figures, reviewer decisions and the DRAFT line cannot be edited. A number you type into a finding must appear in its cited sources.</p>
          <input type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder="What did you change?" aria-label="Change note" />
          <div className="row gap" style={{ marginTop: 8, justifyContent: "flex-end" }}>
            <button className="btn" onClick={() => setEditing(false)}>Cancel</button>
            <button className="btn primary" disabled={busy || !note.trim()} onClick={save}>Save version</button>
          </div>
        </div>
      )}

      <ul className="muted small">{c.standing.map((s: string) => <li key={s}>{s}</li>)}</ul>
    </>
  );
}
