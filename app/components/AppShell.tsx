"use client";

import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Toaster } from "sonner";
import AgentDock from "@/components/AgentDock";
import NavigationLoader from "@/components/NavigationLoader";
import AccountMenu from "@/components/AccountMenu";
import { IconAnalysis, IconCases, IconCompare, IconConfig, IconDashboard, IconHome, IconMemos, IconSparkle, Wordmark } from "@/components/icons";

const NAV = [
  { href: "/home", label: "Home", Icon: IconHome, match: (p: string) => p === "/home" },
  { href: "/cases", label: "Cases", Icon: IconCases, match: (p: string) => p.startsWith("/cases") },
  { href: "/memos", label: "Memos", Icon: IconMemos, match: (p: string) => p.startsWith("/memos") },
  { href: "/analysis", label: "Analysis", Icon: IconAnalysis, match: (p: string) => p.startsWith("/analysis") },
  { href: "/compare", label: "Compare", Icon: IconCompare, match: (p: string) => p.startsWith("/compare") },
  { href: "/config", label: "Limits", Icon: IconConfig, match: (p: string) => p.startsWith("/config") },
  { href: "/dashboard", label: "Dashboard", Icon: IconDashboard, match: (p: string) => p.startsWith("/dashboard") },
];

const RAIL = { min: 60, max: 240, def: 84 };
const AGENT = { min: 320, max: 820, def: 400, wide: 620 };
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

// A thin strip you can drag to resize a column; double-click puts it back to its default width.
function Resizer({ left, onDrag, onReset, onStart, onEnd, label }: {
  left: string; onDrag: (clientX: number) => void; onReset: () => void; onStart: () => void; onEnd: () => void; label: string;
}) {
  const [active, setActive] = useState(false);
  const live = useRef(false);
  return (
    <div className={`resizer ${active ? "active" : ""}`} style={{ left }} role="separator" aria-orientation="vertical" aria-label={label}
      onPointerDown={(e) => { try { e.currentTarget.setPointerCapture(e.pointerId); } catch {} live.current = true; setActive(true); onStart(); }}
      onPointerMove={(e) => { if (live.current) onDrag(e.clientX); }}
      onPointerUp={(e) => { try { e.currentTarget.releasePointerCapture(e.pointerId); } catch {} live.current = false; setActive(false); onEnd(); }}
      onDoubleClick={onReset} title="Drag to resize, double-click to reset" />
  );
}

const lsGet = (k: string) => { try { return localStorage.getItem(k); } catch { return null; } };
const lsSet = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch {} };

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [agentOpen, setAgentOpen] = useState(true);
  const [railW, setRailW] = useState(RAIL.def);
  const [agentW, setAgentW] = useState(AGENT.def);
  const [dragging, setDragging] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const open = lsGet("agent_open");
    if (open !== null) setAgentOpen(open === "1");
    else setAgentOpen(window.innerWidth >= 1280);
    const aw = Number(lsGet("agent_w")), rw = Number(lsGet("rail_w"));
    if (aw) setAgentW(clamp(aw, AGENT.min, AGENT.max));
    if (rw) setRailW(clamp(rw, RAIL.min, RAIL.max));
  }, []);

  const setAgent = (w: number) => { const v = clamp(w, AGENT.min, AGENT.max); setAgentW(v); lsSet("agent_w", String(Math.round(v))); };
  const setRail = (w: number) => { const v = clamp(w, RAIL.min, RAIL.max); setRailW(v); lsSet("rail_w", String(Math.round(v))); };
  const expanded = agentW >= 560;

  if (pathname.startsWith("/login")) return <>{children}<Toaster position="top-center" closeButton toastOptions={{ className: "toast" }} /></>;   // no header or rail before sign-in

  const caseMatch = pathname.match(/^\/cases\/(\d+)/);
  const routeCaseId = caseMatch ? caseMatch[1] : null;
  const fullPageAgent = pathname.endsWith("/ask");       // that page IS the agent, so no dock beside it
  const showDock = agentOpen && !fullPageAgent;

  return (
    <div className="shell">
      <header className="shell-top">
        <Link href="/home" className="brand" aria-label="CREST home"><Wordmark /></Link>
        <div className="shell-top-right">
          <span className="devtag" title="Local development build: simple sign-in on this PC only, no HTTPS yet">Development build</span>
          <button className={`agent-toggle ${showDock ? "on" : ""}`} onClick={() => { setAgentOpen(!agentOpen); lsSet("agent_open", agentOpen ? "0" : "1"); }}
            aria-pressed={agentOpen}><IconSparkle size={18} /> AI agent</button>
          <AccountMenu />
        </div>
      </header>

      <div ref={bodyRef} className={`shell-body ${showDock ? "with-agent" : ""} ${dragging ? "dragging" : ""}`}
        style={{ "--rail-w": `${railW}px`, "--agent-w": `${agentW}px` } as React.CSSProperties}>
        <nav className={`rail ${railW >= 150 ? "wide" : railW < 76 ? "compact" : ""}`} aria-label="Main">
          {NAV.map(({ href, label, Icon, match }) => (
            <Link key={href} href={href} title={label} className={`rail-item ${match(pathname) ? "active" : ""}`}>
              <Icon size={22} /><span>{label}</span>
            </Link>
          ))}
        </nav>

        <Resizer left={`${railW}px`} label="Resize the navigation" onStart={() => setDragging(true)} onEnd={() => setDragging(false)}
          onDrag={(x) => setRail(x - (bodyRef.current?.getBoundingClientRect().left ?? 0))} onReset={() => setRail(RAIL.def)} />

        <main className="panel main-panel">
          <NavigationLoader />
          <motion.div key={pathname} className="main-inner" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, ease: "easeOut" }}>{children}</motion.div>
          <footer className="foot">
            Statistical leads only: most anomalies have innocent explanations. Public data cannot show the reason.
            Nothing here is a finding of wrongdoing.
          </footer>
        </main>

        <AnimatePresence>
          {showDock && (
            <motion.aside key="dock" className="panel agent-panel" initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 24 }} transition={{ duration: 0.2, ease: "easeOut" }}>
              <AgentDock routeCaseId={routeCaseId} expanded={expanded} onToggleExpand={() => setAgent(expanded ? AGENT.def : AGENT.wide)} />
            </motion.aside>
          )}
        </AnimatePresence>

        {showDock && (
          <Resizer left={`calc(100% - ${agentW}px)`} label="Resize the AI agent panel" onStart={() => setDragging(true)} onEnd={() => setDragging(false)}
            onDrag={(x) => setAgent((bodyRef.current?.getBoundingClientRect().right ?? window.innerWidth) - x)} onReset={() => setAgent(AGENT.def)} />
        )}
      </div>
      <Toaster position="top-center" closeButton toastOptions={{ className: "toast" }} />
    </div>
  );
}
