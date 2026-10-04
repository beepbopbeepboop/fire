# CODEGEN_bootstrap_stage2_dump_is_empty: the self-hosted binary exits 0 and writes no dump

## Status (2026-10-04, work/gatefix9 — the `TypeError` is FIXED and was never
## in `gen_module_impl`: it was `id()`, and what is left is a SIGSEGV)

**Still open, and still the right owner of this class. The `TypeError` class
below is closed — its own entry, further down, says where it actually was,
because the localisation in the gatefix8 entry above it ("`gen_module_impl`'s
prologue, input-independent") was WRONG and cost most of a session to
overturn.**

Measured on `work/gatefix9`, same command as the entry below:

    $ python3 tools/suite.py bootstrap-stage2-dumps --no-cache
    suite: 4 passed, 1 failed, 0 skipped  (5 tests, 95 jobs, 229.7 s)

| | gatefix8 | gatefix9 |
|---|---|---|
| items failing | 45 of 46 | **40 of 46** |
| `TypeError: unhashable type: 'list'` | 20 inputs | **gone** (`mojo_id`) |
| `Unexpected SEMICOLON(';')` at `fire_compiler.py:1301:38` | 2 inputs | 2 inputs (unchanged) |
| silent SIGSEGV / SIGBUS, no output at all | (not counted separately) | **38 items** |
| passing | `mojo_failures.mojo` | 6 inputs (`.mojo` and `.py` alike) |

TWO of the SIGSEGVs are closed, one per fix, and each was found by the same
four-command `lldb` recipe at the top of this file rather than by reading the
compiled-path source:

* **`mojo_id` (item 0 in "What was fixed")** — 45 to 43.
* **a struct type tag read was never validated** — 43 to 40.
  `mojo_read_type_tag`/`_safe` read eight bytes at an address and returned
  them unvalidated. A heap string passes every check those readers make (it is
  8-aligned and `malloc_size` is at least 8), so `type(node)` over a plain
  `str` field of an AST node returned the eight bytes of the STRING — for
  `hello.mojo` that is `"print"`, i.e. the integer `0x746e697270`, which is
  inside `[2^31, 2^47)` and therefore accepted by every pointer predicate in
  the runtime. `_WALK_DATACLASS_CACHE.get(type(node))` then classified that
  integer as a boxed string and handed it to `strcmp`: a SIGSEGV on an address
  that was never mapped. A tag is 31 bits by construction
  (`_struct_type_id` is `h * 31 + c & 2147483647`), and the codegen already
  returns a literal 0 for a `char *`/container receiver for exactly this
  reason (`emit_exprs.py`'s `__class__` arm) — so the check is that same rule
  applied where the receiver is boxed and the codegen cannot see it. Both
  readers now share one `_mojo_tag_at`.

**What the remaining 38 have in common, as far as it is measured:** they are
crashes, not diagnostics, so the census needs one crash at a time and the
`lldb` recipe is the instrument. The next two measured, both AFTER the two
fixes above, so both are still open:

1. `mojo_dict_order_indices` dereferencing `0x4d4a424f58310001` — that is
   `MOJO_BOX_MAGIC`, a `MojoBox`'s first field, so a box's CONTENTS reached a
   caller as the box. Reached from `gen_module_impl` →
   `infer_return_elem_type` → `_scratch_vt.update(_as_dict(_base_var_types))`
   (`mojo/middle/resolve_shared.py:1141`), i.e. the SECOND argument of
   `mojo_dict_update` is the magic, not a dict. Same family as
   `bugs/RUNTIME_int64_key_above_2gb_dereferenced_as_pointer.md`'s "a value
   read out of a heterogeneous container" case: something hands a struct's
   first word to a consumer that expected the pointer.
2. the `SEMICOLON` refusal, which is a PARSER bug and not a crash — see "the
   second, independent class" in the gatefix8 entry below.

So the remaining class is a CRASH, not a diagnostic, and it is now the whole of
what is left: 41 of the 46 inputs take the binary down with no message, and
the two `.py` closure inputs are the `SEMICOLON` refusal. `bootstrap-stage2-dumps`
carries a count-checked `expect=` marker again (43 of 46), and the count is
checked against the per-item verdicts — see the 2026-10-04 entry in
`tools/suite.py`'s marker history for why that job is red again after a day of
carrying no marker at all.

### How the `TypeError` was located (the instrument, for the next person)

The entry below sends you to a C main linked against `stage1/fire.ci`. The
cheaper half of that is **lldb on `stage2/mojo` itself**, and it is four
commands:

    $ cd stage2
    $ lldb -b -o 'breakpoint set -n mojo_dict_key_for' -o run -o 'bt 6' -o quit \
          -- ./mojo --dump ../.tmp/one.mojo
    frame #0: mojo`mojo_dict_key_for
    frame #1: mojo`_kw_kind
    frame #2: mojo`mojo_dict_set_str_kw        <- or mojo_dict_contains_kw
    frame #3: mojo`_mojo_middle_types_toplevel  <- the first hit, NOT the crash
    frame #4: mojo`main

Two things about that, both of which cost time here:

* **The FIRST hit is not the crash.** `mojo_dict_key_for` is called for every
  container dict key, and the first one — `_MODULE_ATTR_CTYPES`'s
  `('os', 'environ')` tuple key, which is a legitimate tuple — is fine. The
  crash is the SECOND hit. `continue` once and read the backtrace again.
* **The `TypeError` was never in `gen_module_impl`.** `mojo_dict_key_for`
  raises `unhashable type: 'list'` for a list used as a dict key, and the key
  the compiled path handed it was a live list HANDLE. Reading the list's slots
  out of the debugger is what named it: patch `mojo_dict_key_for` in a COPY of
  `runtime/fire_runtime.c` to print the list it was given (its length and its
  slots), relink `stage1/fire.ci` against the copy (25 s, one `gcc -fgimple`
  command — see the entry below for the exact argv), and the answer is one
  line. What it showed was a ONE-element list holding pointer bytes, used as
  the key of `if id(body) in cache` in `mojo/middle/lambdareduce.py`.

`id()` was the defect; see "What was fixed" below for the fourth item. The
whole `TypeError` class was ONE line of generated code (`static int64_t id
(int64_t x) { return x; }`) that no amount of reading `gen_module_impl` would
have found.

## Status (2026-10-04, work/gatefix8 — the class is much narrower: THREE root
## causes found and fixed, `.tok`/`.ast` are now byte-identical, and what is
## left is a `TypeError` inside the compiled `gen_module`)

**Still open, and still the right owner of this class — but its "new signature"
section below is now WRONG about where the defect is, and this entry says so
rather than leaving the old reading in place.**

Measured on `work/gatefix8` after three fixes (see "What was fixed" for the
commits and the per-fix evidence):

    $ python3 tools/suite.py bootstrap --no-cache
    suite: 4 passed, 1 failed, 5 skipped  (10 tests, 145 jobs, 208 s)

`bootstrap-stage2-dumps` still fails, but **45 of its 46 inputs now get a real
tokenizer and a real parser** instead of the old two-way split (25 refused with
`unterminated string literal`, 21 silently emitting a 2-token stream):

| artifact | stage1 | stage2 BEFORE | stage2 AFTER |
|---|---|---|---|
| `.tok` | correct | 42 bytes / absent | **byte-identical** (`diff` clean on every input measured) |
| `.ast` | correct | 2 bytes / absent | **byte-identical** (`diff` clean on `t1.mojo`, the 45-file corpus agrees on `.tok`) |
| `.ci` | 20-48 KB | a fixed ~33 KB skeleton | **still absent** — `compile_to_gimple` raises |

and the failure has MOVED and changed shape: the 25 `unterminated string
literal` refusals and the 21 empty-token files are gone, and what remains is

    compile_to_gimple failed: TypeError: unhashable type: 'list'      (20 inputs)
    Warning: Could not generate .ast: ../fire_compiler.py:1301:38: Unexpected SEMICOLON(';')   (2 inputs)

So the "C/token/AST writers do not" reading below is superseded: the writers are
fine and the COMPILED CODEGEN raises before it emits anything. That is a
different bug in a different layer, and this doc now owns the census rather
than a guess.

### What is left, and how to see it (measured, one command)

    $ rm -rf stage1 stage2 stage3
    $ python3 tools/suite.py bootstrap --no-cache        # ~210 s wall, peak 1.9 GB
    $ cd stage2 && printf 'x = 1\n' > /tmp/one.mojo && ./mojo --dump /tmp/one.mojo
    compile_to_gimple failed: TypeError: unhashable type: 'list'

`x = 1` is the whole reproduction: the `TypeError` is **input-independent** and
it fires for an EMPTY file too, so it is in `gen_module_impl`'s prologue
(`mojo/backend_gimple/module_gen.py:2430`) rather than in anything a statement
reaches. The stages before it are all clean — verified by calling the closure's
own exported C functions one at a time from a C main linked against
`stage1/fire.ci` (that probe is the cheap instrument and it is worth rebuilding;
see "The instrument" below):

    py_tokenize -> 5 tokens
    Parser() ok / with_filename ok / parse_module -> 1 stmts
    _check_ownership ok
    ast_rewriter.rewrite ok
    desugar_genexps ok
    GimpleGen() ok
    gen_module -> raises TypeError: unhashable type: 'list'

The unprobed remainder between `GimpleGen()` and the raise is
`gimple_gen_coro.lower(stmts)` (not exported, so the probe steps over it),
`register_abi_externs`, the `sys.path.insert` pre-scan (`_SYS_PATH_INSERT_RE`,
whose `.findall` has no lowering outside a for-loop), and `gen_module_impl`
itself. **A `.match`/`.search`/`.findall`/`.sub` receiver on a compile-time-known
pattern is the largest known hole in the compiled path** — `finditer` in a
for-loop and the bare `re.sub`/`re.escape` forms are the only regex lowerings
that exist — and the closure's own codegen uses those missing methods in
`elaborate.py`, `gimple_codegen.py`, `mojo/middle/{types,exprtypes,infra_infer}.py`,
`monomorphize.py`, `reflect.py` and `emit_infra.py`. That inventory is the first
thing to work through.

The second, independent class is the `Unexpected SEMICOLON(';')` on
`fire_compiler.py:1301` (`if c == "\\" and in_str != '`': i += 2; continue` — a
backtick inside a single-quoted string on a `;`-bearing line). The token stream
for that file is byte-identical, so the divergence is in
`fire_compiler.py::_split_on_separators` or in phase 2's sub-statement loop, not
in the lexer.

### What was fixed (four root causes, each with its own evidence)

0. **`id()` returned the VALUE instead of an identity** (`work/gatefix9`, the
   fourth and last of this class's non-crash defects). The generated stub was
   `static int64_t id (int64_t x) { return x; }`, so `id(x)` on a container
   handed back the live HANDLE — and the container registries
   (`mojo_is_registered_list` and its siblings) then read that token as the
   container itself. `mojo/middle/lambdareduce.py`'s `if id(body) in cache`
   therefore reached `mojo_dict_key_for`, which is right to refuse a list as a
   dict key, and the compiler raised `TypeError: unhashable type: 'list'`.
   Fixed with `mojo_id` (runtime): an INTERNED box holding the word, which is
   this runtime's existing representation for "an int64_t that is not
   self-describing", and which every classifier already reads as an integer
   (`mojo_boxed_is_str` excludes boxes, `_value_kind` matches only the
   container registries). Interning is load-bearing rather than tidy: it is
   what makes `id(x) == id(x)`, which `cache[id(body)]` — read then written —
   depends on. Test: `gimple_id_is_an_integer` in `test_gimple_runner.py`,
   CPython as the oracle; it fails on the old stub by dying at exactly the
   membership test.

1. **`str`'s optional `[start[, end]]` window was dropped** by every arm of
   `_lower_str_method` (`startswith`/`endswith`/`find`/`index`/`rfind`/
   `rindex`/`count`), so `src.startswith(delim, j)` compared from byte 0 of the
   WHOLE FILE. That is `Parser._scan_string_end`'s question — "does the literal
   opening at `i` close at `j`" — so every source with an ordinary string
   literal was refused as `unterminated string literal` and every source that
   begins with a `"""` docstring matched at every position and collapsed to a
   2-token stream. **This was both halves of the old signature in this doc.**
2. **`<compiled pattern>.split(text)` had no lowering**, and fell through to
   the `char *` string-method table: `fire_compiler.py::_source_lines` asks
   `_LINE_TERMINATORS.split(src)` for a file's physical lines, so the pattern
   OBJECT was cast to `char *` and used as the separator, `raw_lines` came back
   empty, and the tokenizer emitted one EOF token for everything. Fixed with
   `mojo_regex_split` (runtime) + the `split` arm + `regex_prog_for`
   (consolidated out of `emit_loops` so `finditer`/`findall`/`sub`/`split` share
   one program per pattern).
3. **A defaulted POINTER parameter was padded with the integer 0**, which for a
   `char *` parameter `_emit_call` coerces through `mojo_cstr_or_int_str` into
   the one-character string `"0"` — a true, non-null pointer. So
   `Parser._expect(self, kind, value: str = None)` called as
   `self._expect("LPAREN")` believed a value had been passed and refused every
   file with `Expected '0' got ')'`. Fixed at every padding site
   (`_default_expr_to_pair(param_ctype=...)`), which is why `.ast` is now real.

### The instrument, for whoever picks this up

(The `lldb` recipe is at the top of this file and is the cheap half — four
commands, no rebuild. What follows is the expensive half, needed only to reach
the stages before `gen_module`.)

**The instrument, for whoever picks this up** (it is ~25 s per rebuild — the
~100 s in the gatefix8 entry was measured on an older tree — and it is what
made four fixes possible across two sessions):

1. `python3 -c "from gimple_codegen import compile_to_gimple; compile_to_gimple(open('fire_compiler.py').read(), do_imports=False, filename='fire_compiler.py')"`
   — 2.1 s, 1.9 MB of C for the whole front end. Two edits make it gcc-able:
   the self-call `compile_to_gimple (src, 0, filename)` needs the 4th argument
   its own pinned prototype declares, and its `main` must be renamed so a probe
   `main` can link.
2. Link that against `runtime/fire_runtime.c` + the coro runtime +
   `runtime/fire_coro_ctx_aarch64.S` (NOT `_generic.c` — duplicate
   `_mojo_*{fctx,jump_fctx,make_fctx}`) with a C main that calls the
   fixed-ABI `py_tokenize(char *)` and reads the `Token` struct
   (`{int64_t __mojo_type_id; char *kind; char *value; int64_t line, col;}`,
   listed off a `MojoList *` via `mojo_list_get_int`). That reproduces the
   self-hosted tokenizer exactly — it is the same object graph the stage2 binary
   runs — and it reproduced this doc's class byte for byte, including the
   negative column numbers in the diagnostics.
3. The same trick on `stage1/fire.ci` (45 MB, the whole closure) reaches the
   LATER stages: the stage functions are exported with their hash suffixes
   (`ownership_check_check_module_815e8f`, `ast_rewriter_rewrite_815e8f`,
   `fire_compiler_desugar_genexps_815e8f`, `GimpleGen___init__`,
   `GimpleGen_gen_module`), so a probe can call them one at a time and print
   between them. `Parser`'s allocator is `static`, but its struct layout is in
   the generated `typedef`, so a `calloc`'d copy works. ~100 s to build.

## Status (2026-10-03 measurement, superseded by the entry above)

Open. Measured on the 2026-10-03 full gate (commit `e59dae8c`, python3 3.14),
and re-confirmed on `master` as of `99cdb9b7`; nothing in the compiled path
changed in between, which is the measurement that makes this a standing class
rather than a fresh regression — see "Why this is not a new regression" below.

**The class, in one sentence:** `stage2/mojo --dump <file>` writes a correct
`.pyi`, an **empty** `.ci`, and **no** `.tok` or `.ast`, and exits 0 — so the
per-item fanout `bootstrap-stage2-dumps` passes while the files it produced are
not dumps. The failure is only visible downstream, in the two jobs that compare
the stage trees.

## What the gate reported

`bootstrap-verify` (`tools/bootstrap_verify.py`), verbatim from the run:

    verify: 47 identical, 87 stage1-vs-stage2 diff(s), 0 stage2-vs-stage3 diff(s),
            50 missing from a stage (184 files)

`bootstrap-validate` (`bootstrap-validate.mojo`), verbatim:

    FAILED: 256 mismatch(es) / 172 checked

and the per-file shape, verbatim, for one input:

    DIFF  test_struct.ci: stage1 vs stage2 first differ at byte 0
          test_struct.ci 31503 bytes vs test_struct.ci 0 bytes
    ok   test_struct.pyi
    MISSING test_struct.tok: present in stage1/
    MISSING test_struct.ast: present in stage1/

`bootstrap-validate.mojo` sums to 256 = 87 diffs x 2 (stage1-vs-stage2 and
stage1-vs-stage3, since stage2 and stage3 agree) + 82, so the two jobs are
counting the same thing in two vocabularies; they are not independent
witnesses.

**What that census says, read carefully:**

* `stage1` is right. `bootstrap-stage1-dumps` and
  `bootstrap-stage1-transitive` both PASS, and every `stage1/*.ci` has real
  content (31503 bytes for `test_struct.ci`, 1452022 for `myinterpreter.ci`).
  The reference is not the problem.
* **`stage2-vs-stage3` is 0 diffs.** The compiled binary is a fixed point of
  *itself*: run it twice and the second run reproduces the first, empty and all.
  So this is not nondeterminism and not a partial write — it is the binary
  computing something different from the reference, deterministically.
* 87 of 137 checked-and-present files (75%) are affected. This is the same
  shape as the long-standing per-file sweep in
  `bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md`, whose 2026-09-17
  status entry reads "Sweep: empty self-hosted outputs 38 -> 28" over a 779-file
  corpus. This doc is NOT a re-report of that sweep's *content*; it is the
  statement that the class is still present, is now the whole of what
  `bootstrap-verify` and `bootstrap-validate` report, and has a specific new
  signature (below) that the old census did not separate out.

## The new signature: `.pyi` right, `.ci` empty, `.tok`/`.ast` absent
*(SUPERSEDED 2026-10-04: `.tok`/`.ast` are no longer absent — they are
byte-identical to stage1's. See the Status entry at the top. What is left of
this section's reasoning is the `.pyi`-is-right row, which still holds: the
stub emitter runs before the failure and does not depend on the codegen.)*

This is the part worth writing down, because it is narrower than "the
self-hosted binary is wrong" and therefore cheaper to chase.

`--dump` is supposed to write four artifacts per input: `.ci` (the GIMPLE C),
`.tok` (the token stream), `.ast`, `.pyi` (the type stub). On the compiled
binary, for the inputs visible in the log:

| artifact | stage1 | stage2 |
|---|---|---|
| `.pyi` | correct | **correct** (reported `ok`) |
| `.ci` | 20-30 KB, thousands of lines | **0 bytes** |
| `.tok` | present | **absent** |
| `.ast` | present | **absent** |

A `.pyi` that is byte-identical to the reference next to a `.ci` of zero bytes
is the informative part. It says the self-hosted binary got far enough to
*parse and type* the file, and to run the type-stub emitter, and then produced
nothing for the three artifacts that come out of the code-generation and
tokenizer paths. That localises the defect to "the dump driver runs and its
early stages succeed; the C/token/AST writers do not", rather than "the binary
cannot parse Mojo" (which would have made `.pyi` wrong too) or "the binary
crashes" (which would be a non-zero exit, and `reject='mojo_unsupported_iter'`
exists precisely to catch the non-crashing no-op).

`.tok`/`.ast` being *absent* rather than empty is a second, separate fact and
may have a separate cause: a file that is never opened cannot be empty. It is
recorded here rather than folded into the `.ci` symptom because a fix for one
does not obviously fix the other.

## Why this is not a new regression

The gate that reported it ran on `e59dae8c`. Everything that has landed since,
to `99cdb9b7`, is `formal/` and test/tooling:

    $ git log --oneline e59dae8c..HEAD --name-only \
        | grep -E 'mojo/backend_gimple|mojo/middle|gimple_codegen\.py|module_loader\.py'
    (nothing)

`CLAUDE.md` names `mojo/backend_gimple/*` and `mojo/middle/*` as the files that
decide what the compiled binary computes, and none of them moved. So the
symptom is the standing class, not something the `bugs3` consolidation or the
`formal15` merges introduced. **This is stated as a measurement, not as a
bisect**: proving the negative properly needs a stage2 build on a pre-`bugs3`
tree, and a stage2 build is a self-host build, which this session was not
permitted to run (see "What was not run here").

## Why `bootstrap-stage2-dumps` is NOT the place this is caught

The fanout runs `[./mojo, '--dump', '../{file}']` per item and the runner's
per-item verdict is, in order: memcap, `reject=`, exit code. `reject` is a
**regex over the child's output** (`tools/suite.py`'s `run_job`), and a child
that writes nothing prints nothing. So the fanout's `reject='mojo_unsupported_iter'`
cannot see an empty file, and `bootstrap-stage2-dumps` reported **PASS** in the
same run in which 87 of its products were empty.

Two consequences, and both are already acted on:

1. **`bootstrap-stage2-dumps` had an `expect=` marker that is now stale**, and
   the runner correctly reported a marker whose test passes as a FAILURE. The
   marker is dropped. That is not a claim that the capability works — it is a
   claim that the *fanout* does not measure it, which is why the two jobs that
   do are the ones carrying the marker now.
2. **The marker was not the load-bearing part of the truth.** The old text
   (`SELFHOST_STAGE2_STALL` in `tools/suite.py`) said the sub-jobs "return
   `mojo_unsupported_iter` no-ops **or a wrong dump**". Measured 2026-10-03, the
   `mojo_unsupported_iter` half is GONE — that is why the fanout passes and the
   marker went stale — and the "wrong dump" half is exactly what
   `bootstrap-verify` reports. So the class did not go away; its *detector* in
   that job went away with it.

## The fix, when someone takes it

Nothing below was run here; it is the next step, written so it can be started
without re-deriving anything.

1. **Reproduce with one input, not three stages.** `stage2/mojo` is a single
   binary and `BOOTSTRAP_INPUTS` are single modules, so one command in `stage2/`
   is the whole reproduction:

       cd stage2 && ./mojo --dump ../test_struct.mojo ; ls -l test_struct.*

   No closure dump, no `stage3`, no `verify`. If `test_struct.ci` is 0 bytes
   there, the class is confirmed with the fan-out and the byte comparison out of
   the picture, and every question below is answerable in seconds.
2. **Ask which writer runs.** `--dump` should have one place that opens
   `<base>.ci`, one that opens `<base>.tok`, one that opens `<base>.ast`, and
   one that writes the `.pyi`. A single "did the dump succeed" boolean that
   everything downstream trusts is the thing to find: a path that opens the
   file, writes nothing, and reports success is the whole bug.
3. **The cheapest instrumentation that would have caught this in the fanout:**
   after the dump, `os.path.getsize` each artifact and print the sizes. That is
   one line per artifact, it needs no compiler change, and it turns
   `bootstrap-stage2-dumps` from "cannot see the defect" into "sees it on the
   first item". Until that exists, `expect=` on `bootstrap-verify` is what keeps
   this visible in the tally.
4. **Do not mark `bootstrap-verify`/`bootstrap-validate` `disabled=`.** They
   cost 0.6 s and 0.0 GB — they are three `os.listdir`s and a byte compare, and
   all of their cost is in `bootstrap-stage3-transitive`. Per `CLAUDE.md`'s
   rule (a known failure that is CHEAP runs, with `expect=`), `expect=` is the
   correct marker and `disabled=` would be paying the machine to be told what
   the doc already says.

## What was not run here

No stage tree was built. `stage1`/`stage2`/`stage3` are all absent from a fresh
worktree, and producing them is `fire.py build fire.py` plus a `gcc -O0` over
the 40 MB closure — a self-host build, which this worker was explicitly not
permitted to run. So: the census above is quoted from the gate log rather than
re-measured, and step 1 of "The fix" is where the re-measurement starts.

`bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md` is the doc that owns
the per-file CONTENT of the divergence (which files differ and why) and is not
edited by this one. It is cited here for the 2026-09-17 "empty self-hosted
outputs" census and nothing else.
