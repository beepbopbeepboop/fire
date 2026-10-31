# CODEGEN: self-hosted `.name`-field string used as a dict key loses hash identity

## Status (2026-09-19 update): ~25 real bugs fixed across many commits; root
## cause of the LAST remaining class crystallized as whole-program
## compile-order nondeterminism, not yet fixed

This doc started from one narrow finding (below) and grew, over one long
session, into the tracking doc for `make check-native-dumpfull`'s entire
remaining gap. Summary of what happened, newest first:

- **Whole-program compile-order dependent symbol resolution (OPEN, not
  fixed)**: after fixing every concrete bug found below, `mojoc fire.py
  --dump-full` run twice in a row *still* disagrees with itself, now at a
  `_MOJO_STUB_add`/`_MOJO_STUB_get` vs `gimple_codegen`'s own module-struct
  section ordering (gimple_gen_calls.py's auto-stub path, gated on
  `fname_raw not in gen.func_return_types` — true or false depending on
  whether the DEFINING module has already been compiled by the time this
  CALLING module's call site is lowered). This is the same shape as every
  other divergence chased in this doc: `_module_candidate_paths`'s
  relative-vs-absolute race (fixed), `_MOJO_STUB_GimpleGen_*` count
  differing by ~378 (documented, not fixed), `_build_config_toplev`
  appearing in a different position relative to `_shutil_toplev` (fixed
  differently each time a different upstream nondeterminism source got
  fixed first), and a closure's registered argument count flipping
  (fixed). All of them reduce to: **the ~59-module transitive closure
  gets recursively discovered and compiled in an order that is not
  guaranteed identical between the python3 shim and the self-hosted
  binary**, so "is this symbol's real signature/struct/definition already
  known, or do we need a placeholder/stub/extern-only guess" answers
  differently depending on that order. A one-at-a-time fix at each
  manifestation site (this session's whole approach) demonstrably makes
  real, measurable progress — the self-host-vs-self-host first-
  disagreement byte offset was pushed from a hard CRASH, through byte
  99872, 254836, 689905, 4613182, and 6013115 (each a genuine, separately
  fixed bug) — but each fix only moves WHERE the next disagreement
  surfaces, because the underlying "order isn't guaranteed identical" fact
  is still true. **Do not expect the NEXT one-off fix to be the last
  one** — budget for this as an open-ended architectural property, not a
  bug count to exhaust. The two real fix strategies, in order of
  preference:
  1. **(Recommended, bigger)** Make the recursive module-discovery/compile
     order itself deterministic and independent of shim-vs-self-host
     execution — e.g. a two-pass design: pass 1 walks the whole
     transitive closure collecting every module/symbol's info with NO
     code emission at all (so its own traversal order literally cannot
     affect output), pass 2 emits everything in one final pass ordered by
     `sorted()` over the complete, order-independent knowledge pass 1
     built. This eliminates the entire class at once instead of chasing
     individual call sites forever.
  2. **(What this session did)** Keep bisecting `mojoc fire.py --dump-full`
     run-twice-in-a-row diffs one manifestation at a time (see "How to
     continue" below) — real, valid, but open-ended.

- **~25 concrete self-hosted correctness/nondeterminism bugs, FIXED**,
  across these commits (search the repo log for the exact diffs):
  "Fix self-hosted comprehension compile-failures and identifier-key hash
  loss", "Fix self-hosted crash: FromImportStmt.names tuple corruption in
  gen_module_impl", "Fix FromImportStmt.names tuple-subscript corruption
  across 19 call sites", "Fix ASLR-dependent %-format literal corruption",
  "Fix two more single-var-iterate-then-subscript nondeterminism sources",
  "Fix LayoutSolver/EscapeAnalyzer param-name subscript nondeterminism",
  "Fix more comprehension/subscript-unpack nondeterminism, plus a real
  path-boxing bug", "Fix genexpr/comprehension-join string corruption, and
  module path resolution race". Each commit message has the specific
  before/after repro and byte-offset evidence. The two dominant *shapes*
  of bug, useful as a checklist for anyone auditing more call sites:
  - `for x in some_list: ... x[0]` (or `x[1]`, etc.) — subscripting a
    value obtained by single-variable for-loop iteration, whether
    `some_list` is a real AST field (`stmt.names`, `.extra`) or a freshly
    built list (`_fromimport_names(...)`, `_parse_fstring_parts(...)`,
    `parts` built by `.append((...))`) — BROKEN (working `==` but
    corrupted `len()`/hashing on the subscripted slot). Fix: a plain
    `for a, b in some_list:` unpack directly in the for-statement (NOT a
    comprehension, NOT a subscript) is the one shape confirmed safe
    throughout this session for `list[tuple[str, str]]`-shaped data.
  - `''.join(<comprehension or genexpr>)` — joining a list of computed
    string PIECES via a comprehension/genexpr, tuple-unpack target or not
    — BROKEN (produces an erased `_slit` string pool reference, i.e. a
    raw heap address baked into the generated C as a decimal literal,
    different every run under ASLR). Fix: an explicit accumulation loop
    (`out = ''; for x in things: out += f(x)`).
  Neither `_as_str()` alone (a compile-time type-hint, not a runtime
  conversion) nor keeping the loop-then-subscript/comprehension SHAPE and
  merely guarding the extracted value reliably fixes either pattern —
  both require actually changing the SHAPE to a plain for-loop.

## Original finding (kept for the specific repro), status: two confirmed chokepoints fixed; general pattern likely recurs elsewhere

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

## check-native-dumpfull: crash FIXED, real content divergence remains (update, same session continued)

`make check-native-dumpfull` originally failed with `MOJO_NO_SHIM=1 ./mojoc
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

## Update 2026-09-19: shift to per-file `--dump` sweep; a THIRD open bug found

Per-file `tools/ab_compare.py` sweep (`make -j8 aside bside`, 779 files)
after all the above fixes: **clean=40, CI-DIFF=698, SELFHOST-CRASHED=22,
AST/TOK-DIFF=14** — barely moved from the session's very first sweep
(clean=40, CI-DIFF=696). This does NOT mean the fixes were wasted — most
of them measurably shrank individual files' divergence or fixed crashes
without flipping the file to fully "clean" (e.g. `unescape_c.py`'s
function body went from diverging at byte 29388 to matching byte-for-byte,
but its `__main__`/toplevel block still differs from an unrelated cause) —
but it does mean full per-file byte-identity is still far off and the
right next unit of work is "pick ONE small file, drive it to genuinely
zero diff" rather than continuing to survey.

Picked `gimple_exprtypes.py --dump` (small, `do_imports=False` so no
whole-program recursion, first-diff at byte 11225) and traced it past two
real, now-fixed bugs (`gen._link_import_decl_list` — see the `stmt.module`
`_as_str` guard and `os.path.join`→`+` fixes, both committed) to a THIRD,
NOT YET FOUND bug: `exports.get(name)` in `_emit_imported_global_accessors`
(gimple_gen_infra.py) misses for a stable 2-of-6 subset of
`gimple_ctypes.py`'s real `global_var` exports, every self-hosted run,
even after both `name` (verified byte-correct via `len()`) and the lookup
path (`_cand`) are confirmed clean. Two direct fix attempts (rewriting
`_fi_name`/`_fi_alias` to avoid slicing; fixing `os.path.join`) each
independently verified to make ZERO difference to which 2 entries are
missing — meaning the corruption is upstream of this function entirely,
most likely inside `module_loader.py`'s own regex-based export-text-scan
or its `ModuleLoader._path_cache` dict (`if path in self._path_cache:
return self._path_cache[path]` — itself a dict keyed by a string that's
been through the same corruption-prone construction chain). **Not
investigated inside module_loader.py itself this session** — that file
was never opened/edited. This is the concrete next step: instrument
`module_loader.py`'s own export scan the same MOJO_DEBUG-gated way (see
`_debug_note` — already removed from the current commit, re-add fresh) to
find which of the 2 missing exports' names are actually present in
`ModuleLoader`'s internal parse result vs silently dropped/mis-keyed.

**How to continue efficiently**: this exact investigation (one small
`--dump`, single-file, `do_imports=False`) took roughly a dozen
print-debug-rebuild-test cycles at ~2-3 minutes each to get this far,
each narrowing the search by eliminating one hypothesis. The pattern
that worked: add 2-3 `gimple_ctypes._debug_note(tag, value)` calls
bracketing a suspected function boundary, gated `if mod == 'gimple_ctypes'`
(or similarly scoped to the ONE reproducing case) so the debug output
stays small; run shim first (`MOJO_DEBUG=1 python3 fire.py --dump
gimple_exprtypes.py`, no rebuild needed, instant); THEN `rm -f mojoc &&
make mojoc` (the slow step, ~2 min) and re-run self-hosted
(`MOJO_DEBUG=1 MOJO_NO_SHIM=1 MOJO_HOME=$PWD ./mojoc
$PWD/gimple_exprtypes.py --dump`); compare the two debug traces by eye
(they're short). Move the debug points one function deeper into whichever
side looks suspicious, repeat. This is the exact iota+hash technique from
HOW-TO-DEBUG.html §8b at a coarser grain (values instead of a rolling
hash) — reach for the real rolling-hash+lldb version once a single
function's own internals need bisecting rather than a handful of call
sites across a short chain.
