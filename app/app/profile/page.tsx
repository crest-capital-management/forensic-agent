"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, ROLE_LABEL } from "@/lib/api";
import { whenLabel } from "@/lib/time";
import Loader from "@/components/Loader";
import { initials } from "@/components/AccountMenu";

type Me = { username: string; display_name: string; role: string; password_set_at: string | null; signed_in_devices: number };

const WHAT_ROLE_CAN: Record<string, string> = {
  analyst: "Open cases, accept or reject flags, request escalation, ask the agent, close or reopen cases, write matrix narratives.",
  forensic_lead: "Everything an analyst can do, plus edit, confirm and approve the limits and manage users.",
  adviser: "Read everything and approve escalations for portfolio companies.",
  partner: "Read cases, flags, matrices and the dashboard.",
  memo_owner: "Read cases, flags, matrices and the dashboard.",
};

export default function ProfilePage() {
  const [me, setMe] = useState<Me | null>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => api<Me>("/me").then(setMe).catch(() => {});
  useEffect(() => { load(); }, []);

  async function changePassword(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    if (next !== again) { setErr("The two new passwords differ."); return; }
    setBusy(true);
    try {
      await api("/auth/password", { method: "POST", body: { current, new: next } });
      toast.success("Password changed. Your other devices were signed out.");
      setCurrent(""); setNext(""); setAgain("");
      load();
    } catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function signOut(everywhere: boolean) {
    try { await api(everywhere ? "/auth/logout-all" : "/auth/logout", { method: "POST" }); } catch {}
    window.location.href = "/login";
  }

  if (!me) return <Loader label="Loading your profile" />;
  return (
    <>
      <h1>Profile</h1>
      <div className="card profile-head">
        <span className="avatar avatar-xl" aria-hidden>{initials(me.display_name)}</span>
        <div>
          <div className="profile-name">{me.display_name}</div>
          <div className="muted">{me.username} · {ROLE_LABEL[me.role] || me.role}</div>
        </div>
        <button className="btn profile-signout" onClick={() => signOut(false)}>Sign out</button>
      </div>

      <div className="card">
        <h2>About this account</h2>
        <dl className="profile-dl">
          <dt>Username</dt><dd>{me.username}</dd>
          <dt>Role</dt><dd>{ROLE_LABEL[me.role] || me.role}</dd>
          <dt>What this role can do</dt><dd>{WHAT_ROLE_CAN[me.role] || "Read-only access."}</dd>
          <dt>Password last changed</dt><dd>{me.password_set_at ? whenLabel(me.password_set_at) : "never"}</dd>
          <dt>Devices signed in</dt><dd>{me.signed_in_devices}{me.signed_in_devices > 1 ? " (including this one)" : ""}</dd>
        </dl>
        {me.role === "forensic_lead" && <p className="small"><Link href="/users">Manage users →</Link></p>}
      </div>

      <form id="password" onSubmit={changePassword} className="card form narrowform">
        <h2>Change password</h2>
        <label>Current password
          <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        </label>
        <label>New password (at least 10 characters)
          <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />
        </label>
        <label>New password again
          <input type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} required />
        </label>
        {err && <p className="error small">{err}</p>}
        <button className="btn primary" disabled={busy || !current || !next}>Change password</button>
        <p className="muted small" style={{ margin: "8px 0 0" }}>Changing it signs you out on your other devices.</p>
      </form>

      <div className="card">
        <h2>Sign out everywhere</h2>
        <p className="muted small">Ends every session of this account, on this device and any other, for example if you left yourself signed in on a shared computer.</p>
        <button className="btn" onClick={() => signOut(true)}>Sign out of all devices</button>
      </div>
    </>
  );
}
