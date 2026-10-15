"use client";

import * as Tooltip from "@radix-ui/react-tooltip";
import { ChevronDown, ChevronRight, Info } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import Loader from "@/components/Loader";
import NarrativePanel from "@/components/NarrativePanel";

const PART_MEANING: Record<string, string> = {
  DSRI: "Receivables growing faster than sales.",
  GMI: "Gross margin getting thinner or fatter.",
  AQI: "More of the balance sheet in assets that are not plain, physical or current.",
  SGI: "How fast sales are growing; fast growth adds pressure to keep it up.",
  DEPI: "Depreciation slowing down, which lifts profit.",
  SGAI: "Overhead growing faster or slower than sales.",
  LVGI: "Borrowing and other debts rising against assets.",
  TATA: "Profit that is not backed by cash (accruals) as a share of assets.",
};

type View = "analysis" | "mscore";

const WORDS: Record<string, string> = { normal: "Normal", look: "Worth a look", review: "Review first" };

function Tip({ text, children }: { text: string; children: React.ReactNode }) {
  return (
    <Tooltip.Root delayDuration={120}>
      <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal><Tooltip.Content className="tip" sideOffset={6}>{text}<Tooltip.Arrow className="tip-arrow" /></Tooltip.Content></Tooltip.Portal>
    </Tooltip.Root>
  );
}

function Cell({ c, selected, cid }: { c: any; selected: boolean; cid: string }) {
  if (!c) return <td data-cell={cid} className={`mcell ${selected ? "sel" : ""}`}><span className="muted">—</span></td>;
  const empty = c.value === null || c.value === undefined;
  const body = (
    <div className="mval">
      <span className={empty ? "muted" : ""}>{empty ? "n/a" : c.display}</span>
      {c.badge && <span className={`mbadge m-${c.badge}`}>{WORDS[c.badge]}</span>}
    </div>
  );
  return (
    <td data-cell={cid} className={`mcell ${selected ? "sel" : ""}`}>
      {c.what ? <Tip text={c.what}>{body}</Tip> : body}
    </td>
  );
}

export default function MatrixPage() {
  const { companyId } = useParams<{ companyId: string }>();
  const [basis, setBasis] = useState<"consolidated" | "standalone">("consolidated");
  const [d, setD] = useState<any>(null);
  const [fy, setFy] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<View>("analysis");
  const [err, setErr] = useState("");
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setD(null); setErr("");
    api(`/companies/${companyId}/matrix?basis=${basis}`).then((m) => { setD(m); setFy(m.years[m.years.length - 1] || null); }).catch((e) => setErr(e.message));
  }, [companyId, basis]);

  // Home menu links here with ?view=mscore.
  useEffect(() => { if (new URLSearchParams(window.location.search).get("view") === "mscore") setView("mscore"); }, []);

  // A cell cited in the narrative: open the Beneish parts if needed, scroll to it and flash it.
  function showCell(ref: string) {
    const [, key, y] = ref.split(":");
    if (key === "summary") { setFy(y); document.querySelector(".health")?.scrollIntoView({ behavior: "smooth", block: "center" }); return; }
    if (/^[A-Z]{3,5}$/.test(key) && key !== "beneish") setOpen(true);
    setTimeout(() => {
      const el = document.querySelector(`[data-cell="${ref}"]`);
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
      el.classList.add("flash");
      setTimeout(() => el.classList.remove("flash"), 1800);
    }, 80);
  }

  function pick(v: View) {
    setView(v);
    window.history.replaceState(null, "", v === "mscore" ? "?view=mscore" : window.location.pathname);
  }

  // Start scrolled to the newest years: they matter most when the panel is narrow.
  useEffect(() => { const el = wrapRef.current; if (el) el.scrollLeft = el.scrollWidth; }, [d]);

  if (err) return <><p><Link href="/home">← Home</Link></p><p className="error">{err}</p></>;
  if (!d) return <Loader label="Building the matrix" />;

  const years: string[] = d.years;
  const sum = fy ? d.summary[fy] : null;
  const beneish = d.rows.find((r: any) => r.kind === "parts");
  const mscore = view === "mscore";
  const rows = mscore ? (beneish ? [beneish] : []) : d.rows;

  return (
    <Tooltip.Provider>
      <p><Link href="/home">← Home</Link></p>
      <div className="row between wrap">
        <div>
          <h1 style={{ marginBottom: 2 }}>{d.company.name}</h1>
          <span className="muted">{d.company.symbol} · multi-year matrix</span>
        </div>
        <div className="segmented" role="tablist" aria-label="Basis">
          {(["consolidated", "standalone"] as const).map((b) => (
            <button key={b} role="tab" aria-selected={basis === b} className={basis === b ? "on" : ""} onClick={() => setBasis(b)}>{b}</button>
          ))}
        </div>
      </div>

      {!d.config_approved && (
        <p className="notice small" style={{ marginTop: 12 }}>
          DRAFT: the limits behind these labels have not been approved by the forensic lead. Read every label as a prompt to look, not a result.
        </p>
      )}

      {years.length === 0 ? (
        <p className="muted" style={{ marginTop: 20 }}>Not enough saved data for this basis to build a matrix.</p>
      ) : (
        <>
          <div className="yearbar" aria-label="Quick actions">
            <button className={`btn ${!mscore ? "primary" : ""}`} aria-pressed={!mscore} onClick={() => pick("analysis")}>Multi-Annual Forensic Analysis</button>
            <button className={`btn ${mscore ? "primary" : ""}`} aria-pressed={mscore} onClick={() => pick("mscore")}>Detailed M-Score Breakdown</button>
          </div>

          {mscore && (
            <p className="notice small">
              The eight Beneish parts, year by year. The combined M-score is not shown: the forensic lead must approve its weights, cut-off and Indian adaptation first.
              {beneish?.caveat ? ` ${beneish.caveat}` : ""}
            </p>
          )}

          <div className="yearbar" role="tablist" aria-label="Fiscal year">
            <span className="filterlabel">Fiscal year</span>
            {[...years].reverse().map((y) => (
              <button key={y} role="tab" aria-selected={fy === y} className={`chip ${fy === y ? "on" : ""}`} onClick={() => setFy(y)}>{y}</button>
            ))}
          </div>

          {sum && fy && !mscore && (
            <div className="card health">
              <div className="healthhead">
                <div>
                  <div className="muted small">Health at a glance</div>
                  <div className="big">{fy}</div>
                </div>
                <div className="healthcounts">
                  <span><b className="m-normal-t">{sum.normal}</b> normal</span>
                  <span><b className="m-look-t">{sum.look}</b> worth a look</span>
                  <span><b className="m-review-t">{sum.review}</b> review first</span>
                  <span><b>{sum.no_data}</b> not enough data</span>
                </div>
              </div>
              <div className="healthlist">
                {d.rows.filter((r: any) => r.key !== "beneish").map((r: any) => {
                  const c = r.cells[fy];
                  return (
                    <div key={r.key} className="healthitem">
                      <span>{r.name}</span>
                      <span>{c && c.value !== null ? <>{c.display} {c.badge && <span className={`mbadge m-${c.badge}`}>{WORDS[c.badge]}</span>}</> : <span className="muted">not enough data</span>}</span>
                    </div>
                  );
                })}
                <div className="healthitem"><span>Beneish M-score</span><span className="muted">not shown: the lead must approve its weights first</span></div>
              </div>
            </div>
          )}

          {!mscore && <NarrativePanel companyId={companyId} basis={basis} onCite={showCell} />}

          <div className="matrixwrap" ref={wrapRef}>
            <table className="matrix">
              <thead>
                <tr>
                  <th className="mname">Measure</th>
                  {years.map((y) => <th key={y} className={y === fy ? "sel" : ""}>{y}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map((r: any) => (
                  <Fragment key={r.key}>
                    <tr>
                      <td className="mname">
                        <div className="row gap">
                          {r.kind === "parts" && !mscore && (
                            <button className="icon-btn small-btn" aria-label={open ? "Hide the eight parts" : "Show the eight parts"} onClick={() => setOpen(!open)}>
                              {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                            </button>
                          )}
                          <div>
                            <strong>{r.name}</strong>
                            <div className="muted small">{r.question}</div>
                          </div>
                          <Tip text={[r.rule || r.message, r.caveat].filter(Boolean).join(" ")}><span className="info"><Info size={15} /></span></Tip>
                        </div>
                      </td>
                      {years.map((y) => <Cell key={y} c={r.cells[y]} selected={y === fy} cid={`cell:${r.key}:${y}`} />)}
                    </tr>
                    {r.kind === "parts" && (open || mscore) && r.parts.map((p: any) => (
                      <tr key={p.key} className="subrow">
                        <td className="mname sub">
                          {p.name}
                          {mscore && PART_MEANING[p.key] && <div className="muted small">{PART_MEANING[p.key]}</div>}
                        </td>
                        {years.map((y) => <Cell key={y} c={p.cells[y]} selected={y === fy} cid={`cell:${p.key}:${y}`} />)}
                      </tr>
                    ))}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>

          {!mscore && d.ratios?.length > 0 && (
            <>
              <h2 style={{ marginTop: 24, marginBottom: 2 }}>Ratios</h2>
              <p className="muted small" style={{ marginTop: 0 }}>Plain ratios from the same saved figures. Information only: no limit applies, so there are no labels. Hover a cell to see its working.</p>
              <div className="matrixwrap">
                <table className="matrix">
                  <thead>
                    <tr>
                      <th className="mname">Ratio</th>
                      {years.map((y) => <th key={y} className={y === fy ? "sel" : ""}>{y}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {d.ratios.map((r: any) => (
                      <tr key={r.key}>
                        <td className="mname">
                          <div className="row gap">
                            <div>
                              <strong>{r.name}</strong>
                              <div className="muted small">{r.question}</div>
                            </div>
                            <Tip text={[r.rule, r.caveat].filter(Boolean).join(" ")}><span className="info"><Info size={15} /></span></Tip>
                          </div>
                        </td>
                        {years.map((y) => <Cell key={y} c={r.cells[y]} selected={y === fy} cid={`ratio:${r.key}:${y}`} />)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {!mscore && d.ownership?.length > 0 && (
            <>
              <h2 style={{ marginTop: 24, marginBottom: 2 }}>Ownership, auditor fees and peers</h2>
              <p className="muted small" style={{ marginTop: 0 }}>Shareholding at 31 March of each year, and the auditor's fees from the annual report notes. Information only, except the promoter row, which uses the 2-point step limit from the Job 2 spec. Hover a cell to see its working.</p>
              <div className="matrixwrap">
                <table className="matrix">
                  <thead>
                    <tr>
                      <th className="mname">Measure</th>
                      {years.map((y) => <th key={y} className={y === fy ? "sel" : ""}>{y}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {d.ownership.map((r: any) => (
                      <tr key={r.key}>
                        <td className="mname">
                          <div className="row gap">
                            <div>
                              <strong>{r.name}</strong>
                              <div className="muted small">{r.question}</div>
                            </div>
                            <Tip text={[r.rule, r.caveat].filter(Boolean).join(" ")}><span className="info"><Info size={15} /></span></Tip>
                          </div>
                        </td>
                        {years.map((y) => <Cell key={y} c={r.cells[y]} selected={y === fy} cid={`own:${r.key}:${y}`} />)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <div className="legend">
            <span className="mbadge m-normal">Normal</span> within the usual range
            <span className="mbadge m-look">Worth a look</span> outside it, or in the middle zone
            <span className="mbadge m-review">Review first</span> well outside it
            <span className="muted">n/a = not enough saved data (hover a cell to see why)</span>
          </div>
          <ul className="muted small">
            {d.rows.filter((r: any) => r.caveat).map((r: any) => <li key={r.key}><strong>{r.name}:</strong> {r.caveat}</li>)}
            {d.notes.map((n: string) => <li key={n}>{n}</li>)}
          </ul>
        </>
      )}
    </Tooltip.Provider>
  );
}
