"use client";

import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { Check, ChevronDown, Search } from "lucide-react";
import { useRef, useState } from "react";

export type Option = { value: string | number; label: string };

// A styled dropdown that matches the rest of the app (the browser's own <select> list cannot be styled).
export default function Select({ value, onChange, options, placeholder = "Choose…", disabled, className = "", ariaLabel, searchable }: {
  value: string | number; onChange: (v: string) => void; options: Option[]; placeholder?: string;
  disabled?: boolean; className?: string; ariaLabel?: string; searchable?: boolean;
}) {
  const current = options.find((o) => String(o.value) === String(value));
  const [q, setQ] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const withSearch = searchable ?? options.length > 7;      // long lists get a search box on their own
  const shown = withSearch && q.trim() ? options.filter((o) => o.label.toLowerCase().includes(q.trim().toLowerCase())) : options;
  return (
    <Dropdown.Root onOpenChange={(open) => { if (!open) setQ(""); }}>
      <Dropdown.Trigger asChild disabled={disabled}>
        <button type="button" className={`select-trigger ${className}`} aria-label={ariaLabel}>
          <span className={current ? "" : "muted"}>{current ? current.label : placeholder}</span>
          <ChevronDown size={15} strokeWidth={1.8} aria-hidden />
        </button>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content className="menu select-menu" align="start" sideOffset={6} collisionPadding={12}>
          {withSearch && (
            <div className="select-search">
              <Search size={14} strokeWidth={1.8} aria-hidden />
              <input type="text" autoFocus value={q} placeholder="Search" aria-label="Search the list" onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => {
                  e.stopPropagation();                         // keep the menu's own type-ahead out of the way
                  if (e.key === "ArrowDown") { e.preventDefault(); (listRef.current?.querySelector('[role="menuitemradio"]') as HTMLElement | null)?.focus(); }
                  if (e.key === "Enter" && shown.length === 1) onChange(String(shown[0].value));
                }} />
            </div>
          )}
          {withSearch && shown.length === 0 && <div className="chat-menu-empty muted">Nothing matches.</div>}
          <Dropdown.RadioGroup value={String(value)} onValueChange={onChange} ref={listRef}>
            {shown.map((o) => (
              <Dropdown.RadioItem key={o.value} value={String(o.value)} className="menu-item select-item">
                <span>{o.label}</span>
                <Dropdown.ItemIndicator className="select-check"><Check size={14} strokeWidth={2} /></Dropdown.ItemIndicator>
              </Dropdown.RadioItem>
            ))}
          </Dropdown.RadioGroup>
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}
