"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, ROLE_LABEL } from "@/lib/api";
import Loader from "@/components/Loader";
import Select from "@/components/Select";
import { Tag } from "@/components/Badges";
import { whenLabel } from "@/lib/time";

type U = { username: string; display_name: string; role: string; active: boolean; has_password: boolean; password_set_at: string | null };
type Ev = { id: number; at: string; event: string; username: string; actor: string | null; ip: string | null; detail: string };
const ROLES = Object.keys(ROLE_LABEL);
const EVENT_LABEL: Record<string, string> = {
  login_ok: "Signed in", login_failed: "Wrong sign-in", login_locked: "Locked out", logout: "Signed out", logout_all: "Signed out everywhere",
  password_changed: "Changed own password", password_reset: "Password reset", user_created: "User added",
  user_switched_off: "Switched off", user_switched_on: "Switched on",
};
const EVENT_TONE: Record<string, "accept" | "reject" | "wait"> = { login_failed: "reject", login_locked: "reject", user_switched_off: "wait", password_reset: "wait" };

// Forensic lead only: add people, reset a password, switch an account off.
export default function UsersPage() {
  const [users, setUsers] = useState<U[] | null>(null);
  const [err, setErr] = useState("");
  const [form, setForm] = useState({ username: "", display_name: "", role: "analyst", password: "" });
  const [resetFor, setResetFor] = useState<string | null>(null);
  const [resetPw, setResetPw] = useState("");
  const [events, setEvents] = useState<Ev[]>([]);

  const load = () => {
    api<Ev[]>("/auth/events?limit=50").then(setEvents).catch(() => setEvents([]));
    return api<U[]>("/users").then(setUsers).catch((e) => setErr(e.message));
  };
  useEffect(() => { load(); }, []);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setErr("");
    try { await fn(); toast.success(ok); await load(); } catch (e: any) { setErr(e.message); }
  }

  if (err && !users) return <p className="error">{err}</p>;
  if (!users) return <Loader label="Loading users" />;

  return (
    <>
      <h1>Users</h1>
      <p className="muted small">Only the forensic lead sees this page. Passwords are kept as one-way hashes: nobody, including you, can read one back. Resetting a password signs that person out everywhere.</p>
      {err && <p className="error small">{err}</p>}
      <div className="tablewrap">
        <table className="assets">
          <thead><tr><th>Username</th><th>Name</th><th>Role</th><th>Password</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.username}>
                <td><span className="sym">{u.username}</span></td>
                <td>{u.display_name}</td>
                <td>{ROLE_LABEL[u.role] || u.role}</td>
                <td>{u.has_password ? <span className="muted">set {u.password_set_at ? whenLabel(u.password_set_at) : ""}</span> : <Tag tone="wait">none: cannot sign in</Tag>}</td>
                <td>{u.active ? <Tag tone="accept">active</Tag> : <Tag tone="reject">switched off</Tag>}</td>
                <td>
                  {resetFor === u.username ? (
                    <span className="row gap">
                      <input type="password" autoComplete="new-password" placeholder="New password" value={resetPw} onChange={(e) => setResetPw(e.target.value)} aria-label={`New password for ${u.username}`} />
                      <button className="btn primary" disabled={resetPw.length < 10}
                        onClick={() => act(async () => { await api(`/users/${u.username}/password`, { method: "POST", body: { new: resetPw } }); setResetFor(null); setResetPw(""); }, `Password set for ${u.username}`)}>Set</button>
                      <button className="btn" onClick={() => { setResetFor(null); setResetPw(""); }}>Cancel</button>
                    </span>
                  ) : (
                    <span className="row gap">
                      <button className="btn" onClick={() => setResetFor(u.username)}>{u.has_password ? "Reset password" : "Set password"}</button>
                      <button className="btn" onClick={() => act(() => api(`/users/${u.username}/active`, { method: "POST", body: { active: !u.active } }), u.active ? `${u.username} switched off` : `${u.username} switched on`)}>
                        {u.active ? "Switch off" : "Switch on"}
                      </button>
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <form className="card form narrowform" onSubmit={(e) => { e.preventDefault(); act(async () => { await api("/users", { method: "POST", body: form }); setForm({ username: "", display_name: "", role: "analyst", password: "" }); }, "User added"); }}>
        <h2>Add a user</h2>
        <label>Username<input type="text" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required /></label>
        <label>Display name<input type="text" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} required /></label>
        <label>Role<Select value={form.role} onChange={(v) => setForm({ ...form, role: v })} options={ROLES.map((r) => ({ value: r, label: ROLE_LABEL[r] }))} /></label>
        <label>First password (at least 10 characters)<input type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required /></label>
        <button className="btn primary" disabled={!form.username || !form.display_name || form.password.length < 10}>Add user</button>
      </form>

      <h2>Recent sign-in activity</h2>
      <p className="muted small">The last 50 events. Passwords are never recorded. A wrong sign-in shows the username as typed, so a mistyped name can appear here.</p>
      <div className="tablewrap">
        <table className="assets">
          <thead><tr><th>When</th><th>Event</th><th>Account</th><th>Done by</th><th>Address</th><th>Note</th></tr></thead>
          <tbody>
            {events.length === 0 && <tr><td colSpan={6} className="muted">Nothing recorded yet.</td></tr>}
            {events.map((e) => (
              <tr key={e.id}>
                <td>{whenLabel(e.at)}</td>
                <td>{EVENT_TONE[e.event] ? <Tag tone={EVENT_TONE[e.event]}>{EVENT_LABEL[e.event] || e.event}</Tag> : <span>{EVENT_LABEL[e.event] || e.event}</span>}</td>
                <td><span className="sym">{e.username}</span></td>
                <td>{e.actor || ""}</td>
                <td>{e.ip || ""}</td>
                <td className="muted">{e.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
