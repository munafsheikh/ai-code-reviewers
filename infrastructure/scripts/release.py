"""Release automation: decide, apply and verify version bumps. Stdlib only, no git needed.

    release.py plan  [--root R] [--label L]...   -> JSON {current, next, bump, reason}
    release.py apply VERSION [--root R] [--date YYYY-MM-DD]
    release.py check VERSION [--root R]
    release.py notes VERSION [--root R]
    release.py image-tags --version V|'' --revision SHA --namespace NS  -> KEY=VALUE lines

The bump comes from the CHANGELOG `[Unreleased]` section (Keep a Changelog headings):
  `### Removed` or a line containing "BREAKING"     -> major (minor while 0.x)
  `### Added`, `### Changed` or `### Deprecated`     -> minor
  `### Fixed` or `### Security`                       -> patch
  nothing under [Unreleased]                          -> none (no release)
A merged PR's label overrides it: release:major | release:minor | release:patch | release:skip.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
LEVELS = ("none", "patch", "minor", "major")
LABELS = {f"release:{lvl}": lvl for lvl in ("major", "minor", "patch")} | {"release:skip": "none"}
# Files that carry the released version, and how to find it in each.
PINNED = {
    "pyproject.toml": [r'(?m)^(version = ")(?P<v>\d+\.\d+\.\d+)(")'],
    "orchestrator/__init__.py": [r'(__version__ = ")(?P<v>\d+\.\d+\.\d+)(")'],
}
# Consumer templates reference the published tag and image.
TEMPLATE_GLOBS = [
    "integrations/**/*.yml",
    "integrations/**/*.yaml",
    "integrations/**/*.sh",
    "integrations/**/*.md",
    "README.md",
    "docs/*.md",
    "docs/usage/**/*.md",
    "examples/**/*.md",
    "examples/**/Dockerfile",
    "examples/**/*.yaml",
    ".env.example",
]
TEMPLATE_PATTERNS = [
    r"(ai-code-reviewers/integrations/github@v)(?P<v>\d+\.\d+\.\d+)()",
    r"(ref: refs/tags/v)(?P<v>\d+\.\d+\.\d+)()",
    r"(raw\.githubusercontent\.com/munafsheikh/ai-code-reviewers/v)(?P<v>\d+\.\d+\.\d+)()",
    r"(ghcr\.io/munafsheikh/ai-code-reviewers:)(?P<v>\d+\.\d+\.\d+)()",
    r"((?<![\w./-])munafsheikh/ai-code-reviewers(?:-[a-z-]+)?:)(?P<v>\d+\.\d+\.\d+)()",
    r"(`@v)(?P<v>\d+\.\d+\.\d+)(`)",
]


def current_version(root: Path) -> str:
    m = re.search(PINNED["pyproject.toml"][0], (root / "pyproject.toml").read_text())
    if not m:
        raise SystemExit("pyproject.toml has no version")
    return m.group("v")


def unreleased(changelog: str) -> str:
    m = re.search(r"(?ms)^## \[Unreleased\]\s*\n(.*?)(?=^## \[|\Z)", changelog)
    return m.group(1).strip() if m else ""


def bump_level(section: str) -> tuple[str, str]:
    if not section:
        return "none", "nothing under [Unreleased]"
    heads = set(re.findall(r"(?m)^### (\w+)", section))
    if "BREAKING" in section or "Removed" in heads:
        return "major", "breaking change or removal under [Unreleased]"
    if heads & {"Added", "Changed", "Deprecated"}:
        return "minor", f"{', '.join(sorted(heads & {'Added', 'Changed', 'Deprecated'}))} under [Unreleased]"
    if heads & {"Fixed", "Security"}:
        return "patch", f"{', '.join(sorted(heads & {'Fixed', 'Security'}))} under [Unreleased]"
    return "patch", "unclassified entries under [Unreleased]"


def next_version(current: str, level: str) -> str | None:
    m = SEMVER.match(current)
    if not m:
        raise SystemExit(f"not a version: {current}")
    major, minor, patch = map(int, m.groups())
    if level == "none":
        return None
    if level == "major" and major == 0:
        level = "minor"  # 0.x: breaking changes bump the minor version (SemVer item 4)
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def plan(root: Path, labels: list[str]) -> dict:
    current = current_version(root)
    level, reason = bump_level(unreleased((root / "CHANGELOG.md").read_text()))
    chosen = [LABELS[x] for x in labels if x in LABELS]
    if chosen:
        level, reason = max(chosen, key=LEVELS.index), f"label {', '.join(x for x in labels if x in LABELS)}"
        if "release:skip" in labels:
            level, reason = "none", "label release:skip"
    return {"current": current, "next": next_version(current, level), "bump": level, "reason": reason}


def _template_files(root: Path) -> list[Path]:
    return sorted({p for g in TEMPLATE_GLOBS for p in root.glob(g) if p.is_file()})


def apply(root: Path, version: str, date: str) -> list[str]:
    if not SEMVER.match(version):
        raise SystemExit(f"not a version: {version}")
    changed = []
    for rel, pats in PINNED.items():
        p = root / rel
        text = p.read_text()
        for pat in pats:
            text = re.sub(pat, lambda m: m.group(1) + version + m.group(3), text)
        p.write_text(text)
        changed.append(rel)
    cl = root / "CHANGELOG.md"
    text = cl.read_text()
    if re.search(rf"(?m)^## \[{re.escape(version)}\]", text):
        raise SystemExit(f"CHANGELOG.md already has [{version}]")
    text, n = re.subn(r"(?m)^## \[Unreleased\][ \t]*\n", f"## [Unreleased]\n\n## [{version}] - {date}\n", text, count=1)
    if not n:
        raise SystemExit("CHANGELOG.md has no [Unreleased] section")
    cl.write_text(re.sub(r"\n{3,}", "\n\n", text))
    changed.append("CHANGELOG.md")
    for p in _template_files(root):
        text = p.read_text()
        new = text
        for pat in TEMPLATE_PATTERNS:
            new = re.sub(pat, lambda m: m.group(1) + version + m.group(3), new)
        if new != text:
            p.write_text(new)
            changed.append(str(p.relative_to(root)))
    return changed


def check(root: Path, version: str) -> list[str]:
    errors = []
    for rel, pats in PINNED.items():
        text = (root / rel).read_text()
        for pat in pats:
            found = {m.group("v") for m in re.finditer(pat, text)}
            if found != {version}:
                errors.append(f"{rel}: {sorted(found) or 'no version'} != {version}")
    if not re.search(rf"(?m)^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", (root / "CHANGELOG.md").read_text()):
        errors.append(f"CHANGELOG.md: no dated [{version}] section")
    for p in _template_files(root):
        text = p.read_text()
        for pat in TEMPLATE_PATTERNS:
            for m in re.finditer(pat, text):
                if m.group("v") != version:
                    errors.append(f"{p.relative_to(root)}: references {m.group('v')} != {version}")
    return errors


def notes(root: Path, version: str) -> str:
    m = re.search(rf"(?ms)^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", (root / "CHANGELOG.md").read_text())
    if not m:
        raise SystemExit(f"CHANGELOG.md has no [{version}] section")
    return m.group(1).strip() + "\n"


def image_tags(version: str, revision: str, namespace: str) -> dict[str, str]:
    """Registry tags: a release gets X.Y.Z, X.Y and latest; anything else is edge + sha-<12>."""
    v = version.removeprefix("v")
    if v:
        if not SEMVER.match(v):
            raise SystemExit(f"not a version: {version}")
        tags = [v, v.rsplit(".", 1)[0], "latest"]
    else:
        if not re.fullmatch(r"[0-9a-f]{12,40}", revision):
            raise SystemExit(f"not a commit sha: {revision!r}")
        v, tags = "0.0.0-edge", ["edge", f"sha-{revision[:12]}"]
    if not re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", namespace.lower()):
        raise SystemExit(f"not a registry namespace: {namespace!r}")
    return {"namespace": namespace.lower(), "revision": revision, "version": v, "tags": " ".join(tags)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "apply", "check", "notes"):
        sp = sub.add_parser(name)
        sp.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
        if name == "plan":
            sp.add_argument("--label", action="append", default=[], help="label of the merged PR (repeatable)")
        else:
            sp.add_argument("version")
        if name == "apply":
            sp.add_argument("--date", default=dt.date.today().isoformat())
    it = sub.add_parser("image-tags")
    it.add_argument("--version", default="")
    it.add_argument("--revision", required=True)
    it.add_argument("--namespace", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "image-tags":
        print("\n".join(f"{k}={v}" for k, v in image_tags(a.version, a.revision, a.namespace).items()))
    elif a.cmd == "plan":
        print(json.dumps(plan(a.root, a.label)))
    elif a.cmd == "apply":
        print("\n".join(apply(a.root, a.version, a.date)))
        errs = check(a.root, a.version)
        for e in errs:
            print(e, file=sys.stderr)
        return 1 if errs else 0
    elif a.cmd == "check":
        errs = check(a.root, a.version)
        for e in errs:
            print(e, file=sys.stderr)
        print(f"release check {a.version}: {len(errs)} problem(s)")
        return 1 if errs else 0
    else:
        sys.stdout.write(notes(a.root, a.version))
    return 0


if __name__ == "__main__":
    sys.exit(main())
