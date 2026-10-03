# FORMAL_build_cost_2026-10-03: what `build --formal` costs, measured over 43 files, and the two module-level tables a per-function pass was deriving for itself

**Class:** performance. **Area:** `formal/build.py`'s `_prepare_functions`,
`formal/model.py`'s `struct_derived_names`, and the code paths each feeds —
**shared, so every number here moved both backends at once.**

**Status: two of the three costs below are FIXED and verified (byte-identical
artifacts); the third is left with its exact next step in §6.** Nothing in
`formal/build.py` or `formal/model.py` here is a cache: the fix removes two
derivations of a MODULE-level table that a per-FUNCTION loop was making for
itself, which is the same shape as the `wide` / `dispatch_owners` /
`method_owners` tables those loops already read. There is no invalidation
question, because nothing is remembered across a mutation.

---

## 1. The measurement

43 files, one `build --formal --no-prove` each, every one under
`tools/memslot.py --gb 8` and measured by `/usr/bin/time -l` inside it (memcap's
own peak reports at 0.1 GB granularity, which is not enough to say anything
about a process that peaks at 99 MB, so the wrapper is the admission + ceiling
and `time -l` is the number).

    # .tmp/costmeasure.py — the harness, so the numbers can be re-derived
    python3 .tmp/costmeasure.py --arch arm64 --label base --cold \
        --out .tmp/cost-arm64-base.csv --n-stdlib 14

The spread is 16 small `formal/examples/*.mojo`, the 8 largest of those, 14 of
the stdlib's largest files sampled across its tree, and this repository's 8
largest `.py` — chosen so that the sample contains both ends: a file that costs
the fixed cost and nothing else, and `myinterpreter.py`, which cost more than
the other 42 put together. `--cold` gives the run its own empty `GMOJO_HOME`,
so a stdlib import's dylib is BUILT rather than served from `~/.gmojo/cas`;
without that the second measurement of the same spread is mostly a cache read.

### 1.1 Before (`base`) and after (`fix1`), arm64, cold, 43 files

| | wall, all 43 | max peak RSS | `myinterpreter.py` |
|---|---|---|---|
| `base` (`17ddeaec`) | **144.9 s** | 98.6 MB | **53.0 s** |
| `fix1` (this branch) | **94.4 s** | 98.9 MB | **3.8 s** |

Per-file, the ones that moved (full table in `.tmp/cost-arm64-{base,fix1}.csv`):

| file | base | fix1 | |
|---|---|---|---|
| `myinterpreter.py` | 53.0 | 3.8 | **14.0x** |
| `std/_gpu/intrinsics.mojo` | 7.5 | 3.8 | 2.0x |
| `std/iter/__init__.mojo` | 5.4 | 3.2 | 1.7x |
| `test_formal_imports.py` | 6.6 | 4.3 | 1.5x |
| `gimple_codegen.py` | 4.3 | 4.3 | — |
| every `formal/examples/*.mojo` | 0.6-0.7 | 0.6-0.7 | — |

**Nothing here is a memory problem and that is the first result.** The largest
peak over the whole spread is **98.9 MB**, on `gimple_codegen.py`, and 45 of the
43 rows sit between 45 and 99 MB. `bugs/PERF_memory_over_4gb_is_a_bug.md` sets
3-4 GB as the standard and nothing in the formal build is within two orders of
magnitude of it, so this doc is entirely about TIME. (It also means the formal
suite's memory classes are honest: `formal-*` jobs measured at 0.1-0.2 GB.)

**Read the wall-clock with the caveat the machine forces.** Seven other workers
were running formal builds and self-host compiles on the same box throughout
(load average 12-16 on 18 cores), so individual rows carry several seconds of
noise and a few rows moved the wrong way — `std/pathlib/path.mojo` read 3.8 s in
`base` and 9.8 s in `fix1`, which is contention, not a regression: that file's
build is ~1 s of work either way, and the fixed/head comparison in §5 covers it
on the dimension that is not noisy. **The CALL COUNTS in §3 are the finding;
the wall clock only says which way.**

### 1.2 x86-64

The same 43 files, the same harness, `--backend=x86_64`:

| | wall, all 43 | max peak RSS | `myinterpreter.py` |
|---|---|---|---|
| `base` | **119.4 s** | 115.2 MB | **38.1 s** |
| `fix1` | **79.6 s** | 97.7 MB | **3.8 s** (10.0x) |

Measured rather than argued, because the argument ("both backends share
`_prepare_functions`") is a claim about the pipeline and the sweep is the only
thing that can check it. The two architectures differ in the absolute numbers —
arm64's `base` is 144.9 s against x86-64's 119.4 s, and 53.0 s against 38.1 s on
the one file — which is the emitter and not this doc's subject; the SHAPE is the
same, and so is the ceiling: 115.2 MB.

---

## 2. How the numbers were taken, and why not with `cProfile`

**cProfile's TIME column ranks call counts, not time.** A function called 7
million times inflates until it looks like the cost.
`bugs/PERF_formal_build_recomputes_a_per_struct_census_on_every_ask.md`
measured this and left the correction; it is still true, and it decided the
tool: the ranking below is `time.perf_counter` around candidate entry points,
with `cProfile` used only for its call counts and for the shape of the call
tree. The harness:

    # .tmp/phase_timer.py — wall-clock, inclusive, times overlap where one call
    # contains another and the COUNTS are the point.
    python3 .tmp/phase_timer.py build --formal --no-prove --backend=arm64 \
        -o .tmp/t myinterpreter.py

`myinterpreter.py`, 5 572 lines, 275 structs, 1 031 functions, arm64,
`--no-prove`, in-process:

| | time | calls | what it is |
|---|---|---|---|
| `_prepare_functions` | **33.3 s** | 1 | the shared pipeline, and 29.4 s of the 31.2 s total |
| `refuse_none_comparisons` | **20.8 s** | 2 | §4 |
| `_rewrite_class_constants` | **15.4 s** | 596 | §4 |
| `struct_receiver_stores` | 2.4 s | 2 416 | the field-set derivation, §6 |
| `struct_is_one_field` | 2.9 s | 1 031 | §6 |

(`_self_field_names` is absent from this table on purpose: it is recursive, so
its inclusive time double-counts its own nested calls — 7.5 s over 2.6 M calls
is an artefact of that, not a measurement.)

---

## 3. Cost 1, FIXED: a MODULE-level table derived once per FUNCTION — 43 508 times

`formal/build.py`'s `_prepare_functions` has a `for fn in functions:` loop, and
three things inside it are properties of the MODULE rather than of the function
being rewritten. Two of them were being derived inside the loop.

```python
# formal/build.py, _bound_receiver_structs — was
framed = {name: st for name, st in (structs_by_name or {}).items()
          if M.struct_is_framed(st)}
```

`M.struct_is_framed(st)` is not a cheap predicate. It is
`struct_field_count(st) > 1`, and `struct_field_count` is
`len(struct_field_names(st))`, and `struct_field_names` derives the struct's
whole field set by walking **every method body of that struct twice**
(`formal/model.py`'s `_split_declaration` → `struct_receiver_stores` +
`struct_method_receiver_reads`). So one ask is a whole-struct walk of bodies
nobody has touched since the previous ask.

`structs_by_name` is the module's struct table and `framed` is a filter over
it, so the whole map is a function of the MODULE — while the comprehension sat
inside a per-FUNCTION call. Measured, with the immediate caller attributed:

    # .tmp/callers.py — wraps a model function and records ITS caller
    TARGETS=struct_field_names,struct_is_framed,struct_is_one_field,\
    struct_fits_one_word python3 .tmp/callers.py build --formal --no-prove \
        --backend=arm64 -o .tmp/t myinterpreter.py

    46266  struct_field_names  <- model.py:17048:struct_field_count
    43508  struct_is_framed    <- build.py:7800:_bound_receiver_structs
    1031  struct_fits_one_word <- model.py:17185:struct_is_one_field
     377  struct_fits_one_word <- build.py:1981:_struct_methods

**43 508 of the build's 46 512 field-set derivations were one line, asking a
42-struct question 1 031 times.** With `_prepare_functions` itself at 33 s of a
31 s instrumented build and `struct_receiver_stores` at 2.4 s of it AFTER the
fix (33.6 s before), that one line was the file.

The fix derives `framed` ONCE, beside the `wide` table that is already derived
there and read by the same loop, and threads it — plus the two other derivations
of the same predicate in the same function (`publish_placed_frame_structs`'s
first set, and `wide`'s own filter), so the partition has one derivation instead
of three:

```python
framed = {name: st for name, st in structs_by_name.items()
          if M.struct_is_framed(st)}
wide = {name: st for name, st in structs_by_name.items()
        if name not in framed and not M.struct_fits_one_word(st)}
```

### 3.1 The soundness condition, measured rather than argued

The derivation reads the struct's method BODIES, and `_prepare_functions`
rewrites bodies in place between two asks of the same struct
(`_rewrite_self_fields` replaces list elements; `_rewrite_class_constants`
materialises a class-constant read). A table read at the top of the loop is
therefore only the same answer if the derivation does not move under it — which
is a MEASUREMENT, and it was made before the change, over 14 files (this
repository's own largest sources and the stdlib's biggest):

    # .tmp/drift.py — records every answer every struct gets, per question
    DRIFT=struct_field_names,struct_is_framed,struct_fits_one_word,\
    struct_is_one_field,struct_frame_slots python3 .tmp/drift.py \
        myinterpreter.py formal/model.py gimple_codegen.py \
        ../new-modular/.../string.mojo ../new-modular/.../list.mojo ...

    myinterpreter.py:    asks=93550   structs=649   changed=0
    std/math/math.mojo:  asks=5708    structs=878   changed=0
    std/collections/string/string.mojo: asks=5718 structs=888 changed=0
    std/collections/set.mojo: asks=13702 structs=890 changed=0
    std/iter/__init__.mojo: asks=6157 structs=927 changed=0
    … 14 files …
    TOTAL pairs 7788: changed 0, unchanged 7788

**146 779 asks over 7 788 (question, struct) pairs, and not one of them changed
its answer between two asks inside one `_prepare_functions` call.**

Two things make that a soundness argument and not only a green measurement:

* The change is not a CACHE. Nothing is remembered across a mutation; the
  comprehension that ran 1 031 times now runs once, and the value it produces at
  that one point is what the loop reads. The loop previously read the two HALVES
  of the same partition at two different points — `wide` from before the loop and
  `framed` from inside it — so a struct that moved between the two would be in
  `wide` and in `framed` on the same iteration. Computing both once REMOVES that
  inconsistency rather than introducing one.
* The count is pinned by a test, not by a timing. A build that got slower again
  would be noticed by nobody, and one that got faster by answering a different
  question would pass every refusal test in the tree.
  `test_formal_bracketed_method_field_set.py`'s `module table` group runs the
  SAME source twice, with and without eight padding functions, and asserts that
  every per-struct ask COUNT is unchanged (a table derived per function again
  scales with the function count) and that every per-struct answer LIST is
  identical (the derivation does not move under the loop).

### 3.2 Two smaller redundancies in the same neighbourhood

* `_struct_methods` asked `M.struct_fits_one_word(st)` and `M.struct_is_framed(st)`
  **inside its per-method loop** — M whole-struct walks to answer one question
  about the struct. Hoisted above the loop; nothing in that loop mutates the
  struct, so there is nothing for a later iteration to see.
* `_prepare_functions` built `[f.name for f in functions]` **inside** the
  per-function loop and passed it to `_bound_receiver_structs`. `functions` is
  neither rebound nor extended anywhere inside the loop (the
  `_flatten_closures` / `_lift_lambdas` calls that do change the list are after
  it), so the comprehension was loop-invariant: 1 031 × 1 031 name reads on
  `myinterpreter.py`, a million attribute loads to compute one list. Hoisted.

---

## 4. Cost 2, FIXED: the same shape, one order of magnitude worse — 876 575 inheritance fixed points

After §3 the profile's top entry moved, and it moved to a function that had been
invisible behind it:

| | time | calls |
|---|---|---|
| `_constant_read_sites` | 25.6 s | 997 |
| `_enum_member_sites` | **25.1 s** | 997 |
| `struct_derived_names` | **24.5 s** | **876 575** |
| `iter_nodes` | 0.5 s | 6 324 183 |

`formal/build.py`'s `_enum_member_sites(structs_by_name, bound)` builds the
`S.NAME.value` / `S.NAME.name` census — the accessor sites whose absence is the
silent wrong answer its docstring is about (`Reg.R15.value` printing `0` where
CPython prints `15`). It looped over every struct and asked
`M.struct_is_enum(structs_by_name, st.name)`.

`struct_is_enum` is **not a predicate over a class**. It is
`any(name in struct_derived_names(all_structs, base) for base in ENUM_BASES)` —
and `struct_derived_names` is a FIXED POINT over every struct in the module. So
one ask is a whole-module graph walk, and `_enum_member_sites` is called once per
function: **997 × 275 structs × up to 6 bases = 876 575 whole-module fixed
points**, 24.5 s of a 31 s build, every one of them re-deriving a set of enums
that `myinterpreter.py` does not have any of. `bound` is the only per-function
input, and it is the only thing the function still asks.

The fix follows §3 exactly: `_prepare_functions` derives the module's enum table
once, beside the framed one, and threads it through `_constant_read_sites` →
`_enum_member_sites` (and through `refuse_none_comparisons`,
`_rewrite_class_constants` and `_frame_receivers`, which are its other readers).
`myinterpreter.py`: **35.4 s → 4.3 s** after §3 and §4 together, from 53.0 s at
`base`.

`_enum_member_sites` keeps deriving the table itself when handed no table (`None`),
so a caller with no module context — a test, a tool reading one function's
census — still gets the right answer at the cost of one walk rather than none,
and the test asserts the two paths agree site for site over every function in
the unit.

### 4.1 `struct_derived_names` itself: a provably dead filter

The same function ended with

```python
return {n for n in derived if n in set(names)}
```

`set(names)` — a fresh set of every struct's name — was rebuilt once per element
of `derived`, so the tail cost `#derived × #structs` set insertions to return
`derived` unchanged: `derived` only ever receives
`own = getattr(st, "name", None)` from a struct in the same collection that
passed `own is None`, so every member is in `names` by construction. `names` and
the filter are both gone. **The fixed point beside it is untouched** — it is
load-bearing, and `test_formal_bracketed_method_field_set.py`'s
`an_enum_through_two_levels_of_inheritance_is_still_an_enum` pins it through the
ENUM TABLE rather than through the helper's return value, because that is where
it is observable: `struct Reg(MyBase)` with `struct MyBase(Enum)` is an enum
only if the closure is transitive, and if it stopped being transitive
`Reg.RAX.value` would lose its accessor site and print 0. Verified by breaking
the fixed point and watching that row fail.

---

## 5. Verification

### 5.1 Byte-identical artifacts

The bar for a change that is supposed to be behaviour-preserving is byte-
identical generated output on a large case, so the two sides are built from the
same source and the images `cmp`ed:

    # .tmp/bytecmp.sh — builds each case with this branch's formal/build.py and
    # formal/model.py, then with `git show HEAD:`'s, and compares artifact, exit
    # code and full output (the one `-o` path token normalised out). ARCH picks
    # the backend.
    python3 tools/memslot.py --gb 8 --label bytecmp -- \
        bash .tmp/bytecmp.sh spread $(cat .tmp/spread.txt)
    ARCH=x86_64 python3 tools/memslot.py --gb 8 --label bcx86 -- \
        bash .tmp/bytecmp.sh x86spread $(cat .tmp/spread.txt)

**Both architectures, all 43 files each: 23 rows produce an image and every one
is byte-identical; the other 20 are refusals and every one's exit code and full
diagnostic text is unchanged.** That is the dimension the loaded machine cannot
make noisy — a wrong frame layout or a lost constant site would change an image
or a message, not a timing.

The largest image compared is 100 416 B (`std/collections/string/_unicode_lookups.mojo`,
5 876 lines); the formal backends refuse most large real sources, so a larger
BUILDING case does not exist in this tree — which is why the 43-file verdict
comparison, not one big image, is the primary evidence.

### 5.2 Narrow tests run

    python3 tools/memslot.py --gb 8 --label t -- python3 \
        test_formal_bracketed_method_field_set.py     # PASS=26 FAIL=0
    python3 tools/memslot.py --gb 8 --label tfrun -- python3 \
        test_formal_run.py                            # PASS=803 FAIL=0
    python3 tools/memslot.py --gb 8 --label tfimp -- python3 \
        test_formal_imports.py                        # PASS=61  FAIL=0
    python3 tools/memslot.py --gb 8 --label tvm -- python3 \
        test_formal_value_model.py                    # PASS=46  FAIL=0
    python3 tools/memslot.py --gb 8 --label tmpf -- python3 \
        test_formal_method_param_field.py             # PASS=26  FAIL=0

`test_formal_run.py` is the one that matters most for this change: it is the
corpus of class-constant reads, enum accessor sites and frame layouts, which is
exactly what a wrong `framed` / `enum_structs` table would break, and its
`one_field_struct_field_read_is_correct_on_arm64` cases build and RUN both
architectures rather than comparing them to each other.

`test_formal_imports.py` carries `BOUNDED_BUILD_S = 120`, a wall-clock bound on
`std/python/bindings.mojo` (1 997 lines, the deepest import closure in the
sweep) per architecture — a build that used not to finish at all. Measured here
directly, before and after, on both architectures: 2.71 → 2.81 s (arm64) and
2.57 → 2.52 s (x86_64), with the multi-line refusal **byte-identical** on both.
That file is refused early on an import, so it is corroboration and not a
measurement of this change; it is quoted because it is the one file in the tree
whose cost was already known to be pathological.

**Not run by this pass** (light worker; the integrator owns them): `make gate`,
`make check`, `compile_stdlib.py`, `build_stdlib_dylib.py`, the self-host steps
— `formal/model.py` and `formal/build.py` are inside the self-hosted compile
closure, so `mojoc` builds, the three `stage*` steps, `stdlib-dylib`'s
`skip <module>:` count and `stdlib-syntax`'s unexpected count are owed for what
landed here.

---

## 6. What is left, with the next step

After §3 and §4, `myinterpreter.py` is 3.8 s and the residue is the SAME SHAPE
one level down, which is why it is written down rather than guessed at.

* **`struct_is_one_field` is asked 1 031 times** — once per function, by
  `_prepare_functions`' loop (`if st is not None and M.struct_is_one_field(st)`)
  and by `_one_word_field_map` / `_one_word_sole_field_chain` beside it, plus
  `one_field_mutating_methods` (377) and `_collect_one_field_receiver_rebinds`
  (275). 2.9 s of the remaining 3.8 s.
  **Next step: extend the same derivation to the module's ONE-FIELD set** and
  thread it the same way. It is the third predicate of the one partition
  `struct_is_framed` / `struct_fits_one_word` / `struct_is_one_field` already
  are, and this doc's §3.1 measurement (0 drift over 7 788 pairs, which included
  `struct_is_one_field` and `struct_fits_one_word`) covers it exactly. The
  remaining callers to thread are `_one_word_constructor_bindings`
  (`formal/build.py:6613`), which asks it once per BINDING of the function being
  walked and reaches it through `_frame_receivers`'s `_seed_one_word_bindings`,
  and `_overridden_comptime_names`, which asks `struct_derived_names` per struct.
  **Not attempted in this pass**: it is another four signatures, and the win is
  ~2 s on one file against 53 s already taken off it.
* **`struct_receiver_stores` walks every node of every method body to find
  assignments** (2.05 s of the remaining 3.4 s, 2 245 derivations, 6 160 632
  nodes visited for the few thousand assignments it finds). Two things were
  measured about this rather than guessed, because the difference between them
  is the whole of a 2 s question:

  - **Hoisting the type test out of the walk buys nothing.** The obvious first
    move — test `isinstance(node, (F.AssignStmt, F.AugAssignStmt,
    F.MultiAssignStmt))` in the walk instead of calling `_assignment_targets`
    once per node — measured **2.11 s → 2.05 s (3%)**, inside the run-to-run
    noise, because the cost is not the call: it is the 6.16 M generator steps
    themselves. Not landed, and the reason is in the numbers: a 3% win is not
    worth a second reader of the assignment-shape list (the change needed a
    named `_ASSIGNMENT_STMT_TYPES` tuple to stay DRY, so it was a real
    maintenance cost for nothing).
  - **The statement-position walk is the one that works, and its precondition
    now has a MEASUREMENT.** A walk that descends only into list/tuple-valued
    fields and stops at the first non-statement reaches the same assignments
    over ~8x fewer nodes, provided that no statement is reachable only through a
    scalar field. Checked over the corpus rather than assumed:

        # .tmp/stmtcheck.py — walks every parsed statement tree and reports any
        # node whose class name ends in `Stmt` reached through a non-list field
        python3 tools/memslot.py --gb 8 --label stmt -- python3 .tmp/stmtcheck.py
        # -> parsed 516 files; 58 node types seen
        # -> statements reached through a SCALAR field: 0

    **Zero counterexamples over 516 files and 58 node types** — but that is a
    corpus result, not a proof, and the failure mode if a future node type
    breaks it is a field set missing a store, i.e. two real fields aliased into
    one slot, which is the outcome `struct_field_names`' own docstring calls
    worse than a refusal. **So it wants a differential test over the same
    516-file corpus comparing the two walks' assignment SETS, per struct, before
    it lands** — the shape this doc's §3.1 harness already has. This is
    `bugs/PERF_struct_field_split_asked_once_per_function.md`'s step 2, and it is
    the right SECOND half of §3: §3 made the question rare, this would make it
    cheap, and together they mean a future asker cannot put the cost back.
* **`unit_field_evidence` is asked 78 times per build** (2.34 s of the 6.2 s
  instrumented build, with `iter_struct_defs` at 3 857 460 calls under it), and
  the shape is the same recomputation §3 and §4 removed:
  `formal/imports.py`'s `_attach_declared_census(struct_def, declaring_path)`
  runs `M.unit_field_evidence(module_statements(declaring_path))` **once per
  struct declared in that module**, each call walking the whole statement list
  of a module `module_statements` has already parsed and cached. So a module
  declaring S structs pays S whole-module walks, and the answer is a function of
  `(path, content)` — the exact key `module_statements` already caches on, and
  the evidence tuple is immutable `(frozenset, bool)`, so one walk per module is
  sound by construction rather than by an invalidation argument.
  **NOT ATTEMPTED HERE, and it is a claim conflict rather than a difficulty:**
  `formal/imports.py` is the host-module machinery, which
  `tools/control.py claims` shows another worker holding (`sweep14:hostmods-more2`,
  plus `module:platform+fnmatch+collections-rest` and
  `bug:FORMAL_functools_is_unbuildable_as_a_host_module`), and the rule for a
  light worker is to report an area another worker holds rather than edit it.
  The next step is one memo in `_attach_declared_census` keyed the way
  `module_statements` keys itself.
* **`struct_derived_names` is asked 3 185 more times from
  `_overridden_comptime_names`** (`formal/build.py:8501`), which
  `_constant_read_sites` calls once per LOCAL and once per RECEIVER of the
  function being rewritten — the §4 shape one function deeper, and the reason it
  is listed here rather than fixed is the number: at 28 µs per whole-module
  fixed point (24.5 s over 876 575 calls, §4) 3 185 of them is **0.11 s**, so
  the structural fix — one `{name: frozenset(derived names)}` table derived
  beside `framed`, which would also answer `struct_is_enum`'s 876 genexpr calls
  and `_derived_overrides`' 18 — is not worth the surface. Recorded so the next
  profile of this pipeline does not re-derive it.

## 7. What this doc supersedes

`bugs/PERF_formal_build_recomputes_a_per_struct_census_on_every_ask.md` and
`bugs/PERF_struct_field_split_asked_once_per_function.md` both describe the same
redundancy from 2026-10-02, with the same two candidate fixes and the same
warning that a memo across `_prepare_functions` needs an invalidation argument.
**Both candidate fixes in those docs are now measured and rejected in favour of
threading:** the per-struct field set does not drift (§3.1, 0 of 7 788), so the
invalidated memo is not needed — but the cheaper still needs the loop's
per-function askers removed first, or it is paid 1 031 times. Their §"the exact
next step" step 1 (thread `_init_field_assignments` through `struct_field_type`'s
three helpers) is a smaller redundancy inside the same derivation: measured
here at **0.02 s over 704 calls**, so it is no longer worth doing. They are left
in place as the record of the measurement, and this doc is the one to read for
the current numbers.