# CODEGEN: `str.find(needle, start)` silently drops the `start` argument → stage2 bootstrap infinite loop

Status: **FIXED and verified** (2026-07-17, same day — implemented per the spec below; independently
re-verified: `make check` 160/17/58/1 green, and the previously-infinite
`stage2/mojo --dump ../mojo.py` now completes in ~5s producing all four
artifacts including the 12MB transitive-closure `.ci`. `make bootstrap`
progresses much further but still fails on a separate, pre-existing SIGSEGV
when stage2 dumps `mojo_compiler.py`/`myinterpreter.py` — tracked in
doc/PLAN.md, not this bug.)
Found: 2026-07-17, closing out the stage2-bootstrap performance investigation (doc/PLAN.md)
Severity: blocker — this was the actual root cause of the stage2 `--dump` "hang" / unbounded-memory blowup

## One-line summary

`gimple_codegen.py`'s lowering of the string method `find` consumes only the
needle argument, so `s.find(needle, start)` compiles to `mojo_str_find(s, needle)`
— a search from position 0. In `mojo_compiler.py:766`'s comment-skip branch
(`j = src.find('\n', i)`), this turns "advance to end of current line" into
"jump back to the FIRST newline in the file", making the tokenizer's outer
scan loop cycle forever between the file's first newline and the first
subsequent `#` character.

## Evidence chain (all measured, none guessed)

1. **Sampling profile** (`sample <pid>`) of `stage2/mojo --dump ../mojo.py`
   showed 100% of time in `py_tokenize_replace_multiline_strings`, with the
   `MOJO_PROFILE=1` counters showing one tuple/list allocation per outer-loop
   iteration climbing past 29M at a perfectly steady rate, never finishing.
   (Earlier fixes — `c * 3` string-repetition, `mojo_cstr_slice` O(n) strlen,
   `mojo_cstr_region_eq` — were all real and are all kept, but they reduced
   cost-per-iteration; the iteration count itself stayed unbounded.)

2. **Generated code** (stage1/mojo.ci, `py_tokenize_replace_multiline_strings`,
   the `bb_6` comment branch, `#line 766`):

   ```
   _t15 = _slit_10028;                 /* "\n"            */
   _t16 = mojo_str_find (src, _t15);   /* NO third argument */
   j = _t16;
   ```

   Source line being compiled (`mojo_compiler.py:766`): `j = src.find('\n', i)` —
   the `, i` is gone.

3. **Minimal repro**: a .mojo file with `s = "ab\ncd\nef"; j = s.find("\n", 4)`
   compiles to a 2-arg `mojo_str_find (s, _t3)` call. Python answer: 5.
   Compiled answer: 2 (first newline).

4. **Simulation** (Python re-implementation of `replace_multiline_strings`
   with the buggy find-from-0 semantics substituted, run against the real
   mojo.py): mojo.py's line 1 is the shebang `#!/usr/bin/env python3`, so the
   file's first newline is at position 22. After **5,000,000 iterations** the
   cursor had never passed position 802 of 25,125 bytes, having reset to
   position 22 **42,017 times**. Cycle: scan forward from 22, hit the first
   `#` comment in the code (~position 800), `j = src.find('\n')` → 22, jump
   back, repeat forever. Each cycle re-allocates tuples/placeholder strings,
   which is the unbounded memory growth.

   This also explains why the synthetic 2000-docstring stress file completed
   fine (it contained no `#` after its first newline) while any real source
   file with a comment loops forever, and why the Python-interpreted stage1
   is unaffected (CPython's `str.find` honors `start`).

## Root cause location

`gimple_codegen.py:7369-7371`:

```python
if method == 'find' and arg_vals:
    sep_type = arg_pairs[0][0] if arg_pairs else 'char *'
    return 'int64_t', self._call_expr('int64_t', 'mojo_str_find', [('char *', cstr_ov), (sep_type, arg_vals[0])])
```

Only `arg_vals[0]` is ever consumed. The runtime function itself
(`runtime/mojo_runtime.c:822`, declared `mojo_runtime.h:156`) only takes
`(char *s, char *needle)` — there is no start-aware variant to call.

## Fix specification

1. **`runtime/mojo_runtime.c`**: add

   ```c
   int64_t mojo_str_find_from(char *s, char *needle, int64_t start)
   ```

   with Python semantics: `start < 0` → `start += strlen(s)`, clamp to 0;
   `start > len` → return -1; otherwise `strstr(s + start, needle)`, and on a
   hit return the **absolute** index (`hit - s`), else -1. Match CPython's
   empty-needle edge case: `"ab".find("", 2) == 2` but `"ab".find("", 3) == -1`
   (empty needle at `start <= len` returns `start`).

2. **`runtime/mojo_runtime.h`**: declare it next to `mojo_str_find` (line ~156).

3. **`gimple_codegen.py`**: add
   `'mojo_str_find_from': ('int64_t', ['char *', 'char *', 'int64_t'])`
   to the known-signature table at ~line 3194 (next to the existing
   `'mojo_str_find'` entry), plus any other table `mojo_str_find` already
   appears in (grep — as of this writing 3194 is the only table entry).

4. **`gimple_codegen.py` `method == 'find'` lowering (~7369)**: when
   `len(arg_vals) >= 2`, coerce the second argument to `int64_t` (same
   `self._to_int64(...)` pattern used by `_lower_slice` for slice bounds) and
   call `mojo_str_find_from` instead. The 1-arg path stays exactly as-is.
   Keep the existing `sep_type` handling for the needle unchanged (including
   the `'char'`-typed needle case, whatever it currently does — do not expand
   scope there).

## Test plan

- **Unit**: `s = "ab\ncd\nef"; s.find("\n", 4)` must compile to a
  `mojo_str_find_from` call and, when the generated `.ci` is compiled with
  gcc and run, print 5. (Note: `mojo.py build`'s full-binary path currently
  trips over an unrelated stdlib-dylib symbol (`_CUDA_0c85c9`); compile the
  dumped `.ci` directly against `runtime/mojo_runtime.c` the way
  `/tmp/slice_eq_direct` was verified in the region_eq commit.)
  Also cover: no-match-after-start returns -1; `start` past end returns -1;
  1-arg `find` unchanged.
- **`make check`** — all four sub-targets stay green (`test_gimple.py`'s 159,
  runner, modcache, selfhost). Consider adding a `find`-with-start case to
  `test_gimple.py` so this can't regress silently.
- **The real test**: rebuild `stage1/mojo.ci` + `stage2/mojo` and run
  `cd stage2 && MOJO_HOME=.. PYTHONPATH=.. ./mojo --dump ../mojo.py`. Before
  the fix this loops forever with unbounded RSS. After the fix it must
  terminate (mojo.py is 25KB; with the already-landed cost-per-iteration
  fixes there is no remaining reason for it to take more than seconds).
  Then attempt full `make bootstrap` (stage2 over all files, stage3
  idempotency) — this bug was the blocker documented in doc/PLAN.md.

## Related observations (separate, do NOT fold into this fix)

- The **interpreter** path returns 6 (not 5) for the repro above — its string
  literals appear to carry `\n` as two characters (escape not decoded) in
  this context. Different bug, different subsystem (`myinterpreter.py` /
  tokenizer escape handling); file separately if confirmed.
- This is the third "argument silently dropped" bug in this codebase's
  history (kwargs dropped in `eval_CallExpr`, `do_imports`/`filename` kwargs
  dropped in the `compile_to_gimple` shim lowering, now `find`'s `start`).
  Systemic recommendation: every method-lowering branch in `gimple_codegen.py`
  that consumes a fixed number of `arg_vals` should assert/warn when called
  with more arguments than it consumes — that turns this whole bug class
  into a loud compile-time diagnostic instead of a silent miscompile.
  `startswith`/`endswith`/`count` lowerings have the same shape today (no
  live multi-arg call sites in the self-hosted closure at the moment, but
  the same latent trap).
