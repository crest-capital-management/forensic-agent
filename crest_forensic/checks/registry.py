"""Check registry: the fixed list of Job 1 number checks, in plan order."""
from __future__ import annotations

from crest_forensic.checks.altman import run_j1_16
from crest_forensic.checks.benford import run_j1_17
from crest_forensic.checks.beneish import run_j1_06
from crest_forensic.checks.growth import run_j1_03, run_j1_04, run_j1_05, run_j1_08
from crest_forensic.checks.other_income import run_j1_07
from crest_forensic.checks.profit_cash import run_j1_01, run_j1_02
from crest_forensic.checks.restatement import run_j1_09
from crest_forensic.checks.auditor_fees import run_j2_03
from crest_forensic.checks.price_volume import run_j2_02
from crest_forensic.checks.peer_tax import run_j2_07
from crest_forensic.checks.pledging import run_j2_04
from crest_forensic.checks.ratio_breaks import run_j2_05
from crest_forensic.checks.related_party import run_j2_06
from crest_forensic.checks.shareholding import run_j2_01

REGISTRY = [
    ("J1-01", run_j1_01),
    ("J1-02", run_j1_02),
    ("J1-03", run_j1_03),
    ("J1-04", run_j1_04),
    ("J1-05", run_j1_05),
    ("J1-06", run_j1_06),
    ("J1-07", run_j1_07),
    ("J1-08", run_j1_08),
    ("J1-09", run_j1_09),
    # Added from the PRD (not in the original job specs): need the forensic lead's approval of their limits.
    ("J1-16", run_j1_16),
    ("J1-17", run_j1_17),
    # Job 2 (anomaly tests), from the Job 2 spec.
    ("J2-01", run_j2_01),
    ("J2-02", run_j2_02),
    ("J2-03", run_j2_03),
    ("J2-04", run_j2_04),
    ("J2-05", run_j2_05),
    ("J2-06", run_j2_06),
    ("J2-07", run_j2_07),
]
