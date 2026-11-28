# GIR stage 5c: `None` is not the integer 0 (the representation decision)

Plan source: `doc/GIR.md`, Stage 5c. Measured 2026-11-21:

    def pick(x): print(x is None)
    pick(0)      # CPython False, compiled True   (WRONG)
    pick(None)   # CPython True,  compiled True
    def pick(x=None): print(x)
    pick()       # CPython None,  compiled 0      (WRONG)

## Why the representation is the blocker

`None` and `0` share the null word. The call site unboxes `None` on purpose
(`emit_infra.py`, `mojo_unbox_plain`): the compiler's own code tests `ptype is None` and
`x or default` by the zero word, and handing a box through once crashed the self-hosted compiler
in `strdup`. So changing the representation touches the self-hosted compiler's own paths.

## Next step (the plan's recommendation)

1. Pass the shared None box (`mojo_box_none()`) for a literal `None` argument to an
   UNANNOTATED parameter, and for a parameter default of `None`.
2. Mark such parameters DynWord (`gen._word_mark_dyn`) in the callee, and make `is None` on them use
   `mojo_word_is_none`.
3. Leave annotated `int` parameters unchanged.

## Acceptance

- The three repros above match CPython under `tools/pydiff.py`.
- `test_gimple_runner.py::test_none_argument_is_none_in_the_callee` still passes.
- The owner runs `make bootstrap` (the self-hosted compiler must still compile itself).

## DECISION (owner-delegated, 2026-11-23): how `None` is represented

The owner delegated the representation decision. This is it, and it replaces "the representation
question is still the owner's to answer" above.

**Rule: a slot's representation of `None` follows the kinds of value the slot can hold.** A slot is any
place a value lives: a local, a parameter, a struct field, a container element, or a return value.

1. **References only, plus `None`.** The slot's non-`None` values are all references (struct pointers,
   `str`, list, dict, set, bytes, generator, ...). `None` is the NULL word, exactly as today. This is
   already exact, because a live reference is never NULL. The compiler's own code (`ptype is None`,
   `x or default` over pointers) lives entirely here, so the self-hosted compiler is unaffected.
   In 5b terms the slot is `Erased(T)`; this is the writer that `Erased` has lacked.
2. **A scalar, plus `None`.** The slot's values include an int, float or bool AND `None`. `None` is the
   shared box `mojo_box_none()` and the slot is a tagged word (5b `DynWord` / `Box`). Every read of the
   slot handles the box:
   - `is None` / `is not None` / `== None` read `mojo_word_is_none`;
   - truthiness reads `mojo_truthy_word`;
   - `print` / `str` / `repr` / f-strings read `mojo_repr_boxed`;
   - a use as a number or reference unwraps with `mojo_box_word` / `mojo_box_int` first.
   A store of a literal `None` writes the box (`box_mixed_store`).
3. **No informative evidence.** Every non-`None` value is of unknown kind, for example an
   unannotated parameter that no call site informs. Nothing changes from today. Boxing unknown slots
   is what crashed the self-hosted compiler before (`emit_infra.py`'s `mojo_unbox_plain` note), so the
   default stays the current word.

**Evidence** is what is stored into or passed to the slot: literals, statically typed expressions, and,
for an unannotated parameter, the kinds of the arguments at every call site, padded defaults included.
An unannotated parameter that only ever receives references or `None` is a references-only slot
(rule 1), so a field stored from it inherits rule 1. One that receives a scalar and `None`
(`pick(0)` / `pick(None)`) is rule 2.

**What this settles in the measured cases:**
- `classes/03_none_field_later_set.py`: `session` gets `None` and an int, so rule 2: box. That is what
  the stashed step 2-3 experiment did, and it is right for this case.
- `classes/12_linked_list_nodes.py` / `13_binary_tree_inorder.py`: `next` gets `None` and
  `next_node`, whose call sites pass only `Node(...)` pointers, `self.head` (a references-only
  field) or the default `None`. That is rule 1, NULL, so no box and no change from today. The
  experiment's mistake was treating an unannotated parameter as "may be scalar"; under this rule it
  is classified by its call sites.
- Never `x == None` as `x == 0` (unchanged).

## Next slice (Sonnet): call-site evidence for the field and parameter classification

1. Find where call-site argument kinds are already collected for unannotated parameters (the
   machinery behind `_box_param_call_args` and the "passed a container at one call site and a str or
   number at another" refusal). Expose one query: `param_value_class(func, param) -> 'refs' |
   'scalar' | 'unknown'`, with `None` arguments ignored. Pin it with a test over the reductions.
2. Make `mixed_field_names(struct)` (`emit_infra.py`) use it. A field whose non-`None` stores are all
   `refs` (constructor calls, references-only fields, `refs` parameters) is NOT mixed. One with a
   scalar literal or a `scalar` parameter is mixed. `unknown` does not make it mixed (rule 3).
3. Re-apply the stashed step 2-3 experiment (store boxing plus the box-aware `is None` read) on top.
   Then add the remaining box-aware reads for a mixed field: the constructor default
   (`self.x = None` in `__init__`), truthiness, and printing.
4. Acceptance: under `tools/pydiff.py`, `classes/03` goes OK and `classes/12` and `classes/13` stay
   OK; `c_oracle check` changes C only for programs that store `None` into a scalar field (list them in
   the status entry); `test_pydiff_ratchet.py` stays green; the closure check shows no new stubs;
   stdlib-syntax shows no new failures.

## Status 2026-11-22: measured; the three repros now pass, the pool does not

Re-measured on master (`9767d4c26`):

- The three repros above match CPython: `pick(0)` prints `False`, `pick(None)` prints `True`, `pick()`
  prints `None`. `tools/pydiff.py` reports the two repro files OK, and
  `test_gimple_runner.py::test_none_argument_is_none_in_the_callee` passes. The 2026-11-21 "WRONG" readings
  are stale.
- The full corpus (`python3 tools/pydiff.py tools/pydiff_corpus -j 6`): 285 programs, OK 135, WRONG 112,
  CRASH 29, GCC 3, REFUSED 3, ERROR 2, TIMEOUT 1. Of the 112 WRONG, 65 contain the substring `None` (a
  crude count; it is not the 32-program pool the workers doc named, and the pool list is not in the tree).
- Not verified here: the mechanism the Next step describes (a literal `None` passed to an unannotated
  parameter as `mojo_box_none()`, and the `mojo_word_is_none` read). The repros pass, so something
  already handles them, but the doc has not confirmed which code path does. Owner's `make bootstrap`
  is still the acceptance check for the self-hosted compiler.

So the three repros are fixed, but the bug is not: the None-related WRONG programs remain, and the
representation question (`doc/GIR_WORKERS.md` §6) is still the owner's to answer. The doc stays open.

**Next step (measurement first):** rebuild the 65 `None`-mentioning WRONG programs' list from a fresh
`pydiff` run (`--out DIR` writes each WRONG program's two outputs), group by the first differing line,
and pick the largest group whose cause is the unannotated-parameter path. That group is the slice.

## Status 2026-11-22 (second round): the largest WRONG group is a field slot, and two pipelines disagree

Grouping the 112 WRONG programs by their first differing line (`pydiff --out`): the largest group is
`None` printed as `0` (about 19 programs, e.g. `classes/03_none_field_later_set`, `flow/13_return_tuple_unpack`).
The 2026-11-21 reading "compiled True" is gone; these are all `None` -> `0`.

**Reduction.** The minimal shape that reproduces through the gimple runner (`compile_mojo_to_gimple_exe`,
the path `pydiff` and the test suite use):

```python
class C:
    def __init__(self):
        self.s = None
    def open(self, x):
        self.s = x          # the field is now an int slot
    def take(self):
        r = self.s
        self.s = None       # a None store into that int slot
        return r
c = C()
c.open(42)
print(c.take())             # CPython: 42
print(c.take())             # CPython: None, runner: 0
```

**Two pipelines disagree.** `python3 fire.py run <file>` prints `None` for the same program, while the
runner prints `0`. So the runner path is the one that is wrong, and `fire.py run` is right for this shape
(the difference is consistent with the link-mode vs inline split in CLAUDE.md's verification notes). The
corpus program `classes/03_none_field_later_set.py` passes under `fire.py run` and is WRONG under `pydiff`.

**Mechanism (measured in code, not yet changed).**
- `emit_infra.py` (`box_mixed_store`, around line 4884) boxes a literal `None` with `mojo_box_none()`,
  but only for a slot that the inference has classified as MIXED (box-holding).
- The field `self.s` is inferred `int64_t` from `self.s = x` (an unannotated parameter receiving an int)
  and is not widened to mixed by the later `self.s = None` store. The `'none'` kind
  (`infra_infer.py` `_param_value_binding_kind`, line ~1862) is accepted for parameters but does not
  widen a struct field slot.
- So the store writes the NULL word, and the word read back prints `0`.

**Next step (one measured change):** find where a struct field's type is joined across its stores
(the field-type inference that fills `struct_field_types` for `self.<name> = <value>` assignments), and
make a `'none'` store join a word-typed field into the mixed (box-holding) kind, the same way a parameter
rebinding to `None` is already accepted. Acceptance: the reduction above prints `42` and `None` under the
runner, `pydiff` on `classes/03_none_field_later_set.py` is OK, and the oracle stays byte-identical
everywhere else (the change alters C only for classes that store `None` into a word field, so it should
change the C of only those programs; confirm the changed set by hash).

## Plan (sixth-round planning output, 2026-11-22): the field-level box

Read in code, not yet changed. The box decision for a name is `ginf.mixed_box_name(gen, name)`
(`mojo/backend_gimple/emit_infra.py`, ~line 4857): a name is box-holding if it is in
`mixed_scalar_locals` (bound to more than one scalar kind), `mixed_value_locals`, `boxed_param_names`,
or `tagged_mixed_name`. Stores go through `box_mixed_store` (emit_infra ~4915) and reads by kind.

The reduction's field `self.s` has NO such classification. Its type comes from
`module_gen.py` (the `struct_field_types` writers around lines 8309, 8553, 8645), where the
`can_override` rule only widens `int`->pointer and self-struct pointers; a `None` store never joins
the field. A store `self.s = None` (MemberExpr target, `emit_stmts.py` ~1536-1560 handles only IdentExpr
targets) therefore writes the NULL word, and a read `r = self.s` gives `r` a single kind, so
`mixed_scalar_locals` never sees a second kind.

Steps, each a separate measured change:

1. **Field join.** In `module_gen.py`, when a class's stores into `self.<f>` include a `None`
   literal and an int/str/float store, record the field as mixed (a new `mixed_field_names(struct)`
   next to `mixed_box_name`, in emit_infra.py). Pin it with a test that asks the predicate for the
   reduction's `C.s`.
2. **Store.** In `emit_stmts.py`'s MemberExpr store path (the attribute arm; find it by the
   `FRAME_SETTABLE_IDS` / `mojo_frame_set_attr` neighbourhood, ~line 1500), call
   `ginf.box_mixed_store` when the field is mixed, exactly as the IdentExpr arm does at ~1742.
3. **Read.** A read of a mixed field (`self.s` as an expression, `_quick_type` / `lower_expr`
   for MemberExpr) returns the box word, and the local it binds to (`r = self.s`) is added to
   `mixed_scalar_locals` by the same per-function walk that already adds names bound to two kinds.
4. **Acceptance.** The reduction prints `42` and `None` under the runner; `pydiff` on
   `tools/pydiff_corpus/classes/03_none_field_later_set.py` is OK; the byte-identical oracle is
   unchanged for every program that stores no `None` into a word field (confirm with
   `c_oracle check`, which will list the changed programs; they should be exactly the
   None-into-word-field ones).

This is a multi-file change to the compiled path. It needs the full stdlib compile and the closure
check after it lands, and it changes C for the programs listed above, so it is not a one-slice
change. The steps above are ordered so step 1 can land alone as measured infrastructure.

**Step 1 landed (2026-11-22):** `mixed_field_names(struct)` in `mojo/backend_gimple/emit_infra.py` (next
to `mixed_box_name`) returns the fields that receive a `None` literal and a scalar literal across a
struct's methods, through nested blocks. `test_gimple_mixed_field_names.py` pins five cases (the
reduction gives `{s}`; None-only, int-only and non-literal stores give none; a store inside `if` counts).
No caller yet, so no C changes: `c_oracle` is identical on 285 C and 13 C++ programs, and
`--closure` reports no new stubs (3 == 3). Steps 2 to 4 (the store, the read, the acceptance) are not
done.

**Step 2 experiment (2026-11-22, measured, stashed, not landed).** Boxing a literal `None` stored into a
word-typed field of the owning struct (owner from the receiver's `var_types` type, the field from
`struct_field_types`), and counting non-literal stores as evidence of a second kind:

- The reduction (`self.s` set to 42 in one method, `None` in another, read back through a local) prints
  `42` and `None` under the runner. The store alone is enough for that shape.
- The corpus program `classes/03_none_field_later_set.py` still differs. The field read sites are not
  box-aware: `c.session is None` and `c.session is not None` answer from the word, not the box, and the
  constructor default `self.session = None` in `__init__` is a struct-initialiser write that the store arm
  does not see (the field starts as 0). Printing a field's box is also not yet a `None`.

So steps 3 and 4 are not optional: every read of a mixed field (`is None`, printing, the constructor
default) has to answer from the box, or the store change makes some programs worse. The experiment is
`git stash` entry "stage 5c step 2 experiment" (diff also saved in the session scratchpad). Next step: the
constructor default and the `is None` read, measured one at a time against the same runner check.

**Steps 2 and 3 measured together (2026-11-22, stashed, not landed).** The store arm (boxes a literal
`None` into a word-typed field of the owning struct) plus a box-aware `is None` read of such a field
(`mixed_field_read` in emit_infra, used by `_lbt_boxed_none_compare` in emit_exprs):

- The reduction prints `42` / `None` (runner SAME). The corpus `classes/03_none_field_later_set.py` goes
  WRONG -> OK.
- Byte-identical oracle: only the four class programs that store `None` into a word field change C
  (03, 12, 13, 32), as intended.
- But `classes/12_linked_list_nodes.py` and `classes/13_binary_tree_inorder.py` go WRONG -> CRASH
  (`AttributeError: value`). Their `next` field is word-typed and receives `None` and a struct POINTER
  (`self.next = next_node`, an unannotated parameter). The box-aware `is None` read then asks the runtime
  for a box kind on a pointer. The "may be scalar" evidence the predicate uses for an unannotated
  parameter cannot tell a scalar from a pointer, so it marks a pointer-linked field mixed.

So this change cannot land as is. It needs a type fact the predicate lacks: whether a non-None store is a
scalar or a struct pointer (the struct field table `struct_field_types` distinguishes only a `Node *`
field, and the `next` field here is word-typed). The experiment is stashed (`stash@{0}`, diff in the
session scratchpad). Next measured step: find where a parameter's scalar-vs-pointer kind is known at the
field store (the constructor's argument binding), and make a pointer-valued store exclude the field from
mixed. Re-measure 12 and 13 against the runner before any landing.

**Second measurement of the step 2-3 experiment (2026-11-22).** `classes/12_linked_list_nodes.py` under
the runner: the first line matches, then `LinkedList.to_list` goes wrong. `LinkedList.head` holds
`None` and the struct pointer from `Node(value, self.head)`; the constructor-call store is a pointer
(syntactically known), so it could be excluded, but `Node.next` is assigned an unannotated parameter
(`next_node`, default `None`) that can hold a pointer. Excluding constructor calls alone does not fix 12.
The runtime `mojo_word_is_none` already answers 0 for a non-box pointer, so the earlier "AttributeError"
is the wrong answer reaching a later dereference, not a runtime fault. The remaining fact needed is what
an unannotated parameter holds at each call site, which is a call-site (interprocedural) question.
The experiment is stashed again (`stash@{0}`).


## Status 2026-11-23 (Sonnet): the call-site classification and the mixed-field box landed

Implements the "Next slice" steps 1-4 of the DECISION. The stash experiment was not visible from the worktree, so
it was re-implemented from the description above.

**Landed.**
- `emit_infra.collect_param_value_obs` (called from `module_gen.gen_module_impl` after the constructor/method
  contract passes) walks every call site of this module (free functions, `recv.method(...)`, `Struct(...)` as
  `Struct___init__`; receivers resolved as the method-observation passes do, plus a syntactic `x = Struct(...)`
  binding, because module-level code is not typed yet at that point) and records, per unannotated parameter, a
  bitmask of the argument classes: refs / scalar / unknown. `None` arguments are skipped; an omitted argument
  contributes its declared default (a `= None` default contributes nothing); a spread makes every parameter unknown.
  Up to three rounds, each into a fresh table, so a forwarded parameter or a field stored from one settles.
  `param_value_class(gen, callee, param)` is the query (`'refs' | 'scalar' | 'unknown'`; callee key is the bare name,
  `Struct_method`, or `Struct___init__`). `value_class_of` is the one classifier for an expression: scalar literals
  and their `-`/`+` forms are scalar; str/list/dict/set/tuple literals, `self`, and `Struct(...)` calls are refs;
  a name is its parameter class, else its inferred type (`double` scalar, any pointer type refs, the `int64_t`
  default unknown); `x.f` is the owning struct's `field_value_class`. Everything else is unknown.
- `mixed_field_names(struct, gen=None)`: mixed iff the field gets a `None` store AND a scalar-class store. A
  str/list literal, a constructor call, a refs-only field or a `refs` parameter is NOT scalar, and `unknown` is
  silence. Without `gen` (the structure-only unit test) parameters are unknown, so only literal stores count.
  `mixed_field_read(gen, struct, member)` is the cached emission-time query; it answers only for structs the module
  itself defines (see the limitation below).
- Store: a literal `None` stored into a mixed word-typed field writes `mojo_box_none()` (`box_word_value`), in the
  MemberExpr arm of `_gen_stmt_AssignStmt`. That arm also covers the constructor default `self.x = None`.
- Read: a field read of a mixed field is marked a Box with the new `FLAG_MIXED_FIELD` (`valueinfo.mark_mixed_field`,
  `GimpleGen._word_is_mixed_field`). The existing box machinery then gives the box-aware truthiness
  (`mojo_truthy_word`) and print/str/repr/f-string (`mojo_repr_boxed`); `_lbt_boxed_none_compare` takes the flag as
  its "box-holding" signal so `is None` / `is not None` / `== None` read `mojo_word_is_none`. Arithmetic on such a
  read is excluded from the kind-select (`_kind_arith_operand`): it holds an int or the None box, never a float
  box, and the select form produced a gcc type mismatch.

**Measured.**
- Reduction (class `C` with `self.s`): prints `42` then `None` under `pydiff`. Saved as
  `tools/pydiff_corpus/classes/41_none_field_reset.py`.
- `pydiff` on 03: WRONG -> OK. 12 and 13: WRONG at the start commit and WRONG now, with identical output apart
  from heap addresses (not worse; their C is byte-identical to the start commit, so the `next` field is correctly
  classified refs-only and left alone). `classes/32_builder_chaining.py` also goes WRONG -> OK.
  `tools/pydiff_ok.txt` gained 03, 32 and 41; `test_pydiff_ratchet.py`: 113 listed programs, 0 failures.
- `c_oracle check --base be9e0b706`: C differs for exactly 03, 32 and 41, each a program that stores `None`
  into a field that also receives a scalar (03: `session` gets `None` and the `open(42)` argument; 32: `limit`
  gets `None` and an int from a call site; 41: the reduction). 283 programs and all 35 coroutine C++ companions are
  byte-identical.
- `c_oracle check --closure`: no new stubs (4, base 4); the corpus C differences are the same three programs.
- `stdlib-syntax` (`compile_stdlib.py`): `FAILED: 0 (0 expected, 0 unexpected)` before and after.
  `test_gimple_lint.py`, `test_type_string_ratchet.py`, `test_gimple_mixed_field_names.py` pass.
  (`test_gimple_mixed_field_names.py` now also runs five end-to-end call-site cases through the real pass.)

**Limitations and what remains.**
- Only a struct defined in the module being compiled is mixed-aware. The decision rests on call sites, and the
  defining module's compile sees only its own; an importer reading the same field with another decision would read
  a box as a bare word. A cross-module scheme needs the decision published by the defining module (a per-struct
  export next to `struct_field_types`); until then a mixed field read from another module keeps the old word read.
- A mixed field stored into a dict/list container: `{"k": c.s}` still prints `0` where CPython prints `None`
  (the container store unwraps the box); `[c.s]` prints correctly.
- The kind of a plain local (`x = 5`) is unknown to `value_class_of` (the `int64_t` default is also the "cannot
  tell" type), so `c.put(x)` with an int local is silence, not scalar evidence. Wiring the `_confident_scalar_locals`
  proof in would widen the scalar side.
- The None-related WRONG programs in the pool other than these (65 at the 2026-11-22 count) are not re-measured
  here, so the doc stays open. Next measurement: rerun the corpus, regroup by first differing line.

## Status 2026-11-27 (local scalar evidence, commit adb949f27)

Wires the `_confident_scalar_locals` proof the 2026-11-23 entry named as the
remaining gap: `value_class_of` now consults a new `gen._pv_local_scalar_kinds`
table (built inside `collect_param_value_obs`, keyed per caller key) so a local
bound once to a provable scalar (`x = 5`) yields `'scalar'` instead of the
`int64_t` "cannot tell" default. A call site `c.put(x)` over such a local is
therefore scalar evidence, so the field joins None+scalar into the boxed
`'mixed'` word slot rather than staying refs-only.

**Measured.** `compile_stdlib.py` 610/610 PASSED, 0 unexpected; `stdlib_dylib_ratchet.py`
clean; `c_oracle check` byte-identical C on 286 programs + 35 C++ companions;
`test_gimple_runner.py` 688 passed / 0 failed (None/mixed/box/tagged/pick/optional/field
selection); `test_pydiff_ratchet.py` 139 listed, 0 failures; `test_gimple_mixed_field_names.py`
0 failures; `test_type_string_ratchet.py` counts 0; `test_type_lattice_predicates.py`
0 failures. `pydiff` still has `classes/03`, `32`, `41` OK.

**Still open.** Cross-module mixed-field export; container store unwrapping
(`{"k": c.s}` prints `0`); the larger None-mentioning WRONG pool is not
re-measured; owner runs `make bootstrap` (self-host) as the acceptance check.
