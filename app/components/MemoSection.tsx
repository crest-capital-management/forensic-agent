"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { whenLabel } from "@/lib/time";
import Select from "@/components/Select";
import { Tag } from "@/components/Badges";

type MemoRow = { id: number; reference: string; owner_name: string; status: string; versions: number; updated_at: string };
type Owner = { username: string; display_name: string; role: string };

// Job 4: research memos for a case. A memo uses only flags a reviewer accepted.
export default function MemoSection({ caseId, role, accepted, portfolio = false }: { caseId: number | string; role: string; accepted: number; portfolio?: boolean }) {
  const router = useRouter();
  const [memos, setMemos] = useState<MemoRow[] | null>(null);
  const [owners, setOwners] = useState<Owner[]>([]);
  const [creating, setCreating] = useState(false);
  const [owner, setOwner] = useState("");
  const [scope, setScope] = useState("");
  const [busy, setBusy] = useState(false);
  const canCreate = ["analyst", "forensic_lead", "memo_owner"].includes(role);

  useEffect(() => { api<MemoRow[]>(`/cases/${caseId}/memos`).then(setMemos).catch(() => setMemos([])); }, [caseId]);
  useEffect(() => { api<Owner[]>("/memo-owners").then((o) => { setOwners(o); if (o[0]) setOwner((cur) => cur || o[0].username); }).catch(() => {}); }, []);

  async function create() {
    setBusy(true);
    try {
      const m = await api<{ id: number }>(`/cases/${caseId}/memos`, { method: "POST", body: { owner, scope_note: scope } });
      toast.success("Memo drafted");
      router.push(`/memos/${m.id}`);
    } catch (e: any) { toast.error(e.message); setBusy(false); }
  }

  return (
    <>
      <div className="row between wrap">
        <h2>Research memos</h2>
        {canCreate && <button className="btn" onClick={() => setCreating(!creating)}>New memo</button>}
      </div>
      <p className="muted small" style={{ marginTop: 0 }}>
        A memo is a draft for a named person to edit and sign. It uses only flags a reviewer has accepted ({accepted} so far). Nothing is sent from here.
        {portfolio && " This is a portfolio company, so a flag also needs an escalation approved by the adviser before it can enter a memo."}
      </p>

      {creating && (
        <div className="card form narrowform">
          <strong>Draft a memo from the accepted flags</strong>
          <label>Memo owner (edits and signs it)
            <Select value={owner} onChange={setOwner} options={owners.map((o) => ({ value: o.username, label: `${o.display_name} (${o.username})` }))} />
          </label>
          <label>Scope decisions (optional): which entity, period or topics are in scope
            <textarea rows={2} value={scope} onChange={(e) => setScope(e.target.value)} placeholder="For example: FY2025 and FY2026, revenue and receivables only" />
          </label>
          <div className="row gap" style={{ justifyContent: "flex-end" }}>
            <button className="btn" onClick={() => setCreating(false)}>Cancel</button>
            <button className="btn primary" disabled={busy || !owner || accepted === 0} onClick={create}>Draft memo</button>
          </div>
          {accepted === 0 && <p className="muted small">Accept at least one flag first.</p>}
        </div>
      )}

      {memos && memos.length === 0 && <p className="muted">No memos yet.</p>}
      <div className="stack">
        {(memos || []).map((m) => (
          <Link key={m.id} href={`/memos/${m.id}`} className="card link">
            <div className="row between">
              <span className="row gap"><strong>{m.reference}</strong><span className="muted">owner {m.owner_name}</span></span>
              <span className="row gap">
                {m.status === "signed" ? <Tag tone="accept">signed</Tag> : <Tag tone="wait">draft</Tag>}
                <span className="muted small">{m.versions} version{m.versions === 1 ? "" : "s"} · {whenLabel(m.updated_at)}</span>
              </span>
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}
