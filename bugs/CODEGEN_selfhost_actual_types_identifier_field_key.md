# CODEGEN: self-hosted `.name`-field string used as a dict key loses hash identity

## Status: two confirmed chokepoints fixed; general pattern likely recurs elsewhere

## Problem

On the self-hosted path (`MOJO_NO_SHIM=1 ./mojoc <file> --dump`), a Python
`str` value read from an AST node's **struct field** (e.g. `IdentExpr.name`,
`FunctionDef.name`) behaves inconsistently depending on how it's used:

- `==` / `.startswith()` / `.lstrip()` — work correctly (byte contents are
  intact).
- `len()` — returns **0** for a real non-empty string.
- Used as a **dict key** (`d[x] = ...` then later `d.get(x)` / `x in d`,
  even from a byte-identical `x`) — the lookup **misses**, even when the
  entry was inserted moments earlier in the same function call.

This is a different (and worse) failure mode than the already-known
"tuple-unpack-over-a-list boxes both slots to int64_t" trap documented at
several call sites in `gimple_gen_infra.py`/`gimple_module_gen.py` (see the
"iterate by index, not tuple unpack" comments/commits): those affect a
*computed* tuple value; this one affects a **plain struct field read**,
and plain `for name, type in obj.params:` for-loop unpacks (the established
"safe" alternative) do **not** exhibit it — only accessing the field via
attribute access on a class instance and then keying a dict with it does.

Concretely: `gen._actual_types[tname] = 'char'` (write, `tname = tgt.name`
from an `AssignStmt`'s `IdentExpr` target) followed one statement later by
`gen._actual_types.get(var)` (read, `var` from the same identifier's
`.name` at a comparison site) returns `None` on self-host despite an
immediate self-check (`gen._actual_types.get(tname) == 'char'` right after
the write) confirming the entry WAS there under that exact key at that
exact moment.

## Minimal repro

```python
# /tmp/mojo_repro/t1.py  (not checked in — recreate as needed)
def f(s):
    c = s[0]
    if c == 'x':
        return 1
    return 0
```

```
python3 fire.py --dump t1.py        # shim:      _t5 = (char)c;
MOJO_NO_SHIM=1 ./mojoc t1.py --dump # self-host: _t5 = (int64_t)c;  (WRONG)
```

The wrong self-hosted output reinterprets `c`'s int64_t-boxed character
*value* as a pointer (`(char *)(int64_t)c`) instead of converting it to a
1-char string via `mojo_char_to_str` — because `_to_char_star`
(`gimple_gen_exprs.py`) couldn't recover `c`'s tracked actual type ('char')
from `gen._actual_types`, and fell back to the "assume int64_t next to a
string literal is a char*-boxed pointer" default.

This is very likely the dominant root cause behind the aside/bside A/B
sweep's **696/779-file CI-DIFF** (`tools/ab_compare.py`), since
`_actual_types`-by-identifier-name tracking is the general mechanism this
codegen uses everywhere to recover "this int64_t/char-declared local is
really a char" across statement boundaries — not something specific to
`unescape_c.py`'s `next_char` (the file that surfaced it first).

## Fix applied (two chokepoints)

`_as_str(x)` — already an established "CHOKEPOINT guard" in this codebase
(see `_new_temp`'s `ctype = _as_str(ctype)`, and its docstring in
`fire_compiler.py`) — forces the self-hosted backend to treat the value as
a proper boxed string. Applied at:

- `gimple_gen_stmts.py`, `_track_pointer_actual_type`: `tname = _as_str(tname)`
  at entry (the WRITE side).
- `gimple_gen_exprs.py`, `_to_char_star` (inside the `==`/`!=` string-compare
  BinaryOp lowering): `gen._actual_types.get(_as_str(var))` (the READ side).

With both fixes, the minimal repro above produces `(char)c` on self-host
matching the shim, and `unescape_c.py`'s entire `unescape_c` function body
(previously the first-diverging temp `_t24`) now matches the shim's `.ci`
**byte-for-byte** — the file's remaining CI-DIFF is now confined to the
unrelated `_toplevel`/`__main__`-block codegen (a `content` variable typed
`int` on self-host vs. inlined on the shim — a separate, smaller bug, not
investigated this session).

## What's NOT fixed — general scope still open

Only the two call sites above were fixed. `gen._actual_types`,
`gen.var_types`, `gen._elem_types`, `gen._dict_val_types`, and similar
name-keyed dicts are read/written from **many** other places across
`gimple_gen_*.py`/`gimple_module_gen.py` using a bare `.name` field or a
plain identifier string sourced the same way, any of which may have the
identical latent bug (silently falling back to a wrong default rather than
crashing, which is why this went unnoticed for so long — see the
`build/coro_scoreboard.stackswitch.json`-adjacent aside/bside sweep this
session found it from). A thorough fix would either:

1. Audit every `gen._actual_types`/`gen.var_types`/etc. dict access whose
   key traces back to an AST node's `.name` field and add the same
   `_as_str(...)` guard, or
2. (Better, less error-prone) find *why* a `.name` struct-field read
   erases hash/len identity while a for-loop-unpacked local of the same
   static `str` type doesn't, and fix it at the codegen level that lowers
   struct field reads of `str`-typed fields — this would fix the whole
   class at once instead of one call site at a time.

Option 2 requires more `_actual_types`/GIMPLE-codegen-internals digging
than this session had budget for; option 1 is the safer, incremental path
and is how the rest of this bug's cousins (documented across
`gimple_gen_infra.py`/`gimple_module_gen.py`) have been fixed historically.

## How to continue

Re-run `tools/ab_compare.py` after a fresh `make -j20 aside bside` sweep
(both sides need regenerating — `aside`/`bside`/`ab.mk`/`.ab_locks` are all
gitignored scratch dirs) to find the next-most-common `CI-DIFF` pattern,
then use the same MOJO_DEBUG-gated `gimple_ctypes._debug_note` technique
used this session (see this doc's own investigation trail in the session
transcript) to bisect the specific dict/lookup involved — it is a fast,
low-token alternative to lldb for this class of bug, since the divergence
is almost always a boolean/string flag silently taking the wrong branch,
not a crash.

## Separate, unrelated finding from this session (pre-existing, NOT a regression)

`make check-noshim-dumpfull` currently fails: `MOJO_NO_SHIM=1 ./mojoc
fire.py --dump-full` segfaults with **no** `fire.ci` written at all, which
`test_noshim_dumpfull.py` reports as "worse than the known original SIGBUS"
(which used to at least write the file before crashing). Verified via a
stash/rebuild A-B test that this reproduces identically on `master` HEAD
**without** any of this doc's fixes applied — it is not caused by the
`_as_str` changes above. Also: `tools/ab_compare.py`'s `SELFHOST-CRASHED`
bucket jumped from an initial 23 to 104 when `mojoc` was rebuilt from a
stale (pre-session) binary to current `HEAD` — also confirmed
pre-existing/unrelated via the same stash/rebuild A-B method. Both are
likely the same underlying self-host regression from recent work (the
"Ownership model Phase 4/6" / stack-allocation commits in the recent log)
and warrant their own investigation, ideally starting from `mojoc fire.py
--dump-full` under lldb (`tools/gdbtool`) since it's a hard crash, not a
silent divergence.
