from __future__ import annotations

from pathlib import Path

import pytest

from reqtrace_mcp.core import requirements as reqmod
from reqtrace_mcp.core.annotations import scan, scan_text
from reqtrace_mcp.core.config import Config, ReqtraceError, load_config, safe_path


@pytest.mark.verifies("RT-001")
def test_loads_example_requirements(cfg: Config) -> None:
    reqs = reqmod.load_requirements(cfg)
    assert [r.id for r in reqs] == ["ALT-001", "ALT-002", "ALT-003", "ALT-004"]
    assert reqs[0].acceptance[0].startswith("altitude 499")
    assert reqs[0].source.endswith("alerter.yaml:2")


@pytest.mark.verifies("RT-001")
@pytest.mark.parametrize(
    "yaml_text,message",
    [
        ("- id: bad\n  text: x\n", "must look like"),
        ("- id: R-1\n", "has no text"),
        ("- id: R-1\n  text: x\n  colour: red\n", "unknown fields"),
        ("- id: R-1\n  text: x\n- id: R-1\n  text: y\n", "Duplicate"),
        ("id: R-1\n", "expected a list"),
    ],
)
def test_rejects_malformed_requirements(tmp_path: Path, yaml_text: str, message: str) -> None:
    (tmp_path / "requirements").mkdir()
    (tmp_path / "requirements" / "r.yaml").write_text(yaml_text)
    with pytest.raises(ReqtraceError, match=message):
        reqmod.load_requirements(Config(root=tmp_path))


@pytest.mark.verifies("RT-002")
def test_lint_flags_vague_and_untestable() -> None:
    reqs = reqmod.parse_requirements_text(
        "- id: R-1\n  text: The system should respond fast.\n", "r.yaml"
    )
    msgs = " ".join(f.message for f in reqmod.lint(reqs))
    assert "acceptance" in msgs and "shall" in msgs and "fast" in msgs


@pytest.mark.verifies("RT-003")
def test_scans_comment_annotations_above_decorators_and_trailing() -> None:
    src = (
        "import functools\n"
        "# implements: R-1, R-2\n"
        "@functools.cache\n"
        "def f(): return 1\n"
        "\n"
        "def g():  # implements: R-3\n"
        "    return 2\n"
        "# derived: helper for clamping\n"
        "def h(): return 3\n"
        "# implements: R-4\n"
        "class C:\n"
        "    def m(self): return 4\n"
    )
    items = {i.qualname: i for i in scan_text(src, "m.py", is_test=False)}
    assert items["f"].implements == ["R-1", "R-2"]
    assert items["f"].start_line == 3 and items["f"].def_line == 4
    assert items["g"].implements == ["R-3"]
    assert items["h"].derived == "helper for clamping" and items["h"].implements == []
    assert items["C"].implements == ["R-4"] and items["C.m"].implements == []


@pytest.mark.verifies("RT-003")
def test_comment_not_directly_above_is_ignored() -> None:
    src = "# implements: R-1\n\nx = 1\n\ndef f(): return 1\n"
    assert scan_text(src, "m.py", is_test=False)[0].implements == []


@pytest.mark.verifies("RT-003")
def test_scans_verifies_marks_including_class_level() -> None:
    src = (
        "import pytest\n"
        "@pytest.mark.verifies('R-1')\n"
        "class TestX:\n"
        "    @pytest.mark.verifies('R-2')\n"
        "    def test_a(self): pass\n"
        "@pytest.mark.verifies('R-3', 'R-4')\n"
        "def test_b(): pass\n"
    )
    items = {i.qualname: i for i in scan_text(src, "t.py", is_test=True)}
    assert items["TestX.test_a"].verifies == ["R-1", "R-2"]
    assert items["test_b"].verifies == ["R-3", "R-4"]


@pytest.mark.verifies("RT-003")
def test_scan_example(cfg: Config) -> None:
    res = scan(cfg)
    ids = {i.id for i in res.source_items}
    assert "src/alerter/core.py::altitude_alert" in ids
    assert {i.qualname for i in res.test_items} == {
        "test_alert_at_floor_boundary",
        "test_floor_limits",
    }


@pytest.mark.verifies("RT-010")
def test_paths_cannot_escape_root(tmp_path: Path) -> None:
    with pytest.raises(ReqtraceError, match="outside"):
        safe_path(tmp_path, "../etc/passwd")
    (tmp_path / ".reqtrace.yaml").write_text("source_dirs: ['../../']\n")
    with pytest.raises(ReqtraceError, match="outside"):
        load_config(tmp_path)


@pytest.mark.verifies("RT-010")
def test_symlink_escape_rejected(tmp_path: Path) -> None:
    (tmp_path / "link").symlink_to("/etc")
    with pytest.raises(ReqtraceError, match="outside"):
        safe_path(tmp_path, "link/passwd")


def test_unknown_config_key_rejected(tmp_path: Path) -> None:
    (tmp_path / ".reqtrace.yaml").write_text("test_command: ['rm', '-rf', '/']\n")
    with pytest.raises(ReqtraceError, match="unknown keys"):
        load_config(tmp_path)
