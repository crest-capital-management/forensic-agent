"use client";

import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { KeyRound, LogOut, User, Users } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ROLE_LABEL } from "@/lib/api";

type Me = { username: string; display_name: string; role: string };

// "Forensic lead (dev)" -> "FL"
export function initials(name: string): string {
  const words = name.replace(/\(.*?\)/g, "").trim().split(/\s+/).filter(Boolean);
  return ((words[0]?.[0] || "?") + (words.length > 1 ? words[1][0] : "")).toUpperCase();
}

// The round profile icon at the top right: profile page, change password, users (lead) and sign out.
export default function AccountMenu() {
  const [me, setMe] = useState<Me | null>(null);
  useEffect(() => { api<Me>("/me").then(setMe).catch(() => {}); }, []);

  async function signOut() {
    try { await api("/auth/logout", { method: "POST" }); } catch {}
    window.location.href = "/login";
  }

  if (!me) return <span className="avatar avatar-ghost" aria-hidden />;
  return (
    <Dropdown.Root>
      <Dropdown.Trigger asChild>
        <button type="button" className="avatar" aria-label={`Profile menu for ${me.display_name}`} title={me.display_name}>{initials(me.display_name)}</button>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content className="menu account-menu" align="end" sideOffset={8} collisionPadding={12}>
          <div className="account-who">
            <span className="avatar avatar-lg" aria-hidden>{initials(me.display_name)}</span>
            <span className="account-who-text"><strong>{me.display_name}</strong><span className="muted small">{me.username} · {ROLE_LABEL[me.role] || me.role}</span></span>
          </div>
          <Dropdown.Separator className="menu-sep" />
          <Dropdown.Item asChild className="menu-item"><Link href="/profile"><User size={14} /> Profile</Link></Dropdown.Item>
          <Dropdown.Item asChild className="menu-item"><Link href="/profile#password"><KeyRound size={14} /> Change password</Link></Dropdown.Item>
          {me.role === "forensic_lead" && <Dropdown.Item asChild className="menu-item"><Link href="/users"><Users size={14} /> Manage users</Link></Dropdown.Item>}
          <Dropdown.Separator className="menu-sep" />
          <Dropdown.Item className="menu-item" onSelect={signOut}><LogOut size={14} /> Sign out</Dropdown.Item>
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}
