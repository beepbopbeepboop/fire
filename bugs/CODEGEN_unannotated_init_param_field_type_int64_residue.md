# An unannotated `__init__` param still types its field `int64_t`, so a `str` reads back as a heap address

Found 2026-09-29 while fixing the same-bare-name struct collision
(`bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`,
removed with that fix).
**NOT a struct-identity problem** — reproduces with a SINGLE module and no
name collision, and identically on `master` (verified by
`git checkout master -- gimple_codegen.py mojo/`, re-running, same
output). This is the shape
`bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`
recorded; that doc was **deleted as fixed**, and re-testing says the shape
is not fully fixed, so it is re-filed here rather than resurrected in
`bugs/hard/`.

## Repro

```python
# mb.py
class Dialog:
    def __init__(self, s):          # NOT annotated
        self.s = s
        self.n = s

# main.py
import mb
def main():
    b = mb.Dialog("hi")
    print(b.s)
    print(b.n)
main()
```

CPython: `hi` / `hi`, exit 0.

Compiled: `hi` / `4372863864`, exit 0.

The second line is the bug and the shape of it matters: `b.s` reads the
`char *` field back **correctly**, so the value is stored properly. But
`b.n` is a SECOND field assigned the same `s`, and it is typed `int64_t`
— so the same `char *` is stored into an integer slot and reads back as
the raw pointer. The number is a heap address: it changes on every run
(ASLR) and is silently wrong rather than absent.

Annotating the param (`def __init__(self, s: str)`) makes both correct —
so the field type is inferred from the constructor call's literal
evidence and unannotated params default to `int64_t` when that evidence
is missing or not unanimous.

## Why this is worth re-filing rather than trusting the deletion

`bugs/hard/README.md` records that **8 of 8** previously-closed reports in
this directory still had live residue when re-tested, and names the
recurring causes: a regression test asserting the CPython-wrong answer, a
test file in no `tools/suite.py` bucket, and "a doc closed on a narrower
*spelling* than the one still broken". This is the third of those: the
doc's spelling was presumably annotated params, and the unannotated one —
the one its own title names — still breaks.

## Next step

`module_gen.py`'s constructor-literal-evidence pass
(`_ctor_lit_param_types`, keyed `"<struct>::<param>"`) is the mechanism
that already types a field from unanimous call-site literal evidence, and
its own comment says "not unanimous → leave unresolved". The unannotated
param here has exactly one call site passing a `StringLiteral`, so the
evidence *is* unanimous and the field should type `char *`. Start by
confirming that pass runs for this struct (the composite key is
`"<struct>::<param>"`, and the struct name is a cname as of
commit 78430fa — check both halves of the key agree), then whether the
result is applied to `self.n` or only to the param the call site names
directly.

Distinct from `CODEGEN_method_returning_self_str_field_segfaults.md`
(filed the same day, removed 2026-10-01 as fixed). That one was a
pointer-typed field returned out of a method, and it segfaulted even with
the param annotated — the fault was upstream, at the CONSTRUCTOR's
argument: an annotated `str` param given an integer was bit-reinterpreted
into the `char *` slot and `strlen`ed. Its fix routes an untracked int64_t
through the model's own discriminator instead of a cast. Re-measured here
2026-10-01: still open, still `hi` / `4370470552`.
