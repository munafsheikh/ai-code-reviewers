"""Deterministic analyzers that confirm or reject a rule's regex candidate.

A rule names one with ``analyzer = "<id>"``. The regex stays the cheap, high-recall candidate
finder; the analyzer answers the rule's structural question from the code itself:

  True   confirmed: the finding is kept and reported as ``high`` confidence (verified)
  False  rejected: the candidate is dropped (audited by the caller)
  None   undecidable (e.g. the added lines do not parse on their own): the rule's
         ``analyzer_fallback`` decides, "keep" (default, at the rule's own confidence) or "drop"

Analyzers see only the added lines of the diff, grouped into consecutive blocks, never the
whole file. They are pure functions of (block lines, index of the candidate line), use the
standard library only and never execute the code under review.

Why this exists: benchmarks/experiments/tiny-verify measured candidate -> verify on 90
labelled cases. On structural questions the deterministic verifiers scored F1 1.0 while
models from 135M to 1.5B parameters scored 0.0-0.68, so structural questions are delegated
to tools rather than to small models.
"""

from __future__ import annotations

import ast
import shlex
import textwrap
from collections.abc import Callable

Block = list[str]
Analyzer = Callable[[Block, int], "bool | None"]

_MAX_STATEMENT_LINES = 40
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "request"}
_HTTP_MODULES = {"requests", "httpx"}
_SQL_METHODS = {"execute", "executemany"}


# --- Python ------------------------------------------------------------------------------
def _parse_from(block: Block, idx: int) -> tuple[ast.Module, int] | None:
    """Parse the shortest run of lines starting at ``idx`` that forms whole statements.

    Returns the module and the 1-based line of the candidate inside it. Lines are dedented
    together, so a statement taken from inside a function body still parses.
    """
    for end in range(idx + 1, min(len(block), idx + _MAX_STATEMENT_LINES) + 1):
        try:
            return ast.parse(textwrap.dedent("\n".join(block[idx:end]))), 1
        except SyntaxError:
            continue
    return None


def _parse_block(block: Block, idx: int) -> tuple[ast.Module, int] | None:
    """Prefer the whole block (gives local assignments); fall back to the statement alone."""
    try:
        return ast.parse(textwrap.dedent("\n".join(block))), idx + 1
    except SyntaxError:
        return _parse_from(block, idx)


def _call_on_line(tree: ast.AST, line: int, methods: set[str]) -> ast.Call | None:
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and n.lineno == line and isinstance(n.func, ast.Attribute) and n.func.attr in methods
    ]
    return min(calls, key=lambda n: n.col_offset) if calls else None


def python_http_without_timeout(block: Block, idx: int) -> bool | None:
    """requests/httpx call starting on the line has no ``timeout=`` (``**kwargs`` counts as maybe)."""
    parsed = _parse_block(block, idx)
    if not parsed:
        return None
    tree, line = parsed
    call = _call_on_line(tree, line, _HTTP_METHODS)
    if call is None:
        return None
    owner = call.func.value if isinstance(call.func, ast.Attribute) else None
    if not (isinstance(owner, ast.Name) and owner.id in _HTTP_MODULES):
        return False  # session.get(...) etc.: the session may carry a default timeout
    if any(k.arg is None for k in call.keywords):
        return False
    return not any(k.arg == "timeout" for k in call.keywords)


def _built_string(node: ast.AST, assigns: dict[str, ast.AST], depth: int = 0) -> bool:
    if isinstance(node, ast.Name) and node.id in assigns and depth < 3:
        return _built_string(assigns[node.id], assigns, depth + 1)
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(v, ast.FormattedValue) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        return _stringish(node.left) or _stringish(node.right)
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format"


def _stringish(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.BinOp):
        return _stringish(node.left) or _stringish(node.right)
    return isinstance(node, ast.JoinedStr)


def python_sql_built_string(block: Block, idx: int) -> bool | None:
    """``execute()``'s query is an f-string, %-format, concatenation or .format() result."""
    parsed = _parse_block(block, idx)
    if not parsed:
        return None
    tree, line = parsed
    call = _call_on_line(tree, line, _SQL_METHODS)
    if call is None or not call.args:
        return None
    assigns = {t.id: n.value for n in ast.walk(tree) if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    return _built_string(call.args[0], assigns)


# --- Shell -------------------------------------------------------------------------------
_SAFE_CONTEXT = ("[[", "((", "case ", "export ", "local ", "declare ", "readonly ")


def shell_unquoted_expansion(block: Block, idx: int) -> bool | None:
    """A ``$VAR`` / ``${VAR}`` word on the line is outside quotes in a command argument.

    Not flagged: assignments (``x=$y``), ``[[ ]]``, ``(( ))``, ``case`` words and ``$((...))``,
    where bash does not word-split.
    """
    line = block[idx].split(" #", 1)[0].strip()
    if not line or line.startswith("#") or line.startswith(_SAFE_CONTEXT):
        return False
    try:
        lex = shlex.shlex(line, posix=False, punctuation_chars=";&|")
        lex.whitespace_split = True
        words = list(lex)
    except ValueError:
        return None  # unbalanced quotes: undecidable on one line
    command_start = True
    in_test = False  # inside [[ ... ]] or (( ... )): no word splitting
    for w in words:
        if w in ("[[", "(("):
            in_test = True
            continue
        if w in ("]]", "))") or (in_test and w.endswith("))")):
            in_test = False
            continue
        if in_test:
            continue
        if "$((" in w and "))" not in w.split("$((", 1)[1]:
            in_test = True  # arithmetic expansion split across words: skip until "))"
            command_start = False
            continue
        if w in (";", "&&", "||", "|", "&"):
            command_start = True
            continue
        is_assignment = command_start and "=" in w and not w.startswith(("$", "=", "-"))
        if w.startswith(("'", '"')) or w.startswith("$((") or is_assignment:
            command_start = command_start and is_assignment
            continue
        command_start = False
        if "$" in w and _has_unquoted_var(w):
            return True
    return False


def _has_unquoted_var(word: str) -> bool:
    quote = ""
    i = 0
    while i < len(word):
        ch = word[i]
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == "$" and i + 1 < len(word) and (word[i + 1].isalpha() or word[i + 1] in "_{"):
            return True
        i += 1
    return False


REGISTRY: dict[str, Analyzer] = {
    "python.http-without-timeout": python_http_without_timeout,
    "python.sql-built-string": python_sql_built_string,
    "shell.unquoted-expansion": shell_unquoted_expansion,
}


def get(name: str) -> Analyzer:
    try:
        return REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown analyzer {name!r}; known: {', '.join(sorted(REGISTRY))}") from None
