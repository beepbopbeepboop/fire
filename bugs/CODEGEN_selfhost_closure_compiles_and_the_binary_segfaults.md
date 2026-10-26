# `selfhost`: the self-host closure COMPILES AND LINKS; the produced binary cannot compile a two-line program

(The file name says `segfaults`, and did when this was filed: the produced
binary died of `exit=-11`. That is fixed — see the Status section below, which
measures `exit=1` and names the fault that replaced it. The name stays because
two docs cite it and a rename that breaks its own citations is not worth the
tidiness; the TITLE is the subject, and the subject is now "cannot compile".)

**State: OPEN, measured 2026-10-04, and it REPLACES six docs** — all six of
which described a failure this job no longer has. They were written on
2026-10-02 against trees where the generated C did not compile; that is fixed
on this tree, and their numbers (67 / 80 / 149 / 157 distinct `error:` lines,
`'_mojo_elem_repr_<Node>' undeclared`, `'struct _<module>_toplev' has no
member named 'X'`, `passing argument 1 of 'mojo_repr_list_ints' makes pointer
from integer`) no longer reproduce at all. Keeping six docs that each cost the
next reader a four-minute measurement to re-derive a conclusion that is now
false is the failure mode `bugs/` is supposed to prevent, so they are deleted
and this one carries the measured state.

## Status (2026-10-05, `work/merge-gate28`, on the merged tree): the FIRST fault is closed, and the next one is named

Step 1 of the section below was run — `python3 tools/suite.py selfhost
--no-cache`, 530 s, peak 4.4 GB, on the tree with `work/gatefix10`,
`work/bugs7-1` and `work/merge-formal27a-r2` merged into it. **The SIGSEGV is
gone and the binary now runs to a clean error exit:**

```
  self-host closure: 62 modules, every generator/async lowered in place or its module refused whole: True
  dylib module path refuses an unlinkable generated_cpp: True
  self-host closure: 1563 functions, 1 of them declared in fire_runtime.h under a pinned C name; every such declaration matches its definition: True
Built: /Users/mrs/net/chatgpt/claude/work-451/.tmp/tmp5g2h5e4g/mojo_selfhost
  self-hosted compiler on a two-line program: exit=1 ci_bytes=0 stub_hits=0
  ✗ the self-hosted binary did not exit 0
```

`exit=-11` became `exit=1`. `ci_bytes=0` and `stub_hits=0` are unchanged, so
nothing about the shape moved except the fault itself, and the reading the
previous section asked for is the one that holds: **the type-tag fix closed the
FIRST fault, not the last.** The job is still red and still undeclared-red, and
this doc stays open.

### The next fault, and its message

The binary was kept (the two-line recipe in "The exact next step" item 1 below,
run by hand into `.tmp/shkeep/`), so this cost one build and not three:

```console
$ cd .tmp/shkeep && printf 'x = 1\nprint(x)\n' > probe.mojo
$ ./mojo_selfhost --dump-full probe.mojo ; echo "EXIT $?"
Error generating --dump-full: TypeError: unhashable type: 'list'
Unhandled exception: NotImplementedError: traceback.print_exc: module 'traceback' is not compiled into this binary
EXIT 1
```

So the compiled compiler gets as far as the dump and is refused a dict key by
the runtime's own content-key rule: `mojo_dict_key_for` (`runtime/fire_runtime.c`
line 10567) raises exactly this text for a `MojoList *` that is **not** marked by
`mojo_mark_as_tuple`, which is right for CPython and wrong here, because the
value IS a tuple.

`lldb` names the frame (a breakpoint rather than `-k bt`, because the error is
caught, so there is no stop to catch):

```console
$ lldb -b -o "breakpoint set -n mojo_dict_key_for" -o run -o "bt 30" -o quit -- \
      ./mojo_selfhost --dump-full probe.mojo
* frame #0: mojo_selfhost`mojo_dict_key_for
  frame #1: mojo_selfhost`mojo_dict_set_str_kw + 112
  frame #2: mojo_selfhost`_mojo_middle_types_toplevel.part.0 + 6676
  frame #3: mojo_selfhost`main + 300
```

**`mojo/middle/types.py`'s MODULE-LEVEL code** builds a dict whose key is a
value the runtime says is an unmarked list. One candidate, and it is the only
one of its shape in that module — an AST walk of `types.py`'s module-level
statements finds exactly one dict literal with a non-constant key:

```
L1286 non-constant key: ('os', 'environ')
```

which is `_MODULE_ATTR_CTYPES: dict = {('os', 'environ'): 'MojoDict *'}`, and
the instruction after the failing call in that frame is a `bl mojo_set_new`,
which is where `_FORCE_RENAME_RESERVED = frozenset({...})` (line 1327) builds
its set. That is a HYPOTHESIS built from adjacency in generated code and from
the key's shape — it is not measured, and the mark is a process-wide ADDRESS set
(`_reg_tuple`), so the two ways it can be wrong are different bugs: the tuple
literal never got `mojo_mark_as_tuple`, or it got it on a different `MojoList`
than the one handed to the dict.

### The exact next step (three lldb commands, no rebuild)

The binary these were read off was built into `.tmp/shkeep/` on the worktree that
measured this and was deleted when that worktree finished; `.tmp` does not
survive a reboot either, so step 1 is "rebuild it once, into a directory you
keep" — the two-line `build(td)` recipe in "The exact next step" item 1 below,
which is ~9 minutes — and steps 2 and 3 are seconds each after that:

1. `breakpoint set -n mojo_mark_as_tuple` and `breakpoint set -n
   mojo_dict_key_for`, `continue` to the second. If the pointer `x0` at the
   `mojo_dict_key_for` stop was never an argument at a `mojo_mark_as_tuple`
   stop, the dict-literal key path builds a COPY and the fix is there. If it
   was, then `mojo_mark_as_tuple` ran and the registry lost it, and the fix is
   in `_reg_tuple`'s lifetime.
2. For the first, read `_lower_tuple_literal`'s `mojo_mark_as_tuple` call
   (`mojo/backend_gimple/emit_exprs.py`, at the end of the function, AFTER the
   elements are in — the placement is load-bearing and its comment says why) and
   ask whether a dict literal's KEY is lowered through it at all, or through a
   path that builds the same two-element list without the mark.
3. **Fix the traceback path while you are in there.** The second line of the
   output above is its own defect and it is why this section needed lldb at
   all: the self-hosted binary cannot print the traceback of its own
   unhandled error, because `traceback` is not compiled into it. Every future
   instance of this class — a compiled compiler that raises instead of
   segfaulting — will be reported as one line with no frames. Whichever module
   list excludes `traceback` is the one to look at.

## Status (2026-10-05, `work/gatefix10`): the crash is ROOT-CAUSED and the runtime half is FIXED; the binary is not rebuilt yet

The step-2 next step below ("run it under lldb, take the backtrace") has been
done, and the backtrace names the mechanism in one frame. **What is fixed is
`runtime/fire_runtime.c`'s type-tag reader; what is NOT yet measured is whether
the self-hosted binary survives after that**, because rebuilding it is a
whole-closure compile and this session is not allowed to run one. So this doc
stays open, and the exact jobs to re-run are in "The exact next step".

### The backtrace

Kept, per that step's own advice — `test_selfhost.py` deletes its binary, but
`stage2/mojo` is the same artifact of the same closure and survives in the
worktree:

```console
$ cd stage2 && MOJO_HOME=.. PYTHONPATH=.. lldb -b -o "run --dump ../hello.mojo" -k "bt 40" ./mojo
* thread #1, stop reason: EXC_BAD_ACCESS (code=1, address=0x746e697270)
   * frame #0: mojo`_canon_int + 48
     frame #1: mojo`_dict_lookup_k + 108
     frame #2: mojo`_dict_lookup + 32
     frame #3: mojo`mojo_dict_get_int + 28
     frame #4: mojo`mojo_dict_get_int_kw + 72
     frame #5: mojo`mojo_middle_exprtypes__walk_ast_into_37bd8e + 1964
     ...
    frame #13: mojo`mojo_backend_gimple_module_gen_gen_module_impl_7e9a9f + 244180
```

`0x746e697270` is not an address: it is the five ASCII bytes `'p','r','i','n','t'`
followed by three NULs, read as a little-endian word. So a **`char *` was passed
where a `MojoStr *`-shaped header was expected, and its TEXT was read as the
struct's `__mojo_type_id`.**

### The chain, from the generated C

`stage1/fire.ci`, at the `#line` the backtrace points to
(`mojo/middle/exprtypes.py:73`, inside `_walk_ast_into`):

```c
_t64 = mojo_read_type_tag_safe (_t63);        /* type(node)      */
_nc  = _t64;                                   /* = 0x746e697270  */
_t68 = (MojoDict *)_..._globals._WALK_DATACLASS_CACHE;
_t71 = mojo_dict_get_int_kw (_t68, _nc);       /* _WALK_DATACLASS_CACHE.get(type(node)) */
```

1. `type(x)` is lowered to `mojo_read_type_tag_safe((int64_t)x)`
   (`mojo/backend_gimple/emit_calls.py`, the `fname_raw == 'type'` arm).
2. `_walk_ast_into` asks for `type(node)` for EVERY node **before** its
   `isinstance(node, str)` early-return — deliberately, for the reason its own
   comment gives (the scalar test lowers to a non-NULL test and mistakes a
   boxed pointer for an int). So on a `str` node, `type()` is evaluated.
3. `mojo_read_type_tag_safe` validated the ADDRESS (`_mojo_tagged_addr_ok`) but
   never the WORD: a heap `char *` is 8-byte aligned and `malloc_size` says it
   is >= 8 bytes for any string of 5+ characters, so all three address checks
   passed and the string's own bytes came back as an identity.
4. That identity is >= 2 GiB, so `mojo_boxed_is_str` classified it as a boxed
   string on the next hop, `mojo_dict_get_int_kw` took its `_KW_STR` arm, and
   `_canon_int` dereferenced it.

Step 3 is the defect: **the predicate's own domain is inverted.** `CRASH.md`'s
fix made a 31-bit TAG stop looking like a pointer; this is a POINTER that was
allowed to produce a tag, and CRASH.md could not see it because its faulting
value was small.

### What landed

`runtime/fire_runtime.c`: `mojo_read_type_tag` and `mojo_read_type_tag_safe` now
share one `_mojo_struct_type_tag`, which validates the word it read as well as
the address it read it from — a tag is always in `[0, 0x7fffffff]` (every
producer masks: `_struct_type_id`'s `& 2147483647`, the exception ids'
`& 0x7fffffff`), so anything else is "not a registered struct", which is the
answer both readers already return for every other shape. The invariant is
disjointness in both directions: **a tag is never pointer-shaped, and a
pointer-shaped value never produces a tag**, so no consumer of either reader can
reach `_canon_int` from a string again.

`runtime/test_fire_coro_gen.c` carries `test_type_tag_reads_reject_a_boxed_string`,
which links the real `fire_runtime.c` and covers: the measured case (a 5-char
heap string reads 0), the bounded residual (a 4-char string's word is inside the
tag range and no predicate on the word can exclude it, so what is asserted is
the bound, not a zero), the positive case (a heap tagged struct reads its own tag
back exactly), and the crash chain end to end —
`mojo_dict_get_int_kw(d, mojo_read_type_tag_safe("print"))`, which SEGFAULTS if
the range check is removed. Verified both ways:

```console
$ python3 test_coro_runtime.py          # with the check:    20/20 passed
$ # ...with the range check deleted:    FAIL layer1-shim (all four builds), no CHECK line — a crash
```

`mojo_hash` is fixed as a side effect and it was a real divergence: it asks the
same reader to tell "struct or string?", so a 5+ character string used to hash
by IDENTITY where CPython hashes by CONTENT (`{s: 1}` lookups, set membership).

### The exact next step

1. **Rebuild and re-run `selfhost`** — `python3 tools/suite.py selfhost
   --no-cache` — which needs a whole-closure compile and so was out of scope
   for the session that landed this. It is the only thing that can say whether
   this was the FIRST crash or the first of several: a fix that removes a
   segfault usually exposes the next one, and the honest reading of this
   section is "the first fault is closed", not "the binary works".
2. **`bootstrap-stage2-dumps`** is the cheap witness for the same question
   (per-file `--dump` on `stage2/mojo`, 46 items) and needs only
   `bootstrap-stage2-cc` first. Its shape on this tree: `fire.py` and
   `myinterpreter.py` `exit 1`, `module_loader.py` and `generated_dispatch.py`
   `exit 245`, most `.mojo` items `exit 245`/`246`/`250`, and the rest die on
   signals (-6/-10/-11) — measured here, not quoted from the gate.
3. If a next crash appears, the same recipe applies and is now cheap: the
   stage trees persist in the worktree, so `lldb -b -o run -k "bt 40"` on the
   existing `stage2/mojo` answers in seconds instead of after a 15-minute
   rebuild. Do NOT re-run the doc's step 1 (copying the binary out of
   `test_selfhost.py`'s tempdir) first: `stage2/mojo` is the same artifact.

## What I ran

```sh
python3 tools/memslot.py --gb 8 --label selfhost -- python3 tools/suite.py -j1 selfhost
```

which is `python3 test_selfhost.py` under the runner. 914 s and 643 s on two
runs of this branch, peak 4.4 GB.

## What I see

```
  self-host closure: 62 modules, every generator/async lowered in place or its module refused whole: True
  dylib module path refuses an unlinkable generated_cpp: True
  self-host closure: 1555 functions, 1 of them declared in fire_runtime.h under a pinned C name; every such declaration matches its definition: True
Built: /Users/mrs/net/chatgpt/claude/work-422/.tmp/tmpjsttg9_q/mojo_selfhost
  self-hosted compiler on a two-line program: exit=-11 ci_bytes=0 stub_hits=0
  ✗ the self-hosted binary did not exit 0
Results: 1 passed, 1 failed
✗ self-host compile/link regressed (GCC error, ICE, undefined symbol, or the produced binary cannot compile)
```

`Built:` is the load-bearing line and it is NEW relative to every one of the
six docs it replaces: **the whole-closure `.ci` compiles AND links.** All three
static halves are green. `test_selfhost.py`'s verdict sentence still says
"compile/link regressed", which is its one fixed wording for the build half
being red — it is now the RUN half that is red, and the sentence is what makes
the job's own output misleading about which stage failed.

Independently confirmed at the gcc level, on the same closure, with the exact
recipe a since-deleted doc gave (the `compile_to_gimple_cached` +
`gcc -fgimple -fsyntax-only` one), which is the cheapest instrument for this
question and is why the `grep` filter is the load-bearing part of it:

```
$ python3 -c "import gimple_codegen; open('.tmp/fire_full.ci','w').write(
      gimple_codegen.compile_to_gimple_cached(open('fire.py').read(),
      do_imports=True, filename='fire.py'))"          # 44.6 MB, peak 1.3 GB
$ $(python3 -c 'from build_config import find_gcc; print(find_gcc())') \
      -fgimple -fsyntax-only -O0 -g3 -ftrivial-auto-var-init=zero \
      -I runtime $(python3-config --cflags) -x c .tmp/fire_full.ci
gcc rc=0
$ grep -cE "^[^ ].*\.(py|ci|h|c):[0-9]+:[0-9]+: error: " .tmp/selfhost_gcc.txt
0
$ grep -c " error: " .tmp/selfhost_gcc.txt
7
```

All seven unfiltered matches are the compiler's OWN source text quoting gcc
diagnostics inside the generated C (`gimple_codegen.py:4331`'s "internal
compiler error: in build2", `mojo/middle/types.py`'s "compile error: the
callee's C prototype carries no defaults", `fire.py`'s `print(f"JIT error: …")`)
— which is precisely the counting trap
the six docs this one replaces warned about, and why the
filtered count is the one to read. The tree is clean.

The same closure's companion, measured because
the companion-discard guard needed it and refused to guess:

```
_run_pipeline(fire.py, do_imports=True) ->
  ci bytes       44647501
  cpp bytes      0          <- NO C++ companion is produced at all
  cpp symbols    0
  ci  symbols    0
  mgco in ci     True       <- every generator goes down the stack-switch path
```

## It is NOT a regression from the branch that found it

The branch base (`ccb157ed`, the merge this worker started from) was extracted
with `git archive` into `.tmp/base` and `test_selfhost.py` run there
unmodified — same command, same ceiling, 4.3 GB:

```
  self-host closure: 62 modules, every generator/async lowered in place or its module refused whole: True
  self-host closure: 1548 functions, 1 of them declared in fire_runtime.h under a pinned C name; every such declaration matches its definition: True
Built: /Users/mrs/net/chatgpt/claude/work-422/.tmp/tmpgae36mkq/mojo_selfhost
  self-hosted compiler on a two-line program: exit=-11 ci_bytes=0 stub_hits=0
  ✗ the self-hosted binary did not exit 0
Results: 1 passed, 1 failed
```

**Identical stage, identical symptom, identical numbers** (`exit=-11`,
`ci_bytes=0`, `stub_hits=0`), and the only difference is the function count:
1548 on the base against 1555 here, which is exactly the seven functions this
branch added to the closure: the four from the star-spread fix
(`mojo/middle/types.py`'s `is_star_spread`, and
`mojo/backend_gimple/emit_exprs.py`'s `_is_star_spread`, `_emit_star_spread` and
`_literal_slot_kinds`), `mojo/middle/lambdareduce.py`'s `lambda_bound_to` and
`params_supplied_at_calls`, and `emit_calls.py`'s `_pad_lambda_defaults`.

So this is a standing red, it is not mine, and a session that reads a red
`selfhost` in the gate after merging this branch should read it as inherited.

## Why it still matters

`selfhost` is in `check` and in `gate` and carries **no `expect=` marker**, so
this is an *undeclared* red — every one of the six docs it replaces said so, and
it is still true. Everything downstream of the self-host BUILD is therefore
unmeasured too: `mojoc`, `native-dumpfull`, `bootstrap-stage1-*` and
`bootstrap-stage2-cc`.

## The exact next step

The failure is now a single, much narrower question than any of the six docs
posed, and it is a RUNTIME fault in the produced binary, not a codegen one:

1. Keep the binary. `test_selfhost.py`'s `build()` chdirs into a
   `tempfile.mkdtemp()` and nothing copies `mojo_selfhost` out, so the one
   artifact that would answer this is deleted at the end of every run —
   which is why this has cost three sessions a full build each. A two-line
   `shutil.copy(out, os.path.join(REPO, 'build', 'mojo_selfhost'))` after the
   `Built:` line would turn the next attempt into a 10-second lldb session
   instead of a 15-minute rebuild. That is a change to
   `bugs/TEST_*` territory rather than a compiler fix, and it is the cheapest
   thing on this page.
2. `x = 1\nprint(x)\n` is the whole input, so the crash is early and does not
   need the closure's full behaviour: run it under lldb, take the backtrace,
   and the first frame inside a `_mojo_*` runtime entry point names the
   mechanism. `ci_bytes=0` says the crash happens before any `.ci` is written,
   and `stub_hits=0` says no `weak` "unavailable in compiled mode" stub is in
   play — which rules out the whole class
   `run_produced_binary`'s own docstring documents (a stub returning nothing
   made every `for node in <stub>(...)` iterate zero times), and is worth
   recording so the next reader does not start there.
3. `bugs/CODEGEN_module_toplevel_undefined_in_selfhost.md` and
   `bugs/CODEGEN_cas_py_never_compiles_so_the_selfhost_closure_has_no_definitions.md`
   are the two live candidates this tree still carries for a self-hosted
   compile-time crash, and neither has been re-measured since the closure
   started linking. Start with whichever the backtrace names.

## What the six deleted docs contributed, and where it went

Not all of it was stale, so it is worth saying where the load-bearing parts
went rather than dropping them:

* **The counting trap** (`grep ' error: '` matches the compiler's own quoted
  diagnostics) — reproduced above, with the filtered count beside it.
* **`_KindRow.kinds` is one byte per slot**, and a spread breaks that
  invariant — that turned out to be a REAL bug on this tree, in
  `mojo/backend_gimple/emit_exprs.py`'s literal lowerings, and is fixed. The
  general statement it rests on is recorded in that function's docstring.
* **A module-level global read at function scope must be a field of its
  module's `_toplev` struct** — that no longer reproduces, and
  `mojo/backend_gimple/module_gen.py`'s own comment on the deliberate
  non-rollback of `_module_globals` (which one of the six docs named as the
  leading candidate) is unchanged and still the right place to read if it ever
  comes back.
* **157 errors is a property of an earlier tree, not of the registry** — kept
  here as the standing argument for why no doc here states a count.

## Related

- `bugs/CODEGEN_bootstrap_stage2_dump_is_empty.md` — the other half of the
  self-host story, and a different subject: this is about the produced BINARY,
  that one about the `--dump` artifact the stage2 compiler writes.
- `bugs/UNTESTED.md` §3.3 — "a non-zero exit is the only verdict
  `tools/suite.py` can see", and this is a step below that: the binary links,
  runs, and produces nothing.