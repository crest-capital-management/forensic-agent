"""Phase 1 CLI.

Commands:
    init-db                         create tables (dev convenience; use alembic in prod)
    search <query>                  read-only: dump the provider's raw /stocks/search response
    discover <sc_id>                fetch every Phase 1 endpoint live, save snapshots, print
                                     the raw structure so the field-mapping config can be filled in
    ingest <sc_id> --name NAME      fetch + snapshot + normalize a company end to end
    ingest-yahoo <sc_id> --ticker TCS.NS
                                    add Yahoo Finance as a second source (free, no key; carries
                                     real operating cash flow). Company must already be ingested.
    run-screen <sc_id_or_name> --basis consolidated --from FY2023 --to FY2026 [--allow-draft-config]
                                    Phase 2: run the Job 1 number checks (J1-01..J1-09), create flags.
                                     Refuses to run unless the limits in config/check_config.yaml
                                     are approved; --allow-draft-config is for development only.
    show-flags <sc_id_or_name> [--run RUN_ID]
                                    flags, per-check status and data gaps for a run (default: latest)
    ingest-document <sc_id> <pdf> --fy FY2026
                                    Phase 3: store an annual report (hash + every page's text), find its
                                     sections, read the printed statements and the auditor's identity
    extract-text <sc_id> --fy FY2026 [--basis both] [--checks J1-10,J1-11,J1-14,J1-15]
                                    [--extractor claude|gemini|recorded] [--recorded FILE] [--force]
                                    Phase 3: the model points at passages in the report; code then verifies
                                     every quote. Needs ANTHROPIC_API_KEY unless --extractor recorded
    show-findings <sc_id_or_name> [--fy FY2026] [--all]
                                    passages found, and whether each quote passed verification
    check-golden <sc_id_or_name> [--golden PATH]
                                    compare each source's saved numbers with the audited annual-report
                                     figures in tests/golden/ — which source is right, field by field
    show-resolved <sc_id_or_name> [--field cash_flow_from_operations] [--basis consolidated]
                                    which value a check would use per year, and why
    reprocess <sc_id_or_name>       re-run normalization on ALREADY-SAVED snapshots —
                                     zero network calls. Use this after editing
                                     config/field_mapping_rapidapi.yaml instead of
                                     re-ingesting, especially on a limited API quota.
    show-snapshots <sc_id_or_name>
    show-quality <sc_id_or_name>
    show-values <sc_id_or_name> [--year FY2025] [--basis standalone]
"""
from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import select

from crest_forensic.connectors.rapidapi_moneycontrol import RapidApiMoneyControlConnector
from crest_forensic.db.models import Company, DataQualityEvent, LineItem, Snapshot
from crest_forensic.db.session import get_session, init_db
from crest_forensic.connectors.yfinance_connector import YFinanceConnector
from crest_forensic.documents.ingest import ingest_document
from crest_forensic.text.auditor import run_auditor_identity
from crest_forensic.text.extractors import ClaudeExtractor, GeminiExtractor, RecordedExtractor
from crest_forensic.text.run import run_text_task
from crest_forensic.documents.statements import extract_all_documents, extract_statement_lines
from crest_forensic.db.models import (
    CheckResultRow, Document, DocumentVersion, Flag, GuardrailEvent, Run, TextFinding,
)
from crest_forensic.guardrails.config_gate import ConfigNotApproved
from crest_forensic.guardrails.language import LEADS_NOT_PROOF, PUBLIC_DATA_LIMIT
from crest_forensic.screen import run_screen, years_between
from crest_forensic.ingestion.derive import derive_cfo_indirect
from crest_forensic.ingestion.fetch_and_snapshot import save_snapshot
from crest_forensic.ingestion.mapping import DEFAULT_MAPPING_PATH, load_field_mapping
from crest_forensic.ingestion.normalize import normalize_snapshot
from crest_forensic.ingestion.resolve import detect_source_conflicts, resolve_value
from crest_forensic.ingestion.yahoo import (
    YAHOO_PROVIDER,
    ingest_yahoo,
    load_yahoo_mapping,
    normalize_yahoo_batch,
)
from crest_forensic.ingestion.supported_status import compute_supported_status

STATEMENT_TYPES = ["income", "balance_sheet", "cash_flow"]
BASES = ["standalone", "consolidated"]


def _get_or_create_company(session, sc_id: str, name: str | None, sector: str | None,
                            isin: str | None, nse_symbol: str | None) -> Company:
    company = session.execute(select(Company).where(Company.sc_id == sc_id)).scalar_one_or_none()
    if company is None:
        company = Company(
            sc_id=sc_id,
            name=name or sc_id,
            sector=sector,
            isin=isin,
            nse_symbol=nse_symbol,
        )
        session.add(company)
        session.flush()
    return company


def _resolve_company(session, identifier: str) -> Company | None:
    return session.execute(
        select(Company).where(
            (Company.sc_id == identifier)
            | (Company.nse_symbol == identifier)
            | (Company.name == identifier)
        )
    ).scalar_one_or_none()


def cmd_init_db(args: argparse.Namespace) -> None:
    init_db()
    print("Tables created.")


def cmd_set_password(args: argparse.Namespace) -> None:
    """Set (or create) a review-app user's password. Typed at a hidden prompt: it is never printed, logged or stored in clear."""
    import getpass

    from crest_forensic.review import auth, service

    session = get_session()
    try:
        service.ensure_default_users(session)
        user = session.execute(select(service.AppUser).where(service.AppUser.username == args.username.lower())).scalars().first()
        if user is None:
            if not args.role or not args.name:
                raise SystemExit(f"No user '{args.username}'. To create one add --role (one of {', '.join(service.ROLES)}) and --name.")
            user = service.AppUser(username=args.username.lower(), display_name=args.name, role=args.role)
            session.add(user)
        first = getpass.getpass(f"New password for {user.username} (at least {auth.MIN_PASSWORD} characters): ")
        if getpass.getpass("Type it again: ") != first:
            raise SystemExit("The two entries differ. Nothing was changed.")
        auth.check_new_password(first, user.username)
        user.password_hash = auth.hash_password(first)
        user.password_set_at = auth._now()
        auth._revoke_all(session, user.username)
        session.commit()
        print(f"Password set for {user.username} ({user.role}).")
    except service.RuleError as exc:
        session.rollback()
        raise SystemExit(str(exc))
    finally:
        session.close()


def cmd_search(args: argparse.Namespace) -> None:
    connector = RapidApiMoneyControlConnector()
    response = connector.search_company(args.query)
    print(f"status_code={response.status_code}")
    print(json.dumps(response.payload, indent=2)[:4000])


def cmd_discover(args: argparse.Namespace) -> None:
    """Live discovery: hit every Phase 1 endpoint, save snapshots, print structure.

    This is Step 1 of the Phase 1 build: inspect real field names before the
    field-mapping config is filled in. Nothing here is normalized yet.
    """
    connector = RapidApiMoneyControlConnector()
    session = get_session()
    company = _get_or_create_company(session, args.sc_id, args.name, None, None, None)

    for statement_type in STATEMENT_TYPES + ["ratios"]:
        for basis in BASES:
            if statement_type == "ratios" and basis == "consolidated":
                continue  # ratios endpoint doesn't take type=
            response = connector.fetch_financials(args.sc_id, statement_type, basis)
            snapshot = save_snapshot(session, company.company_id, response)
            print(f"\n=== {statement_type} / {basis} — status {response.status_code} "
                  f"(snapshot_id={snapshot.snapshot_id}) ===")
            print(json.dumps(response.payload, indent=2)[:3000])

    response = connector.fetch_shareholding(args.sc_id)
    snapshot = save_snapshot(session, company.company_id, response)
    print(f"\n=== shareholding — status {response.status_code} "
          f"(snapshot_id={snapshot.snapshot_id}) ===")
    print(json.dumps(response.payload, indent=2)[:3000])

    session.commit()
    print(f"\nSaved {len(STATEMENT_TYPES) * 2 + 1} snapshots for company_id={company.company_id}. "
          f"Inspect the JSON above, then fill in config/field_mapping_rapidapi.yaml.")


def cmd_ingest(args: argparse.Namespace) -> None:
    connector = RapidApiMoneyControlConnector()
    session = get_session()
    mapping_config = load_field_mapping(DEFAULT_MAPPING_PATH)

    company = _get_or_create_company(
        session, args.sc_id, args.name, args.sector, args.isin, args.nse_symbol
    )

    for statement_type in STATEMENT_TYPES:
        for basis in BASES:
            response = connector.fetch_financials(args.sc_id, statement_type, basis)
            snapshot = save_snapshot(session, company.company_id, response)
            if response.parse_error:
                continue
            created = normalize_snapshot(session, snapshot, mapping_config, basis, statement_type)
            print(f"{statement_type}/{basis}: {len(created)} line items from snapshot {snapshot.snapshot_id}")

    session.flush()
    for basis in BASES:
        derived = derive_cfo_indirect(session, company.company_id, basis)
        print(f"derived cash_flow_from_operations/{basis}: {len(derived)} years")

    company.supported_status = compute_supported_status(session, company.company_id, company.sector)
    session.commit()
    print(f"\ncompany_id={company.company_id} supported_status={company.supported_status}")


_ENDPOINT_PATH_TO_KEY = {
    "/stocks/financials/income": "income",
    "/stocks/financials/balance-sheet": "balance_sheet",
    "/stocks/financials/cash-flow": "cash_flow",
    "/stocks/financials/ratios": "ratios",
}


def cmd_reprocess(args: argparse.Namespace) -> None:
    """Re-normalize already-saved snapshots. Makes NO network calls."""
    session = get_session()
    mapping_config = load_field_mapping(DEFAULT_MAPPING_PATH)
    company = _resolve_company(session, args.identifier)
    if not company:
        print("Company not found.")
        return

    # Clear this company's previously-derived rows so re-running doesn't
    # duplicate them. Snapshots themselves are never touched.
    session.query(LineItem).filter(LineItem.company_id == company.company_id).delete()
    session.query(DataQualityEvent).filter(DataQualityEvent.company_id == company.company_id).delete()
    session.flush()

    snapshots = session.execute(
        select(Snapshot).where(Snapshot.company_id == company.company_id).order_by(Snapshot.snapshot_id)
    ).scalars().all()

    for snap in snapshots:
        endpoint = _ENDPOINT_PATH_TO_KEY.get(snap.source_endpoint)
        if endpoint not in ("income", "balance_sheet", "cash_flow"):
            continue
        basis = snap.request_params.get("type", "standalone")
        created = normalize_snapshot(session, snap, mapping_config, basis, endpoint)
        print(f"snapshot {snap.snapshot_id} ({endpoint}/{basis}): {len(created)} line items")

    # Yahoo batches are normalized AFTER the RapidAPI rows exist, because
    # inferring Yahoo's basis needs RapidAPI's revenue to compare against.
    session.flush()
    batches: dict[str | None, list[Snapshot]] = {}
    for snap in snapshots:
        if snap.source_provider == YAHOO_PROVIDER:
            batches.setdefault(snap.request_params.get("batch"), []).append(snap)
    yahoo_mapping = load_yahoo_mapping()
    for batch_id, batch_snaps in batches.items():
        basis, created = normalize_yahoo_batch(session, company.company_id, batch_snaps, yahoo_mapping)
        print(f"yfinance batch {batch_id}: {len(created)} line items, basis={basis}")

    session.flush()
    doc_items = extract_all_documents(session, company.company_id)
    print(f"annual-report statements: {len(doc_items)} line items")

    session.flush()
    for basis in BASES:
        derived = derive_cfo_indirect(session, company.company_id, basis)
        print(f"derived cash_flow_from_operations/{basis}: {len(derived)} years")

    session.flush()
    conflicts = detect_source_conflicts(session, company.company_id)
    print(f"source conflicts: {len(conflicts)}")

    company.supported_status = compute_supported_status(session, company.company_id, company.sector)
    session.commit()
    print(f"\ncompany_id={company.company_id} supported_status={company.supported_status}")


def cmd_ingest_document(args: argparse.Namespace) -> None:
    session = get_session()
    company = _resolve_company(session, args.sc_id)
    if not company:
        print("Company not found - run `ingest` (or `discover`) for it first.")
        return
    version, created = ingest_document(session, company.company_id, args.path, args.doc_type, args.fy)
    print(f"{'stored' if created else 'already stored (same file hash)'}: document_version {version.id}, "
          f"{version.page_count} pages, sha256 {version.file_sha256[:16]}")
    for name, span in sorted(version.sections.items()):
        print(f"  {name:36s} pages {span['first']}-{span['last']}")

    items = extract_statement_lines(session, version, company.company_id)
    print(f"read {len(items)} figures from the printed statements")
    for basis in BASES:
        ident = run_auditor_identity(session, company.company_id, version, basis)
        if ident:
            print(f"auditor ({basis}): {ident.payload['firm_name']}, firm registration no. "
                  f"{ident.payload['registration_no']} (page {ident.page_number}, {ident.validation_status})")
    session.flush()
    for basis in BASES:
        derive_cfo_indirect(session, company.company_id, basis)
    detect_source_conflicts(session, company.company_id)
    company.supported_status = compute_supported_status(session, company.company_id, company.sector)
    session.commit()
    print(f"supported_status={company.supported_status}")


def cmd_extract_text(args: argparse.Namespace) -> None:
    from sqlalchemy import select as _select

    session = get_session()
    company = _resolve_company(session, args.sc_id)
    if not company:
        print("Company not found.")
        return
    version = session.execute(
        _select(DocumentVersion).join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.company_id == company.company_id, Document.fiscal_year == args.fy)
        .order_by(DocumentVersion.id.desc())).scalars().first()
    if not version:
        print(f"No annual report ingested for {args.fy}. Run ingest-document first.")
        return
    try:
        if args.extractor == "recorded":
            extractor = RecordedExtractor(args.recorded)
        elif args.extractor == "gemini":
            extractor = GeminiExtractor()
        else:
            extractor = ClaudeExtractor()
    except RuntimeError as exc:
        print(f"Cannot start: {exc}")
        return
    bases = BASES if args.basis == "both" else [args.basis]
    checks = [c.strip() for c in args.checks.split(",") if c.strip()]
    print(f"extractor: {extractor.model_label}")
    for check_id in checks:
        for basis in bases:
            run = run_text_task(session, company.company_id, version, check_id, basis, extractor, force=args.force)
            session.commit()   # save each paid model call at once, so a later failure cannot lose it
            if run.status == "NO_PAGES":
                print(f"{check_id} {basis}: no relevant pages found in this report")
                continue
            passed = sum(1 for f in run.findings if f.validation_status == "PASSED")
            failed = len(run.findings) - passed
            reused = " [reused saved result]" if run.reused else ""
            print(f"{check_id} {basis}: pages {run.pages_sent[0]}-{run.pages_sent[-1]} ({len(run.pages_sent)} sent)"
                  f"{reused}: {passed} verified, {failed} rejected")
            for f in run.findings:
                if f.validation_status == "FAILED":
                    print(f"     REJECTED {f.finding_type} p{f.page_number}: {f.validation_detail}")
    session.commit()


def cmd_show_findings(args: argparse.Namespace) -> None:
    from sqlalchemy import select as _select

    session = get_session()
    company = _resolve_company(session, args.identifier)
    if not company:
        print("Company not found.")
        return
    stmt = _select(TextFinding).where(TextFinding.company_id == company.company_id)
    if args.fy:
        stmt = stmt.where(TextFinding.financial_year == args.fy)
    if not args.all:
        stmt = stmt.where(TextFinding.check_id.in_(["J1-10", "J1-11", "J1-14", "J1-15"]))
    order = (TextFinding.financial_year, TextFinding.check_id, TextFinding.basis, TextFinding.id)
    from crest_forensic.db.models import LlmCall as _LlmCall
    from crest_forensic.text.priority import primary_call

    primaries: dict = {}
    for f in session.execute(stmt.order_by(*order)).scalars():
        call = session.get(_LlmCall, f.llm_call_id)
        key = (f.document_version_id, call.task)
        if key not in primaries:
            primary = primary_call(session, f.document_version_id, call.task)
            primaries[key] = primary.id if primary else None
        tag = "main" if primaries[key] == call.id else "cross-check, not counted"
        q = " ".join(f.quote.split())
        more = "..." if len(q) > 230 else ""
        print(f"[{f.validation_status}] {f.check_id} {f.financial_year} {f.basis} p{f.page_number} {f.finding_type}"
              f"  <{call.model.split(' ')[0][:28]}: {tag}>")
        print(f'        "{q[:230]}{more}"')
        if f.validation_detail:
            print(f"        rejected: {f.validation_detail}")


def cmd_ingest_yahoo(args: argparse.Namespace) -> None:
    session = get_session()
    company = _resolve_company(session, args.sc_id)
    if not company:
        print("Company not found — run `ingest` (or `discover`) for it first.")
        return
    if not company.nse_symbol and args.ticker.upper().endswith(".NS"):
        company.nse_symbol = args.ticker.upper()[:-3]

    basis, created = ingest_yahoo(session, YFinanceConnector(), company, args.ticker)
    print(f"yfinance {args.ticker}: {len(created)} line items, inferred basis = {basis}")

    session.flush()
    conflicts = detect_source_conflicts(session, company.company_id)
    print(f"source conflicts found: {len(conflicts)}")
    for c in conflicts:
        vals = ", ".join(f"{p}={v / 1e7:,.0f}cr" for p, v in sorted(c["values"].items()))
        print(f"  {c['field']} {c['fy']} {c['basis']}: {vals}")

    company.supported_status = compute_supported_status(session, company.company_id, company.sector)
    session.commit()
    print(f"supported_status={company.supported_status}")


def cmd_ingest_prices(args: argparse.Namespace) -> None:
    from crest_forensic.connectors.yfinance_connector import fetch_prices
    from crest_forensic.ingestion.fetch_and_snapshot import save_snapshot

    session = get_session()
    company = _resolve_company(session, args.sc_id)
    if not company:
        print("Company not found.")
        return
    for ticker in (args.ticker, args.index):
        resp = fetch_prices(ticker, args.years)
        snap = save_snapshot(session, company.company_id, resp)
        if resp.parse_error:
            print(f"{ticker}: FAILED ({resp.parse_error})")
        else:
            d = resp.payload["data"]
            print(f"{ticker}: {len(d)} days {d[0]['date']} to {d[-1]['date']}, last close {d[-1]['close']:.2f} (snapshot {snap.snapshot_id})")
    session.commit()


def cmd_ingest_exchange_file(args: argparse.Namespace) -> None:
    from pathlib import Path
    from crest_forensic.ingestion.exchange_files import ingest_exchange_file

    session = get_session()
    company = _resolve_company(session, args.sc_id)
    if not company:
        print("Company not found.")
        return
    for f in args.files:
        try:
            print(ingest_exchange_file(session, company.company_id, Path(f)))
        except Exception as exc:
            print(f"{f}: FAILED ({type(exc).__name__}: {exc})")
    session.commit()


def cmd_auditor_fees(args: argparse.Namespace) -> None:
    from crest_forensic.documents.auditor_fees import fee_changes, ingest_auditor_fees, load_auditor_fees

    session = get_session()
    company = _resolve_company(session, args.sc_id)
    if not company:
        print("Company not found.")
        return
    for f in args.pdfs:
        try:
            print(ingest_auditor_fees(session, company.company_id, f))
        except Exception as exc:
            print(f"{f}: FAILED ({type(exc).__name__}: {exc})")
    session.commit()
    fees, notes = load_auditor_fees(session, company.company_id)
    changes = {c["fy"]: c for c in fee_changes(fees)}
    print("INR crore, standalone: FY | audit | tax | other | reimb | audit chg | total chg")
    for fy in sorted(fees):
        v, c = fees[fy], changes.get(fy)
        print(f"  {fy} | {v['audit_fee_cr']} | {v['tax_matters_cr']} | {v['other_services_cr']} | {v['reimbursement_cr']} | "
              + (f"{c['audit_fee_change_pct']:+.1f}% | {c['total_change_pct']:+.1f}%" if c else "- | -")
              + f"   (report {v['report_fy']}, page {v['page']})")
    for n in notes:
        print("NOTE:", n)


def cmd_related_party(args: argparse.Namespace) -> None:
    from crest_forensic.documents.related_party import ingest_related_party, load_related_party

    session = get_session()
    company = _resolve_company(session, args.sc_id)
    if not company:
        print("Company not found.")
        return
    for m in ingest_related_party(session, company.company_id):
        print(m)
    session.commit()
    for basis in ("standalone", "consolidated"):
        data, notes = load_related_party(session, company.company_id, basis)
        print(f"{basis} (INR crore): FY | revenue from related parties | purchases from related parties")
        for fy in sorted(data):
            print(f"  {fy} | {data[fy]['revenue_cr']:,} | {data[fy]['purchases_cr']:,}   (report {data[fy]['report_fy']}, page {data[fy]['page']})")
        for n in notes:
            print("NOTE:", n)


def cmd_ingest_peers(args: argparse.Namespace) -> None:
    from crest_forensic.ingestion.peers import ingest_peers

    session = get_session()
    company = _resolve_company(session, args.sc_id)
    if not company:
        print("Company not found.")
        return
    for m in ingest_peers(session, company.company_id, args.approved_by, args.note):
        print(m)
    session.commit()


def cmd_run_screen(args: argparse.Namespace) -> None:
    session = get_session()
    company = _resolve_company(session, args.identifier)
    if not company:
        print("Company not found.")
        return
    years = years_between(args.first, args.last)
    try:
        run = run_screen(session, company.company_id, args.basis, years,
                         allow_draft_config=args.allow_draft_config)
    except ConfigNotApproved as exc:
        print(f"REFUSED: {exc}")
        return
    session.commit()
    print(f"run {run.id} complete: {run.flags_created} flags, {run.flags_dropped} dropped by guardrails.")
    _print_run(session, run)


def _print_run(session, run: Run) -> None:
    company = session.get(Company, run.company_id)
    print("=" * 78)
    if not run.config_approved:
        print(f"DRAFT CONFIG - limits not approved by the forensic lead "
              f"({run.manifest['unapproved_limit_count']} limit values are proposals or still needed).")
    print(f"{company.name} | {run.basis} | {run.years[0]}..{run.years[-1]} | run {run.id} | "
          f"code {run.code_version} | config v{run.manifest['config_version_id']}")
    print("-" * 78)
    for row in session.execute(select(CheckResultRow).where(CheckResultRow.run_id == run.id)
                               .order_by(CheckResultRow.check_id)).scalars():
        d = row.detail
        flagged = sum(1 for m in d["metrics"] if m["severity"])
        print(f"{row.check_id}  {row.status:18s} {d['observations']} computed, {flagged} flagged, "
              f"{len(d['skipped'])} skipped")
        for note in d["notes"]:
            print(f"        note: {note}")
        for sk in d["skipped"][:6]:
            print(f"        skipped {sk['fy']}: {sk['reason']} - {sk['detail'][:110]}")
        if len(d["skipped"]) > 6:
            print(f"        ... and {len(d['skipped']) - 6} more skipped")
    print("-" * 78)
    flags = session.execute(select(Flag).where(Flag.run_id == run.id)
                            .order_by(Flag.check_id, Flag.financial_year)).scalars().all()
    order = {"high": 0, "medium": 1, "low": 2}
    for f in sorted(flags, key=lambda f: (order[f.severity], f.check_id, f.financial_year)):
        print(f"[{f.severity.upper():6s}] {f.check_id} {f.financial_year}  "
              f"materiality={f.materiality.get('label')}  evidence_confidence={f.evidence_confidence}")
        print(f"         {f.what_observed}")
        if "evidence" in f.citation:
            for e in f.citation["evidence"]:
                q = " ".join(e["quote"].split())
                more = "..." if len(q) > 200 else ""
                print(f'         {e["fy"]} {e["file_name"]} p{e["page"]} (printed p{e["printed_page"]}): "{q[:200]}{more}"')
            print(f"         rule {f.severity_rule_id}; document sha256 {f.citation['evidence'][0]['document_sha256'][:12]}; "
                  f"config: {f.citation['config_status']}")
        else:
            if "inputs" in f.citation:
                provs = sorted({i["provider"] + ("(derived)" if i["derived"] else "") for i in f.citation["inputs"]})
            else:   # filing, shareholding, price and auditor-fee flags cite saved snapshots, not statement line items
                kind = next((k for k in ("filings", "shareholding", "prices", "auditor_fees") if k in f.citation), "snapshots")
                provs = [f"saved {kind.replace('_', ' ')} (snapshots {', '.join(sorted({str(v) for c in f.citation.get(kind, []) for k2, v in c.items() if k2.endswith('snapshot_id') or k2 == 'snapshot_id'}))})"]
            print(f"         rule {f.severity_rule_id}; sources: {', '.join(provs)}; "
                  f"config: {f.citation['config_status']}")
    if not flags:
        print("No flags raised.")
    for g in session.execute(select(GuardrailEvent).where(GuardrailEvent.run_id == run.id)).scalars():
        print(f"DROPPED {g.check_id} {g.financial_year}: [{g.guardrail}] {g.detail}")
    print("-" * 78)
    print(LEADS_NOT_PROOF)
    print(PUBLIC_DATA_LIMIT)


def cmd_show_flags(args: argparse.Namespace) -> None:
    session = get_session()
    company = _resolve_company(session, args.identifier)
    if not company:
        print("Company not found.")
        return
    stmt = select(Run).where(Run.company_id == company.company_id)
    stmt = stmt.where(Run.id == args.run) if args.run else stmt.order_by(Run.id.desc())
    run = session.execute(stmt).scalars().first()
    if not run:
        print("No runs yet.")
        return
    _print_run(session, run)


def cmd_check_golden(args: argparse.Namespace) -> None:
    from pathlib import Path

    from crest_forensic.ingestion.golden import MATCH, MISMATCH, MISSING, evaluate_golden, golden_bases, load_golden

    session = get_session()
    company = _resolve_company(session, args.identifier)
    if not company:
        print("Company not found.")
        return
    path = Path(args.golden) if args.golden else (
        Path(__file__).resolve().parent / "tests" / "golden" / f"{company.sc_id.lower()}_golden.yaml")
    if not path.exists():
        print(f"No golden file at {path}")
        return
    golden = load_golden(path)
    print(f"Answer key: {golden.get('source_document', path.name)}  (tolerance 0.1%)")
    for provider in ("annual_report_pdf", "rapidapi_moneycontrol", "yfinance"):
        for basis in golden_bases(golden):
            rows = evaluate_golden(session, company.company_id, golden, basis, provider)
            n = {k: sum(1 for r in rows if r["status"] == k) for k in (MATCH, MISMATCH, MISSING)}
            if n[MATCH] == 0 and n[MISMATCH] == 0:
                print(f"\n{provider} / {basis}: no data from this source")
                continue
            print(f"\n{provider} / {basis}: {n[MATCH]} match, {n[MISMATCH]} mismatch, {n[MISSING]} not provided")
            for r in rows:
                if r["status"] == MISMATCH:
                    print(f"   MISMATCH {r['field']:26s} {r['year']}  printed {r['expected'] / 1e7:>10,.0f}  "
                          f"source {r['actual'] / 1e7:>10,.0f}  ({r['diff_pct']}% off)")
                elif r["status"] == MISSING:
                    print(f"   missing  {r['field']:26s} {r['year']}")


def cmd_show_resolved(args: argparse.Namespace) -> None:
    session = get_session()
    company = _resolve_company(session, args.identifier)
    if not company:
        print("Company not found.")
        return
    keys = session.execute(
        select(LineItem.financial_year, LineItem.basis)
        .where(LineItem.company_id == company.company_id)
        .where(LineItem.standard_field == args.field)
        .where(LineItem.period_type == "annual")
        .distinct()
    ).all()
    if args.basis:
        keys = [k for k in keys if k.basis == args.basis]
    print(f"{args.field} — what a check would use (Rs crore)")
    for fy, basis in sorted(keys, key=lambda k: (k.basis, k.financial_year)):
        r = resolve_value(session, company.company_id, args.field, fy, basis)
        shown = f"{r.value / 1e7:>12,.0f}" if r.value is not None else f"{'—':>12s}"
        who = r.provider or ""
        extra = ""
        if r.status in ("AGREE", "SOURCE_CONFLICT") and r.candidates:
            extra = "  [" + ", ".join(f"{p}={v / 1e7:,.0f}" for p, v in sorted(r.candidates.items())) + "]"
        print(f"{basis:13s}{fy:8s}{shown}  {r.status:17s}{who}{extra}")


def cmd_show_snapshots(args: argparse.Namespace) -> None:
    session = get_session()
    company = _resolve_company(session, args.identifier)
    if not company:
        print("Company not found.")
        return
    rows = session.execute(
        select(Snapshot).where(Snapshot.company_id == company.company_id).order_by(Snapshot.fetched_at)
    ).scalars().all()
    for s in rows:
        print(f"[{s.snapshot_id}] {s.fetched_at.isoformat()} {s.source_endpoint} "
              f"params={s.request_params} hash={s.payload_hash[:12]} provisional={s.provisional}")


def cmd_show_quality(args: argparse.Namespace) -> None:
    session = get_session()
    company = _resolve_company(session, args.identifier)
    if not company:
        print("Company not found.")
        return
    rows = session.execute(
        select(DataQualityEvent).where(DataQualityEvent.company_id == company.company_id)
        .order_by(DataQualityEvent.created_at)
    ).scalars().all()
    for e in rows:
        print(f"[{e.severity.upper()}] {e.issue_type} field={e.field_name} :: {e.note}")


def cmd_show_values(args: argparse.Namespace) -> None:
    session = get_session()
    company = _resolve_company(session, args.identifier)
    if not company:
        print("Company not found.")
        return
    stmt = select(LineItem).where(LineItem.company_id == company.company_id)
    if args.year:
        stmt = stmt.where(LineItem.financial_year == args.year)
    if args.basis:
        stmt = stmt.where(LineItem.basis == args.basis)
    rows = session.execute(stmt.order_by(LineItem.standard_field, LineItem.financial_year)).scalars().all()
    for li in rows:
        print(f"{li.standard_field:35s} {li.financial_year:10s} {li.basis:14s} "
              f"raw={li.raw_value!r:>15s} normalized={li.normalized_value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crest_forensic")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db").set_defaults(func=cmd_init_db)

    p = sub.add_parser("set-password", help="set or create a review-app user's password (hidden prompt)")
    p.add_argument("username")
    p.add_argument("--role", help="only when creating a new user")
    p.add_argument("--name", help="display name, only when creating a new user")
    p.set_defaults(func=cmd_set_password)

    p = sub.add_parser("search")
    p.add_argument("query")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("discover")
    p.add_argument("sc_id")
    p.add_argument("--name", default=None)
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("ingest")
    p.add_argument("sc_id")
    p.add_argument("--name", default=None)
    p.add_argument("--sector", default=None)
    p.add_argument("--isin", default=None)
    p.add_argument("--nse-symbol", dest="nse_symbol", default=None)
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("reprocess")
    p.add_argument("identifier")
    p.set_defaults(func=cmd_reprocess)

    p = sub.add_parser("ingest-document")
    p.add_argument("sc_id")
    p.add_argument("path", help="path to an annual report PDF")
    p.add_argument("--fy", required=True, help="the financial year the report covers, e.g. FY2026")
    p.add_argument("--doc-type", default="annual_report")
    p.set_defaults(func=cmd_ingest_document)

    p = sub.add_parser("extract-text")
    p.add_argument("sc_id")
    p.add_argument("--fy", required=True)
    p.add_argument("--basis", default="both", choices=["both", "standalone", "consolidated"])
    p.add_argument("--checks", default="J1-10,J1-11,J1-14,J1-15")
    p.add_argument("--extractor", default="claude", choices=["claude", "gemini", "recorded"])
    p.add_argument("--recorded", default=None, help="JSON file of recorded findings (with --extractor recorded)")
    p.add_argument("--force", action="store_true", help="call the model again even if a saved result exists")
    p.set_defaults(func=cmd_extract_text)

    p = sub.add_parser("show-findings")
    p.add_argument("identifier")
    p.add_argument("--fy", default=None)
    p.add_argument("--all", action="store_true", help="include J1-12 auditor-identity rows")
    p.set_defaults(func=cmd_show_findings)

    p = sub.add_parser("ingest-yahoo")
    p.add_argument("sc_id")
    p.add_argument("--ticker", required=True, help="Yahoo ticker, e.g. TCS.NS")
    p.set_defaults(func=cmd_ingest_yahoo)

    p = sub.add_parser("ingest-prices", help="save daily prices for a company and the index as snapshots")
    p.add_argument("sc_id")
    p.add_argument("--ticker", default="TCS.NS")
    p.add_argument("--index", default="^NSEI")
    p.add_argument("--years", type=int, default=5)
    p.set_defaults(func=cmd_ingest_prices)

    p = sub.add_parser("ingest-exchange-file", help="save hand-downloaded NSE results CSV / BSE SHP xml as snapshots")
    p.add_argument("sc_id")
    p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_ingest_exchange_file)

    p = sub.add_parser("auditor-fees", help="read the auditor remuneration note from ingested annual report PDFs and show the fees")
    p.add_argument("sc_id")
    p.add_argument("pdfs", nargs="*")
    p.set_defaults(func=cmd_auditor_fees)

    p = sub.add_parser("related-party", help="read the related-party totals from the ingested annual reports and show them")
    p.add_argument("sc_id")
    p.set_defaults(func=cmd_related_party)

    p = sub.add_parser("ingest-peers", help="fetch the peer set's financials (yfinance) and link the peers to a company")
    p.add_argument("sc_id")
    p.add_argument("--approved-by", required=True, help="who approved the peer set (the forensic lead)")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_ingest_peers)

    p = sub.add_parser("run-screen")
    p.add_argument("identifier")
    p.add_argument("--basis", required=True, choices=["standalone", "consolidated"])
    p.add_argument("--from", dest="first", required=True, help="first financial year, e.g. FY2023")
    p.add_argument("--to", dest="last", required=True, help="last financial year, e.g. FY2026")
    p.add_argument("--allow-draft-config", action="store_true",
                   help="DEVELOPMENT ONLY: run with unapproved limits; all output is stamped as a draft")
    p.set_defaults(func=cmd_run_screen)

    p = sub.add_parser("show-flags")
    p.add_argument("identifier")
    p.add_argument("--run", type=int, default=None)
    p.set_defaults(func=cmd_show_flags)

    p = sub.add_parser("check-golden")
    p.add_argument("identifier")
    p.add_argument("--golden", default=None)
    p.set_defaults(func=cmd_check_golden)

    p = sub.add_parser("show-resolved")
    p.add_argument("identifier")
    p.add_argument("--field", default="cash_flow_from_operations")
    p.add_argument("--basis", default=None)
    p.set_defaults(func=cmd_show_resolved)

    p = sub.add_parser("show-snapshots")
    p.add_argument("identifier")
    p.set_defaults(func=cmd_show_snapshots)

    p = sub.add_parser("show-quality")
    p.add_argument("identifier")
    p.set_defaults(func=cmd_show_quality)

    p = sub.add_parser("show-values")
    p.add_argument("identifier")
    p.add_argument("--year", default=None)
    p.add_argument("--basis", default=None)
    p.set_defaults(func=cmd_show_values)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
