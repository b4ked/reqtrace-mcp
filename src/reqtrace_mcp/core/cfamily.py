"""C and C++ support: find functions, classes and GoogleTest tests with tree-sitter.

Conventions (comments, so no build-system or header changes are needed in the product):

    // implements: REQ-001, REQ-002        (or /* implements: REQ-001 */)
    uint32_t Extend(uint32_t crc, const uint8_t* data, size_t count) { ... }

    // derived: table-driven speed-up, no parent requirement
    static void BuildTable() { ... }

    // verifies: REQ-001
    TEST(Crc32CTest, StandardVectors) { ... }

The comment applies to the next definition (above any `template<...>` line), or sits at the
end of the definition's first line. GoogleTest `TEST`, `TEST_F`, `TEST_P`, `TYPED_TEST` and
`TYPED_TEST_P` become test items named `Suite.Name`. In test files, functions named `test*`
(Unity/CMocka style) and any function carrying `// verifies:` (typically the `main` of a plain
test executable) are tests too.

tree-sitter parses without compiling, so it copes with code for other platforms and with
macros it can't expand. It is a parser, not a compiler: heavily macro-generated functions
may be missed, and the scanner reports files it could only partly parse.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from .model import CodeItem

C_SUFFIXES = (".c", ".h")
CPP_SUFFIXES = (".cc", ".cpp", ".cxx", ".c++", ".hh", ".hpp", ".hxx", ".h++", ".ipp")
ALL_SUFFIXES = C_SUFFIXES + CPP_SUFFIXES
GTEST_MACROS = {"TEST", "TEST_F", "TEST_P", "TYPED_TEST", "TYPED_TEST_P", "FRIEND_TEST"}

_COMMENT_START = re.compile(r"^\s*(//|/\*|\*)")
IMPLEMENTS_RE = re.compile(r"(?://+|/\*+|\*)\s*implements\s*:\s*(.+?)\s*(?:\*/)?\s*$", re.I)
VERIFIES_RE = re.compile(r"(?://+|/\*+|\*)\s*verifies\s*:\s*(.+?)\s*(?:\*/)?\s*$", re.I)
DERIVED_RE = re.compile(r"(?://+|/\*+|\*)\s*derived\s*:\s*(.*?)\s*(?:\*/)?\s*$", re.I)
REQ_ID_RE = re.compile(r"[A-Z][A-Z0-9]*-\d+")


def is_cfamily(path: str) -> bool:
    return path.lower().endswith(ALL_SUFFIXES)


@lru_cache(maxsize=2)
def _parser(cpp: bool) -> Any:
    try:
        from tree_sitter import Language, Parser
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise RuntimeError(
            "C/C++ support needs tree-sitter (pip install tree-sitter "
            "tree-sitter-c tree-sitter-cpp)"
        ) from exc
    import tree_sitter_c
    import tree_sitter_cpp

    grammar = tree_sitter_cpp if cpp else tree_sitter_c
    return Parser(Language(grammar.language()))


def _uses_cpp(path: str, text: str) -> bool:
    if path.lower().endswith(CPP_SUFFIXES):
        return True
    if path.lower().endswith(".h"):  # headers are ambiguous; C++ grammar is a superset
        return bool(re.search(r"\b(namespace|class|template|::)\b|::", text))
    return False


def _leading(lines: list[str], start: int, def_line: int) -> list[str]:
    """Contiguous comment lines directly above `start` (1-based), plus a trailing comment
    on the definition line."""
    out: list[str] = []
    ln = start - 1
    while ln >= 1 and (_COMMENT_START.match(lines[ln - 1]) or lines[ln - 1].strip().endswith("*/")):
        out.append(lines[ln - 1].strip())
        ln -= 1
    first = lines[def_line - 1] if def_line - 1 < len(lines) else ""
    for marker in ("//", "/*"):
        idx = first.find(marker)
        if idx >= 0:
            out.append(first[idx:].strip())
            break
    return out


def _parse(comments: list[str]) -> tuple[list[str], list[str], str | None]:
    impl: list[str] = []
    ver: list[str] = []
    derived: str | None = None
    for c in comments:
        if m := IMPLEMENTS_RE.search(c):
            impl += REQ_ID_RE.findall(m.group(1))
        if m := VERIFIES_RE.search(c):
            ver += REQ_ID_RE.findall(m.group(1))
        if m := DERIVED_RE.search(c):
            derived = m.group(1) or "(no rationale given)"
    return list(dict.fromkeys(impl)), list(dict.fromkeys(ver)), derived


def _function_name(declarator: Any) -> tuple[str, Any] | None:
    """Walk pointer/reference declarators down to the function_declarator; return its name."""
    node = declarator
    while node is not None and node.type != "function_declarator":
        node = node.child_by_field_name("declarator")
    if node is None:
        return None
    name = node.child_by_field_name("declarator")
    return (name.text.decode(), node) if name is not None else None


def _gtest_name(fn_decl: Any) -> str | None:
    params = fn_decl.child_by_field_name("parameters")
    if params is None:
        return None
    parts = [c.text.decode().strip() for c in params.named_children]
    return f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else None


CONTAINERS = {
    "translation_unit",
    "declaration_list",
    "preproc_if",
    "preproc_ifdef",
    "preproc_else",
    "preproc_elif",
    "preproc_elifdef",
    "linkage_specification",
    "declaration",
    "type_definition",
}


_PREPROC_COND = re.compile(r"^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b")


def _without_conditionals(text: str) -> str:
    """Blank conditional-compilation lines (keeping line numbers). Fixes the classic
    `#ifdef __cplusplus / extern "C" {` pattern, which an un-preprocessed parse can't balance.
    Both branches of an #if are then seen, which is what a traceability scan wants."""
    return "\n".join("" if _PREPROC_COND.match(ln) else ln for ln in text.split("\n"))


def _tree(text: str, rel_path: str) -> Any:
    """Parse, retrying on errors: without #if lines, and (for C) with the C++ grammar, which
    accepts declarations without a return type such as `TEST(Suite, Name) { ... }` (GoogleTest,
    Unity Fixture). The attempt with the fewest errors wins."""
    cpp = _uses_cpp(rel_path, text)
    tree = _parser(cpp).parse(text.encode())
    if not tree.root_node.has_error:
        return tree
    best, best_err = tree, _count_errors(tree)
    for use_cpp in [cpp] if cpp else [cpp, True]:
        for src in (text, _without_conditionals(text)):
            if use_cpp == cpp and src is text:
                continue
            cand = _parser(use_cpp).parse(src.encode())
            err = _count_errors(cand)
            if err < best_err:
                best, best_err = cand, err
            if not err:
                return best
    return best


def _count_errors(tree: Any) -> int:
    n, stack = 0, [tree.root_node]
    while stack:
        node = stack.pop()
        n += node.type == "ERROR" or node.is_missing
        stack.extend(node.children)
    return n


def scan_cfamily(text: str, rel_path: str, is_test: bool) -> list[CodeItem]:
    tree = _tree(text, rel_path)
    lines = text.splitlines()
    items: list[CodeItem] = []

    sigs: dict[int, str] = {}

    def add(
        node: Any,
        outer_start: int,
        qual: str,
        kind: str,
        parent: CodeItem | None,
        fdecl: Any = None,
    ) -> CodeItem:
        start = outer_start
        def_line = node.start_point[0] + 1
        impl, ver, derived = _parse(_leading(lines, start, def_line))
        if parent is not None and is_test:
            ver = list(dict.fromkeys([*parent.verifies, *ver]))
        body = node.child_by_field_name("body")
        body_start = body.start_point[0] + 1 if body is not None else def_line
        item = CodeItem(
            id=f"{rel_path}::{qual}",
            path=rel_path,
            qualname=qual,
            kind=kind,  # type: ignore[arg-type]
            start_line=start,
            def_line=def_line,
            body_start=body_start,
            end_line=node.end_point[0] + 1,
            implements=impl,
            verifies=ver,
            derived=derived,
        )
        if fdecl is not None:
            sigs[len(items)] = _signature(fdecl)
        items.append(item)
        return item

    def walk(
        node: Any, prefix: str, outer_start: int | None = None, cls: CodeItem | None = None
    ) -> None:
        for ch in node.children:
            start = outer_start or ch.start_point[0] + 1
            t = ch.type
            if t == "namespace_definition":
                name = ch.child_by_field_name("name")
                body = ch.child_by_field_name("body")
                ns = f"{prefix}{name.text.decode()}::" if name is not None else prefix
                if body is not None:
                    walk(body, ns)
            elif t == "template_declaration":
                walk(ch, prefix, start, cls)
            elif t in ("class_specifier", "struct_specifier", "union_specifier"):
                name = ch.child_by_field_name("name")
                body = ch.child_by_field_name("body")
                if name is None or body is None:
                    continue
                c = add(ch, start, f"{prefix}{name.text.decode()}", "class", None)
                for member in body.children:
                    mstart = member.start_point[0] + 1
                    target = member
                    if member.type == "template_declaration":
                        target = next(
                            (m for m in member.children if m.type == "function_definition"), member
                        )
                    if target.type == "function_definition":
                        fn = _function_name(target.child_by_field_name("declarator"))
                        if fn:
                            add(target, mstart, f"{c.qualname}.{fn[0]}", "method", c, fn[1])
            elif t == "function_definition":
                fn = _function_name(ch.child_by_field_name("declarator"))
                if fn is None:
                    continue
                name, fdecl = fn
                if name in GTEST_MACROS:
                    tname = _gtest_name(fdecl)
                    if tname:
                        add(ch, start, tname, "test", None)
                    continue
                if "::" in name:  # out-of-line member: Class::method
                    owner, _, meth = name.rpartition("::")
                    qual = f"{prefix}{owner}.{meth}"
                    kind = "method"
                else:
                    qual, kind = f"{prefix}{name}", "function"
                item = add(ch, start, qual, kind, cls, fdecl)
                # In test files: Unity/CMocka-style test_* functions, and any function that
                # says what it verifies (typically `main` of a plain test executable).
                if is_test and (name.startswith("test") or item.verifies):
                    item.kind = "test"
            elif t in CONTAINERS:
                walk(ch, prefix, None, cls)

    walk(tree.root_node, "")
    # C++ overloads share a name: give each a readable, stable id from its parameter types.
    counts: dict[str, int] = {}
    for it in items:
        counts[it.qualname] = counts.get(it.qualname, 0) + 1
    for idx, it in enumerate(items):
        if counts[it.qualname] > 1 and idx in sigs:
            it.qualname = f"{it.qualname}({sigs[idx]})"
    # Same signature twice means alternative #if branches: add the line to keep ids unique.
    counts = {}
    for it in items:
        counts[it.qualname] = counts.get(it.qualname, 0) + 1
    for it in items:
        if counts[it.qualname] > 1:
            it.qualname = f"{it.qualname}@L{it.def_line}"
        it.id = f"{rel_path}::{it.qualname}"
    return items


def _signature(fdecl: Any) -> str:
    """Parameter types without names.

    `const uint8_t* data, size_t count` -> `const uint8_t*, size_t`.
    """
    params = fdecl.child_by_field_name("parameters")
    if params is None:
        return ""
    out = []
    for p in params.named_children:
        text = " ".join(p.text.decode().split())
        name = p.child_by_field_name("declarator")
        while name is not None and name.type != "identifier":
            inner = name.child_by_field_name("declarator")
            if inner is None:  # reference_declarator keeps its target as a plain child
                kids = [k for k in name.named_children]
                inner = kids[-1] if kids else None
            name = inner
        if name is not None and text.endswith(name.text.decode()):
            text = text[: -len(name.text.decode())].rstrip()
        out.append(text.replace(" *", "*").replace(" &", "&"))
    return ", ".join(out)


def has_parse_errors(text: str, rel_path: str) -> bool:
    return bool(_tree(text, rel_path).root_node.has_error)


def gtest_base(full_name: str) -> tuple[str, str]:
    """Map a runtime GoogleTest name to (static `Suite.Name`, instance label).

    Plain:         Crc32CTest.Crc32c                 -> Crc32CTest.Crc32c, ""
    Typed (P):     Portable/ExtendTest/0.HelloWorld  -> ExtendTest.HelloWorld, "Portable/0"
    Value-param:   Inst/Suite.Name/3                 -> Suite.Name, "Inst/3"
    """
    suite, _, name = full_name.partition(".")
    sparts = suite.split("/")
    nparts = name.split("/")
    base_suite = (
        next((p for p in sparts if not p.isdigit() and p != sparts[0]), sparts[0])
        if len(sparts) > 1
        else sparts[0]
    )
    inst = [p for p in sparts if p != base_suite] + nparts[1:]
    return f"{base_suite}.{nparts[0]}", "/".join(inst)
