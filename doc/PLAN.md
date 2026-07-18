# Known Bugs and Outstanding Work

This document tracks verified, still-open defects and deferred feature work.
See `IMPL.md` for what's already implemented and working, and `STDLIB.md` for
stdlib transpilation status. Historically this file also tracked the GIMPLE
bootstrap error-fixing plan from the project's early phase (May 2026) and
`BACKLOG-CODEGEN.md` tracked defects deferred from the 2026-07-03 hardening
pass — both are long since resolved or superseded and have been folded in
here (open items) and into `IMPL.md` (fixed items). `BACKLOG-CODEGEN.md`
itself is now a thin redirect, kept only because a number of in-code
comments still reference its old section numbers (`§4d`, `§4f`, etc.).

---

## Known bugs (verified, real, still open)

- **✅ RESOLVED 2026-07-17 — `make bootstrap` is now fully green (all 3
  stages verified, 0 failures).** The long investigation log below is kept
  for its diagnostic trail, but the headline: the final 2/152
  `mojo.tok`/`.ast` divergences were fixed by two changes landing together.
  (1) The *root cause* was a codegen bug, not the `in`-operator gap the log
  spent most of its length on: `_safe_coerce_emit` (`gimple_codegen.py`)
  coerced a bare `char` into a `char *` slot with a raw `(char *)` cast,
  reinterpreting the char's BYTE VALUE as a pointer address (`'_'` →
  `(char *)0x5f`), which then segfaulted the instant anything dereferenced
  it. Reproduced in a **6-line** file — `prev = s[k-1] if k>0 else ''` (a
  mixed-type ternary: `char` branch vs `char *` branch) followed by
  `prev == '_'` — no closures, no big function, no `in` involved. Fixed by
  converting `char → char *` via `mojo_char_to_str` (a real 1-char string),
  matching Python's "a str of length 1" semantics; other narrow-scalar →
  pointer coercions (genuine boxing) are unchanged. THIS is what made the
  two earlier `==`-rewrite attempts crash (they advanced the prefix loop
  far enough to reach a non-empty `prev`, tripping the latent ternary bug) —
  the "closure vs method / temp-aliasing" theories in the log below were
  both wrong; the lldb `x0=0x28` / `x1="'_'"` evidence was pointing at the
  `prev == '_'` comparison the whole time. (2) With that unblocked, the
  actual mistokenization fix: `replace_multiline_strings`'s prefix-scan loop
  (`mojo_compiler.py`) switched from `src[k-1] in 'fFrRbBuUtT'` (the
  documented always-False `in`-for-char* stub, which made self-hosted prefix
  detection never fire) to explicit `==` comparisons, the same proven-safe
  pattern `_strip_string_prefix_and_quotes` already uses. `make check`
  green, `make bootstrap` fully verified.

  Separate pre-existing bug spotted in passing (NOT chased — orthogonal,
  reproduces in a 4-line file): `str(0)` prints `None`/empty instead of
  `"0"` in the compiled path. `str(5)` works. File as its own bug.

  _Original investigation log (kept for the diagnostic trail):_

- **Stage2 self-hosted `--dump` of a large file (mojo.py itself, ~900KB) is
  still far too slow/memory-hungry to finish in reasonable time, even after
  fixing two real, confirmed contributing bugs.** Investigated 2026-07-17
  chasing what first looked like a stage2-bootstrap segfault (see the
  `compile_to_gimple` entry below) but turned out, once that crash was
  fixed, to actually hang/balloon in memory (traced live via `lldb attach`
  + `ps` RSS sampling, not guessed): `stage2/mojo --dump ../mojo.py` grew to
  89GB RSS at 100% CPU before being killed, entirely inside
  `py_tokenize_replace_multiline_strings` (mojo_compiler.py's own
  tokenizer, self-hosted) - no subprocess/child process involved, all
  single-threaded in-process cost. Two real bugs found and fixed along the
  way (both in `runtime/mojo_runtime.c`):
  1. `mojo_cstr_slice(s, start, stop)` called `strlen(s)` on *every* call
     regardless of how small `start`/`stop` were, so a tight scanning loop
     that repeatedly slices a fixed 3-byte window out of a large string
     (exactly what the triple-quote-close scan in `replace_multiline_strings`
     does) was accidentally O(n^2) in the string length. Fixed: only fall
     back to a full `strlen()` when negative indices or an omitted stop
     actually require it; otherwise bound the scan by `stop`.
  2. `_set_slot_int`'s hash (`v * 2654435761ULL`, then `% cap` for a
     power-of-two `cap`) keeps only the hash's low bits, which are the
     weakest bits of a plain multiplicative hash - and this function's only
     real caller (`mojo_set_add_int` on the object-identity/type-tag
     registries like `_mojo_list_registry`) keys by heap pointer, which on
     this platform is 16-byte aligned, so every key collided on the same
     1-in-16 slots instead of spreading out. Fixed by folding the high bits
     down (`h ^= h >> 32`) before the modulo.
  Each fix produced a real, measured improvement (89GB-and-still-climbing
  with pegged CPU → a much slower, no-longer-exponential-looking linear
  climb after fix #1; fix #2 was verified correct and kept but didn't
  measurably change the trajectory for this specific case) - but the
  process still hadn't finished after several minutes and tens of GB even
  with both fixes applied.

  Got a real call-count profile (temporary counters in
  `runtime/mojo_runtime.c`, gated behind `MOJO_PROFILE=1` so they're zero-
  cost when unset - `_mojo_prof_tick`/`_mojo_prof` near the top of the file,
  currently still in place; strip once this is fully resolved) instead of
  further manual reasoning about the generated code, per the instruction
  above. Result: for mojo.py's ~900K-character source, `mojo_list_new`/
  `mojo_mark_as_tuple` reached **70+ million calls at 306 seconds and still
  climbing at a steady, non-decaying rate** (no plateau) - roughly **78x**
  the character count, not the small fixed multiple (~3-4x) you'd expect
  from `mojo.py`'s `--dump` handler independently calling `py_tokenize(src)`
  once each for `.tok` and `.ast` plus once more inside
  `compile_to_gimple_cached` for `.ci`. `mojo_dict_new` stayed flat at 49
  the entire time (ruling out a dict-related blowup). Fixed the one
  concretely-provable piece of that redundancy: `mojo.py`'s own `--dump`
  handler tokenized `src` twice, completely independently, for `.tok` and
  `.ast`; now tokenizes once and reuses the tokens for both (parsing still
  has its own try/except so a parse failure doesn't take `.tok` down with
  it). That's a real, worthwhile fix, but it only accounts for a 2x-ish
  slice of a ~78x (and still growing) problem - **the dominant remaining
  cause is still open**. `mojo_dict_new` staying flat at 49 for the whole
  run is actually a useful clue here: `replace_multiline_strings`'s own
  per-call `string_cache = {}` should contribute one dict creation per
  `py_tokenize` invocation, and 49 total dict creations across the *entire*
  self-hosted toolchain's execution (tokenizer + parser + ast_rewriter +
  gimple_codegen, all compiled and running) is far too small a number for
  `py_tokenize` to have been entered anywhere near 78 times - so the
  leading theory going into the next session is that `py_tokenize` is only
  called a handful of times (consistent with `.tok`/`.ast`/`.ci`), and the
  ~20x-per-call amplification is happening *inside* a single call's own
  loop - i.e. `replace_multiline_strings`'s outer `while i < n:` cursor is
  not making full forward progress every iteration in the *compiled* form,
  even though a manual trace of the Python source proves it always should
  (every branch sets `i` to a value `> `the old `i`, or exits) - a mismatch
  between the source's guaranteed semantics and the compiled behavior,
  same flavor of bug as the `c * 3` fix above.

  Attempted to confirm this directly by adding a temporary print of `i`
  every 100,000 loop iterations inside `replace_multiline_strings` (source
  instrumentation, not a runtime-level counter) - this immediately
  **segfaulted the self-hosted binary** rather than producing data (`make
  check`, including `check-selfhost`, was and is still green - this only
  broke when the instrumented source was itself compiled and *run* to
  process a real file, a gap `check-selfhost`'s compile+link-only guard
  doesn't cover). Reverted immediately rather than chase a second bug
  mid-investigation. This is itself a real, reproducible, previously-
  unknown self-host crash (adding a local variable + a
  string-concatenation-heavy `print()` inside this specific nested-closure
  function), worth a fresh investigation on its own, but out of scope for
  this session.

  **Follow-up (same day, continued investigation): used real profiling
  tools instead of more manual counters/reasoning**, per direct feedback
  that this class of bug "instantly lights up like a christmas tree" under
  a sampler. macOS's built-in `sample <pid> <seconds>` (no recompilation,
  no new crash risk, unlike the reverted Python-source instrumentation
  above) immediately confirmed the theory with hard numbers instead of
  inference: **~90% of ALL CPU time (3817/4254 samples) was inside
  `mojo_cstr_slice`**, specifically the closing-triple-quote scan's
  `while ... src[j:j+3] != quote3:` - materializing a heap-allocated
  3-byte string via malloc+memcpy on every character scanned, purely to
  immediately `strcmp` it away. Fixed properly: added
  `mojo_cstr_region_eq(s, start, stop, needle)` to `runtime/mojo_runtime.c`
  (bounded scan, no allocation, direct `memcmp`) and taught
  `gimple_codegen.py`'s `_lower_binary` to recognize the AST shape
  `<slice> == / != <string>` (either operand order, no step) and lower
  directly to it instead of the generic slice-then-compare path - a
  targeted fix, not a broad rewrite, verified correct against 5 edge
  cases (both operand orders, non-match, wrong-length, and an empty-slice
  edge case) and confirmed via a second profile: `cstr_slice` calls
  dropped from 400M+ to ~490K for the same run.

  **This did not fix the underlying hang** - it fixed the dominant *cost
  per iteration*, but a second `sample` run afterward showed
  `mojo_cstr_region_eq` still at ~67% of CPU time, simply because the
  *iteration count* itself is still the real bug: `mojo_mark_as_tuple`/
  `mojo_list_new` (one call per character in `replace_multiline_strings`'s
  OUTER loop, from the `if c in ('"', "'"):` check) had already reached 29
  million calls at ~112 seconds and was still climbing steadily, for a
  ~900K-character file - roughly 32x too many outer-loop iterations, not
  a cost-per-iteration problem. So the outer `while i < n:` loop is
  genuinely not making full forward progress every iteration in the
  *compiled* form (confirmed a manual trace of the Python source proves it
  always should - every branch sets `i` to a value provably `> `the old
  `i`, or exits the loop).

  **ROOT CAUSE FOUND (2026-07-17, later the same day): it is not a loop-
  lowering bug and not a 32x slowdown - it is a true infinite loop caused
  by a silently dropped call argument.** `gimple_codegen.py`'s `find`
  lowering (~line 7369) consumes only `arg_vals[0]`, so
  `j = src.find('\n', i)` (mojo_compiler.py:766, the comment-skip branch)
  compiles to `mojo_str_find(src, "\n")` - a search from position 0. Every
  `#` encountered after the file's first newline therefore jumps the cursor
  BACK to that first newline (mojo.py's line 1 is the shebang, so position
  22), and the scanner cycles forever between position 22 and the first
  `#` comment in the code. (The earlier "~900K characters / ~32x" framing
  was wrong on both counts - mojo.py is 25,125 bytes and the iteration
  count is unbounded, not a fixed multiple.) Verified three independent
  ways: the call visibly missing its third argument in the generated
  `.ci`; a minimal repro (`s.find("\n", 4)` compiles to the 2-arg call,
  answering 2 where Python answers 5); and a simulation of the buggy
  semantics against the real mojo.py that never passed position 802 in
  5,000,000 iterations, resetting the cursor to position 22 exactly
  42,017 times. **FIXED same day** per the spec in
  `bugs/CODEGEN_str_find_start_arg_dropped.md`: `mojo_str_find_from`
  runtime helper (CPython find semantics), 2-arg `find` lowering in
  `gimple_codegen.py`, signature-table entry, and a `test_gimple.py`
  regression case locking both forms. Independently verified: `make check`
  160/17/58/1 green, and the previously-infinite
  `stage2/mojo --dump ../mojo.py` completes in ~5s (peak RSS ~38MB vs the
  pre-fix 89GB), producing `.tok`/`.ast`/`.pyi` and the full 12MB
  transitive-closure `.ci`. The temporary `MOJO_PROFILE` counters were
  stripped from `runtime/mojo_runtime.c` as planned. The interim fixes
  from this investigation (`c * 3` repetition, `mojo_cstr_slice` strlen
  bound, `_set_slot_int` hash mixing, `mojo_cstr_region_eq`, the
  `.tok`/`.ast` tokenize-once dedup) all stay.

  **Follow-up (2026-07-17, resumed later the same day): that SIGSEGV is
  root-caused and FIXED.** `_alloc_{sn}` (`gimple_codegen.py` ~line 16277,
  every self-hosted struct's constructor) did a raw `malloc` and set only
  `__mojo_type_id`, leaving every other field as uninitialized garbage.
  `_lower_MemberExpr` checks `struct_field_types` (real instance fields)
  *before* `_class_attrs` (class-level globals) - so once a name is in
  both (needed for `_CONV_KWS`/`_known_traits`/etc. to get the right C
  type at all, per the hardcoded self-host table above), `self.X` reads
  the never-initialized instance field instead of the correctly-populated
  class-level global. `_CONV_KWS = {'ref', 'out', 'mut', ...}` (a class
  attribute, never assigned inside `__init__` - Python's own attribute
  fallback to the class dict is exactly why the source never needs to)
  therefore dereferenced garbage as a `MojoSet *` the first time a
  self-hosted `Parser` actually hit the `ref`/`out`/`mut` soft-keyword
  path while parsing `mojo_compiler.py`. Confirmed via `lldb` (`_set_slot_str`
  null-ish deref inside `mojo_set_contains_str`, called from
  `Parser__parse_primary`) and by tracing the generated `.ci`'s
  `_mojo_classattr_init()` (correctly populates the class-level global) vs.
  `_alloc_Parser()` (never copies it into the instance). Fix: seed the
  instance field from the class-level global inside `_alloc_{sn}` itself,
  for every name present in both `_class_attrs[sn]` and
  `struct_field_types[sn]` *with matching declared types* (the type-match
  guard matters: `LayoutSolver.STACK`/`HEAP` hit the same
  `_class_attrs`/`struct_field_types` overlap but with an unrelated,
  pre-existing wrong-type gap in `struct_field_types` that was harmless
  until this fix tried to write into it - skipped, no worse off than
  before). This mirrors real Python semantics (a fresh instance's
  attribute starts as the class value until something assigns over it) and
  composes correctly with any later per-instance `self.X = ...`. Verified:
  `make check` green, and both `mojo_compiler.py` and `myinterpreter.py`
  now dump cleanly under stage2 (previously SIGSEGV, exit 139). Full
  `make bootstrap` (stage1+2+3+verify) now reaches the verify step and
  passes **150/152** checks - every `.mojo` test file and every core `.py`
  file (`mojo_compiler`, `myinterpreter`, `module_loader`, `mojo_main`,
  `generated_dispatch`) matches byte-for-byte across all three stages.

  **The last 2/152: `mojo.tok`/`mojo.ast` still diverge (stage1 vs stage2
  only)**, root-caused to the exact same `'in' for char*'` gap flagged
  above, at a second call site: `replace_multiline_strings`'s own prefix-
  detection loop (`while k > 0 and src[k-1] in 'fFrRbBuUtT' and letters < 2`,
  `mojo_compiler.py` ~line 776) still uses the vulnerable pattern - unlike
  `Parser._strip_string_prefix_and_quotes`, which was already rewritten
  with explicit `==` comparisons specifically because of this bug (see its
  docstring). Symptom: an f-string at mojo.py's own line 174
  (`f"""def _repl_expr(): ..."""`) never has its `f` prefix recognized, so
  the placeholder ends up glued onto the leftover `f` as one run-on NAME
  token (`f__MOJO_STR_5__`) instead of a real STRING token - confirmed via
  a byte-level diff of stage1 vs stage2's `mojo.tok`.

  **Two fix attempts made and reverted, both reproducing the historically-
  documented regression** (see the `_lower_in_impl` comment): rewriting the
  loop with explicit `==` comparisons (mirroring
  `_strip_string_prefix_and_quotes`'s already-proven-safe pattern exactly)
  made the full `--dump ../mojo.py` SIGSEGV instead of just mistokenizing -
  confirmed via `lldb`: `mojo_cstr_cmp` crashes on a null-ish pointer
  inside `py_tokenize_replace_multiline_strings`, traced to the generated
  `.ci` for the new `_pc == 'f'`-style comparisons - each one lowers to
  `mojo_char_to_str(_pc)` + `mojo_cstr_cmp(...)` (a **string** comparison,
  not a direct scalar `char` equality check), and the right-hand operand is
  wrong/missing at that specific call site. A second attempt renamed every
  new local (`_pc`/`_is_prefix_char` → `_rmls_pc`/`_rmls_is_prefix_char`) to
  rule out a cross-function name collision with
  `_strip_string_prefix_and_quotes`'s identically-named locals - same
  crash, same offset, ruling that theory out.

  **Follow-up (resumed again the same day): went one level deeper with
  `lldb` register inspection** (`frame select 0` +
  `register read x0 x1` at the `strcmp` crash frame) instead of more
  static reasoning about the generated `.ci`. Result superseded the
  "closure-scoping" theory: `x0 = 0x28` - a small integer, not a null or
  wild *pointer* in the usual sense - while `x1` pointed at valid-looking
  memory containing the bytes `"'_'"` (quote, underscore, quote). Tracing
  the static `.ci` in isolation had shown a *plausible-looking*,
  correctly-wired call (`_t36 = mojo_char_to_str(_rmls_pc)`, compared
  against `_slit_10171 = "f"`, a real, correctly-initialized static
  global) - so the static picture and the live register picture disagree
  with each other. That mismatch, plus `x1`'s content looking like it
  belongs to a *different* comparison entirely (`prev == '_'`, a few lines
  further down in the same source function, not the `'f'` prefix check),
  points at a temp-variable (SSA slot) reuse/aliasing bug specific to this
  one large, already-complex function once a new local is added to it -
  not a fundamental problem with char-literal comparisons or closures in
  general (plenty of both already work correctly elsewhere in this exact
  file). Root cause still not pinned down further; would need the
  generated `.ci` for the *exact* binary that crashed cross-referenced
  against `lldb`'s disassembly address-by-address (harder than it sounds
  without proper debug info surviving `-fgimple`'s `-Og` build - see the
  "`debug map object file ... does not exist`" `frame variable` failures
  in both attempts) to confirm which temp got aliased and why.

  Both attempts were cleanly reverted; `mojo_compiler.py` is unchanged
  from before this investigation. 150/152 with a known, narrow,
  well-isolated, now reasonably-well-characterized failure mode is a
  sensible place to pause - two independent fix attempts (different
  implementations, different variable names) both triggered a crash
  keyed to this exact function's size/complexity rather than to any
  single line changed, which is a real signal to be more cautious here,
  not less, before a third attempt.

- **`compile_to_gimple`/`compile_to_gimple_cached` are not recursively
  self-hosted — every call to them from already-compiled code shells out to
  a `python3` subprocess instead of calling the compiled body natively.**
  Confirmed 2026-07-17 while debugging a stage2-bootstrap segfault.
  `gimple_codegen.py`'s call-lowering (~line 6314, the
  `module_name == 'gimple_codegen' and method_name in ('compile_to_gimple',
  'compile_to_gimple_cached')` branch) unconditionally lowers such calls to
  the `gimple_codegen_compile_to_gimple` runtime shim
  (`runtime/mojo_runtime.c` ~line 2007), which writes the source to a temp
  file and runs `python3 -c "import gimple_codegen; ..."` via `popen()`,
  with the comment "caching is a Python-process concern; the self-hosted
  binary's subprocess fallback just compiles (same output, uncached)."
  Bootstrap (`make bootstrap`) proves the compiler can compile *itself
  once, top-to-bottom* — that's real self-hosting for that one operation —
  but it never exercises a compiled program *recursively* invoking its own
  compiler mid-execution (e.g. `module_loader.py` compiling an on-demand
  import, or a JIT path), so that capability was never actually finished;
  this shim is the acknowledged stand-in. Consequences: (1) fragile —
  the shim's popen/buffer-growing read loop is a real crash surface (see
  the stage2 segfault investigation this same session), and a `python3`
  install is a hard runtime dependency for any compiled program that hits
  this path, not just a build-time one; (2) `compile_to_gimple_cached`'s
  whole point (the module cache in `cas.py`) is silently discarded on this
  path — every recursive compile through the shim is uncached, even though
  the surrounding Python-level infrastructure has a perfectly good cache.
  A real fix means making `compile_to_gimple` safely re-entrant when called
  from within already-compiled code: the self-hosted body needs to (a) not
  rely on any Python-only global/module state that a nested invocation
  would stomp on, (b) reach the module cache (`cas.py`'s
  `module_key`/`get_or_build_text`) natively instead of losing caching
  entirely, and (c) actually get called instead of being special-cased to
  the shim in `gimple_codegen.py`'s call-lowering. Likely needs its own
  bootstrap-style verification (recursive self-compile, not just the
  current single top-level self-compile) before trusting it in place of
  the subprocess fallback.
- **`@` matmul defaults its result type to `int64_t`** when `__matmul__`'s
  return type is unknown (`_lower_matmul`, `gimple_codegen.py` ~line 5323).
- **Typed `except` dispatch is impossible** — the runtime carries no
  exception-type tag (`mojo_exc_obj` is an untyped `void *`), so only the
  first `except` handler is ever emitted (with a compile-time warning:
  "multiple except handlers are not supported"). Needs a type tag in the
  runtime exception slot: (1) add `_mojo_exc_type` to exception state, (2)
  `mojo_raise(type_tag)` stores it, (3) codegen passes the type when
  raising and checks it in handlers. See `runtime/mojo_runtime.c` (near the
  exception stack) and `gimple_codegen.py`'s except-handler dispatch.
- **`for a, b in ...` tuple for-targets emit invalid C** — `BUGS-AST.md`
  BUG-013, still listed there as outstanding. The for-loop target isn't
  validated as a plain identifier before being spliced into the generated
  C loop variable name.
- **Struct reflection field *lists* can still cross-contaminate between two
  modules' same-named classes, even after the field-merge collision fix
  below** — `mojo_compiler.py`'s `ExprStmt.value: object` (and similar
  generically-typed AST fields: `VarDecl.value`, `ReturnStmt.value`, etc.)
  resolve to a plain `int64_t` in `struct_field_types`, indistinguishable
  from a genuine int field (same root ambiguity as the `.ast`
  `repr()`/`None` note in `IMPL.md`'s reflection section — Python's dynamic
  `object` typing has no equivalent in this erased-to-C64 representation).
  Not module-collision-related; a real, currently-accepted limitation of
  field-by-field `repr()`.
- ~~Struct reflection keyed by bare struct name collided across modules
  defining a same-named class~~ **fixed 2026-07-07** — see `IMPL.md`,
  "Struct reflection no longer collides across same-named classes in
  different modules".
- **`re.search()`/`re.match()` (and `.group()`/`.start()`/`.end()` on their
  result) have zero real implementation as expressions** — confirmed
  2026-07-06 investigating `monomorphize.py`. `re`/a compiled pattern is
  typed as a plain scalar (`int64_t`) at the call site, so `re.search(pat,
  s)` falls through to `_lower_method_call`'s generic "unknown method on a
  scalar receiver" fallback (~line 5941, `gimple_codegen.py`): it silently
  returns the *receiver's own value* unchanged, annotated
  `/* {ot}.{method}() stubbed */`. Concretely, `m = re.search(pat, s)`
  compiles to `m = re;` (the `re`-module marker, always non-null), so
  `if m:` is *always true* regardless of whether a match occurred, and
  `m.group(1)` similarly returns garbage (the same non-null marker,
  reinterpreted as `char *` — a wild pointer, not the captured text).
  This is a **silent miscompile**, not a crash — worse than the
  `re.sub()` bug below in that GCC's `-fsyntax-only` check (what
  `compile_stdlib.py` validates) can't catch it, since the generated C is
  syntactically fine. It *is* diagnosable today via `MOJO_DEBUG=1` (uses
  the existing `_stub_result`/`_debug_note` mechanism — see
  `monomorphize.py`'s own `compile_fn`, whose `m = re.search(...)` /
  `name = m.group(1)` is exactly this). Real fix needs `re.search()`/
  `.match()` to return a genuine Match-or-None representation (probably a
  side-table keyed the same way `.finditer()`'s per-iteration match vars
  are, but for a single expression rather than a for-loop) — a real,
  standalone feature, not a quick patch.
- **`re.sub(pattern, repl, src)` where `repl` is a plain replacement
  *string* (not a callback) crashed with `SIGILL`** — fixed 2026-07-06,
  see `IMPL.md`. Confirmed via `monomorphize.py`'s own
  `safe_suffix`/`monomorphize_source`, both of which use exactly this form
  (`re.sub(r'[^A-Za-z0-9_]', '_', s)`, `re.sub(rf'\b{re.escape(tp)}\b',
  str(concrete), src)`). Pre-existing bug (not introduced by this
  session's regex-engine work — the callback-resolution logic was only
  extracted into a shared helper, not changed), just newly exposed because
  `safe_suffix`'s pattern is compile-time-foldable and so now actually
  reaches the real engine instead of silently no-opping via the old
  POSIX-regcomp fallback.
- **`elaborate.py`'s own `re.sub(..., f'fn {mangled}', src, count=1)`**
  would hit the same `repl`-is-a-string shape (now fixed) **but the file
  doesn't currently parse through this compiler at all** (`SyntaxError:
  Unexpected INDENT`, an unrelated, pre-existing front-end gap) — so this
  specific call site is unreachable/moot until that's fixed separately.
  Also note: `count=1` (limit to first replacement) isn't honored by
  either `re.sub()` backend — always replaces every match. Not yet known
  to matter for any *reachable* call site.
- **`consolidate_string_pool.py`'s `re.sub()` calls** use the same
  string-replacement form (now fixed) but the file isn't imported by
  anything and isn't part of the self-hosted closure — a standalone dev
  script, always run interpreted. Not a live risk.

## Known feature gaps (regex)

- **`re.findall()`/`re.split()` have no codegen lowering at all** — only
  `.finditer()` and `.sub()` (with a compile-time-foldable pattern) are
  implemented (see `IMPL.md`'s regex-engine section). `.match()`/`.search()`
  don't even have a stub type in `_quick_type` that matches their real
  shape (returns a dummy `int`) — see the confirmed silent-miscompile bug
  above for what actually happens at the real lowering site.
- **`re` module flags are stubbed constants, not honored.**
  `ast_rewriter.py`'s `re_multiline`/`re_dotall`/`re_ignorecase`/`re_verbose`
  rules give `re.MULTILINE` etc. their real CPython integer values so
  evaluating the constant doesn't crash, but neither regex backend
  (`mojo_re_sub_fn`'s POSIX `regcomp`, or the new compile-time engine in
  `regex_compile.py`/`mojo_regex_search`) actually consumes a flags
  argument. `re.compile(pattern, re.MULTILINE)` compiles and runs, but the
  flag has no effect. Real fix: for the POSIX path, translate the flags int
  into `regcomp`'s `REG_ICASE` etc. (`MULTILINE`/`VERBOSE` have no direct
  POSIX ERE equivalent and would need pattern preprocessing); for the new
  engine, it could honor flags directly at compile time (e.g. case-fold
  character ranges for `IGNORECASE`), which is more tractable now that a
  real compile-time-known-pattern engine exists.
- **Lookahead/lookbehind assertions (`(?=...)`, `(?!...)`, etc.) are
  unsupported** by the new regex engine (`regex_compile.py`) — found via
  `gimple_codegen.py`'s own `\b(inout|borrowed|...)\s+(?=\w)` pattern
  during the `re.sub()` fix. Falls back to the POSIX backend gracefully
  (no crash), but POSIX ERE doesn't support lookahead either, so such a
  pattern silently no-ops via `re.sub`'s "compile failed, return input
  unchanged" behavior either way.

## Deferred generalizations (2026-07-04, still open)

Found while building `ast_rewriter.py` (an AST-to-AST rewrite pass giving
"Python idiom → concrete runtime call" mappings a real rule table instead of
inline `elif` chains). `ast_rewriter.py` is itself part of the self-hosted
closure, so it had to stay inside the currently self-hostable Python subset —
that ruled out three genuinely useful features, each real standalone compiler
work:

- **Real `type()`/RTTI.** `mojo_type()` and `mojo_obj_getattr` are stubs
  because there is no runtime type tag on boxed values. Fixing this for
  real needs a tagged-union object representation (type tag + int64_t
  backing) — same root need as the typed-`except`-dispatch bug above.
  Highest payoff of the three: fixes every future generic/dynamic-idiom
  gap, not just this one. `ast_rewriter.py` works around it today with a
  literal `isinstance` chain (`_node_type_name`) instead of
  `type(x).__name__`.
- **Generators (`yield`).** No coroutine/iterator-state-machine codegen
  exists; a generator function can't currently be self-hosted at all.
  `ast_rewriter.py` avoids this by returning lists instead of yielding.
- **Tuple-keyed dicts.** `MojoDict` is string-keyed only; there's no
  composite-key hashing. `ast_rewriter.py`'s discrimination trie encodes
  what would naturally be a `(path, kind, value)` tuple key as a single
  string key (`_edge_key`) instead.

## Struct method type safety (deferred)

Unknown struct methods get a variadic `int64_t f(...);` extern
(`_lower_struct_method_call`) — defeats type checking and forces int64
returns for anything not already known. Concrete (non-variadic) signatures
for common built-ins (`iter`, `next`, `swap`, `divmod`, `ord`, `chr`, `sort`)
were tried and reverted (broke 13 files in `compile_stdlib.py` against the
real modular stdlib, since real callers pass pointer types too — a hard
`-Wint-conversion` error on GCC 14+, not a warning). Full type safety here
needs the same tagged-union type system (type tag + int64_t backing) called
for above.

## Structure / maintainability (behavior-preserving refactors)

Pure tech debt — no known bug, just size/organization:

- `gen_module` is ~2,200 lines with ten numbered "Phase" sections —
  decompose along those comments into `_gen_module_phase*` methods.
- `_lower_method_call` (~430 lines), `_lower_binary` (~350),
  `_gen_stmt_AssignStmt` (~230), `_emit_call` (~220) similarly.
- `_KNOWN_SIGS` and the hardcoded interpreter/AST struct-field tables in
  `gen_module` belong in `gimple_spec_gen.py` (created for that purpose).
- Three parallel type dicts (`_actual_types`, `_global_c_decl_types`,
  `_global_var_types`) must stay manually synchronized
  (`POINTER_TYPE_AUDIT.md`) — unify into one `TypeInfo` table.
- Other modules import private helpers (`_mojo_type`, `_safe_name`,
  `_c_escape`, `_TYPE_MAP`) — promote to a documented public surface.
- The regex-detection/pattern-folding logic embedded in `gimple_codegen.py`
  (`_try_const_fold_str`, the `re.sub`/`.finditer()` branches in
  `_lower_call`, the Phase 1.7 `_regex_patterns` module-level scan) is a
  good candidate to move into `ast_rewriter.py`'s declarative rule table —
  but only the *detection* side moves cleanly; the actual C emission
  (compile-time array generation, custom for-loop control flow, per-match
  accessors) is inherently codegen work and can't be expressed as a pure
  AST-to-AST rewrite. Worth doing once the regex feature gaps above are
  closed, not before (no point relocating logic that's still being
  actively extended). See conversation 2026-07-06 for the full analysis.

## Tooling notes for future refactor work

- **Snapshot harness**: `test_gimple.py`'s 157 sources can be snapshotted
  without gcc in ~0.1s by monkeypatching `test_gimple.test` to dump
  `compile_to_gimple(src)` to a directory; `diff -rq` the dirs before/after.
  Behavior-preserving commits must be byte-identical; deliberate fixes get
  reviewed hunk-by-hunk. Use this for any of the structure refactors above.
- **A stale `build/libmojostdlib.dylib` causes**
  `dyld: symbol not found '_MojoList__write_to'` (or similar) when running
  compiled binaries — rebuild with `build_stdlib_dylib.py` after any
  codegen or runtime.c change (see `CLAUDE.md`'s quality-gates section).
