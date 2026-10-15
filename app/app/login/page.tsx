"use client";

import { ArrowRight, Eye, EyeOff, Lock, ShieldCheck, User } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { Wordmark } from "@/components/icons";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      await api("/auth/login", { method: "POST", body: { username, password } });
      const next = new URLSearchParams(window.location.search).get("next") || "/home";
      window.location.href = next.startsWith("/") && !next.startsWith("//") ? next : "/home";   // never leave the app
    } catch (e: any) {
      setErr(e.message);
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <section className="auth-brand">
        <div className="auth-brand-inner">
          <div className="auth-wordmark"><Wordmark /></div>
          <div className="auth-sub">CREST FORENSIC REVIEW</div>
          <h2>Forensic Accounting<br />Review</h2>
          <p>Screen listed companies for warning signs in their public filings. Every flag is cited to its source and left for a person to judge.</p>
          <p className="auth-tag">Statistical leads only: it describes and cites, a person concludes.</p>
        </div>
      </section>

      <section className="auth-form-side">
        <form className="auth-card" onSubmit={submit}>
          <div className="auth-eyebrow">WELCOME BACK</div>
          <h1>Sign in to your account</h1>
          <p className="muted">Access the CREST forensic review tool.</p>

          <label>Username
            <span className="auth-field">
              <User size={16} strokeWidth={1.6} aria-hidden />
              <input type="text" autoComplete="username" autoFocus placeholder="your username" value={username} onChange={(e) => setUsername(e.target.value)} required />
            </span>
          </label>
          <label>Password
            <span className="auth-field">
              <Lock size={16} strokeWidth={1.6} aria-hidden />
              <input type={show ? "text" : "password"} autoComplete="current-password" placeholder="your password" value={password} onChange={(e) => setPassword(e.target.value)} required />
              <button type="button" className="auth-eye" aria-label={show ? "Hide password" : "Show password"} onClick={() => setShow(!show)}>
                {show ? <EyeOff size={16} strokeWidth={1.6} /> : <Eye size={16} strokeWidth={1.6} />}
              </button>
            </span>
          </label>

          {err && <p className="error small" role="alert">{err}</p>}
          <button className="auth-submit" disabled={busy || !username || !password}>
            {busy ? "Signing in…" : <>Sign in <ArrowRight size={16} strokeWidth={1.8} /></>}
          </button>

          <div className="auth-divider"><span>SECURE ACCESS</span></div>
          <div className="auth-note">
            <ShieldCheck size={18} strokeWidth={1.5} aria-hidden />
            <span>Passwords are stored as one-way hashes and a sign-in lasts 12 hours. Forgot your password, or need an account? Ask the forensic lead.</span>
          </div>
        </form>
      </section>
    </div>
  );
}
