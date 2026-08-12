# CODEGEN: compiled-path generator-comprehension tuple-unpack — first element wrong

## Status (found 2026-08-12, during independent re-verification of the
`_compr_generator_loop` bare-comma-target fix)

**Not fixed. Newly discovered, pre-existing — confirmed independent of
that fix (see below).**

## What

`[a for a, _ in <tuple-yielding generator>()]` (also `for (a, _) in ...`,
paren-wrapped — same code path, same bug) compiled through `mojo.py
build` produces the WRONG value for the first element: it comes out as
`None` (later shows up as a `NoneType`/uninitialized read once printed —
concretely, `print([...])` renders the first slot as the string `None`
where every other slot has the correct int). The interpreter
(`mojo.py run`) gives the correct result for the identical program.

## Repro

```mojo
def pair_gen(n: Int):
    i: Int = 0
    while i < n:
        yield i, i * 10
        i = i + 1

def main() -> None:
    result = [a for a, _ in pair_gen(4)]
    print(result)
```

Compiled (`mojo.py build`): `[None, 1, 2, 3]`
Interpreted (`mojo.py run`): `[0, 1, 2, 3]` (correct)

## Confirmed independent of the bare-comma-target fix

The identical wrong-first-value symptom reproduces with the OLD,
already-working paren-wrapped target too:

```mojo
result = [a for (a, _) in pair_gen(4)]
```

Same `[None, 1, 2, 3]`. That form's detection
(`gen0.target.startswith('(')`) was untouched by
`CODEGEN_generator_function_Lib_test_test_exception_group.md`'s fix
(commit `892af02`, this session) — it worked (compiled) before that fix
too. So this is a pre-existing bug in the shared value-extraction path
(`_emit_generator_tuple_unpack`, or upstream in how the FIRST
`{base}_resume`/`{base}_value` pair populates the boxed tuple list),
not a regression from that fix, and not something that fix's own scope
(target-string detection only) could plausibly touch.

## Where to look

`gimple_codegen.py`:
- `_compr_generator_loop` (~line 17360): `bb_cond` calls
  `{base}_resume({it_val})`, `bb_body` reads `{base}_value({it_val})`
  into `val`, then calls `_emit_generator_tuple_unpack(var_names,
  tuple_slot_ctypes, val)`.
- `_emit_generator_tuple_unpack` (~line 22061): per-slot
  `mojo_list_get_int`/`_str`/`_double` reads off `val` (the boxed tuple
  list). Slot-index logic looks correct on inspection — the actual
  divergence is likely earlier, in how the FIRST `resume()`/`value()`
  pair populates that boxed list (a coroutine "prime on construction"
  double-advance, or a shared/reused boxed-list object with a
  stale/not-yet-populated slot 0 on the very first access) — not
  independently diagnosed further here.
- The identical `is_tuple_target`/tuple-unpack machinery in
  `_gen_for_generator_iter` (~line 22146, a plain `for a, b in
  <generator>():` STATEMENT, not a comprehension) should be checked too
  — if it shares the same first-value bug, the root cause is in the
  shared boxing/resume protocol, not comprehension-specific.

## Impact

Only affects the COMPILED path (`mojo.py build`) consuming a real,
tuple-yielding compiled generator through a comprehension with a
tuple-unpacking target. The interpreter is unaffected. Real-world
severity: found via a synthetic repro during unrelated verification
work, not yet confirmed to affect any specific stdlib file's test
outcome (may or may not matter for
`Lib/test/test_exception_group.py`'s own `LeafGeneratorTest` — that
file's build is still blocked by unrelated `Lib/test/support/__init__.py`
gaps regardless, per the sibling doc, so this hasn't been checked against
real test output).

Not attempted here — found during merge-time verification, out of scope
for the session that found it.
