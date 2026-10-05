# Two `TestRegister31` cases are red in `test_formal_call_proof_gen.py` — the generator now emits `arm64_reg_or_sp` where they pin `arm64_reg`

**Area:** TEST (`test_formal_call_proof_gen.py::TestRegister31`) · **Status:
OPEN, pre-existing on `master`, measured on `work/formal27-1` 2026-10-04. Not
fixed here: it is outside that worker's claims, and the fix is a decision about
which spelling the generator should use.**

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_call_proof_gen.py TestRegister31
…
FAIL: test_the_model_reads_rn_as_sp_exactly_where_the_assembler_allows_it
     (form='cmp sp, x16')
FAIL: test_the_generator_keeps_its_own_spelling_and_why
AssertionError: … != 'some { s with nzcv := arm64_subs_flags '
Ran 3 tests in 0.255s
FAILED (failures=2)
```

and, to establish it is not this branch, the same two cases on the branch's own
base test file with `git show HEAD:test_formal_call_proof_gen.py` in place
(`cp`, not `checkout`):

```console
$ cp .tmp/base_cpg.py test_formal_call_proof_gen.py && python3 \
      tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_call_proof_gen.py TestRegister31
Ran 3 tests in 0.255s
FAILED (failures=2)
```

Both red before anything on this branch.

## What the two cases assert, and why they no longer hold

`TestRegister31` exists because register 31 is SP on AArch64 and an ordinary
register elsewhere in the encoding space — the family that a NEG reading as
`sp - Xn` when the assembler wrote `-Xn` (fixed in `471e0e5b`) and
`bugs/FORMAL_arm64_ldr_str_unsigned_offset_reads_register_31_as_zero.md` record.
It pins two things about `lib/ProofLib.lean`'s `arm64_step`:

1. **`test_the_model_reads_rn_as_sp_exactly_where_the_assembler_allows_it`**
   cross-checks the library's per-form `Rn` branch against **clang's assembler**
   (`_assembler_accepts`), so it is the case that cannot pass for the wrong
   reason: it first asserts that the oracle accepted the architecture's own set
   of forms, then asserts that each form's branch mentions
   `arm64_reg_or_sp` exactly when the assembler allows `sp` there. It now fails
   on `cmp sp, x16` — so either the library's `CMP`-immediate/register branch
   stopped naming the helper, or the assembler now accepts a form the table
   excludes. **Which of the two is the case's job to say and does not**; the
   message reports the disagreement and stops.
2. **`test_the_generator_keeps_its_own_spelling_and_why`** is the complement and
   is explicit that the two spellings are DELIBERATE: the generator's `_step_rhs`
   says `s.sp`/`arm64_reg`, the library says `arm64_reg_or_sp`, and the step
   lemma closes by `exact`-ing the library's lemma at the concrete word, so the
   two only have to be `defeq`. It fails on `_step_rhs(0xeb1003ff, 6)` — the
   `SUBS Xd, XZR, Xm` word — so **the generator has started emitting the helper**
   (`arm64_reg_or_sp 31 s`), which is what the docstring says it must not do:
   "the `simp only` lists in this generator need the helper in them too", and
   they do not.

## Why it matters rather than being a stale expectation

Case 2's own docstring states the consequence in the conditional: if the
generator emits `arm64_reg_or_sp`, then every downstream
`simp only […, arm64_reg, arm64_set_reg]` goal in `formal/arm64_proof_gen.py`
has to carry the helper as well, "which is what every downstream goal
consumes". A proof that goes wrong that way does not fail where the change was
made — it fails as a `simp` that cannot rewrite, hundreds of seconds later, in
a proof for an unrelated program. So this is the class a NEG read as `sp - Xn`
where the assembler wrote `-Xn` records — an emitted word read as a different
instruction than the one written — caught one step earlier, and it is exactly
the failure the assertion exists to prevent.

## The exact next step

Decide which spelling the generator should emit, and then make the two cases say
it — the cases are the SPEC here, and both directions are defensible:

1. **Keep the generator's spelling** (`s.sp` / `arm64_reg`) and make
   `_step_rhs` name the ordinary register for `Rn = 31` again. Then case 1 is
   about the LIBRARY's branch only and case 2 is about the GENERATOR's, which is
   how they read now, and the `simp only` lists stay as they are.
2. **Adopt the helper everywhere** — emit `arm64_reg_or_sp` from `_step_rhs` AND
   add it to every `simp only […, arm64_reg, arm64_set_reg]` list in
   `formal/arm64_proof_gen.py`. That is the direction case 2's message names, it
   is more uniform, and it costs a regeneration of every emitted proof (so the
   cached verdicts all invalidate — `formal/lean.py`'s verdict cache is keyed on
   the proof text).

Whichever is chosen, case 1 needs its message to say WHICH side disagrees rather
than "one of them is wrong about the architecture": the disagreement is between
`lib/ProofLib.lean`'s branch and clang, and the reader has to be told which one
the assertion compared against what.

`test_formal_call_proof_gen.py` is a registered gate test, so this red is in the
tally today and is declared by no `expect=`.