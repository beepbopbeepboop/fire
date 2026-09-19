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

## check-noshim-dumpfull: crash FIXED, real content divergence remains (update, same session continued)

`make check-noshim-dumpfull` originally failed with `MOJO_NO_SHIM=1 ./mojoc
fire.py --dump-full` segfaulting with **no** `fire.ci` written at all
(confirmed pre-existing via stash/rebuild A-B testing, not caused by this
doc's `_as_str` fixes above). Root-caused and fixed in two follow-up
commits:

- `gen_module_impl`'s `FromImportStmt` handling read alias names via
  `for alias in stmt.names: alias[0]/alias[1]`. `FromImportStmt.names` is
  `list[(str, str|None)]`, and its own dataclass docstring already
  documented that these tuples box to int64_t self-hosted, providing the
  actual fix: `stmt.name_alias_strs` (a flat `list[str]` of
  `"name"`/`"name|alias"` composites) + `gimple_ctypes._fi_name`/`_fi_alias`
  accessors, already used correctly elsewhere in the same file but not
  here. Switched to it; the crash reproduced ~100% before, 0% after across
  10+ runs. The same broken `_fromimport_names(stmt)` + `_fip[0]`/`_fip[1]`
  subscript shape existed at **19 separate call sites** across
  `gimple_gen_funcs.py`/`gimple_gen_infra.py`/`gimple_gen_resolve.py`/
  `gimple_module_gen.py` — all fixed the same way.
- `_lower_percent_format` and its `MojoBytes` sibling (`gimple_gen_exprs.py`)
  built a `parts` list of tuples, then iterated `for part in parts:` and
  subscripted `part[0]`/`part[1]`/`part[2]` — the identical trap, but here
  even an `_as_str()` guard on the extracted values was NOT sufficient;
  the corrupted text still flowed into `_intern_string`, baking a raw heap
  ADDRESS into the generated C as a decimal literal
  (`mojo_str_cat (<address>, ...)`) — different every process run under
  ASLR. Confirmed via running `mojoc fire.py --dump-full` **twice in a
  row** and diffing the two self-hosted outputs against each other (not
  against the shim) — proof of genuine non-determinism, not just a
  shim-vs-self-host difference. Fixed by normalizing `parts` to uniform
  3-tuples and switching to a plain `for kind, text, conv in parts:`
  unpack, avoiding the subscript entirely.

**Net effect of both fixes**: the self-host-vs-self-host first-disagreement
offset moved from byte 6012936 to byte 254836 (earlier — expected, since
fixing the *first* nondeterminism source exposes whichever one used to be
masked behind it) rather than eliminating disagreement entirely. There is
at least one more nondeterminism source, not yet fixed:

## Open: closure call argument-COUNT nondeterminism (not yet fixed)

Two back-to-back self-hosted `--dump-full` runs of the identical `fire.py`
disagree at `module_loader.py:535`'s `_scan_source(content)` closure call
— compiled sometimes as `ModuleLoader_load_module_from_path__scan_source
(_env, _t162)` (2 args, correct: `_scan_source` is declared
`def _scan_source(src_content):`, one param) and sometimes as `(..., _t162,
0)` (a bogus 3rd arg). Traced to `gimple_gen_calls.py`'s closure-call
lowering (~line 2630-2656): `user_param_count = len(expected_params) - ...`
computed from `expected_params` (the closure's registered signature) is
sometimes wrong (too high by one), triggering the "pad missing trailing
args with a default, or `('int', '0')` if no default is known" fallback
that exists for genuinely-optional trailing parameters — `_scan_source` has
none, so this fallback should never fire for it. This is very likely THE
SAME underlying root cause as the `_build_config_toplev`-position /
`_MOJO_STUB_GimpleGen_*`-count divergences documented separately in this
session's commits: a closure/function's real signature becomes "known" at
a different POINT in the whole-program compile depending on which order
the ~59-module (recursive, `sorted()`-at-every-level but not necessarily
globally-consistent) transitive closure gets discovered and compiled in —
not yet proven to be literally the same code path, but the shape (a
just-registered-vs-not-yet-registered signature flipping behavior) matches
exactly. NOT YET FIXED. Whether a call with too many/few arguments could
ever produce a hard GCC error (rather than silently compiling, which is
what's been observed so far — `mojoc` built with exit 0 every time) has not
been checked; if the extern prototype for the affected closure also
fluctuates in lock-step with the call site (plausible, since it's likely
computed from the same `expected_params` source), that would explain why
GCC never complained despite the arg-count mismatch, and this bug would
still be a real, if currently silent, correctness risk.

**How to continue**: this needs the root compile-order-determinism issue
solved, not another individual call-site patch — the pattern of "signature
becomes known at a different point depending on discovery order" will keep
resurfacing at new call sites (stub declarations, closure calls, module
struct positions, ...) until the underlying transitive-closure recursion
order is made to not matter (either by making it truly identical between
shim and self-host, or — architecturally cleaner per this project's own
"pick the production-quality approach" convention — by making anything
order-SENSITIVE (stub emission, closure-arg-padding, struct-position)
insensitive to order instead, e.g. a two-pass design: pass 1 discovers
every module and every signature with no code emission at all, pass 2
emits everything in one final deterministic (alphabetically `sorted()`)
order using pass 1's complete, order-independent knowledge. That is a
substantially larger refactor than any single fix landed this session.

Also confirmed pre-existing/unrelated via stash/rebuild A-B testing at the
start of this investigation (not fixed, not caused by anything in this
doc): `tools/ab_compare.py`'s `SELFHOST-CRASHED` bucket jumped from an
initial 23 to 104 when `mojoc` was rebuilt from a stale (pre-session)
binary to current `HEAD` at the very start of this session — i.e. **always
rebuild `mojoc` fresh (`rm -f mojoc && make mojoc`) before trusting any
aside/bside sweep number**, since `make mojoc`'s Makefile rule only lists
`fire.py` + runtime files as prerequisites (not its full transitive
closure), so `make mojoc` alone frequently no-ops on a stale binary.
