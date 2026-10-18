# MERGE: `_step_rhs_generic`'s `B.cond` arm interpolates a PYTHON `w`, so the arm raises `NameError` instead of emitting Lean

**Area:** FORMAL, proof generation — `formal/arm64_proof_gen.py::_step_rhs_generic`
(the `idx == 51` arm). Found 2026-10-18 while merging `work/formal412-docs`.
**Status: OPEN, one line, and NOT fixed here because the fix cannot be verified
without a Lean run** (see "Why it is filed and not fixed").

## What I ran, and what I saw

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 -c "import sys; sys.path.insert(0, '.'); \
    import formal.arm64_proof_gen as G; print(G._step_rhs_generic(51))"
NameError: name 'w' is not defined

$ python3 -c "import sys; sys.path.insert(0, '.'); \
    import formal.arm64_proof_gen as G; print(51 in G._WORK_STEP_BY_IDX)"
False

$ python3 -c "import symtable; \
    src = open('formal/arm64_proof_gen.py').read(); \
    t = symtable.symtable(src, 'f', 'exec'); \
    [print(c.get_name(), s.get_name()) for c in t.get_children() \
     if c.get_name() == '_step_rhs_generic' for s in c.get_symbols() \
     if s.is_global() and not s.is_assigned() and s.get_name() == 'w']"
_step_rhs_generic w
```

## What is wrong

Every other arm of `_step_rhs_generic` emits a Lean term in which `w` is the
word variable, and writes it by interpolation (`f"… {(((w >>> 5) &&& 0x3f).toNat) …}"`,
where the `{…}` is a PYTHON expression over `_RD`, `_RN`, `_RM` and friends). The
`B.cond` arm writes:

```python
    if idx == 51:  # B.cond -- flags-only, exactly as in _step_rhs
        return (f"(if arm64_matches_condition {w & 0xf} s.nzcv = true then "
```

`{w & 0xf}` is a PYTHON expression, and `w` is not a Python name in this module
— so the arm raises. Two things follow from it:

1. **It would emit an un-typeable term anyway**, even if `w` were bound: the
   result is interpolated as `arm64_matches_condition 5 s.nzcv` (a `Nat`
   literal) rather than the word-level `((w &&& 0xf) : Nat).toNat` every
   `_step_rhs` sibling produces by computing `cond = w & 0xf` in Python and
   printing the number. `w` is a `UInt32` in the `work_step_*` statements, so
   `w & 0xf` is not Lean at all.

2. **The arm is unreachable today**, which is why nothing has measured it: `51`
   is not a key of `_WORK_STEP_BY_IDX`, the 47-entry table the universal-theorem
   closer walks. The one caller is
   `_pc_dependent = "s.pc" in (_step_rhs_generic(idx) or "")`, so the crash
   arrives the first time a `B.cond` is added to that table — at which point it
   looks like proof generation failing for no reason.

`_step_rhs` (which TAKES `w`) gets the same arm right, at line ~3766:
`cond = w & 0xf` as a Python statement, then `cond` interpolated.

## The exact next step

```python
    if idx == 51:  # B.cond -- flags-only, exactly as in _step_rhs
        return (f"(if arm64_matches_condition {COND_FIELD} s.nzcv = true then "
```

where `COND_FIELD` is `"((w &&& 0xf).toNat)"` — `_RD` already establishes the
shape (`_RD = "((w &&& 0x1f).toNat)"`) and `w` is the `UInt32` the generated
`work_step_*` statement binds. Adding `B.cond` to `_WORK_STEP_BY_IDX` is then
what exercises it, and
`test_formal_call_proof_gen.py::TestRegister31::test_no_arm_of_the_generic_rhs_
builder_raises` (added with this doc, and green) will catch the next arm that
raises rather than a proof run 45 s later.

**Verify with a Lean run** — `python3 tools/suite.py formal-call-proof-gen`, or
`python3 -m unittest test_formal_call_proof_gen.TestUnsignedOffsetAccess` for
the encoder half. The fix is not verifiable in a light worker: the nearest
attempt at the neighbouring Lean-facing tests, `python3 -m unittest
test_formal_call_proof_gen.TestUnsignedOffsetAccess`, breaches an 8 GB reservation
on this tree.

## The guard that IS landed

`test_formal_call_proof_gen.py::TestRegister31::test_no_arm_of_the_generic_rhs_
builder_raises` sweeps every index of `_WORK_STEP_BY_IDX` through
`_step_rhs_generic` and reports the ones that raise. It is green on this tree,
which is the honest state of the question: the table is clean, and `51` is not in
the table. It is a regression guard, not a fix.
