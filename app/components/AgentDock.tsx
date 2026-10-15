"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import Select from "@/components/Select";
import AgentChat, { ChatSkeleton } from "@/components/AgentChat";
import ChatMenu from "@/components/ChatMenu";
import { useChats } from "@/components/useChats";
import { IconCollapse, IconExpand, IconNewChat, IconSparkle } from "@/components/icons";

const lsGet = (k: string) => { try { return localStorage.getItem(k); } catch { return null; } };
const lsSet = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch {} };

// The agent docked on the right. It follows the case in the URL; elsewhere it uses the case you pick.
export default function AgentDock({ routeCaseId, expanded, onToggleExpand }: { routeCaseId: string | null; expanded: boolean; onToggleExpand: () => void }) {
  const [cases, setCases] = useState<any[] | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    api("/cases").then((all: any[]) => {
      const c = all.filter((x) => x.status !== "closed");   // closed cases are not offered to the agent
      setCases(c);
      const saved = lsGet("agent_case");
      setPicked(saved && c.some((x) => String(x.id) === saved) ? saved : c[0] ? String(c[0].id) : null);
    }).catch(() => setCases([]));
    api("/me").then(() => setOnline(true)).catch(() => setOnline(false));
  }, []);

  const caseId = routeCaseId || picked;
  const { chats, sessionId, select, refresh, ready, closed } = useChats(caseId);

  return (
    <div className="dock">
      <div className="dock-head">
        <span className="dock-icon"><IconSparkle size={18} /></span>
        <div className="dock-title">
          <strong>Forensic AI agent</strong>
          <span className={`dock-status ${online === false ? "off" : ""}`}>
            <i /> {online === null ? "Connecting" : online ? "Connected ✓" : "Offline"}
          </span>
        </div>
        <button className="icon-btn" title="New chat (the earlier chats stay saved in the history)" onClick={() => select(null)} disabled={!caseId}><IconNewChat size={17} /></button>
        <ChatMenu chats={chats} sessionId={sessionId} onSelect={select} disabled={!caseId} />
        <button className="icon-btn" title={expanded ? "Narrow the panel" : "Widen the panel"} onClick={onToggleExpand}>
          {expanded ? <IconCollapse size={17} /> : <IconExpand size={17} />}
        </button>
      </div>

      {!routeCaseId && cases && cases.length > 0 && (
        <label className="dock-case">Case
          <Select value={picked || ""} onChange={(v) => { setPicked(v); lsSet("agent_case", v); }} options={cases.map((c) => ({ value: c.id, label: `#${c.id} · ${c.name || c.company} · ${c.years.join(", ")}` }))} />
        </label>
      )}

      {caseId ? (
        !ready ? <ChatSkeleton /> : <AgentChat key={caseId} caseId={caseId} sessionId={sessionId} onSession={select} onChange={refresh} closed={closed} />
      ) : (
        <div className="chat-empty">
          <p><strong>No case yet.</strong></p>
          <p className="muted">The agent answers questions about a case. Open one from the company list or{" "}
            <Link href="/cases/new">start a new case</Link>.</p>
        </div>
      )}
    </div>
  );
}
