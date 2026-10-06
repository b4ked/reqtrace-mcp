# Contributing

## Traceability convention

- Requirements live in `requirements/*.yaml`. Each has an id such as `ABC-001`.
- **Code:** put `# implements: ABC-001` (comma-separate several ids) on the line directly above
  each function or class that implements a requirement, above any decorators.
- Code that no requirement asks for should not be added. If a helper is genuinely needed, mark
  it `# derived: <reason>` so a reviewer can check it.
- **Tests:** mark every test with `@pytest.mark.verifies("ABC-001")` naming the requirements it
  checks. Cover each acceptance criterion, including both sides of every boundary.
- Keep the public names and signatures in `src/` unchanged; tests should exercise them.

## Running tests

    python3 -m pytest

## Reporting problems

Record problems with requirements (ambiguous, conflicting, untestable) and defects found in
review in `FINDINGS.json` at the repository root, as a JSON list of objects:

    {"req_id": "ABC-001", "kind": "defect", "file": "src/pkg/mod.py", "line": 12,
     "description": "..."}

`kind` is one of: `defect`, `missing_requirement`, `untested_behaviour`, `weak_test`,
`unrequired_code`, `requirement_issue`.
