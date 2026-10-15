"""PDF export of a memo (Job 4), the same content as the Word file.

The status line ("DRAFT - for human review", or "Signed by ... on ...") and the reference are stamped at the top of EVERY page, and
the page number at the bottom, after the body has been laid out. Nothing is sent anywhere; the file only goes back to the person
who asked for it.
"""
from __future__ import annotations

import io
from html import escape as e

import fitz  # PyMuPDF

CSS = """
body { font-family: sans-serif; font-size: 10pt; line-height: 1.35; }
h1 { font-size: 18pt; margin: 0 0 4pt 0; }
h2 { font-size: 13pt; margin: 14pt 0 4pt 0; }
h3 { font-size: 11pt; margin: 10pt 0 3pt 0; }
p { margin: 0 0 5pt 0; }
li { margin: 0 0 3pt 0; }
td { padding: 2pt 8pt 2pt 0; vertical-align: top; }
.muted { color: #555555; }
.warn { font-weight: bold; }
.src { font-size: 8.5pt; color: #333333; }
"""

PUBLIC = {"yes": "public data can close this", "partly": "public data can partly close this", "no": "public data cannot close this"}


def _html(m: dict) -> str:
    c, h = m["content"], m["content"]["header"]
    out = [f"<h1>Research assessment memo</h1><p><b>{e(h['company'])} ({e(h['symbol'])})</b></p>"]
    rows = [("Reference", m["reference"]), ("Case", f"#{m['case_id']}"), ("Years in scope", ", ".join(h["years"])),
            ("Basis", ", ".join(h["bases"])), ("Version", str(m["shown_version_no"])), ("Owner", h["owner"]),
            ("Data as of", h["data_as_of"]), ("Status", m["banner"])]
    out.append("<table>" + "".join(f"<tr><td><b>{e(k)}</b></td><td>{e(v)}</td></tr>" for k, v in rows) + "</table>")
    out.append(f"<p class='{'muted' if h['limits_approved'] else 'warn'}'>{e(h['limits_line'])}</p>")
    out += [f"<p class='warn'>Notice: {e(n)}</p>" for n in c.get("notices", [])]

    out.append("<h2>1. Assessment scope and objective</h2>" + "".join(f"<p>{e(t)}</p>" for t in c["scope"]))
    out.append("<h2>2. Background and trigger</h2>" + "".join(f"<p>{e(t)}</p>" for t in c["background"]))

    out.append("<h2>3. Findings summary</h2>")
    for i, f in enumerate(c["findings"], 1):
        r = f["reviewer"]
        out.append(f"<h3>Finding {i}: {e(f['check_id'])}, {e(f['financial_year'])}, {e(f['basis'])} "
                   f"({e(f['severity'])}, {e(str(f['materiality']).replace('_', ' '))})</h3>")
        out.append(f"<p>{e(f['text'])}</p><p class='muted'>{e(f['limit_line'])}</p>")
        out.append(f"<p>Accepted by {e(r['by_name'] or r['by'])} on {e(r['at'][:10])}: &ldquo;{e(r['reason'])}&rdquo;"
                   + (" (decision carried over from an earlier identical flag)" if r["carried_from_earlier_run"] else "") + "</p>")
        out.append("<ul class='src'>" + "".join(
            f"<li>[{e(s['ref'])}] {e(s['label'])}" + (f" &mdash; &ldquo;{e(s['quote'])}&rdquo;" if s.get("quote") else "") + "</li>"
            for s in f["sources"]) + "</ul>")
        out.append(f"<p class='muted'><i>{e(f['standing_line'])}</i></p>")

    out.append("<h2>4. Open questions and gaps</h2><ul>" + "".join(
        f"<li>{e(q['text'])} <span class='muted'>({e(PUBLIC[q['public_data']])}: {e(q['how'])})</span></li>" for q in c["open_questions"]) + "</ul>")
    ns = c["next_steps"]
    out.append("<h2>5. Recommended next steps</h2><h3>Possible on public data</h3><ul>" + "".join(f"<li>{e(s)}</li>" for s in ns["public"])
               + "</ul><h3>What a formal engagement with data access would need</h3><ul>" + "".join(f"<li>{e(s)}</li>" for s in ns["engagement"]) + "</ul>")

    signed = (f"Signed by {e(m['owner_name'])} on {e(m['signed_at'][:10])} (version {m['signed_version_no']})."
              if m["status"] == "signed" else "Signature: ______________________ &nbsp;&nbsp; Date: ______________")
    out.append(f"<h2>6. Ownership and sign-off</h2><p>Owner: {e(h['owner'])}</p><p>{e(c['ownership']['note'])}</p><p>{signed}</p>")

    a = c["annex_a"]
    out.append("<h2>Annex A. Method and limits</h2><p>Checks used: " + e(", ".join(f"{x['check_id']} {x['name']}" for x in a["checks"])) + "</p><ul>"
               + "".join(f"<li>Run {r['run_id']} ({e(r['basis'])}), years {e(', '.join(r['years']))}, limits approved: "
                         f"{'yes' if r['config_approved'] else 'no'}, code {e(r['code_version'])}</li>" for r in a["runs"])
               + f"</ul><p>Source precedence: {e(a['source_rule'])}.</p><p>{e(a['library_line'])}</p>")
    seen, cites = set(), []
    for s in c["annex_b"]:
        if s["ref"] not in seen:
            seen.add(s["ref"])
            cites.append(f"<li>[{e(s['ref'])}] {e(s['label'])}</li>")
    out.append("<h2>Annex B. Citations</h2><ul class='src'>" + "".join(cites) + "</ul>")
    out.append("<h2>Annex C. Change log</h2><ul>" + "".join(
        f"<li>Version {v['version_no']} ({e(v['kind'])}), {e(v['created_at'][:16].replace('T', ' '))} UTC, by "
        f"{e(v['created_by_name'] or v['created_by'])}: {e(v['change_note'])}</li>" for v in m["versions"]) + "</ul>")
    out.append(f"<h2>Annex D. Documentation references (ICAI FAIS, SEBI RIA)</h2><p>{e(c['annex_d']['text'])}</p>")
    ae = c.get("annex_e")
    if ae:
        out.append(f"<h2>Annex E. Scheme hypotheses (Job 3)</h2><p>{e(ae['line'])}</p>")
        for h in ae["matches"]:
            out.append(f"<h3>{e(h['scheme_id'])} {e(h['scheme_name'])}</h3><p>{e(h['class_label'])}: hypothesis, {h['coverage_pct']}% of the scheme's indicators present. "
                       f"Accepted by {e(h['lead'])}" + (f" and {e(h['partner'])}" if h["partner"] else "") + ".</p>"
                       "<ul>" + "".join(f"<li>Present: {e(p['indicator'])} ({e(p['detail'])})</li>" for p in h["present"])
                       + f"<li>Missing: {e('; '.join(h['missing']) or 'none')}</li>"
                       + f"<li>Facts that cut against it: {e('; '.join(h['against']))}</li>"
                       + f"<li>Common innocent explanations: {e('; '.join(h['innocent']))}</li>"
                       + "<li>Evidence that would confirm or refute it: " + e("; ".join(f"{x['text']} ({'public' if x['public'] else 'not public'})" for x in h["evidence"])) + "</li>"
                       + f"<li>References: {e('; '.join(ae['references'].get(h['scheme_id'], [])))}</li></ul>")
    out += [f"<p class='muted'><i>{e(line)}</i></p>" for line in c["standing"]]
    return "<html><body>" + "".join(out) + "</body></html>"


def build_pdf(m: dict) -> bytes:
    story = fitz.Story(html=_html(m), user_css=CSS)
    buf = io.BytesIO()
    writer = fitz.DocumentWriter(buf)
    page_rect = fitz.paper_rect("a4")
    body = page_rect + (50, 60, -50, -55)
    more = True
    while more:
        dev = writer.begin_page(page_rect)
        more, _ = story.place(body)
        story.draw(dev)
        writer.end_page()
    writer.close()

    doc = fitz.open("pdf", buf.getvalue())
    head = f"{m['banner']}   |   {m['reference']}   |   version {m['shown_version_no']}"
    for n, page in enumerate(doc, 1):
        w = page.rect.width
        page.insert_textbox(fitz.Rect(40, 24, w - 40, 48), head, fontsize=9, fontname="hebo", align=fitz.TEXT_ALIGN_CENTER)
        page.insert_textbox(fitz.Rect(40, page.rect.height - 40, w - 40, page.rect.height - 20), f"Page {n} of {len(doc)}",
                            fontsize=8, fontname="helv", align=fitz.TEXT_ALIGN_CENTER)
    out = doc.tobytes()
    doc.close()
    return out
