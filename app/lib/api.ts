// Calls the review API. Who you are comes from the signed-in session cookie.
export async function api<T = any>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: init.method || "GET",
    headers: { "Content-Type": "application/json" },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    cache: "no-store",
    credentials: "same-origin",
  });
  const data = await res.json().catch(() => ({}));
  // Not signed in (or the session ended): go to the login page and come back afterwards. A wrong password on the login page itself just shows its message.
  if (res.status === 401 && path !== "/auth/login" && typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
    return new Promise<T>(() => {});
  }
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`);
  return data as T;
}

export const ROLE_LABEL: Record<string, string> = {
  analyst: "Analyst",
  forensic_lead: "Forensic lead",
  adviser: "Adviser",
  partner: "Partner",
  memo_owner: "Memo owner",
};
