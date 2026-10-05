# PERF: `struct_field_names` is still asked once per FUNCTION, so the largest compiler sources still miss the sweep's timeout

**Status: still OPEN, and smaller than it was.** Step 1 below (memoize the
derivation with an invalidation argument) was **not** taken and is not needed:
`_prepare_functions` now derives the module's FRAMED table once and THREADS it,
so the derivation is no longer asked per function at all — the soundness
condition step 1 worried about was measured and it holds (146 779 asks over 7 788
(question, struct) pairs across 14 files, zero of which changed their answer
inside one `_prepare_functions` call). `myinterpreter.py` went 53.0 s → 3.8 s on
arm64 and 38.1 s → 3.8 s on x86-64, artifacts byte-identical.
`bugs/FORMAL_build_cost_2026-10-03.md` is the doc to read.
**What is left, both in that doc's §6: step 2 (the statement-position walk —
its precondition is now measured, 0 counterexamples over 516 files and 58 node
types, but it wants a corpus differential test before it lands because the
failure mode is a field set missing a store), and `struct_is_one_field`, still
asked once per function.**

**2026-10-05 (`work/bugs7-4`): the fourth per-function asker is closed.**
`struct_sole_field_name` — the `_one_word_sole_field_chain` read this doc's
sibling measures as a per-function slope — is now `model.sole_field_names`'s
table, threaded beside `one_field` through the eight helpers that ask, and
`test_formal_per_struct_asks.py`'s third case is a strict equality instead of a
slope: **33 asks at 20 functions and 33 at 40**, against 64 and 84 before.
208 artifacts (every `formal/examples/*.mojo`, both backends, the emitter text)
byte-identical. See `bugs/PERF_struct_field_names_is_still_asked_once_per_
function.md`, which is where the numbers and the byte comparison are, and whose
four steps this closed. What this doc's own §6 names as still open is unchanged:
`struct_is_one_field` and the statement-position walk.

**This doc's step 1 — the memo — was NOT taken and is still not needed**, and the
new table is the reason that reads differently than it did on 2026-10-02: a
memo's whole difficulty is invalidation, and a table published once per module
has no window to invalidate inside. The measurement §"Why a memo is NOT the
obvious fix" gives is what makes it safe; a fourth table keyed the same way is
the same argument applied to the same question.

**The 2026-10-02 measurement this doc records, and its `tool`-class framing:**
The 361 files with no verdict were ALL timeouts at `-t 30` (not one a memory
kill, not one a driver error — measured by parsing the sweep log: 361
`TOOL: … (timeout (> 30s))` and zero of any other `tool` cause). Most of that is
fixed and landed (`struct_method_receiver_reads`, `struct_demoted_method_names`,
the per-class field-name caches in `iter_nodes` / `_self_field_names`,
`_constant_read_sites`' spelling filter, `model.class_constant_candidates`); on a
26-file sample chosen to be the LARGEST of the 361, 25 now reach a verdict at
`-t 120` where none did. One file does not, and this is its doc.

## The measurement (2026-10-02 tree + this branch's fixes, arm64, `-j4`)

```
python3 tools/memslot.py --gb 8 --label t -- \
  python3 tools/formal_sweep.py -j 4 -t 120 --allow-concurrent --no-stdlib \
  $(cat .tmp/sample-files.txt)
-> 25 of 26 verdicts;  TOOL: formal/arm64_codegen.py  (timeout (> 120s))
```

Standalone, `build --formal --no-prove` on that file: **40.3s CPU**, ~95-137s
wall on a host at load ~66 on 18 cores. Every other file in the sample is
between 3 and 25s CPU.

**The same 26 files on x86-64, same tree, `-j4 -t 120`: 25 of 26 as well**, with
the same one file outstanding. The cause is in the SHARED model
(`formal/model.py`'s derivations and `formal/build.py`'s site census, which run
before either backend's emitter is reached), so one fix moves both
architectures — but the x86-64 sweep is the only evidence that it does, and the
cause was shared by construction: the 2026-10-02 logs show 361 arm64 and 360
x86-64 timeouts out of 644 files each, the same 361/360 shape. (The x86-64 log's
`tool` class also holds 7 files this arm64 HOST cannot adjudicate — it cannot
dlopen an x86-64 dylib — which is a property of the host, not of the backend,
and is unrelated to this.)


## The shape that is left

`formal/model.py`'s `_split_declaration` derives a struct's whole field set, and
deriving it walks EVERY method body of that struct twice (the `iter_nodes` store
census in `struct_receiver_stores`, the `_self_field_names` read walk in
`struct_method_receiver_reads`). The derivation is a function of the struct's
AST, and it is correct to re-derive it — but its ASKERS are per-function, so a
module with F functions whose methods all live on one big struct pays F walks of
that struct:

```
formal/arm64_codegen.py:  1,836 _split_declaration calls over 81 distinct structs,
                           1,074 of them on ARM64Codegen (177 methods, 15k lines)
```

Callers, by share of the build (sampled, arm64):

| caller | share | reached through |
|---|---|---|
| `struct_field_names` | **81.6%** | — |
| `struct_field_count` | 54.3% | `struct_fits_one_word` (39.7%), the frame pass's width checks |
| `struct_demoted_method_names` / `struct_receiver_stores` | 57.1% | the store census inside every derivation |
| `struct_is_one_field` | 26.6% | `build.py`'s `_one_word_field_map`, `_one_word_sole_field_chain`, `_frame_receivers` |
| `struct_frame_slots` | 27.3% | `build.py`'s `_struct_methods` |

So: `formal/build.py`'s `_prepare_functions` loop asks "is this struct one word?"
and "what are its fields?" once per function, and each ask is a fresh walk of
the owner's 177 method bodies.

## Why a memo is NOT the obvious fix, stated so the next pass does not try it

The derivation cannot be cached across the `_prepare_functions` loop, because
**that loop mutates the very bodies the derivation reads, in place**, between
two asks of the same struct:

* `_take_the_receiver_by_reference` — which is what `_return_the_receiver` was
  called until 2026-10-03 — set `ReturnStmt.value` on an existing node and
  appended to `fn.body`. It does neither now: the receiver is handed over by
  reference and the emitters do the two instructions, so this bullet is history
  for the mutator and live for every walk below it. (`_rewrite_self_fields` and
  `_apply_constant_sites` still replace list elements, which is the property this
  section is about.)
* `_rewrite_self_fields` REPLACES list elements (`node[i] = …`), keeping the
  list's length — so a length- or identity-based validity token cannot see it;
* `_apply_constant_sites` replaces nodes in the same way;
* `_flatten_closures` / `_lift_lambdas` assign a fresh `fn.body`.

The consequence is not hypothetical: for a ONE-field struct, `self.f` becomes
`self`, so after the rewrite the struct reaches and stores neither `f` nor the
name — and a class-level-declared `f` is the only thing keeping it in the field
set. A stale entry therefore produces a field set with a field MISSING, i.e. a
frame laid out one slot short, which builds and computes the wrong answer. This
is why the shipped fixes are all redundancy removal within one derivation
rather than a cache across them.

## The two next steps, in the order I would take them

1. **Memoize the derivation, with the invalidation the invariant actually
   allows.** Inside `_prepare_functions`'s per-function loop the ONLY body
   mutated at iteration *k* is `functions[k]`, so the ONLY struct whose
   derivation can change is `method_owners.get(functions[k].name)`. A memo keyed
   by `id(struct_def)` in `formal/model.py`, invalidated once per iteration for
   that one owner (and in `attach_field_evidence`, which re-attaches evidence to
   structs this unit imported, and in `formal/dataclass_transform.py`, which
   rewrites method bodies before the loop) is sound **if** that list of
   invalidation points is complete — which is the whole of the work, and it wants
   the same treatment `bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`
   gave the equivalent question on the compiled side. It takes
   `formal/arm64_codegen.py` from 1,074 walks of `ARM64Codegen` to ~177 (one per
   method) or better, which is the missing 2 orders of magnitude.
2. **Or make one derivation cheaper, which needs no invalidation at all.** The
   store census (`struct_receiver_stores`, 57% here) is a full `iter_nodes` walk
   that only cares about `AssignStmt` / `AugAssignStmt` / `MultiAssignStmt`
   targets, and a statement is never reachable only through an EXPRESSION field —
   so a statement-position walk finds exactly the same assignments over ~8x fewer
   nodes. The same walk could then also collect the receiver reads
   (`_self_field_names`' answer), taking two walks per method body down to one.
   Ceiling: about 1.5x on this file, i.e. 40s -> ~27s CPU, which would put it
   inside `-t 30` on an unloaded machine. Both halves want a differential test
   over the corpus — the harness that proved the field-name caches equivalent
   (675 files parsed, node sequences identity-compared) is the shape to reuse,
   and the `iter_nodes` vs statement-position assignment sets have to be compared
   on every one of them.

Neither is attempted here: this branch's changes are equivalence-only
redundancy removal, and (1) is a cache whose failure mode is a silently
mis-laid-out frame.

**Not run by this pass** (light worker; the integrator owns them): `make gate`,
`make check`, `compile_stdlib.py`, `build_stdlib_dylib.py`, and the self-host
steps — `formal/model.py` and `formal/build.py` are inside the self-hosted
compile closure, so `mojoc` builds, the three `stage*` steps,
`stdlib-dylib`'s `skip <module>:` count and `stdlib-syntax`'s unexpected count
are owed for the changes that DID land.
