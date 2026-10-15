"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { parseUtc } from "@/lib/time";
import Select from "@/components/Select";
import Loader from "@/components/Loader";
import { Sev, Tag } from "@/components/Badges";

type Run = {
  id: number; company: string; basis: string; years: string[]; started_at: string; flags_created: number;
  config_approved: boolean; config_version: number; code_version: string;
};

const show = (v: any) => (v === null || v === undefined ? "none" : typeof v === "object" ? JSON.stringify(v) : String(v));
const label = (r: Run) =>
  `Run #${r.id} · ${r.basis} · ${r.years[0]}–${r.years[r.years.length - 1]} · ${parseUtc(r.started_at).toLocaleString()} · ${r.flags_created} flags`;

function Decision({ d }: { d: any }) {
  if (!d) return null;
  return (
    <p className="muted">
      Earlier run: {d.decision === "accept" ? "accepted" : "rejected"} by {d.reviewer} (“{d.reason}”). Decisions are not
      copied to the newer run; review it again there.
    </p>
  );
}

function FlagLine({ f }: { f: any }) {
  return (
    <div className="row gap wrap">
      <Sev v={f.severity} />
      <strong>{f.check_id}</strong>
      <span className="muted">{f.financial_year}</span>
      <span>{f.what_observed}</span>
    </div>
  );
}

export default function ComparePage() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [a, setA] = useState<number | "">("");
  const [b, setB] = useState<number | "">("");
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState("");
  const [all, setAll] = useState(false);

  useEffect(() => {
    api<Run[]>("/runs")
      .then((r) => {
        setRuns(r);
        const q = new URLSearchParams(window.location.search);
        const qa = Number(q.get("a")), qb = Number(q.get("b"));
        if (qa && qb) { setA(qa); setB(qb); return; }
        if (r.length) {
          const newest = r[0];
          const same = r.filter((x) => x.company === newest.company && x.basis === newest.basis);
          if (same.length > 1) { setB(same[0].id); setA(same[1].id); }
        }
      })
      .catch((e) => setErr(e.message));
  }, []);

  const runA = runs?.find((r) => r.id === a);
  const bOptions = useMemo(
    () => (runs || []).filter((r) => runA && r.id !== runA.id && r.company === runA.company && r.basis === runA.basis),
    [runs, runA],
  );

  async function go() {
    setErr(""); setRes(null);
    try { setRes(await api(`/compare?a=${a}&b=${b}`)); } catch (e: any) { setErr(e.message); }
  }

  useEffect(() => { if (a && b && runs) go(); /* eslint-disable-next-line */ }, [a, b, runs]);

  if (!runs) return err ? <p className="error">{err}</p> : <Loader label="Loading runs" />;

  return (
    <>
      <h1>Compare runs</h1>
      <p className="muted">
        See what changed between two screens of the same company and basis, for example after a restatement, new data,
        changed limits or new code. Older runs are never edited.
      </p>
      <div className="card form">
        <label>Earlier run (A)
          <Select value={a} onChange={(v) => { setA(Number(v)); setB(""); setRes(null); }} options={runs.map((r) => ({ value: r.id, label: label(r) }))} />
        </label>
        <label>Later run (B), same company and basis
          <Select value={b} disabled={!runA} onChange={(v) => setB(Number(v))} options={bOptions.map((r) => ({ value: r.id, label: label(r) }))} />
        </label>
      </div>
      {err && <p className="error">{err}</p>}

      {res && (
        <>
          <div className="card">
            <h2 style={{ marginTop: 0 }}>{res.company} · {res.basis}</h2>
            <p><strong>{res.headline}</strong></p>
            <div className="grid">
              {[["Changed", res.changed.length], ["New in B", res.new.length], ["Gone from B", res.gone.length],
                ["Unchanged", res.unchanged.length]].map(([k, v]) => (
                <div className="card stat" key={String(k)}><div className="muted">{k}</div><div className="big">{v}</div></div>
              ))}
            </div>
            {res.possible_causes.length > 0 && (
              <>
                <h3>Possible causes (from what differed between the runs)</h3>
                <ul>{res.possible_causes.map((c: string) => <li key={c}>{c}</li>)}</ul>
                <p className="muted">{res.note}</p>
              </>
            )}
          </div>

          <h2>What was different between the two runs</h2>
          <label className="inline">
            <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Show items that did not differ
          </label>
          <table>
            <thead><tr><th>Item</th><th>Run A</th><th>Run B</th></tr></thead>
            <tbody>
              {res.differences.filter((d: any) => all || !d.same).map((d: any) => (
                <tr key={d.item}>
                  <td>
                    {d.item} {!d.same && <Tag tone="wait">differs</Tag>}
                    {d.detail && Array.isArray(d.detail) && (
                      <ul>
                        {d.detail.map((c: any) => (
                          <li key={c.path} className="muted">
                            {c.path.replace("checks.", "")}: {show(c.old_value)} ({c.old_source}) → {show(c.new_value)} ({c.new_source})
                          </li>
                        ))}
                      </ul>
                    )}
                    {d.detail && !Array.isArray(d.detail) && (
                      <div className="muted">added snapshots: {show(d.detail.added)} · removed: {show(d.detail.removed)}</div>
                    )}
                  </td>
                  <td>{show(d.a)}</td><td>{show(d.b)}</td>
                </tr>
              ))}
              {res.differences.every((d: any) => d.same) && !all && (
                <tr><td colSpan={3} className="muted">Nothing differs between these two runs&apos; inputs.</td></tr>
              )}
            </tbody>
          </table>

          {res.check_status_changes.length > 0 && (
            <>
              <h2>Checks whose status changed</h2>
              <ul>
                {res.check_status_changes.map((c: any) => (
                  <li key={c.check_id}>{c.check_id}: {show(c.a)} → {show(c.b)}</li>
                ))}
              </ul>
            </>
          )}

          <h2>Changed flags ({res.changed.length})</h2>
          <div className="stack">
            {res.changed.map((f: any) => (
              <div className="card" key={f.flag_id}>
                <FlagLine f={f} />
                <table>
                  <thead><tr><th>What changed</th><th>Before (A)</th><th>After (B)</th></tr></thead>
                  <tbody>
                    {f.changes.map((c: any, i: number) => (
                      <tr key={i}>
                        <td>{c.what}{c.detail && <div className="muted">{c.detail}</div>}</td>
                        <td>{c.before === null && c.after === null ? "—" : show(c.before)}</td>
                        <td>{c.before === null && c.after === null ? "—" : show(c.after)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <Decision d={f.decision_in_a} />
              </div>
            ))}
            {res.changed.length === 0 && <p className="muted">None.</p>}
          </div>

          <h2>New in run B ({res.new.length})</h2>
          <div className="stack">
            {res.new.map((f: any) => <div className="card" key={f.flag_id}><FlagLine f={f} /></div>)}
            {res.new.length === 0 && <p className="muted">None.</p>}
          </div>

          <h2>Gone from run B ({res.gone.length})</h2>
          <div className="stack">
            {res.gone.map((f: any) => (
              <div className="card" key={f.flag_id}><FlagLine f={f} /><Decision d={f.decision} /></div>
            ))}
            {res.gone.length === 0 && <p className="muted">None.</p>}
          </div>

          <details>
            <summary>Unchanged flags ({res.unchanged.length})</summary>
            <div className="stack">
              {res.unchanged.map((f: any) => (
                <div className="card" key={f.flag_id}><FlagLine f={f} /><Decision d={f.decision_in_a} /></div>
              ))}
            </div>
          </details>
        </>
      )}
    </>
  );
}
