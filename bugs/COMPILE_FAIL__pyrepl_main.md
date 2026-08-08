# COMPILE_FAIL: _pyrepl/main.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/_pyrepl/main.py`

## Status (updated 2026-08-07) — FIXED

`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/_pyrepl/main.py`
now compiles clean and links to a working executable (exit code 0, no
`-Wint-conversion` errors). Fixed as part of
`bugs/hard/CODEGEN_global_prescan_blind_to_trystmt_and_bare_annotation.md`
(that doc's "Part 2"/"Part 3" — Phase 1.7's own pointer-boxing decision
for a bare annotation, plus the separate struct-field-declaration pass's
missing `type_ann` consultation and its f-string-source-text-as-a-
compile-time-constant bug). See that doc for the full mechanism and the
exact code changes; kept here only as the original real-world repro
record.

## Status (superseded — kept for history, 2026-08-06)

Re-ran against current HEAD; the specific error text has changed since
the original scan (which used a homebrew-installed `.../lib/python3.14/
_pyrepl/main.py` copy — same file, path differs) but the underlying bug
is the same class. Root-caused, NOT fixed — see below.

## Current error

```
/Users/mrs/net/Python-3.14.6/Lib/_pyrepl/main.py:19:29: error: assignment to 'char *' from 'int64_t' {aka 'long long int'} makes pointer from integer without a cast [-Wint-conversion]
/Users/mrs/net/Python-3.14.6/Lib/_pyrepl/main.py:22:29: error: assignment to 'char *' from 'int64_t' {aka 'long long int'} makes pointer from integer without a cast [-Wint-conversion]
/Users/mrs/net/Python-3.14.6/Lib/_pyrepl/main.py:30:8: error: assignment to 'char *' from 'int' makes pointer from integer without a cast [-Wint-conversion]
```
at:
```python
CAN_USE_PYREPL: bool
FAIL_REASON: str
try:
    ...
except Exception as e:
    CAN_USE_PYREPL = False
    FAIL_REASON = f"warning: can't use pyrepl: {e}"        # line 19
else:
    CAN_USE_PYREPL = True
    FAIL_REASON = ""                                        # line 22
...
            print(FAIL_REASON, file=sys.stderr)             # line 30
```

## Root cause

`FAIL_REASON: str` is a bare annotated module-level global, assigned
ONLY inside a top-level `try`/`except`/`else` block — never via a plain
top-level `AssignStmt`. `gen_module`'s Phase 1.7 global pre-scan
(`gimple_codegen.py`) only matches plain top-level `AssignStmt` nodes (a
`TryStmt`'s nested assignments are invisible to it, and the bare
annotation itself parses to a `VarDecl` with no value, a third shape
Phase 1.7 doesn't consult either) — so `FAIL_REASON`'s real type is
never resolved, and a separate, more permissive fallback then seeds its
initial value with the literal SOURCE TEXT of the f-string expression,
string-repr'd, under an `int`-typed struct field. Every later assignment
to it then mismatches against whatever declared type actually won.

Standalone repro confirmed:
```python
FAIL_REASON: str
try:
    raise RuntimeError("x")
except Exception as e:
    FAIL_REASON = f"warning: {e}"
else:
    FAIL_REASON = ""

def main():
    print(FAIL_REASON)

main()
```

Full mechanism written up as a new hard bug:
`bugs/hard/CODEGEN_global_prescan_blind_to_trystmt_and_bare_annotation.md`
— this is a sibling gap to the ALREADY-FIXED `IfStmt`-blindness in this
exact same Phase 1.7 pass (`bugs/COMPILE_FAIL_importlib__bootstrap_external.md`,
commit `fd29316`), just triggered by `TryStmt` instead of `IfStmt`, plus
a second compounding gap for bare (unassigned) type annotations.

## Not fixed

Per this session's standing guidance: this touches global-variable
type-inference machinery immediately adjacent to the areas already
flagged high-risk (the very same Phase 1.7 pass this fix would extend
has direct history — see `bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`'s
note on two real regressions from confident-looking type-inference
changes this session), and a real fix here needs a genuinely different
algorithm shape (unify types across ALL `try`/`except`/`else` branches,
not resolve to one, unlike the `IfStmt` case) plus tracking down an
untracked third fallback producing the garbage placeholder value. Left
for a dedicated pass — see the hard-bug doc's "What a real fix needs"
for the concrete 3-step plan.
