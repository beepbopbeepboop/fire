# TEST_formal_specialization_a_cross_module_specialization_is_refused_by_name: a registered row whose needle is a refusal the build no longer produces for that shape

**Area:** TEST (one row of `test_formal_specialization.py`). **Status: OPEN —
pre-existing, measured on `master` as well as on the branch that found it, so it
is not a regression from anything in flight.** Not fixed here: the row belongs to
the specialization area and the choice it forces is a compiler question, not a
test question (see "The choice", below).

**This is an UNDECLARED red.** `tools/suite.py` registers `formal-specialization`
in the `proofs` bucket with **no** `expect=` marker, so `make gate` counts it as
a failure. Found from the `sweep5:module-state` claim while running the narrow
suites; it is not related to that claim.

## What I ran

```
$ python3 test_formal_specialization.py
  PASS  a specialization's root is a callee, not a read
  PASS  a bare read of an imported name is still refused
  PASS  a subscript of an imported value is refused, not silently dropped
  FAIL  a cross-module specialization is refused by name
        a cross-module specialization is refused for something other than the
        brackets:  name like `exit` or `write` is provided by libSystem. The
        exclusion is measured and settled in bugs/FORMAL_known_limits.md §1.1 …
  ...
formal specialization: PASS=6 FAIL=1
```

Reproduced without the harness, from the row's own fixture
(`lib.mojo` exporting a generic `widen` plus a concrete `anchor`, and
`prog.mojo` calling `widen[3](5)`):

```
$ python3 fire.py build --formal --no-prove --backend=arm64 -o prog.bin prog.mojo
build: main: `widen` is called, and it is imported from `lib`, so the call has
to bind a symbol `lib` exports. That module does not export it, and the reason
is `doc/ABI.md`'s export rule rather than anything about this call: a name with
a leading `_` is private, a generic template is not one symbol but one per
instantiation (`_get_kgen_string[asm]()` is the measured case — both at once),
an overload has no single symbol, and a C library name like `exit` or `write` is
provided by libSystem. The exclusion is measured and settled in
bugs/FORMAL_known_limits.md §1.1, and the generic case in §1.2. …
```

## Why the row is stale, which is a fact and not an opinion

The row checks three things (`test_formal_specialization.py:274-281`): the
refusal names `widen` (it does), it contains `"brackets cannot be bound"` (it
does not), and it says why a cross-module instantiation has no callee (it does,
in different words).

`"brackets cannot be bound"` is still in the tree — `model.specialization_call_refusal`
(`formal/model.py:3151`) is where it comes from, and `test_refusal_taxonomy.py`
pins it — so the sentence was not deleted. **It is simply not reached for this
shape any more**, because for `widen[3](5)` the *export* check fires first:
`widen` is a generic of another module, `reflect.export_exclusions` files it as
`EXCL_GENERIC`, so the dylib does not advertise it, and the call's symbol lookup
refuses before any specialization recogniser is asked.

So the backend's answer for this program did not get worse — it got **more
specific**: it names the actual reason (a generic is not one symbol) and cites
the measured case. The row is asserting a refusal for a different construct, the
way `test_formal_run.py`'s `a_mutated_module_global_is_refused` was (decided and
fixed on 2026-10-02; see `bugs/FORMAL_module_state_no_storage.md`'s "Re-measured
2026-10-02").

## The choice, for whoever owns the specialization area

Two consistent outcomes, and the second is what the tree does today:

1. **`specialization_call_refusal` first.** A call whose callee is spelled with
   BRACKETS gets the specialization sentence whatever the callee resolves to,
   because "the brackets are a generic's comptime parameters" is the more
   informative diagnosis for a program that wrote brackets — and it is the only
   one that mentions that `widen`'s instantiation is the boundary symbol, which
   is the thing a reader of this program needs. Cost: move the check ahead of
   the export lookup for that one shape, and keep the export sentence for every
   other unresolved callee.
2. **The export sentence is the answer here.** Then the row's third check
   already passes and only the middle one is wrong; replace
   `"brackets cannot be bound"` with a needle the export sentence really
   contains, and move the bracket-specific coverage to the shape that still
   produces it (the same file's other two rows, and `test_refusal_taxonomy.py`,
   which pins it at `test_refusal_taxonomy.py:291`).

Either way the row must stop being red, and it is `expect=`-able meanwhile if
the owner wants the gate green before the decision — but note that CLAUDE.md's
rule is that an `expect=` needs a reason and a doc link, and this doc is that
link, so a marker here is legitimate rather than a silencer.

## Also measured on the same run, and NOT filed separately

`test_formal_receiver_position.py` fails 3 of 16 on `master`, and
`formal-receiver-position`'s `expect=` marker says "2 of 12" — so the marker
absorbs two and the third (`refuse_a_dotted_specialized_callee_names_it`, which
now stops at a read-before-assignment message instead) rides along inside the
EXPECTED verdict. That is the subject of
`TEST_expect_marker_undercounts_the_failures_it_absorbs`, so it is
reported here rather than duplicated.

## Scope

Not fixed here, and not a regression from the `sweep5:module-state` work: the
identical `PASS=6 FAIL=1` comes from a `git archive master | tar -x -C
.tmp/mbase` extraction with none of that branch's changes in it. Nothing in
`formal/model.py`'s value model, the two formal codegens, or any other row of
that file causes it.