# FORMAL: two x86-64 base+index forms have neither a fuzz draw nor an `as` check

Part of the x86-64 half of the instruction census (`tools/formal_isa_census.py`,
`test_formal_isa_census.py`).

## Symptom

`python3 test_formal_isa_census.py` fails with exactly two rows:

    ('encode_mov_rm8_r8_idx', ['fuzz', 'as_check'])
    ('encode_movzx_r64_rm8_idx', ['fuzz', 'as_check'])

Both are the base+index spellings of forms that ARE covered in their
base+displacement form:

| covered today | missing |
|---|---|
| `encode_mov_rm8_r8` (fuzz `mov_rm8_r8`, AS case `movb %sil, -1(%rbp)`) | `encode_mov_rm8_r8_idx` |
| `encode_movzx_r64_rm8` (fuzz `movzx_r64_rm8`, AS case `movzbq -1(%rbp), %rax`) | `encode_movzx_r64_rm8_idx` |

## Why they cannot be backlogged

The arm64 gaps in the same census are recorded in `BACKLOG` with a bug doc. This
side deliberately cannot be: `test_no_new_x86_row_lands_on_the_backlog` asserts
that no x86-64 form is on `BACKLOG` at all, so an x86 row may only be cleared by
real coverage. That is the right rule -- otherwise every new x86 form would land
on the exemption list the first time it was emitted.

## What is missing

`formal/x86_64_model_fuzz.py`'s pool builds a memory operand through
`_mem(r, size)`, which is `(_reg(r, MEM_BASES), _disp(r, size))` -- a base plus
a CONSTANT displacement. There is no pool entry that adds an index register, so
`base + index` addressing is never drawn and never compared against the model.
Adding the two forms means teaching the pool (and whatever the harness's memory
model does with the effective address) about a second register in the address,
then adding the matching `as` rows in `test_x86_64_encoders.py`.

## Done when

`python3 test_formal_isa_census.py` exits 0 with these two rows showing both
`FUZZ` and `AS`, and the harness actually comparing an `base + index` effective
address rather than the forms being exempted.
