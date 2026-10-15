"use client";

import { motion } from "framer-motion";
import { Check, Copy } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { parseUtc } from "@/lib/time";
import { Tag } from "@/components/Badges";
import { IconSend } from "@/components/icons";

const SUGGESTIONS = [
  "Which flags are the most severe, and what do they mean in plain words?",
  "Explain how the receivables flag was worked out.",
  "What limits were used for these flags, and who set them?",
  "Which checks had not enough data to run?",
  "What does the auditor's report say about the opinion?",
];

const STATUS: Record<string, { text: string; tone: string }> = {
  clarify: { text: "needs a fuller question", tone: "wait" },
  answered: { text: "checked answer", tone: "accept" },
  refused: { text: "refused: leading question", tone: "wait" },
  blocked: { text: "blocked by a guardrail", tone: "reject" },
  error: { text: "model unavailable", tone: "reject" },
};

const CITE = /(\[[A-Za-z]+:[^\]\s]+\])/g;

// Where a reference leads, when it leads to a page of its own. Figures and filing pages open a detail box instead.
function refHref(ref: string, caseId: string | number): string | null {
  const [kind, id] = ref.split(":");
  if (kind === "flag") return `/cases/${caseId}/flags/${id}`;
  if (kind === "run" || kind === "check") return `/cases/${caseId}`;
  if (kind === "limit") return "/config";
  return null;
}

function Cites({ text, caseId, onOpen }: { text: string; caseId: string | number; onOpen: (ref: string) => void }) {
  return (
    <>
      {text.split(CITE).map((p, i) => {
        const m = p.match(/^\[([A-Za-z]+):([^\]\s]+)\]$/);
        if (!m) return <span key={i}>{p}</span>;
        const ref = `${m[1]}:${m[2]}`;
        const href = refHref(ref, caseId);
        return href
          ? <Link key={i} className="cite" href={href}>{ref}</Link>
          : <button key={i} type="button" className="cite" title="Show this source" onClick={() => onOpen(ref)}>{ref}</button>;
      })}
    </>
  );
}

// Paragraphs, plus simple pipe tables like the reference's "ASPECT | EXPLANATION" block.
function Answer({ text, caseId, onOpen }: { text: string; caseId: string | number; onOpen: (ref: string) => void }) {
  const lines = text.split("\n");
  const blocks: ({ t: "p"; s: string } | { t: "table"; rows: string[][] })[] = [];
  for (let i = 0; i < lines.length; ) {
    if (lines[i].trim().startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const cells = lines[i].trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells);
        i++;
      }
      blocks.push({ t: "table", rows });
    } else {
      const start = i;
      while (i < lines.length && !lines[i].trim().startsWith("|")) i++;
      const s = lines.slice(start, i).join("\n").trim();
      if (s) blocks.push({ t: "p", s });
    }
  }
  return (
    <div className="answer">
      {blocks.map((b, k) =>
        b.t === "p" ? (
          <p key={k}><Cites text={b.s} caseId={caseId} onOpen={onOpen} /></p>
        ) : (
          <div key={k} className="answer-table">
            <table>
              <thead><tr>{b.rows[0].map((c, j) => <th key={j}>{c}</th>)}</tr></thead>
              <tbody>
                {b.rows.slice(1).map((r, ri) => (
                  <tr key={ri}>{r.map((c, ci) => <td key={ci}><Cites text={c} caseId={caseId} onOpen={onOpen} /></td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        ),
      )}
    </div>
  );
}

// Chat-style "typing" indicator with a short status that changes while the answer is being checked.
const THINKING = ["Reading the saved flags…", "Checking the citations…", "Writing the answer…"];
export function Typing({ steps = THINKING }: { steps?: string[] }) {
  const [i, setI] = useState(0);
  useEffect(() => { const t = setInterval(() => setI((n) => Math.min(n + 1, steps.length - 1)), 4000); return () => clearInterval(t); }, [steps]);
  return (
    <div className="typing" role="status" aria-live="polite">
      <span className="typing-dots"><i /><i /><i /></span>
      <span className="typing-text">{steps[i]}</span>
    </div>
  );
}

export function ChatSkeleton() {
  return (
    <div className="chat-skel" aria-busy="true">
      <div className="skel you" />
      <div className="skel l1" /><div className="skel l2" /><div className="skel l3" />
    </div>
  );
}

export function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 1600);
    } catch {
      toast.error("Could not copy: select the text and copy it by hand.");
    }
  }
  return (
    <button type="button" className="copy-btn" onClick={copy} aria-label="Copy the answer" title="Copy the answer">
      {done ? <Check size={14} /> : <Copy size={14} />}
      <span>{done ? "Copied" : "Copy"}</span>
    </button>
  );
}

const clock = (iso: string) => parseUtc(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function SourceDetail({ s }: { s: any }) {
  const [kind] = s.ref.split(":");
  return (
    <div className="refdetail">
      <div className="refdetail-label">{s.label}</div>
      {s.quote && <blockquote>{s.quote}</blockquote>}
      {kind === "page" && <div className="muted small">{s.file ? `${s.file}, ` : ""}PDF page {s.page}{s.printed_page ? ` (printed page ${s.printed_page})` : ""}</div>}
      {kind === "fin" && <div className="muted small">A figure saved from the sources named in brackets. Values are in crore (1 crore = 10 million).</div>}
      <div className="muted small refdetail-id">{s.ref}</div>
    </div>
  );
}

function Turn({ m, caseId }: { m: any; caseId: string | number }) {
  const [open, setOpen] = useState<string | null>(null);
  const refsRef = useRef<HTMLDivElement>(null);
  const openRef = (ref: string) => {
    setOpen(ref);
    requestAnimationFrame(() => refsRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
  };
  const opened = m.sources.find((x: any) => x.ref === open);
  return (
    <motion.div className="turn" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.22 }}>
      <div className="bubble you">{m.question}</div>
      <div className={`bubble agent st-${m.status}`}>
        <div className="row gap wrap">
          <Tag tone={STATUS[m.status]?.tone}>{STATUS[m.status]?.text || m.status}</Tag>
          {m.model && <span className="muted small">{m.model.split(" ")[0]}</span>}
        </div>
        <Answer text={m.answer} caseId={caseId} onOpen={openRef} />
        {m.warnings.map((w: string, i: number) => <p key={i} className="notice small">{w}</p>)}
        {m.sources.length > 0 && (
          <div className="refs" ref={refsRef}>
            <div className="refs-title">{m.sources.length} reference{m.sources.length === 1 ? "" : "s"}</div>
            <div className="refs-list">
              {m.sources.map((s: any, i: number) => {
                const inner = (<><span className="refnum">{i + 1}</span><span className="reflabel">{s.label}</span></>);
                const href = refHref(s.ref, caseId);
                return href
                  ? <Link key={s.ref} href={href} className="refchip" title={s.ref}>{inner}</Link>
                  : <button key={s.ref} type="button" className={`refchip ${open === s.ref ? "open" : ""}`} aria-expanded={open === s.ref}
                      title="Show this source" onClick={() => setOpen(open === s.ref ? null : s.ref)}>{inner}</button>;
              })}
            </div>
            {opened && <SourceDetail s={opened} />}
          </div>
        )}
        {m.tool_calls.length > 0 && (
          <details className="small">
            <summary>What the agent looked at ({m.tool_calls.length})</summary>
            <ul>
              {m.tool_calls.map((t: any, i: number) => (
                <li key={i}>{t.name}({Object.entries(t.args || {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")}){t.ok ? "" : " — returned an error"}</li>
              ))}
            </ul>
          </details>
        )}
        <div className="stamp-row">
          <CopyButton text={m.answer} />
          <span className="stamp">{clock(m.created_at)}</span>
        </div>
      </div>
    </motion.div>
  );
}

export default function AgentChat({ caseId, sessionId, onSession, onChange, closed }: {
  caseId: string | number; sessionId: number | null; onSession: (id: number) => void; onChange?: () => void;
  closed?: { by: string; reason: string; at: string } | null;
}) {
  const [msgs, setMsgs] = useState<any[] | null>(null);
  const [me, setMe] = useState<any>(null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState("");
  const [err, setErr] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const justCreated = useRef<number | null>(null);   // a chat this component just started: its messages are already on screen

  useEffect(() => { api("/me").then(setMe).catch(() => {}); }, []);
  useEffect(() => {
    setErr("");
    if (sessionId === null || !Number.isInteger(sessionId)) { setMsgs([]); return; }                       // a fresh chat: nothing to load
    if (justCreated.current === sessionId) { justCreated.current = null; return; }
    setMsgs(null);
    api(`/cases/${caseId}/ask?session_id=${sessionId}`).then(setMsgs).catch((e) => setErr(e.message));
  }, [caseId, sessionId]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy]);

  async function send(question: string) {
    if (!question.trim() || busy) return;
    setErr(""); setBusy(true);
    setPending(question.trim()); setQ("");   // show the question as sent and empty the box straight away
    try {
      const m = await api(`/cases/${caseId}/ask`, { method: "POST", body: { question, session_id: sessionId } });
      setMsgs([...(msgs || []), m]);
      if (sessionId === null && Number.isInteger(m.session_id)) { justCreated.current = m.session_id; onSession(m.session_id); }
      onChange?.();
    } catch (e: any) {
      setErr(e.message);
      setQ(question);                         // give the text back so nothing is lost
    } finally {
      setBusy(false); setPending("");
    }
  }

  if (!msgs) return err ? <p className="error">{err}</p> : <ChatSkeleton />;
  const shown = msgs;
  const canAsk = me && ["analyst", "forensic_lead"].includes(me.role);

  return (
    <div className="agentchat">
      <div className="chat-scroll">
        {shown.length === 0 && (
          <div className="chat-empty">
            <p><strong>Ask about this case.</strong></p>
            <p className="muted">The agent reads the saved flags, figures, limits and filing pages. It describes and cites; it never concludes.</p>
            {canAsk && !closed && (
              <div className="stack">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="chip suggestion" disabled={busy} onClick={() => send(s)}>{s}</button>
                ))}
              </div>
            )}
          </div>
        )}
        {shown.map((m) => <Turn key={m.id} m={m} caseId={caseId} />)}
        {busy && <div className="turn">{pending && <div className="bubble you">{pending}</div>}<div className="bubble agent typing-bubble"><Typing /></div></div>}
        <div ref={endRef} />
      </div>

      {err && <p className="error small">{err}</p>}
      {closed ? (
        <p className="notice small">This case is closed ({closed.reason}). Reopen it from the case page to ask more questions. The chats so far stay readable.</p>
      ) : canAsk ? (
        <div className="composer">
          <textarea rows={1} value={q} maxLength={1000} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(q); } }}
            placeholder="Ask about the flags, figures, limits or the filing" />
          <button className="send" aria-label="Send" disabled={busy || !q.trim()} onClick={() => send(q)}><IconSend size={20} /></button>
        </div>
      ) : (
        <p className="notice small">Your role ({me?.role}) can read this conversation but not ask questions.</p>
      )}
      <p className="chat-foot">This agent can make mistakes. Statistical leads only: most anomalies have innocent explanations. Always verify against the filing.</p>
    </div>
  );
}
