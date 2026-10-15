"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { api, ROLE_LABEL } from "@/lib/api";
import { whenLabel } from "@/lib/time";
import Select from "@/components/Select";
import { Tag } from "@/components/Badges";

type Member = { username: string; display_name: string; role: string | null; added_by: string; added_at: string; is_creator: boolean };
type Candidate = { username: string; display_name: string; role: string };
type Access = { can_manage: boolean; members: Member[]; candidates: Candidate[]; also_see: string[] };

// Who may open this case. Forensic leads always can; everyone else needs to be a member (or hold the adviser or partner duty described below).
export default function AccessPanel({ caseId }: { caseId: number | string }) {
  const [data, setData] = useState<Access | null>(null);
  const [pick, setPick] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<Access>(`/cases/${caseId}/access`).then((d) => { setData(d); setPick((cur) => cur || d.candidates[0]?.username || ""); }).catch(() => {});
  }, [caseId]);
  useEffect(load, [load]);

  async function change(path: string, username: string, done: string) {
    setBusy(true);
    try { const d = await api<Access>(`/cases/${caseId}/access${path}`, { method: "POST", body: { username } }); setData(d); setPick(d.candidates[0]?.username || ""); toast.success(done); }
    catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  }

  if (!data) return null;
  return (
    <details className="card" style={{ marginTop: 16 }}>
      <summary><strong>Who can open this case</strong> <span className="muted small">({data.members.length} member{data.members.length === 1 ? "" : "s"} · forensic leads see every case)</span></summary>
      <div className="stack" style={{ marginTop: 8 }}>
        {data.members.map((m) => (
          <div key={m.username} className="row between wrap">
            <span className="row gap">
              <strong>{m.display_name}</strong>
              <span className="muted small">{m.role ? ROLE_LABEL[m.role] || m.role : ""}</span>
              {m.is_creator && <Tag>opened the case</Tag>}
            </span>
            <span className="row gap">
              <span className="muted small">added by {m.added_by} · {whenLabel(m.added_at)}</span>
              {data.can_manage && !m.is_creator && <button className="btn" disabled={busy} onClick={() => change("/remove", m.username, "Access removed")}>Remove</button>}
            </span>
          </div>
        ))}
        {data.can_manage && data.candidates.length > 0 && (
          <div className="row gap wrap" style={{ alignItems: "flex-end" }}>
            <label style={{ minWidth: 260 }}>Give access to
              <Select value={pick} onChange={setPick} options={data.candidates.map((c) => ({ value: c.username, label: `${c.display_name} (${ROLE_LABEL[c.role] || c.role})` }))} />
            </label>
            <button className="btn primary" disabled={busy || !pick} onClick={() => change("", pick, "Access given")}>Add</button>
          </div>
        )}
        {!data.can_manage && <p className="muted small">Only the forensic lead or the person who opened the case can change who has access.</p>}
        <ul className="muted small" style={{ margin: 0 }}>{data.also_see.map((t) => <li key={t}>{t}</li>)}</ul>
      </div>
    </details>
  );
}
