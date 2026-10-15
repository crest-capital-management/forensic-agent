"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

export type Closure = { by: string; reason: string; at: string };
export type Chat = { id: number; title: string; created_by: string; message_count: number; last_at: string };

const lsGet = (k: string) => { try { return localStorage.getItem(k); } catch { return null; } };
const lsSet = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch {} };

// The chats of one case and which one is open. sessionId null = a fresh chat that is saved when the first question is sent.
export function useChats(caseId: string | number | null) {
  const [chats, setChats] = useState<Chat[]>([]);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [closed, setClosed] = useState<Closure | null>(null);
  const [ready, setReady] = useState(false);   // false until the case's chats are known, so no empty-chat flash

  const loadStatus = useCallback(async () => {
    if (!caseId) return;
    try { const s = await api<{ closure: Closure | null }>(`/cases/${caseId}/status`); setClosed(s.closure); } catch {}
  }, [caseId]);
  // The case page announces a close or reopen so every open chat updates at once.
  useEffect(() => { window.addEventListener("case-changed", loadStatus); return () => window.removeEventListener("case-changed", loadStatus); }, [loadStatus]);

  const refresh = useCallback(async () => {
    if (!caseId) return [];
    try { const list = await api<Chat[]>(`/cases/${caseId}/chats`); setChats(list); return list; } catch { return []; }
  }, [caseId]);

  useEffect(() => {
    setChats([]); setSessionId(null); setReady(false); setClosed(null);
    if (!caseId) return;
    let live = true;
    loadStatus();
    refresh().then((list) => {
      if (!live) return;
      const saved = Number(lsGet(`agent_session_${caseId}`)) || null;
      setSessionId(saved && list.some((c) => c.id === saved) ? saved : list[0]?.id ?? null);
      setReady(true);
    });
    return () => { live = false; };
  }, [caseId, refresh, loadStatus]);

  const select = useCallback((id: number | null) => {
    setSessionId(id);
    if (caseId) lsSet(`agent_session_${caseId}`, id === null ? "" : String(id));
  }, [caseId]);

  return { chats, sessionId, select, refresh, ready, closed };
}
