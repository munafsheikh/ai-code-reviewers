"""Protected benchmark fixtures must keep meeting the offline quality gate."""

from orchestrator import config as cfg
from orchestrator.cli import validate
from orchestrator.evaluation import bench


def test_offline_benchmark_meets_quality_gate():
    res = bench.run("offline", repeat=2)
    thresholds = cfg.load_toml(cfg.home() / "policies/quality-gates/benchmarks.toml")["offline"]
    assert bench.check_thresholds(res, thresholds) == [], bench.to_markdown(res)


def test_fixture_manifest_is_current():
    r = validate.Report()
    validate.check_fixtures(cfg.home(), r)
    assert r.errors == []
