"""Builds JOB3_SCHEME_OUTLINE.md and .docx for the forensic lead from typology/schemes_draft.yaml.

Run:  .\\.venv\\Scripts\\python.exe -m crest_forensic.typology.build_outline
The illustration at the end uses the flags of the newest saved TCS screens (a flag labelled "not material" does not count as a present
indicator: that is a proposal for the lead). It shows how the scoring would behave; it is not a finding about TCS.
"""
from __future__ import annotations

from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

INTRO = [
    "Purpose: this is the scheme library that Job 3 uses. Job 3 takes the flags a reviewer accepted and asks which known patterns of "
    "accounting misstatement or misuse they resemble. Every output is a hypothesis for planning the next step. The tool never says that "
    "anything wrong was done and never says who did it.",
    "Status: version 1, in use. The developer wrote it on the forensic lead's instruction, using the public ACFE Fraud Tree structure and "
    "public ICAI FAIS titles. The lead can change any scheme. Every match still needs the lead's review, and a match that names an "
    "individual also needs a partner's review.",
    "References: each scheme cites the named branch of the ACFE Fraud Tree and the ICAI FAIS standard titles. Page and paragraph numbers "
    "are not given; the reviewer adds them when verifying, and accepting a match asks the lead to confirm the references were checked.",
    "How a match is scored: coverage = indicators present / indicators in the scheme. A scheme is ranked only when at least 3 indicators "
    "are present, so one strong signal never makes a match. Only flags a reviewer accepted count, and flags labelled not material do not. "
    "Missing indicators are listed, facts that cut against the scheme are kept, and innocent explanations are shown next to every match.",
    "Public-record indicators (regulator orders, tribunal rulings, exchange announcements, credible news) are added by a person with the "
    "source, on the case screen. The tool does not search the web by itself.",
]
QUESTIONS = [
    "Is the list of schemes right? Add, remove or rename any.",
    "Is the scoring rule acceptable (at least 3 present indicators, only accepted and material flags)?",
    "Keep or drop MKT-01 (price or volume moving before results)? It is outside the public Fraud Tree.",
    "Add page or paragraph references for any scheme where you want them cited more exactly.",
]


def load() -> dict:
    return yaml.safe_load((HERE / "schemes.yaml").read_text(encoding="utf-8"))


def illustration(data: dict) -> tuple[list[str], list[dict]]:
    """Which check ids carry a material flag in the newest saved screens, and how each scheme would score."""
    from sqlalchemy import select

    from crest_forensic.db.models import Flag, Run
    from crest_forensic.db.session import get_session

    session = get_session()
    runs = session.execute(select(Run).where(Run.company_id == 1).order_by(Run.id.desc()).limit(2)).scalars().all()
    present, notes = set(), []
    for run in runs:
        for f in session.execute(select(Flag).where(Flag.run_id == run.id)).scalars():
            if (f.materiality or {}).get("label") == "not_material":
                notes.append(f"{f.check_id} {f.financial_year} ({run.basis}) is labelled not material, so it does not count")
                continue
            present.add(f.check_id)
    rows = []
    for s in data["schemes"]:
        have = [i for i in s["indicators"] if i.get("tool_check") in present]
        rows.append({"id": s["id"], "name": s["scheme_name"], "present": len(have), "total": len(s["indicators"]),
                     "ranked": len(have) >= data["scoring"]["min_present"]})
    head = [f"Flags counted from runs {', '.join(str(r.id) for r in runs)}: {', '.join(sorted(present)) or 'none'}."] + sorted(set(notes))
    return head, rows


def refs(s: dict) -> str:
    acfe = "; ".join(c["locator"] for c in s["citations"]["acfe"])
    fais = "; ".join(c["title"] for c in s["citations"]["fais"])
    return f"ACFE Fraud Tree and Report to the Nations ({acfe}). {fais}."


def reachable(s: dict, data: dict) -> str:
    n = sum(1 for i in s["indicators"] if i.get("tool_check"))
    need = data["scoring"]["min_present"]
    return (f"Indicators our current checks can supply: {n} of {len(s['indicators'])} (a match needs {need}). "
            + ("" if n >= need else "Cannot be matched until a public-record input (enforcement orders, news, exchange announcements) is added."))


def markdown(data: dict, head: list[str], rows: list[dict]) -> str:
    out = ["# Job 3: scheme library, version 1", ""]
    out += [f"{p}\n" for p in INTRO]
    out += ["## What you can still change", ""] + [f"{i}. {q}" for i, q in enumerate(QUESTIONS, 1)] + [""]
    out += ["## Schemes", ""]
    for s in data["schemes"]:
        out += [f"### {s['id']}: {s['scheme_name']}", "", f"*Class (verify): {s['acfe_class']}*", "", f"**Pattern:** {s['plain_pattern']}", "",
                "| Indicator | Counts as present when |", "|---|---|"]
        out += [f"| {i['text']} | {i.get('tool_check') or 'public-record item'} |" for i in s["indicators"]]
        out += ["", f"*{reachable(s, data)}*", "", "**Facts that would cut against it:** " + "; ".join(s["contradicting"]), "",
                "**Common innocent explanations:** " + "; ".join(s["innocent_explanations"]), "",
                "**Evidence that would confirm or refute it:**"]
        out += [f"- {e['text']} ({'public' if e['public'] else 'NOT public: needs access to the company'})" for e in s["evidence_to_confirm"]]
        out += ["", f"**References:** {refs(s)}", ""]
    out += ["## How it would score on the saved TCS screens (illustration only, not a finding)", ""] + [f"- {h}" for h in head] + [""]
    out += ["| Scheme | Indicators present | Ranked? |", "|---|---|---|"]
    out += [f"| {r['id']} {r['name']} | {r['present']} of {r['total']} | {'yes' if r['ranked'] else 'no (fewer than 3)'} |" for r in rows]
    return "\n".join(out) + "\n"


def docx(data: dict, head: list[str], rows: list[dict], path: Path) -> None:
    import docx as dx

    d = dx.Document()
    d.add_heading("Job 3: scheme library, version 1", 0)
    for p in INTRO:
        d.add_paragraph(p)
    d.add_heading("What you can still change", 1)
    for q in QUESTIONS:
        d.add_paragraph(q, style="List Number")
    d.add_heading("Schemes", 1)
    for s in data["schemes"]:
        d.add_heading(f"{s['id']}: {s['scheme_name']}", 2)
        d.add_paragraph(f"Class (please verify): {s['acfe_class']}")
        d.add_paragraph(f"Pattern: {s['plain_pattern']}")
        t = d.add_table(rows=1, cols=2)
        t.style = "Light Grid Accent 1"
        t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Indicator", "Counts as present when"
        for i in s["indicators"]:
            c = t.add_row().cells
            c[0].text, c[1].text = i["text"], i.get("tool_check") or "public-record item"
        d.add_paragraph(reachable(s, data))
        d.add_paragraph("Facts that would cut against it: " + "; ".join(s["contradicting"]))
        d.add_paragraph("Common innocent explanations: " + "; ".join(s["innocent_explanations"]))
        d.add_paragraph("Evidence that would confirm or refute it:")
        for e in s["evidence_to_confirm"]:
            d.add_paragraph(f"{e['text']} ({'public' if e['public'] else 'NOT public: needs access to the company'})", style="List Bullet")
        d.add_paragraph(f"References: {refs(s)}")
    d.add_heading("How it would score on the saved TCS screens (illustration only, not a finding)", 1)
    for h in head:
        d.add_paragraph(h, style="List Bullet")
    t = d.add_table(rows=1, cols=3)
    t.style = "Light Grid Accent 1"
    for c, txt in zip(t.rows[0].cells, ("Scheme", "Indicators present", "Ranked?")):
        c.text = txt
    for r in rows:
        c = t.add_row().cells
        c[0].text, c[1].text, c[2].text = f"{r['id']} {r['name']}", f"{r['present']} of {r['total']}", "yes" if r["ranked"] else "no (fewer than 3)"
    d.save(path)


def main() -> None:
    data = load()
    head, rows = illustration(data)
    (ROOT / "JOB3_SCHEME_OUTLINE.md").write_text(markdown(data, head, rows), encoding="utf-8")
    docx(data, head, rows, ROOT / "JOB3_SCHEME_OUTLINE.docx")
    print("written JOB3_SCHEME_OUTLINE.md and .docx;", f"{len(data['schemes'])} schemes;", head[0])
    for r in rows:
        print(f"  {r['id']}: {r['present']}/{r['total']} ranked={r['ranked']}")


if __name__ == "__main__":
    main()
