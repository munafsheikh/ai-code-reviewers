import datetime as dt

from orchestrator.contracts import Finding, Location
from orchestrator.engine import gate
from orchestrator.recovery.audit import Audit

POLICY = {
    "gate": {
        "block_on": "major",
        "warn_on": "minor",
        "model_findings_can_block": True,
        "model_min_confidence_to_block": "medium",
        "fail_on_infrastructure_error": False,
    }
}


def f(sev="major", source="rule", conf="high"):
    return Finding(
        "R-001",
        "s",
        "t",
        sev,
        "security",
        Location("a", 1),
        "e",
        "ev",
        "fix",
        conf,
        "verified" if source == "rule" else "hypothesis",
        source,
    )


def test_pass_warn_block():
    assert gate.evaluate([], POLICY, [])["status"] == "pass"
    assert gate.evaluate([f("minor")], POLICY, [])["status"] == "warn"
    g = gate.evaluate([f("critical")], POLICY, [])
    assert (g["status"], g["exit_code"], g["legacy_severity"]) == ("block", 1, "BLOCK")


def test_low_confidence_model_finding_does_not_block():
    g = gate.evaluate([f("critical", "model", "low")], POLICY, [])
    assert g["status"] == "warn"
    assert gate.evaluate([f("critical", "model", "medium")], POLICY, [])["status"] == "block"


def test_infrastructure_error_policy():
    assert gate.evaluate([], POLICY, ["down"])["status"] == "pass"
    strict = {"gate": {**POLICY["gate"], "fail_on_infrastructure_error": True}}
    assert gate.evaluate([f("critical")], strict, ["down"])["exit_code"] == 2


def test_baseline_suppresses_until_expiry_and_stays_visible():
    finding = f("critical")
    exc = [{"fingerprint": finding.fingerprint, "reason": "accepted", "expires": "2099-01-01", "owner": "me"}]
    gate.apply_baseline([finding], exc, Audit(open("/dev/null", "w")))
    g = gate.evaluate([finding], POLICY, [])
    assert g["status"] == "pass" and g["suppressed_findings"] == 1 and finding.suppressed["reason"] == "accepted"

    expired = f("critical")
    audit = Audit(open("/dev/null", "w"))
    gate.apply_baseline([expired], [{**exc[0], "expires": "2000-01-01"}], audit, today=dt.date(2026, 1, 1))
    assert expired.suppressed is None and audit.events[0]["action"] == "baseline_exception_expired"
