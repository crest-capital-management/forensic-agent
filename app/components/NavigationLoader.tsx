"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import Loader from "@/components/Loader";

// Shows the loading screen the instant an internal link is clicked, until the new page has arrived.
// Next's own loading.tsx cannot cover this gap in development: the old page just stays on screen
// ("Rendering…") while the next route compiles.
export default function NavigationLoader() {
  const pathname = usePathname();
  const [pending, setPending] = useState(false);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as HTMLElement | null)?.closest?.("a");
      if (!a || a.target === "_blank" || a.hasAttribute("download")) return;
      const url = new URL(a.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      if (url.pathname === window.location.pathname) return;   // same page: nothing to wait for
      setPending(true);
    }
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, []);

  // The new page has arrived.
  useEffect(() => setPending(false), [pathname]);

  // Never leave the screen stuck if a navigation fails.
  useEffect(() => {
    if (!pending) return;
    const t = setTimeout(() => setPending(false), 30000);
    return () => clearTimeout(t);
  }, [pending]);

  if (!pending) return null;
  return (
    <div className="nav-loader" aria-busy="true">
      <Loader label="Opening the page" />
    </div>
  );
}
