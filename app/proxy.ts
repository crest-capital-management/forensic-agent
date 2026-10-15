import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Runs before every page. Nobody sees any page of the app without a valid session: the cookie is checked with the review API
// (which is what really protects the data; this stops the app's pages and shell from showing at all).
const API = "http://127.0.0.1:8000";
const COOKIE = "crest_session";

function withNoStore(res: NextResponse): NextResponse {
  res.headers.set("Cache-Control", "no-store, max-age=0");   // after sign-out, Back must not show a saved copy of a page
  return res;
}

async function signedIn(req: NextRequest): Promise<boolean | null> {
  if (!req.cookies.get(COOKIE)) return false;
  try {
    const r = await fetch(`${API}/api/me`, { headers: { cookie: req.headers.get("cookie") || "" }, cache: "no-store" });
    return r.status === 200;
  } catch {
    return null;       // the API is not reachable: let the page load and say so, instead of looping to the login page
  }
}

export async function proxy(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  const ok = await signedIn(req);

  if (pathname.startsWith("/login")) {
    if (ok === true) {                                    // already signed in: no need to see the login page
      const next = req.nextUrl.searchParams.get("next") || "/home";
      return withNoStore(NextResponse.redirect(new URL(next.startsWith("/") && !next.startsWith("//") ? next : "/home", req.url)));
    }
    return withNoStore(NextResponse.next());
  }
  if (ok === false) {
    const to = new URL("/login", req.url);
    to.searchParams.set("next", pathname + search);
    const res = NextResponse.redirect(to);
    if (req.cookies.get(COOKIE)) res.cookies.delete(COOKIE);     // an expired or revoked cookie is dropped
    return withNoStore(res);
  }
  return withNoStore(NextResponse.next());
}

// Pages only: the API (guarded by its own session check), Next's files and the fonts are left out.
export const config = { matcher: ["/((?!api|_next|fonts|favicon.ico|.*\\..*).*)"] };
