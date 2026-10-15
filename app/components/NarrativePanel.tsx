"use client";

import { ChevronDown, ChevronRight, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { whenLabel } from "@/lib/time";
import { Tag } from "@/components/Badges";
import { CopyButton, Typing } from "@/components/AgentChat";

const CITE = /(\[cell:[^\]\s]+\])/g;
const STEPS = ["Reading the matrix…", "Writing the narrative…", "Checking every cited cell…"];
const STATUS: Record<string, { text: string; tone: string }> = {
  answered: { text: "checked narrative", tone: "accept" },
  blocked: { text: "blocked by a guardrail", tone: "reject" },
  error: { text: "model unavailable", tone: "reject" },
};

type N = { id: number; text: string; status: string; model: string | null; warnings: string[]; created_by: string; created_at: string; sources: { ref: string; label: string }[]; stale: boolean; cached?: boolean; methodology?: string | null };

const MAX = 1500;
const EXAMPLE = "For example: Lean on cash conversion (Sloan) first. Explain Altman zones in more detail. Keep Benford to one line, it is a weak signal for us.";

function Text({ text, onCite }: { text: string; onCite: (ref: string) => void }) {
  return (
    <div className="narr-text">
      {text.split("\n").map((line, i) => (
        <p key={i} className={line.startsWith("- ") ? "narr-li" : ""}>
          {line.split(CITE).map((p, j) => {
            const m = p.match(/^\[(cell:[^\]\s]+)\]$/);
            return m
              ? <button key={j} type="button" className="cite" title="Show this cell in the matrix" onClick={() => onCite(m[1])}>{m[1].replace("cell:", "")}</button>
              : <span key={j}>{p}</span>;
          })}
        </p>
      ))}
    </div>
  );
}

// An AI reading of the matrix below. Written on request (it uses model quota), checked in code, stored, and reused until the matrix changes.
export default function NarrativePanel({ companyId, basis, onCite }: { companyId: string | number; basis: string; onCite: (ref: string) => void }) {
  const [n, setN] = useState<N | null | undefined>(undefined);   // undefined = loading, null = none written yet
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [canWrite, setCanWrite] = useState(false);
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState("");          // the methodology stored for the person working now
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => { api("/me").then((me: any) => setCanWrite(["analyst", "forensic_lead"].includes(me.role))).catch(() => {}); }, []);
  useEffect(() => { api<{ text: string }>("/me/methodology").then((m) => { setSaved(m.text); setDraft(m.text); }).catch(() => {}); }, []);
  const load = useCallback(() => api<N | null>(`/companies/${companyId}/matrix/narrative?basis=${basis}`).then(setN), [companyId, basis]);
  useEffect(() => {
    setN(undefined); setErr("");
    load().catch((e) => { setN(null); setErr(e.message); });
  }, [load]);

  async function saveMethodology(text: string) {
    setSaving(true); setErr("");
    try {
      const m = await api<{ text: string }>("/me/methodology", { method: "PUT", body: { text } });
      setSaved(m.text); setDraft(m.text); setEditing(false);
      toast.success(m.text ? "Your methodology is saved" : "Your methodology is cleared");
      await load();                                  // the stored narrative may now be out of date
    } catch (e: any) { setErr(e.message); }
    finally { setSaving(false); }
  }

  const write = useCallback(async (force: boolean) => {
    setBusy(true); setErr("");
    try { setN(await api<N>(`/companies/${companyId}/matrix/narrative`, { method: "POST", body: { basis, force } })); }
    catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  }, [companyId, basis]);

  const has = !!n;
  return (
    <section className="card narr">
      <div className="row between wrap">
        <div className="row gap">
          <span className="dock-icon"><Sparkles size={16} strokeWidth={1.6} /></span>
          <div>
            <strong>AI narrative</strong>
            <div className="muted small">A plain-language reading of the cells below. It describes and cites; it never concludes.</div>
          </div>
        </div>
        {canWrite && !busy && n !== undefined && (
          <button className={`btn ${has ? "" : "primary"}`} onClick={() => write(has)}>{has ? "Write again" : "Write narrative"}</button>
        )}
      </div>

      <div className="meth">
        <button type="button" className="meth-toggle" aria-expanded={editing} onClick={() => setEditing(!editing)}>
          {editing ? <ChevronDown size={14} /> : <ChevronRight size={14} />} My methodology
          <span className="muted">{saved ? "· saved" : "· not set"}</span>
        </button>
        {editing && (
          <div className="meth-body">
            <p className="muted small">
              Your own notes on how you like a matrix read. They steer what the narrative stresses and in what order, and are saved to
              your user only. They never change a number, a label or an approved limit, and the narrative is still checked in code.
            </p>
            <textarea rows={4} value={draft} maxLength={MAX} placeholder={EXAMPLE} onChange={(e) => setDraft(e.target.value)} aria-label="My methodology" />
            <div className="row between">
              <span className="muted small">{draft.length}/{MAX}</span>
              <div className="row gap">
                {saved && <button className="btn" disabled={saving} onClick={() => saveMethodology("")}>Clear</button>}
                <button className="btn primary" disabled={saving || draft.trim() === saved} onClick={() => saveMethodology(draft)}>Save</button>
              </div>
            </div>
          </div>
        )}
      </div>

      {busy && <div className="narr-busy"><Typing steps={STEPS} /></div>}
      {err && <p className="error small">{err}</p>}
      {n === undefined && !err && <div className="chat-skel"><div className="skel l1" /><div className="skel l2" /><div className="skel l3" /></div>}
      {n === null && !busy && !err && (
        <p className="muted small" style={{ margin: "10px 0 0" }}>
          {canWrite ? "No narrative has been written for this basis yet. It uses one model request (the free daily quota is limited)." : "No narrative has been written for this basis yet. Only an analyst or the forensic lead can write one."}
        </p>
      )}
      {n && !busy && (
        <>
          {n.stale && <p className="notice small">The matrix has changed since this was written (new data or limits). Write it again to refresh it.</p>}
          <div className="row gap wrap" style={{ marginTop: 10 }}>
            <Tag tone={STATUS[n.status]?.tone}>{STATUS[n.status]?.text || n.status}</Tag>
            {n.model && <span className="muted small">{n.model.split(" ")[0]}</span>}
            {n.methodology && <span className="badge" title={n.methodology}>with a methodology</span>}
          </div>
          <Text text={n.text} onCite={onCite} />
          {n.warnings.map((w, i) => <p key={i} className="notice small">{w}</p>)}
          <div className="stamp-row">
            <CopyButton text={n.text} />
            <span className="stamp">Written {whenLabel(n.created_at)} by {n.created_by}</span>
          </div>
        </>
      )}
    </section>
  );
}
