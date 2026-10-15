"use client";

import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { Check, History, Plus } from "lucide-react";
import { whenLabel } from "@/lib/time";
import type { Chat } from "@/components/useChats";

// Past chats of this case: pick one to read it again and carry on, or start a fresh one.
export default function ChatMenu({ chats, sessionId, onSelect, disabled }: {
  chats: Chat[]; sessionId: number | null; onSelect: (id: number | null) => void; disabled?: boolean;
}) {
  return (
    <Dropdown.Root>
      <Dropdown.Trigger asChild>
        <button className="icon-btn" title="Chat history" aria-label="Chat history" disabled={disabled}><History size={17} strokeWidth={1.6} /></button>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content className="menu chat-menu" align="end" sideOffset={6} collisionPadding={12}>
          <Dropdown.Item className="menu-item chat-new" onSelect={() => onSelect(null)}>
            <Plus size={14} strokeWidth={2} /> New chat
          </Dropdown.Item>
          <Dropdown.Separator className="menu-sep" />
          {chats.length === 0 && <div className="chat-menu-empty muted">No earlier chats on this case yet.</div>}
          {chats.map((c) => (
            <Dropdown.Item key={c.id} className="menu-item chat-item" onSelect={() => onSelect(c.id)}>
              <span className="chat-item-text">
                <span className="chat-item-title">{c.title}</span>
                <span className="chat-item-meta">{c.message_count} message{c.message_count === 1 ? "" : "s"} · {whenLabel(c.last_at)} · {c.created_by}</span>
              </span>
              {c.id === sessionId && <Check size={14} strokeWidth={2} className="chat-item-check" />}
            </Dropdown.Item>
          ))}
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}
