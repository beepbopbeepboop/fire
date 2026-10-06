# Handover: partial and open work from the 2026-09-26/27 bugs/hard campaign

**Read this before picking up anything below.** Ten agents worked `bugs/hard/`
over two waves. This file exists for two reasons, and the second is the
important one:

1. one place listing what is **partly** done, with a code pointer and the exact
   next step, so nobody re-derives it;
2. several findings existed **only in an agent's report** — i.e. only in a
   conversation — and would have been lost. They are in §4, marked as
   recovered. Treat §4 as the weakest-evidence section and re-verify before
   acting on it; everything in §2 and §3 has a doc with measurements behind it.

Nothing here is a live index. Each item names its own doc, and that doc is the
authority. This file is a snapshot as of 2026-09-27.

## Status, 2026-10-02: re-measured, and two entries were wrong about which half is open

A snapshot this old had stopped being true about itself, so each entry was
re-checked against the tree rather than against its own prose. What moved:

* **§2.1 is HALF fixed, and its residue has its own doc** —
  `x = [1, 2, 3]; Box(x)` prints `1 2 3` on both paths today (the shape this
  entry listed as still broken is fixed), while `Reader(self._items)` still
  loses the element type and now **SEGFAULTs** rather than printing nothing.
  Filed as
  `bugs/CODEGEN_dispatched_for_loop_shares_one_var_between_dict_and_list_arms.md`,
  with the generated C, because the crash is a SECOND bug (one C variable
  shared between `_gen_for_iter`'s dict and list arms, so the dict arm's
  `char *` key type wins) and fixing only the field type leaves it reachable.
* **§2.4 is entirely closed.** The alias form this entry called "still open,
  own doc" was fixed and verified against CPython on BOTH pipelines
  (single-TU and link mode) on 2026-09-30, and its doc was deleted with the
  fix — so the "still open" line was pointing at nothing.
* **Nine of this file's citations were of docs deleted by their own fixes.**
  Rewritten to name the bug, which is what the ratchet
  (`tools/dangling_doc_refs.py --ratchet`) now requires of any file that
  edits this one: deleting a bug doc invalidates every sentence that pointed
  at it, and a check that fails on an INCREASE is the only thing that keeps
  the next set from arriving.
* Not re-measured, and why: §2.2 and §2.3 name live docs owned by other
  workers (`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`,
  `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md`), so their
  bodies are current by construction and re-deriving them here would only
  produce a second copy to disagree with. §2.5's first entry's claim that the
  `async for`-over-a-generator gap now "drives the generator for real" is one
  line and was not re-run.

---

## 1. Fixed in this campaign — do not redo

Committed as `435cc71` (verification wave) and `9f8a9b7` (fix wave). Eight
closed reports removed, eight bugs fixed, 7 new docs written. `check` 9/9,
`gate` green except the pre-existing self-hosted SIGSEGV. The single most
valuable change was not a bug fix: `test_gimple_runner.py` (125 cases) and
`test_gimple_generator_runner.py` (151) were in **no suite bucket at all** and
now run in `check`.

---

## 2. PARTIAL — the recorded gap is fixed, named residue remains

### 2.1 Container-typed ctor args reached via a local or `self.<f>` — HALF FIXED, and the residue now has its own doc

Was the ctor-arg-field-type doc (deleted with its fix). Fixed by a
third, purely-syntactic evidence pass beside the existing literal-argument
one in `module_gen.py` (traces an `IdentExpr`/`self.<field>` ctor argument
to its own container-literal assignment, feeding the same unanimity-gate
dicts the literal pass already uses) — not the context observer a prior
attempt wired in and reverted. See `bugs/BUGFIX_ROADMAP.md` item 30 for the
verification record (`test_gimple.py` 326/326, `test_selfhost.py` green).

**Re-measured 2026-10-02, and the "still" below is now half stale.** Of the
two shapes this entry listed:

    x = [1, 2, 3]; Box(x)      # FIXED — prints 1 2 3 on both paths
    Reader(self._items)        # STILL BROKEN, and it is a SIGSEGV

The first is correct today against CPython 3.14.7 on the same text
(`compile_to_gimple` + `gcc -fgimple` + run, which is the same path
`test_gimple_runner.py` uses), so the "An agent built the fix, measured it turn
`selfhost` red, and removed it" history below is about a shape that now works.
`[i]` on the second's field is also correct (`print(r.items[0])` → `10`); only
`for i in r.items` crashes, with SIGSEGV (exit -11), reproducibly and with
`MallocScribble=1`.

The residue has its own doc and a root cause that is TWO bugs, not one, which
is why it is filed rather than left here:

    bugs/CODEGEN_dispatched_for_loop_shares_one_var_between_dict_and_list_arms.md

— the field is `int64_t` because `self.items = items` has no call-site evidence
(the inference half), and the crash is `_gen_for_iter`'s dict/list runtime
dispatch sharing ONE C variable between both arms, so the dict arm's `char *`
key type wins a list-of-ints loop and `print(i)` calls `mojo_print((char *)10)`
(the codegen half). Neither half alone leaves the SIGSEGV unreachable, and the
doc records why the obvious one-line default for the shared variable is a
regression for the other arm.

**The next step recorded below is stale advice**: move the context observation
after `_inferred_var_types` is populated (`module_gen.py:3808`, `:3813`,
`:5394`) and before the `pm`/field pass (`:2807`-`:2843`), writing
`_ctor_lit_param_types` exactly as the literal observer does. It is a
reordering of two delicate passes, and the original prescribed fix (a
`ListExpr` case in `_arg_scalar_type`) broke selfhost — do not use it. What
today's measurement adds is that the ordering is no longer the whole answer:
the field's ELEMENT type is still never threaded at all
(`_field_elem_types['Reader']` is empty), which is why the loop falls to
runtime dispatch in the first place.

### 2.2 Variadic lambda call sites are not packed
Doc: `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`

The lifted **definition** is correct — `int64_t main_lambda_1 (MojoList * a)`,
and the code's own comment says "callers pack the loose args into it". The
lifted **call site** picks `mojo_fnptr_call_N` by written argument count and
passes them positionally as scalars, never packing:

    mojo_fnptr_call_2 (e, (int64_t)4, (int64_t)5)

so the callee reads `a = 4` as a `MojoList *` and dereferences address 4. All
probes SIGSEGV (139) where CPython gives 9 / 6 / 8. **Corpus is 3 sites, not
1**: `Tools/c-analyzer/c_common/fsutil.py:285`,
`Lib/importlib/util.py:247`, `Lib/doctest.py:1566` — the last assigned to an
*attribute*, so any fix must handle a field-held variadic lambda. This is a new
call-site lowering keyed on a signature; the doc records the existing packing
precedent.

### 2.3 Invoking a keyword-only parameter as a callee
Doc: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md`

4 of the 6 recorded shapes are still refused, all for this one reason. A
kw-only param that is merely *not called* compiles and runs fine; calling it
does not. Same missing callable-value representation as §2.2, from a different
direction. The real source file is on disk at
`/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib/Tools/c-analyzer/c_common/fsutil.py`
— an earlier audit concluded it was absent and reconstructed minimal programs,
which is how this got wrong twice. **If you audit a COMPILE_FAIL doc, read
the real file first.**

### 2.4 `module.Class(...)` construction — FIXED 2026-09-27 (qualified form); alias form still OPEN
Was the highest-leverage item in this file — it gated the struct-collision
bug entirely. Fixed for the headline shape: `mod_a.Dialog("a")` (a real
module marker's attribute naming a real, already-inlined struct) lowered to
a generic method-call fallback that just echoed the module-handle receiver
back as the "result" (`int64_t.Dialog() stubbed`), so `x` bound to the
module handle itself and `x.widgetName` raised `AttributeError`. New check
at the top of `_lower_method_call`
(`mojo/backend_gimple/emit_methods.py`) routes this shape to
`_lower_struct_constructor` instead, for both a plain `import mod_a` and a
`from PKG import submodule` binding. Verified end-to-end (compiles, runs,
prints `a`); regression `test_gimple_runner.py`'s
`qualified_module_struct_construction`.

**Consequence, confirmed live**: with construction unblocked, the
struct-collision bug — two same-named structs from different modules sharing a
bare name, so one TU's field read lands in the other's layout, its doc deleted
with its fix — is now genuinely reachable — a same-arity collision reproduces its predicted
silent field-coercion as a real running program (see that doc's updated
Status). The 4-step collision fix itself is still NOT attempted (rated
moderate-to-high risk, foundational struct-identity machinery) — next
session's natural continuation.

**The ALIAS spelling is closed too** (`from mod_a import Dialog as ADialog;
ADialog("a").widgetName` — it used to fall through to the generic
single-string-arg "opaque constructor" fallback, so `ADialog("a")` silently
became the string `"a"`, because `gen.struct_field_types` is keyed by the
struct's bare defining name and a class alias is not registered into
`gen.imported_symbols` at all). Measured against CPython 3.14.7 on the same
text on BOTH pipelines — single-TU and link mode — `a` on all three; its doc
is deleted with the fix (`e447341a`), which is why this entry has no pointer
left to give. **Nothing in §2.4 is open.**

### 2.5 Yield-kind and capture residue
- ~~the coro captured-param capture crash~~ — **closed 2026-09-29, its doc
  removed with the fix.** Items 2 and 3 are fixed: the orphaned
  regression file is registered (`coro-nested-capture`) and 10/10, and the
  capture-independent `async for`-over-a-generator gap (which printed `0`
  where CPython prints `11`, with only a `mojo_unsupported_iter` warning)
  now drives the generator for real. Re-testing that doc's own
  "Verified genuinely fixed" list also surfaced and fixed three more: a
  wait-descriptor bound as the `async for` loop variable (a heap address,
  exit 0 — now a compile-time refusal), two nested `async def`s sharing one
  captured local (a generated-code argument-count error), and Increment D's
  honest refusal not existing on the `MOJO_CORO=cpp` backend at all.
- the coro yield-kind case (its doc is deleted now) — case 8, which
  was **reclassified**: the same wrong output appears with no generator at all
  (`def show(data): for r in data: print(r)` called with `[1.5, 2.5]`), so it
  is the ordinary loop lowering not knowing a list *parameter's* element type.
  A different subsystem, behind its own gate.
- ~~the silent-wrong bytes values — `partition` returns a
  `MojoList *` rather than a tuple, because **this runtime has no tuple type
  at all**: a tuple *literal* lowers to a plain `MojoList *` distinguished
  only by a marker. Not a bytes fix; the repr is already correct.~~
  **RESOLVED 2026-09-29 — and the stated reason was false.** A tuple type
  has existed for some time, as the `mojo_mark_as_tuple` marker, used at
  eight construction sites and already read by `isinstance(x, tuple)`. The
  marker was not *load-bearing*: `repr` read it and nothing else, so a tuple
  was a list that merely printed like one. Making it load-bearing closed the
  doc's residue (mutating a tuple now raises with CPython's exact exception
  type and text) and the doc is removed. Two silent wrong values the doc did
  not have fell out of the same helper family: `l == m` was a raw C POINTER
  comparison, and `list.count(x)` had no lowering at all and answered 0.
  This is the second time in this directory that a residue's stated reason
  for existing was stale rather than the residue itself.
- struct kwargs / inline unpack (doc deleted with the fix) — a read with no
  compile-time slot index needs one C type for a heterogeneous value. That is
  the runtime's missing container tag (boxing), not a struct bug. **RESOLVED,
  and the doc deleted 2026-10-02**: the tag is what `mojo_list_get_boxed` /
  `mojo_is_boxed` / `mojo_repr_boxed` are, beside the kinds side table on the
  live `MojoList` address. No bug doc remains open for it.

---

## 3. OPEN

The function-scoped-import module not inlined (its doc is deleted now) —
this entry is STALE. It was PARTIAL on 2026-09-27 (single-TU fixed, link mode open) and
is now **fully fixed and the doc deleted** (2026-09-29): the link-mode half
was three independent defects, not the one the doc predicted — a
`_parsed_import` that could not resolve a bare local `.py` sibling at all, a
duplicated source-text classifier that did not know the `class X:` spelling,
and a second hand-rolled copy of `gen_module_impl`'s inline-compile loop that
skipped the cross-module hint pre-passes. See the 2026-09-29 section of
`bugs/hard/README.md` for the record and for the five *other* bugs the work
surfaced (including one that had the `linkmode` gate step red on master).
Regression coverage: 5 new cases in `test_link_mode.py`, 2 in
`test_gimple.py`.

The fstring / `str()` of a list garbage (doc deleted with the fix) — FIXED
2026-09-27. `_stringify_value` gained the same `MojoList *`/`MojoSet *`/
`MojoDict *` branches (plus boxed-container re-typing) `print`'s dispatch
already had. The fix record for the mechanism it shares is at
`mojo_list_set_kinds` / `mojo_list_get_boxed` in runtime/fire_runtime.c and at
`_STRUCT_CALL_SIGS` in `mojo/backend_gimple/emit_methods.py`.

---

## 4. RECOVERED — existed only in an agent report, verified by me only where marked ✓

These have **no doc**. They are the reason this file exists.

### 4.1 A function returning a local it just bound is typed `int64_t` — FIXED 2026-09-27
    def f():
        var s = 'abc'
        return s
    print(f())          # was 4374205200   -> now abc

The list variant (`s = [1, 2, 3]; return s`) was already correct — the
recorded claim that it was "identical for str and list" was stale; only
string/bytes were still broken. Cause: `_container_literal_locals`
(`mojo/middle/infra_infer.py`, feeding `_infer_return_type`) recorded a
local's first-binding container-literal type for exactly four node shapes
(`ListExpr`/`DictExpr`/`SetExpr`/`TupleExpr`) and explicitly excluded
scalars by design — but a string/bytes literal is a `char *`/`MojoBytes *`
POINTER, the identical "pointer coerced through the int64_t default" hazard
a container is, not a genuine scalar. Added a `StringLiteral` case
(`is_bytes` picks `char *` vs `MojoBytes *`) beside the existing four.
Verified via `test_gimple_runner.py`'s `gimple_return_local_bound_to_string_literal`.

### 4.2 Container printing — FIXED 2026-09-27 (2 of 3), 1 left OPEN
    print([True, False])      # was [1, None]        -> now [True, False]
    print({1, 2})             # was the set's ADDRESS -> now {1, 2}

Fixed: `mojo_repr_list_bools` (new runtime helper, `runtime/fire_runtime.c`)
routed via `_list_repr_fn`'s new `_Bool`-elem branch (`emit_infra.py`); a
new `MojoSet *` dispatch arm in `print`'s type switch (`emit_infra.py`,
beside the existing `MojoDict *`/`MojoBytes *` arms — it simply had none).
Verified via `test_gimple_runner.py`'s `gimple_print_bool_list`/
`gimple_print_set_literal`.

Still open, own doc:
`bugs/CODEGEN_ctor_temp_field_read_loses_element_type.md` —
`print(B4([i for i in range(3)]).v)` → `[None, 1, 2]`, element tracking lost
on a field read off a **constructor temporary** (through a local it is
exactly right). Needs a new call-site-to-field ELEMENT-type tracer, one
level deeper than the container-TYPE tracer §2.1 just landed.

### 4.3 A loop target that rebinds across domains — FIXED 2026-09-27
    for x in [1, 2]: ...
    for x in ['p', 'q']: ...     # was pointer decimals, exit 0 -> now p, q

Fixed in `_gen_for_list` (`mojo/backend_gimple/emit_loops.py`), mirroring
the retype check `_gen_for_set` already had for the loud
`MojoBytes *`/`char *` conflict: `_declare_var`'s deliberate first-decl-wins
is wrong for a loop TARGET specifically (a rebind, not a read), so a second
loop over a different element domain now forces a fresh C declaration
instead of silently keeping the first loop's. Verified via
`test_gimple_runner.py`'s `gimple_for_loop_target_rebind_int_then_str`.

### 4.4 `test_coro_nested_async_capture.py` — FIXED 2026-09-27, registered
Was 0/9, unregistered. Renamed the 7 pre-rename `mojo_*` runtime paths in
`_RUNTIME_SRCS`/`_CORO_CTX_SRC` to `fire_*`, and rewrote
`test_struct_capture_refused_to_cpp` (asserted the *pre*-Increment-E refusal)
into `test_struct_capture_compiles_boxed_and_correct` (asserts compiles,
boxes, and prints the CPython-correct answer, verified via `_build_and_run`).
9/9. Registered in `tools/suite.py` as `coro-nested-capture`, in the
`coroutine` bucket (gate, alongside `coro`).

### 4.5 Attributed 2026-09-27 — `ipaddress` CFAIL is the known callable-value gap
`test_coro_bugs.py` now reports `CFAIL=1 COMPILE=1 LOWERED=2 RAISE=5` (was
`CFAIL=1 LOWERED=2 RAISE=6`; `test_test_string_test_string` moved off RAISE
to COMPILE as a side effect of this session's fixes — not independently
chased down further, since COMPILE is already a clean outcome). The
`ipaddress` CFAIL (77 `__mgco_` refs, then `gcc -fgimple -fsyntax-only`
fails with `expected expression before 'sizeof'` at
`Lib/ipaddress.py:1548`, `self.hosts = self.__iter__`) is attributed: its
own doc, `bugs/CODEGEN_generator_function_Lib_ipaddress.md`, already scopes
the remaining blocker as needing "a dynamic-class-object-as-callable-value
model", explicitly "genuinely feature-sized, not attempted" — the SAME
missing first-class-callable-value representation §2.2 (variadic lambda
call sites) and §2.3 (kw-only param invoked as callee) are blocked on, just
a third symptom of it. Not a fresh mystery; no new doc needed.

Generator value cycles (`q1`↔`q2`) bus-error (138) on unbounded mutual
recursion. A recursion-depth gap, not a value-typing gap; out of scope, and
pre-existing.

### 4.6 Generated C was not reproducible across processes — ROOT-CAUSED AND FIXED

This one started as a footnote ("`test/runtime/test_locks.mojo` produced two
distinct hashes in six batch runs") and turned out to be the most consequential
thing in the campaign, so it is recorded in full.

**It was `PYTHONHASHSEED`.** Same file, same compiler:

    seed=0,1,2,4,6,7,10,12   ->  8861c9cf11d8329c
    seed=3,5,8,9,11          ->  4e0e7e4057d5fe34

Stable **within** a process, two outputs **across** processes. The diff was two
declarations swapping:

    - int64_t * _;            int64_t * rawCounter;     (seed 0)
      int64_t * rawCounter;  + int64_t * _;              (seed 3)

**Cause:** `mojo/backend_gimple/emit_infra.py:1704` iterated `ci.mut_names` —
a **frozenset** — to emit the boxed-mut-capture declarations, so their order
followed Python string hashes. `ClosureInfo.mut_names` is a frozenset
(`mojo/middle/solvers.py`), and the three other `mut_names` uses in the tree
(`module_gen.py:7939`, `:8444`, `emit_funcs.py:99`) are membership tests, so
this was the only unsorted site that reached output. **Fixed** by wrapping it in
`sorted()`, matching the `sorted(gen._boxed_mut_locals)` precedent 50 lines
below. Verified: 10 seeds → 1 hash; 70 stdlib modules × 3 seeds → 0 differing.

Why it mattered: it makes **every "generated C is byte-identical" claim
seed-dependent** unless the seed was pinned, and `bootstrap`'s
stage1 == stage2 == stage3 comparison is exactly the check it can silently
defeat. Any past byte-identity claim made without a pinned
`PYTHONHASHSEED` is weaker than it looked — worth re-checking the ones that
were load-bearing.

---

## 5. One methodological note, because it cost real time

`make gate` reported 3 timeouts in `runner` and 9 in `gimple-runner` right after
a compiled-path edit. **They were cold-cache artifacts, not hangs and not
contention**: the edit changed `compiler_fingerprint()`, so every artifact
rebuilt. Both files pass standalone (151/0, 17/0) and both pass through the
runner. Do not "fix" a timeout you saw right after a closure edit — check
whether the code is even in the file you think it is, and re-run warm.

Two timeouts in this campaign were also **real** and worth keeping: the
variadic-lambda SIGSEGV (§2.2) and the ctor-arg segfault (§2.1) are genuine
crashes, not harness artifacts. The distinction is whether exit 139 reproduces
on a single isolated repro — that is the test.
