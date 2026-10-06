"""Find trace annotations in source and tests (Python here; C and C++ in `cfamily`).

Code:  `# implements: REQ-001, REQ-002` or `# derived: <rationale>` on the line(s) directly
       above a def/class (above its decorators), or as a trailing comment on the def line.
Tests: `@pytest.mark.verifies("REQ-001", ...)` on a test function or test class.

Comments are not in Python's AST, so we combine `tokenize` (comments) with `ast` (structure).
"""

from __future__ import annotations

import ast
import fnmatch
import io
import re
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

from .cfamily import ALL_SUFFIXES, has_parse_errors, is_cfamily, scan_cfamily
from .config import Config, rel, safe_path
from .model import CodeItem

IMPLEMENTS_RE = re.compile(r"#\s*implements\s*:\s*(.+)$", re.I)
DERIVED_RE = re.compile(r"#\s*derived\s*:\s*(.*)$", re.I)
REQ_ID_RE = re.compile(r"[A-Z][A-Z0-9]*-\d+")


@dataclass
class ScanResult:
    source_items: list[CodeItem] = field(default_factory=list)
    test_items: list[CodeItem] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)

    def by_id(self) -> dict[str, CodeItem]:
        return {i.id: i for i in [*self.source_items, *self.test_items]}


def _comments(text: str) -> dict[int, str]:
    out: dict[int, str] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                out[tok.start[0]] = tok.string
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return out


def _leading_comments(
    def_start: int, def_line: int, comments: dict[int, str], lines: list[str]
) -> list[str]:
    """Contiguous comment lines directly above `def_start`, plus a trailing comment on the def."""
    found: list[str] = []
    ln = def_start - 1
    while ln >= 1 and lines[ln - 1].strip().startswith("#"):
        if ln in comments:
            found.append(comments[ln])
        ln -= 1
    if def_line in comments:
        found.append(comments[def_line])
    return found


def _parse_annotations(comments: list[str]) -> tuple[list[str], str | None]:
    ids: list[str] = []
    derived: str | None = None
    for c in comments:
        m = IMPLEMENTS_RE.search(c)
        if m:
            ids.extend(REQ_ID_RE.findall(m.group(1)))
        d = DERIVED_RE.search(c)
        if d:
            derived = d.group(1).strip() or "(no rationale given)"
    return list(dict.fromkeys(ids)), derived


def _verifies_marks(decorators: list[ast.expr]) -> list[str]:
    ids: list[str] = []
    for dec in decorators:
        call = dec if isinstance(dec, ast.Call) else None
        func = call.func if call else dec
        name = ast.unparse(func)
        if name.endswith("mark.verifies") and call is not None:
            for arg in call.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    ids.extend(REQ_ID_RE.findall(arg.value))
    return list(dict.fromkeys(ids))


def _body_start(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> int:
    first = node.body[0]
    # Skip a docstring so "executed the body" means real code ran.
    if (
        len(node.body) > 1
        and isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return node.body[1].lineno
    return first.lineno


def scan_file(path: Path, rel_path: str, is_test: bool) -> list[CodeItem]:
    return scan_text(path.read_text(encoding="utf-8"), rel_path, is_test)


def scan_text(text: str, rel_path: str, is_test: bool) -> list[CodeItem]:
    if is_cfamily(rel_path):
        return scan_cfamily(text, rel_path, is_test)
    tree = ast.parse(text, filename=rel_path)
    lines = text.splitlines()
    comments = _comments(text)
    items: list[CodeItem] = []

    def make(
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
        qual: str,
        kind: str,
        parent: CodeItem | None,
    ) -> CodeItem:
        start = min([node.lineno, *[d.lineno for d in node.decorator_list]])
        impl, derived = _parse_annotations(_leading_comments(start, node.lineno, comments, lines))
        verifies = _verifies_marks(node.decorator_list)
        if parent is not None and is_test:
            verifies = list(dict.fromkeys([*parent.verifies, *verifies]))
        item = CodeItem(
            id=f"{rel_path}::{qual}",
            path=rel_path,
            qualname=qual,
            kind=kind,  # type: ignore[arg-type]
            start_line=start,
            def_line=node.lineno,
            body_start=_body_start(node),
            end_line=node.end_lineno or node.lineno,
            implements=impl,
            verifies=verifies,
            derived=derived,
        )
        items.append(item)
        return item

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            make(node, node.name, "function", None)
        elif isinstance(node, ast.ClassDef):
            cls = make(node, node.name, "class", None)
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    make(sub, f"{node.name}.{sub.name}", "method", cls)
    return items


def suffixes(cfg: Config) -> tuple[str, ...]:
    return ALL_SUFFIXES if cfg.is_cpp else (".py",)


def _source_files(cfg: Config, dirs: list[str]) -> list[Path]:
    sfx = suffixes(cfg)
    files: list[Path] = []
    for d in dirs:
        base = safe_path(cfg.root, d)
        if base.is_file() and base.name.lower().endswith(sfx):
            files.append(base)
        elif base.is_dir():
            files.extend(
                p
                for p in base.rglob("*")
                if p.is_file() and p.name.lower().endswith(sfx) and ".reqtrace" not in p.parts
            )
    return sorted(set(files))


def is_test_path(cfg: Config, rel_path: str) -> bool:
    """A test file: under a test dir, or (C/C++) named like one, e.g. `*_unittest.cc`."""
    dirs = [d.strip("/").removeprefix("./") for d in cfg.test_dirs]
    in_dir = any(d in ("", ".") or rel_path == d or rel_path.startswith(d + "/") for d in dirs)
    name = rel_path.rsplit("/", 1)[-1]
    return in_dir or any(fnmatch.fnmatch(name, pat) for pat in cfg.test_file_patterns)


def is_ignored(cfg: Config, rel_path: str) -> bool:
    return any(fnmatch.fnmatch(rel_path, pat) for pat in cfg.ignore)


def scan(cfg: Config) -> ScanResult:
    result = ScanResult()
    all_files = set(_source_files(cfg, [*cfg.source_dirs, *cfg.test_dirs]))
    for f in sorted(all_files):
        rp = rel(cfg.root, f)
        is_test = is_test_path(cfg, rp)
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            items = scan_text(text, rp, is_test)
        except SyntaxError as exc:
            result.parse_errors.append(f"{rp}:{exc.lineno}: {exc.msg}")
            continue
        if is_cfamily(rp) and has_parse_errors(text, rp):
            result.parse_errors.append(
                f"{rp}: only partly parsed (macros or syntax tree-sitter cannot handle); "
                "functions in the unparsed part may be missing"
            )
        if not is_test:
            result.source_items.extend(items)
        elif is_cfamily(rp):
            result.test_items.extend(i for i in items if i.kind == "test")
        else:
            result.test_items.extend(
                i
                for i in items
                if i.qualname.split(".")[-1].startswith("test") or i.kind == "class"
            )
    return result


def test_nodeid(item: CodeItem) -> str:
    """Test id without parametrize/instance suffix: a pytest node id for Python
    (`tests/test_x.py::TestC::test_y`), `path::Suite.Name` for GoogleTest, `path::main` for a
    plain C/C++ test executable."""
    if is_cfamily(item.path):
        return f"{item.path}::{item.qualname}"
    return f"{item.path}::{item.qualname.replace('.', '::')}"


def item_source(cfg: Config, item: CodeItem) -> str:
    lines = (cfg.root / item.path).read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[item.start_line - 1 : item.end_line])
