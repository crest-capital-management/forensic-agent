"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { parseUtc } from "@/lib/time";
import Select from "@/components/Select";
import Loader from "@/components/Loader";
import { Tag } from "@/components/Badges";

type Setting = { path: string; label: string; value: any; source: string; kind: "number" | "severity" | "text" };

const SOURCE_TONE: Record<string, string> = { spec: "accept", lead: "accept", proposal: "wait", needs_lead: "reject" };
const show = (v: any) => (v === null || v === undefined ? "none" : String(v));

export default function ConfigPage() {
  const [d, setD] = useState<any>(null);
  const [me, setMe] = useState<any>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(() => {
    api("/config").then(setD).catch((e) => setErr(e.message));
    api("/me").then(setMe).catch(() => {});
  }, []);
  useEffect(load, [load]);

  async function act(path: string, body: unknown, done: string) {
    setErr("");
    setMsg("");
    try {
      await api(path, { method: "POST", body });
      setEdits({});
      setReason("");
      setMsg(done);
      toast.success(done);
      load();
    } catch (e: any) {
      setErr(e.message);
      toast.error(e.message);
    }
  }

  if (!d) return err ? <p className="error">{err}</p> : <Loader label="Loading limits and rules" />;

  const isLead = me?.role === "forensic_lead";
  const dirty = Object.keys(edits);
  const live = d.live;

  function save() {
    const settings: Setting[] = d.checks.flatMap((c: any) => c.settings);
    const changes = dirty.map((path) => {
      const s = settings.find((x) => x.path === path)!;
      const raw = edits[path].trim();
      let value: any = raw;
      if (s.kind === "number") value = raw === "" || raw === "none" ? null : Number(raw);
      if (s.kind === "severity") value = raw === "none" || raw === "" ? null : raw;
      return { path, value };
    });
    act("/config/edit", { changes, reason }, "Saved as a new version. The approval was cleared; approve again when ready.");
  }

  return (
    <>
      <h1>Limits and severity rules</h1>
      <div className="card">
        <div className="row gap wrap">
          <strong>Live version {live.version}</strong>
          {live.approved ? (
            <Tag tone="accept">approved by {live.approved_by}</Tag>
          ) : (
            <Tag tone="wait">DRAFT: not approved</Tag>
          )}
          <span className="muted">
            {live.from === "file" ? "from the config file (nothing saved in the app yet)" : `saved in the app by ${live.created_by}`}
          </span>
        </div>
        {live.note && <p className="muted">Last note: {live.note}</p>}
        <p>
          {d.summary.unconfirmed_proposals} of {d.summary.settings} settings are still unconfirmed developer proposals.{" "}
          {d.summary.undefined} have no number yet, so those checks show the metric and never raise a flag.
        </p>
        <p className="muted">
          Every run records which version it used. Changing anything makes a new version and clears the approval, so an
          approval always belongs to one exact set of values. Screens stay stamped DRAFT until a version is approved.
        </p>
      </div>

      {isLead ? (
        <div className="card">
          <h2>Your changes</h2>
          <label>Reason (required for every change, confirmation and approval)
            <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <div className="row gap wrap">
            <button className="btn primary" disabled={dirty.length === 0} onClick={save}>
              Save {dirty.length || ""} change{dirty.length === 1 ? "" : "s"}
            </button>
            <button className="btn" disabled={d.summary.unconfirmed_proposals === 0}
              onClick={() => act("/config/confirm-proposals", { reason }, "Proposals confirmed as they stand.")}>
              Confirm all {d.summary.unconfirmed_proposals} proposals as they stand
            </button>
            <button className="btn" disabled={live.from === "file" || live.approved || d.summary.unconfirmed_proposals > 0}
              onClick={() => act("/config/approve", { reason }, "Approved. New screens will no longer be stamped DRAFT.")}>
              Approve this version
            </button>
          </div>
          <p className="muted">
            Approval needs every proposal changed or confirmed first. Settings with &quot;none&quot; and needs_lead can stay empty.
          </p>
          {msg && <p style={{ color: "var(--ok)", fontWeight: 600 }}>{msg}</p>}
          {err && <p className="error">{err}</p>}
        </div>
      ) : (
        <p className="notice">
          You are signed in as {me?.role}. Only the forensic lead can change or approve limits; you can read everything here.
        </p>
      )}

      {d.checks.map((c: any) => (
        <div className="card" key={c.check_id}>
          <div className="row between">
            <h2 style={{ margin: 0 }}>{c.check_id}: {c.name}</h2>
            <span className="muted">{c.rule_id}</span>
          </div>
          <p className="muted">
            {c.implemented ? c.metric : "Not implemented yet: the plan gives no formula or source for this check."}
          </p>
          {c.settings.length > 0 && (
            <table>
              <thead><tr><th>Setting</th><th>Value</th><th>Source</th></tr></thead>
              <tbody>
                {c.settings.map((s: Setting) => {
                  const cur = s.path in edits ? edits[s.path] : show(s.value);
                  return (
                    <tr key={s.path}>
                      <td>{s.label}</td>
                      <td>
                        {!isLead ? (
                          show(s.value)
                        ) : s.kind === "severity" ? (
                          <Select value={cur} onChange={(v) => setEdits({ ...edits, [s.path]: v })} options={["none", "high", "medium", "low"].map((v) => ({ value: v, label: v }))} />
                        ) : (
                          <input type="text" value={cur} style={{ width: s.kind === "text" ? "26em" : "7em" }}
                            onChange={(e) => setEdits({ ...edits, [s.path]: e.target.value })} />
                        )}
                        {s.path in edits && <span className="muted"> (unsaved; was {show(s.value)})</span>}
                      </td>
                      <td><Tag tone={SOURCE_TONE[s.source]}>{s.source.replace("_", " ")}</Tag></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      ))}

      <h2>Source meanings</h2>
      <ul>
        {Object.entries(d.sources).map(([k, v]) => (<li key={k}><strong>{k.replace("_", " ")}</strong>: {String(v)}</li>))}
      </ul>

      <h2>Version history</h2>
      {d.versions.length === 0 ? (
        <p className="muted">No versions saved in the app yet. The config file is still live.</p>
      ) : (
        <div className="stack">
          {d.versions.map((v: any) => (
            <div className="card" key={v.id}>
              <div className="row between">
                <strong>Version {v.version}</strong>
                <span className="muted">{parseUtc(v.created_at).toLocaleString()} · {v.created_by}</span>
              </div>
              {v.approved_by && <Tag tone="accept">approved by {v.approved_by}</Tag>}
              <p>{v.note}</p>
              {v.changes.length > 0 && (
                <table>
                  <thead><tr><th>Setting</th><th>Before</th><th>After</th></tr></thead>
                  <tbody>
                    {v.changes.map((c: any) => (
                      <tr key={c.path}>
                        <td>{c.path.replace("checks.", "")}</td>
                        <td>{show(c.old_value)} ({c.old_source})</td>
                        <td>{show(c.new_value)} ({c.new_source})</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
