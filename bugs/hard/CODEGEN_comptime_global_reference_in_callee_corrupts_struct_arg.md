# HARD BUG: calling a helper that reads a module-level `comptime` global loses a struct-pointer argument's mutation, in `mojo dylib`'s per-module compile

## Status (2026-08-15, found while independently re-verifying a different fix)

Found and isolated while investigating whether the box.3d game's
`chest_total_count`/`remove_from_slot` "returns wrong value" symptom
(noted as an open question in
`box.3d/game/bugs/DYLIB_sibling_import_calls_bind_to_weak_stubs.md`)
shared a root cause with a separate crash bug found in the same
session. It does not — that investigation is what led here. **Not
fixed, not fully root-caused** — this doc records a precise, minimal,
verified repro and a strong, narrowed-down lead, per this project's
"file it, don't half-fix it" convention for `bugs/hard/`.

## Symptom

A struct field mutated via a helper function silently reverts to its
old value (as if the mutation never happened) when that helper's own
body ALSO calls a second helper that reads a module-level `comptime`
constant — even though calling that same second helper WITHOUT the
`comptime` reference, or calling it standalone (not nested inside the
struct-mutating helper), works fine. No compile error, no crash — just
a wrong runtime value.

## Repro (minimal, verified, self-contained — not the real game files)

```mojo
# t.mojo
comptime MAX_COUNT: UInt64 = 64

struct Chest:
    s0_id: UInt64
    s0_count: UInt64

def clamp_count(n: UInt64) -> UInt64:
    if n > MAX_COUNT:
        return MAX_COUNT
    return n

def _set_slot(c: Chest, item_id: UInt64, count: UInt64) -> None:
    c.s0_id = item_id
    c.s0_count = count

def chest_set(c: Chest, item_id: UInt64, count: UInt64) -> None:
    _set_slot(c, item_id, clamp_count(count))

def Chest_new() -> Chest:
    return Chest(0, 0)

@cdecl
def t() -> Int64:
    var c = Chest_new()
    chest_set(c, UInt64(5), UInt64(10))
    return Int64(c.s0_count)
```

Build and run:
```
python3 mojo.py dylib -o /tmp/t.dylib t.mojo
python3 -c "
import ctypes
import build_stdlib_dylib as bsd
ctypes.CDLL(bsd.runtime_dylib())
lib = ctypes.CDLL('/tmp/t.dylib')
lib.t_t.restype = ctypes.c_int64
print(lib.t_t())
"
```

**Expected: `10`. Actual: `0`.**

The build itself succeeds cleanly (no compile/link errors) — this is a
silent wrong-value bug, not a build failure.

## What was ruled out (bisection notes)

Starting from the real game's `base/chest.mojo` (27-field `Chest`
struct, `chest_set`/`chest_total_count`/`clamp_count` etc.), reproduced
the wrong-value symptom, then bisected down to the 7-line repro above
by removing pieces one at a time and re-testing after each removal
(exact values from that session):

- **Not cross-module/cross-file struct visibility.** Reproduces
  identically in a single file with zero imports at all (the repro
  above is one file). Originally suspected this was the same root
  cause as a separate `mojo dylib` cross-file-struct-parameter bug
  found the same session — directly disproved: that bug involves a
  caller in a DIFFERENT file than the struct's definition; this one
  reproduces with everything in one file.
- **Not the multi-slot `elif` chain or the `while` loop** in the real
  `chest_total_count`/`_get_slot`/`_set_slot`. The repro above has a
  single field, no loop, no conditional slot dispatch — just a direct,
  unconditional field write.
- **Not `UInt64` vs `Int64`** specifically — reproduced with both types
  in intermediate bisection steps (not shown above, but confirmed both
  ways before settling on `UInt64` to match the real game's types).
- **Not "any nested call as the last argument to a struct-mutating
  call."** `_set_slot(c, item_id, identity(v))` where
  `identity(n: UInt64) -> UInt64: return n` (no `comptime` reference,
  no branch) — mutation works correctly, returns the right value.
  `_set_slot(c, item_id, clamp_count_literal(v))` where
  `clamp_count_literal` has the SAME branching shape as `clamp_count`
  (`if n > UInt64(64): return UInt64(64) ... return n`) but compares
  against a literal instead of a `comptime` name — ALSO works
  correctly. Only swapping the literal `UInt64(64)` for a reference to
  a module-level `comptime MAX_COUNT: UInt64 = 64` reproduces the bug.
- **Not specific to the call being syntactically nested as an
  argument expression.** Hoisting it to a local first —
  `var clamped = clamp_count(count); _set_slot(c, item_id, clamped)`
  instead of `_set_slot(c, item_id, clamp_count(count))` — still
  reproduces. So it's not an argument-evaluation-order/register-
  clobbering-at-the-call-site issue in the narrow syntactic sense;
  something about `chest_set`'s body calling a `comptime`-global-
  reading helper AT ALL (regardless of exactly where in the body)
  appears to corrupt how `c`'s mutation is later observed by the
  caller.
- **Not specific to `_set_slot` being a separate helper function at
  all** in the earliest (pre-bisection) form — the ORIGINAL discovery
  used the real, unmodified `base/chest.mojo` copied into a single
  file with an appended `Block { chest: Chest }` wrapper struct and a
  test function doing:
  ```mojo
  var b = Block(0, Chest_new())
  chest_set(b.chest, UInt64(0), UInt64(5), UInt64(10))
  chest_set(b.chest, UInt64(1), UInt64(5), UInt64(7))
  return Int64(chest_total_count(b.chest, UInt64(5)))
  ```
  (expected `17`, got `0`) — confirms the bug is not an artifact of
  the later minimization, just reduced down to its essence.

## What's still unknown / promising leads

Not traced into `gimple_codegen.py` itself yet. Where to look, based on
the bisection above:

- The trigger is specifically a **module-level `comptime NAME: T =
  value` declaration** (parsed by `mojo_compiler.py`'s
  `_parse_comptime`, ~line 2887) being **read inside a function that is
  itself called from within another function that also takes a struct
  parameter and mutates one of its fields**. Look at how
  `gimple_codegen.py` registers/lowers top-level `comptime` decls
  (search for wherever it handles the AST node `_parse_comptime`
  produces — this doc's author did not locate that specific lowering
  site, only the parser side) — a plausible mechanism: if a
  `comptime` global's VALUE gets materialized as some kind of
  per-call-frame temp, global-state cache, or is threaded through a
  code path that conflicts with how a struct-pointer parameter's
  address/temp is tracked across a call boundary, that could explain
  why merely calling the comptime-reading helper (regardless of
  whether its result is used, hoisted, or inlined) disturbs the
  caller's own struct-pointer bookkeeping.
- Since a LITERAL-comparing helper with the identical branch shape
  does NOT reproduce, this is almost certainly not about `if`/
  branching, return-type inference, or general nested-call codegen —
  it's specific to `comptime` global resolution.
- Not yet checked: whether this reproduces via `mojo build` (link
  mode / whole-program inline compile) or only `mojo dylib`'s
  per-module standalone compile (`build_stdlib_dylib.py`'s compile
  primitive) — all repro attempts so far used `mojo dylib`. Worth
  checking whether `do_imports=True` whole-program compiles are also
  affected, or whether this is scoped to the standalone per-module
  path specifically (the same path the box.3d game's dylib build
  uses).
- Not yet checked: whether the corruption is in the WRITE (the field
  assignment inside `_set_slot`/`chest_set` doesn't actually take
  effect) or in the READ (the caller's `c` becomes a different/stale
  pointer after the call returns) — dumping the generated C for the
  minimal repro above (not yet done this session) would likely settle
  this quickly and should be the first step for whoever picks this up.

## Why this matters

This is the actual, currently-unresolved reason the box.3d game's real
`chest_total_count`/`remove_from_slot` calls return wrong values even
after their SEPARATE undefined-symbol link-failure issue is one day
fixed (see `box.3d/game/bugs/DYLIB_sibling_import_calls_bind_to_weak_stubs.md`)
— `base/chest.mojo`'s real `clamp_count`/`clamp_item_id` both read
module-level `comptime` constants (`MAX_COUNT`, `MAX_ITEM_ID`) from
inside helpers called by the struct-mutating functions, exactly
matching this repro's shape.

## Verification (for whoever fixes this)

1. The minimal repro above returns `10`, not `0`.
2. The original discovery shape (`Block { chest: Chest }` wrapper +
   real `base/chest.mojo` content, two `chest_set` calls +
   `chest_total_count`) returns `17`, not `0`.
3. Full quality gate: `test_gimple.py`, `test_module_cache.py`,
   `make check-selfhost`, from-scratch stdlib dylib rebuild (0 skip
   lines), `compile_stdlib.py` (no `-j`) 664/664 0 unexpected — this
   touches struct field mutation and/or comptime-global resolution,
   both broadly used, so a fix here has real regression risk and needs
   the full gate, not just the two new repros above.
