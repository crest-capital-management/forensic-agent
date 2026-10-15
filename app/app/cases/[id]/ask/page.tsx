"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import AgentChat from "@/components/AgentChat";
import { ChatSkeleton } from "@/components/AgentChat";
import ChatMenu from "@/components/ChatMenu";
import { useChats } from "@/components/useChats";

// Full-page version of the agent (the same chat that is docked on the right of every other page).
export default function AskPage() {
  const { id } = useParams<{ id: string }>();
  const { chats, sessionId, select, refresh, ready, closed } = useChats(id);
  return (
    <>
      <p><Link href={`/cases/${id}`}>← Back to case</Link></p>
      <div className="row between">
        <h1>Ask the agent</h1>
        <div className="row gap">
          <button className="btn" onClick={() => select(null)}>New chat</button>
          <ChatMenu chats={chats} sessionId={sessionId} onSelect={select} />
        </div>
      </div>
      <p className="notice">
        The agent only <strong>reads</strong> the saved data for this case. It cannot create, change or dismiss a flag,
        run a screen, or contact anyone. Code checks every answer before you see it: every source it cites must really
        have been looked up, banned wording is blocked, and numbers that match nothing in the data are marked. It
        describes; it never concludes who or what is responsible. Questions and answers are saved.
      </p>
      <div className="agent-fullpage">{!ready ? <ChatSkeleton /> : <AgentChat caseId={id} sessionId={sessionId} onSession={select} onChange={refresh} closed={closed} />}</div>
    </>
  );
}
