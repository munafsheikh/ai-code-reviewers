"""`acr` command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from orchestrator import __version__, schema
from orchestrator import config as cfg
from orchestrator.engine import report
from orchestrator.recovery.audit import Audit


def _read_diff(args) -> str:
    if args.git_range:
        repo = args.repo or "."
        # The repository is untrusted: disable every git feature that can execute repo-controlled commands.
        cmd = [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "diff.external=",
            "-C",
            repo,
            "diff",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            args.git_range,
        ]
        if args.paths:
            cmd += ["--", *args.paths]
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    if args.diff in (None, "-"):
        return sys.stdin.read()
    return Path(args.diff).read_text(encoding="utf-8", errors="replace")


def cmd_review(args) -> int:
    from orchestrator.engine.review import run_review

    if args.model_host:
        os.environ["ACR_MODEL_HOST"] = args.model_host
    if args.model:
        os.environ["ACR_SMALL_MODEL"] = args.model
    try:
        diff_text = _read_diff(args)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"[acr] cannot read diff: {e}", file=sys.stderr)
        return 2
    result = run_review(
        diff_text,
        args.profile,
        args.policy,
        revision=args.revision,
        repository=args.repository,
        audit=Audit(log_stream=sys.stderr if args.verbose else open(os.devnull, "w")),
    )
    errors = schema.validate(result, schema.load("review-result"))
    if errors:  # never emit an unvalidated document
        print("[acr] internal error: result failed schema validation:\n  " + "\n  ".join(errors[:10]), file=sys.stderr)
        return 2
    formats = [f.strip() for f in args.format.split(",") if f.strip()]
    legacy_error = result["run"].get("legacy_raw_output") is None and result["run"]["profile"] == "legacy"
    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        for f in formats:
            (out / report.EXTENSIONS[f]).write_text(report.RENDERERS[f](result), encoding="utf-8")
    stdout_fmt = args.stdout or (formats[0] if not args.out_dir else None)
    if stdout_fmt and not (stdout_fmt == "legacy" and legacy_error):
        sys.stdout.write(report.RENDERERS[stdout_fmt](result))
    g = result["gate"]
    for e in result["run"]["infrastructure_errors"]:
        print(f"[acr] {'ERROR' if g['status'] == 'error' else 'degraded'}: {e}", file=sys.stderr)
    msg = {
        "block": "BLOCKED — fix flagged issues or record a time-boxed baseline exception.",
        "warn": "MINOR issues noted — not blocking.",
        "error": "review could not run; see errors above.",
    }
    if g["status"] in msg:
        print(f"\n[acr] {msg[g['status']]}", file=sys.stderr)
    return g["exit_code"]


def cmd_validate(args) -> int:
    from orchestrator.cli import validate

    r = validate.run(skip=set(args.skip.split(",")) if args.skip else set())
    for w in r.warnings:
        print(f"warning: {w}")
    for e in r.errors:
        print(f"error: {e}")
    print(f"validate: {r.checked} checks, {len(r.errors)} errors, {len(r.warnings)} warnings")
    return 1 if r.errors or (args.strict and r.warnings) else 0


def cmd_bench(args) -> int:
    from orchestrator.cli.validate import fixture_manifest
    from orchestrator.evaluation import bench

    root = cfg.home()
    if args.update_manifest:
        (root / "benchmarks" / "fixtures" / "MANIFEST.sha256").write_text(fixture_manifest(root))
        print("updated benchmarks/fixtures/MANIFEST.sha256")
        return 0
    res = bench.run(args.profile, args.repeat, policy=args.policy)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(res, indent=2) + "\n")
        Path(args.out).with_suffix(".md").write_text(bench.to_markdown(res))
    print(bench.to_markdown(res))
    if args.gate:
        gates = cfg.load_toml(root / "policies" / "quality-gates" / "benchmarks.toml")
        thresholds = gates.get(args.profile, gates.get("default", {}))
        fails = bench.check_thresholds(res, thresholds)
        for f in fails:
            print(f"quality gate FAILED: {f}", file=sys.stderr)
        if fails:
            return 1
        print(f"quality gate passed ({args.profile}: {thresholds})")
    return 0


def cmd_models(args) -> int:
    models = cfg.load_models()
    if args.action == "list":
        for m in models.values():
            print(
                f"{m.id:<28} {m.tier:<6} {m.kind:<14} {m.params_b:>5}B {m.license_class:<22} {m.ref:<24} "
                f"ram>={m.min_ram_mb}MB digest={'pinned' if m.digest else 'UNPINNED'}"
            )
        return 0
    if args.action == "recommend":
        return _recommend(models, args)
    from orchestrator.engine.adapters import load_adapter

    profile = cfg.env_overrides(cfg.load_profile(args.profile))
    adapter = load_adapter(profile["runtime"]["wrapper"], profile["runtime"])
    h = adapter.health()
    if not h.ok:
        print(f"runtime unavailable: {h.detail}", file=sys.stderr)
        return 2
    have = {x.get("name"): x.get("digest") for x in h.models}
    rc = 0
    for m in models.values():
        actual = have.get(m.ref)
        if actual is None:
            state = "absent"
        elif not m.digest:
            state = f"unpinned (runtime digest {actual[:16]})"
            if args.pin:
                path = cfg.home() / "models" / "registry" / f"{m.id}.toml"
                path.write_text(path.read_text().replace('digest = ""', f'digest = "sha256:{actual}"', 1))
                state = "pinned now"
        elif actual.startswith(m.digest.removeprefix("sha256:")):
            state = "verified"
        else:
            state, rc = f"MISMATCH (runtime {actual[:16]})", 1
        print(f"{m.id:<22} {m.ref:<24} {state}")
    return rc


def _recommend(models: dict, args) -> int:
    """Pick small/large models that fit the machine and the policy's license classes."""
    policy = cfg.load_policy(args.policy)
    allowed = policy.get("models", {}).get("allowed_license_classes") or ["permissive", "open-weight-restricted", "non-production"]
    budget = args.ram_mb
    fits = [m for m in models.values() if m.min_ram_mb <= budget and m.license_class in allowed and m.status != "rejected"]
    if not fits:
        print(f"no registered model fits {budget} MB under policy '{args.policy}'", file=sys.stderr)
        return 1
    # Prefer code-specialised models, then the largest that fits (a proxy for quality), small tier first.
    rank = {"code-instruct": 0, "instruct": 1, "reasoning": 2}
    by_tier = {}
    for tier in ("small", "large"):
        cand = sorted((m for m in fits if m.tier == tier), key=lambda m: (rank.get(m.kind, 3), -m.params_b))
        by_tier[tier] = cand
    print(f"Machine: {budget} MB RAM/VRAM available to the model · policy {args.policy} allows {', '.join(allowed)}\n")
    for tier in ("small", "large"):
        print(f"{tier} tier:")
        for m in by_tier[tier][:4]:
            print(f"  {m.id:<28} {m.params_b:>5}B {m.kind:<14} {m.license:<34} needs {m.min_ram_mb} MB  ({m.ref})")
        if not by_tier[tier]:
            print("  (none fits)")
    small = by_tier["small"][0].id if by_tier["small"] else None
    large = by_tier["large"][0].id if by_tier["large"] else None
    print("\nSuggested environment:")
    if small:
        print(f"  ACR_SMALL_MODEL={small}")
    if large:
        print(f"  ACR_LARGE_MODEL={large}  ACR_PROFILE=deep  ACR_MEMORY_BUDGET_MB={budget}")
    print("Benchmark before adopting: acr bench --profile balanced (see the model-matrix workflow).")
    return 0


def cmd_skills(args) -> int:
    for s in cfg.load_skills().values():
        print(f"{s.id:<30} v{s.version:<7} {s.category:<16} tier={s.tier:<5} rules={len(s.rules):<2} prompt={'yes' if s.prompt else 'no'}")
    return 0


def cmd_health(args) -> int:
    from orchestrator.engine.adapters import load_adapter

    profile = cfg.env_overrides(cfg.load_profile(args.profile))
    if not profile.get("routing", {}).get("tiers") and profile.get("mode") != "legacy":
        print(json.dumps({"status": "ok", "runtime": "not required (rules-only profile)"}))
        return 0
    adapter = load_adapter(profile["runtime"]["wrapper"], profile["runtime"])
    h = adapter.health()
    print(
        json.dumps(
            {
                "status": "ok" if h.ok else "unavailable",
                "endpoint": adapter.endpoint,
                "detail": h.detail,
                "models": [m.get("name") for m in h.models],
            }
        )
    )
    return 0 if h.ok else 2


def cmd_serve(args) -> int:
    from orchestrator.cli import serve

    return serve.main(args.host, args.port, args.profile)


def cmd_docs(args) -> int:
    from orchestrator.cli import docsgen

    return docsgen.main(check=args.action == "check")


def cmd_evolve(args) -> int:
    from orchestrator.evaluation import evolve

    text = evolve.report()
    if args.out:
        Path(args.out).write_text(text)
    print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="acr", description="Offline, model-agnostic AI code review.")
    p.add_argument("--version", action="version", version=f"acr {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("review", help="review a unified diff")
    r.add_argument("--diff", help="diff file, or - for stdin (default)")
    r.add_argument("--git-range", help="review `git diff RANGE`, e.g. origin/main...HEAD")
    r.add_argument("--repo", help="repository for --git-range (default: cwd)")
    r.add_argument("--paths", nargs="*", help="limit --git-range to these pathspecs")
    r.add_argument(
        "--profile", default=os.environ.get("ACR_PROFILE", "balanced"), help="profile id or path (default: $ACR_PROFILE or balanced)"
    )
    r.add_argument("--policy", default=os.environ.get("ACR_POLICY"), help="policy id or path (default: from profile)")
    r.add_argument("--format", default="markdown", help="comma list of json,sarif,markdown,legacy")
    r.add_argument("--out-dir", help="write every format to this directory")
    r.add_argument("--stdout", choices=list(report.RENDERERS), help="format to print when --out-dir is used")
    r.add_argument("--model", help="override the small-tier model (registry id or runtime ref)")
    r.add_argument("--model-host", help="model runtime base URL (default from profile / $ACR_MODEL_HOST)")
    r.add_argument("--revision", default=os.environ.get("ACR_REVISION"), help="source revision for traceability")
    r.add_argument("--repository", default=os.environ.get("ACR_REPOSITORY"), help="repository URI for traceability")
    r.add_argument("-v", "--verbose", action="store_true", help="structured recovery logs on stderr")
    r.set_defaults(func=cmd_review)

    v = sub.add_parser("validate", help="validate manifests, schemas, rule examples, permissions, fixtures")
    v.add_argument("--strict", action="store_true", help="treat warnings as errors")
    v.add_argument("--skip", help="comma list of checks to skip: structure,skills,models,wrappers,profiles,policies,fixtures")
    v.set_defaults(func=cmd_validate)

    b = sub.add_parser("bench", help="run the benchmark suite")
    b.add_argument("--profile", default="offline")
    b.add_argument("--repeat", type=int, default=1, help="runs per case (measures stability)")
    b.add_argument("--policy", default=None, help="policy id (default: from profile); e.g. evaluation for benchmarking")
    b.add_argument("--out", help="write JSON (and .md) report here")
    b.add_argument("--gate", action="store_true", help="enforce policies/quality-gates/benchmarks.toml")
    b.add_argument("--update-manifest", action="store_true", help="re-record fixture checksums (protected)")
    b.set_defaults(func=cmd_bench)

    m = sub.add_parser("models", help="list registry models or verify runtime digests")
    m.add_argument("action", choices=["list", "verify", "recommend"])
    m.add_argument("--ram-mb", type=int, default=8192, help="recommend: memory available to the model")
    m.add_argument("--policy", default="default", help="recommend: policy whose license classes apply")
    m.add_argument("--profile", default="balanced")
    m.add_argument("--pin", action="store_true", help="record runtime digests for unpinned manifests")
    m.set_defaults(func=cmd_models)

    s = sub.add_parser("skills", help="list skills")
    s.set_defaults(func=cmd_skills)

    h = sub.add_parser("health", help="check the model runtime for a profile")
    h.add_argument("--profile", default=os.environ.get("ACR_PROFILE", "balanced"))
    h.set_defaults(func=cmd_health)

    sv = sub.add_parser("serve", help="run the HTTP review service")
    sv.add_argument("--host", default=os.environ.get("ACR_BIND", "127.0.0.1"))
    sv.add_argument("--port", type=int, default=int(os.environ.get("ACR_PORT", "8088")))
    sv.add_argument("--profile", default=os.environ.get("ACR_PROFILE", "balanced"))
    sv.set_defaults(func=cmd_serve)

    d = sub.add_parser("docs", help="generate or check reference docs in docs/generated")
    d.add_argument("action", choices=["generate", "check"])
    d.set_defaults(func=cmd_docs)

    e = sub.add_parser("evolve", help="produce an evidence-based improvement proposal")
    e.add_argument("--out", help="write the proposal markdown here")
    e.set_defaults(func=cmd_evolve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
