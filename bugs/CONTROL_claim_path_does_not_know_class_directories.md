# CONTROL: `norm_claim` does not normalise a `bugs/<class>/` path, so two spellings of one document do not conflict

Found 2026-11-13 while fixing `FORMAL_doc_index_queue_misses_docs_in_bugs_mid`
(the formal queue scanned one directory). `tools/control.py::norm_claim` accepts
a bare name, a name with `.md`, and a `bugs/` path — but only `bugs/` and
`bugs/hard/`:

    m = re.fullmatch(r"(?:bugs/(?:hard/)?)?([A-Za-z0-9_]+?)(?:\.md)?", c)

The swarm's class-directory reorg moved documents into `bugs/mid/` (35e261a02
and its siblings) and `norm_claim` was not updated.

## Measured

    $ python3 - <<'PY'
    import sys; sys.path.insert(0, 'tools')
    import control
    stem = 'FORMAL_arm64_instruction_coverage'
    mid, top = f'bugs/mid/{stem}.md', f'bugs/{stem}.md'
    print(repr(control.norm_claim(mid)))
    print(repr(control.norm_claim(top)))
    print(control.conflicts(control.norm_claim(mid), control.norm_claim(top)))
    PY
    'bugs/mid/FORMAL_arm64_instruction_coverage.md'
    'bug:FORMAL_arm64_instruction_coverage'
    False

(Both spellings are built from one stem so this document does not itself cite a
path that is not in the tree; the top-level one is where the same document sat
before the reorg.)

`control.py claim bugs/mid/<name>.md` therefore registers the literal path as
its claim, with two consequences:

- it does not conflict with a worker holding `bug:<name>`, so `spawn`/`claim`
  admit two workers on one document — the one thing the conflict rule exists to
  stop;
- `tools/formal_doc_index.py::live_claims()` keys a claim by splitting on `:`
  and stripping `.md`, so this claim's key is `bugs/mid/FORMAL_arm64_
  instruction_coverage`, which no row looks up: the document's queue row says
  **unclaimed** while it is held.

## Expected

A bare document name, a name with `.md`, `bugs/<name>.md` and
`bugs/<class>/<name>.md` are one claim — `bug:<name>` — whatever class
directory the swarm has moved the document to.

## Next step

Widen the class-directory part of `norm_claim`'s regex from `hard/` to any one
class-directory segment, e.g.

    r"(?:bugs/(?:[A-Za-z0-9_]+/)?)?([A-Za-z0-9_]+?)(?:\.md)?"

and add cases to the claim tests (`tools/test_claim_release.py`, or whichever
`tools/test_control_*.py` owns `norm_claim`) for `bugs/mid/<name>.md`,
`bugs/hard/<name>.md` and a bare name, asserting all three normalise to one
string and conflict with each other. Failing on an unrecognised path is the
alternative if the regex is meant to be exhaustive; silently returning it
unchanged is the one answer that must not stand.
