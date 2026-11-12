# CODEGEN_tagged_generator_mixed_type_step4-part2: tagged-word/container mixed name — refuse with a named diagnostic

**Parent BUG:** `bugs/hard/CODEGEN_tagged_generator_mixed_type_step4.md` (plan step 4, "remove the refusal"; floats and strs are done).
**Class:** mid (this doc lives in `bugs/mid/`).

Depends on part1 (the container census, whose recorded decision is option 2;
the census is `test_tagged_container_corpus.py`). **If part1 recorded option 1 (a real mixed rebind
site was found), STOP and report NEEDS-INFO** — this part implements option
2, which the 2026-11-12 census selected (610 stdlib + 226 repo files, 0
candidates). Do not retarget silently.

## Goal

A name bound to a tagged generator word and ALSO to a container value is
refused today with a generic message that names neither binding. Make the
refusal an honest diagnostic that names the two bindings and the conflicting
types, keep every other behaviour byte-identical, and prove both directions
with a test.

## Current state (measured 2026-11-12, on this branch's HEAD)

The refusal lives in `mojo/backend_gimple/emit_stmts.py`, in the simple-name
assignment arm (~1610–1660). After the step-2 float/str work, float and
`char *` stores are boxed before the check, so the only C types still
reaching it are other pointer types (`MojoList *` / `MojoDict *` / `MojoSet *`
— containers). Two trigger halves raise `RuntimeError(f"{tname!r}: {MIXED_NAME_NON_INT64_REFUSAL}")`:

1. `_tagged_bind and is_non_int_c_type(gen.var_types.get(tname))` — a tagged
   word stored into a name whose declared C type is a container pointer.
2. `is_non_int_c_type(vtype) and ginf.tagged_mixed_name(gen, tname)` — a
   container value stored into a name `tagged_mixed_name` marks as mixed.

`MIXED_NAME_NON_INT64_REFUSAL` (`mojo/backend_gimple/emit_infra.py` ~3744)
reads "a name bound to a tagged generator word … cannot also hold a value of
another C type (str or float): the box cannot carry it; refused".
`test_dict_slot_read_regression.py` Test 2 asserts the substring
`"cannot also hold a value of another C type"` on this path — keep that
substring (in the shared constant, or in whatever constants replace it).

Repro (from `bugs/mid/CODEGEN_tagged_generator_mixed_type_container.md`):

```mojo
def g():
    yield 1
    yield None
    yield 2
def main():
    x = [1, 2]
    for v in g():
        x = v
        print(x)
    print(len(x))
main()
```

raises `RuntimeError: 'x': … cannot also hold a value of another C type (str
or float) …` from the emit_stmts.py site.

## Scope

1. `mojo/backend_gimple/emit_stmts.py`: at the refusal site, produce a
   diagnostic that names (a) the name, (b) the conflicting C type, (c) which
   side was the tagged word and which the container store — e.g. "bound to a
   tagged generator word elsewhere in this function and also to a container
   value of C type 'MojoList *' here; no representation holds both; refused"
   for direction 2, and the corresponding wording for direction 1. You do not
   need the generator's name — name the binding shape and the types. Keep the
   substring `cannot also hold a value of another C type` somewhere in the
   raised text (Test 2 above depends on it).
2. Do NOT change: the float (`mojo_box_from_double`) and str
   (`mojo_box_from_str`) boxing arms, the `_stored_kinds` double-vs-`char *`
   cross-kind arm, any read site, or the runtime. The only behavioural delta
   is the message text on the container path.
3. `test_gimple_generator_runner.py`: add the repro above to
   `run_tagged_for_target_bind_tests` as a `test_generator_refused`-style case
   asserting the new message names the name and the container type (and keep
   the `cannot also hold a value of another C type` substring assertion).
   Cover direction 1 (`for v in g(): L = v` where `L: List[Int]` is declared /
   container-typed) as a second case if the harness allows it cheaply;
   otherwise one case plus a comment naming direction 1 as the same raise
   site.
4. `git rm bugs/mid/CODEGEN_tagged_generator_mixed_type_container.md` in the
   same commit — the decision part1 records closes it (decided option 2, and
   this part lands it). Rewrite the two citations it leaves behind:
   `docs/tagged_generator_mixed_type-plan.md` (the step-4 paragraph part1
   amended) and the `Status (2026-11-11)` line of
   `bugs/hard/CODEGEN_tagged_generator_mixed_type_step4.md` (name the symptom
   — "the mixed container case is a named diagnostic" — not the deleted path;
   keep the hard doc's SPLIT line untouched). Then run
   `python3 tools/dangling_doc_refs.py --ratchet` and fix anything it names;
   it must not gain a citation.

## Acceptance

- The repro above refuses with the new text naming the name, the container
  C type, and the two binding shapes (tagged word here / container here, per
  direction), and still contains `cannot also hold a value of another C type`.
- `test_dict_slot_read_regression.py` Test 2 passes unchanged.
- The new refusal case(s) in `run_tagged_for_target_bind_tests` pass; no
  other case changes state. The 22 known failures stay exactly the ones in
  `bugs/mid/SUITE_gimplegenerators.md`.
- `bugs/mid/CODEGEN_tagged_generator_mixed_type_container.md` is deleted and
  `python3 tools/dangling_doc_refs.py --ratchet` reports no new dangling
  citations.

## Done when

Command (the one suite job that covers this area; `gimplegenerators`, in the
`check` bucket):

    python3 tools/memslot.py --gb 8 --label tagged-container-refused -- python3 test_gimple_generator_runner.py

It exits 0 with the new case PASS, and the failure list contains exactly the
22 cases already recorded in `bugs/mid/SUITE_gimplegenerators.md` (nothing
new red, and `tagged_for_target_*` all green). Also run
`python3 test_dict_slot_read_regression.py` and expect its Test 2 to PASS.

## Not in this part

A container-kind box (option 1) — rejected by the census. Any change to the
float/str arms or the read sites. Reconciling the plan's literal step-4 wording
("Remove MIXED_NAME_NON_INT64_REFUSAL …") beyond the step-4 paragraph part1
already amended.
