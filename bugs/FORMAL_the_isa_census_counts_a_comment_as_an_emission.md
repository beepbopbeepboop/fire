# FORMAL_the_isa_census_counts_a_comment_as_an_emission

**Area:** FORMAL, `tools/formal_isa_census.py::call_sites` and the `emitted`
definition it feeds. **Status: OPEN, diagnosed, not fixed. Found 2026-10-08 while
verifying the TST row of `bugs/FORMAL_the_flagged_fuzz_pool_does_not_draw_tst.md`
(this branch's fix, which added TST to `gen_flagged_alu`).**

**Not fixed here because `tools/formal_isa_census.py` is
`bug:FORMAL_arm64_instruction_coverage` / `bug:FORMAL_x86_64_instruction_coverage_backlog`'s
write set (worker `formal158-docs`, which is editing this file on
`work/formal158-docs` today), so it is reported rather than edited.**

## What I ran

```console
$ python3 tools/formal_isa_census.py --arch x86_64 | grep cmov
   encode_cmov_r64_r64            NO   NO   NO   ?     x86_64_codegen.py x1
                                       cmov_r64_r64; NOT asked by formal/x86_64_model_coverage_test
$ python3 test_formal_isa_census.py
AssertionError: Lists differ: [] != [('encode_cmov_r64_r64', ['lean', 'fuzz', 'as_check'])]
```

## What was seen

`encode_cmov_r64_r64` is reported as an EMITTED x86-64 form with no LEAN arm, no
fuzz case and no `as` check, and `test_formal_isa_census.py`'s
`test_every_emitted_form_has_a_model_a_fuzz_case_and_an_as_check` fails on it.
It is not emitted at all: the one "reference" `call_sites` finds is the NAME in a
**comment** in `formal/x86_64_codegen.py` (line ~1803, the `_emit_…` docstring
explaining why the clamp uses two branches instead of a `cmov`). An AST walk of
the two `LEVER_ROOTS` for x86-64 finds **zero** references:

```console
$ python3 - <<'PY'
import ast
for f in ("formal/x86_64_codegen.py", "formal/macho_linker.py"):
    t = ast.parse(open(f).read(), f)
    print(f, [n.lineno for n in ast.walk(t)
              if getattr(n, "attr", None) == "encode_cmov_r64_r64"
              or getattr(n, "id", None) == "encode_cmov_r64_r64"])
PY
formal/x86_64_codegen.py []
formal/macho_linker.py []
```

`call_sites` uses `re.findall(r"\b%s\b" % name, text)` over the emitter files, so
a docstring or comment that merely NAMES an encoder makes it an emitted form.
The census's own docstring already rejects exactly this for the FUZZ and AS
columns — *"AST rather than grep because a docstring mentioning an encoder is not
coverage"* — so the `emitted` definition is the one column that still uses grep.

**Measured scope: `encode_cmov_r64_r64` is the ONLY false positive.** An
AST-based `call_sites` was computed against the current tree and compared with
the regex one: the regex-only set is `['encode_cmov_r64_r64']` for x86-64 and
`[]` for arm64, and the AST-only set is `[]` for both. So the fix removes one
row and changes no other emitted form.

## Why it matters

The census is the RATCHET the whole instruction-coverage argument rests on
(`test_formal_isa_census.py` is the test that says an emitted form has a model, a
fuzz case and an `as` check). A row that is emitted only in a comment is a false
claim of coverage in the other direction: it makes the matrix report a gap that
does not exist, and the test red for a form no image can contain. It is invisible
today only because the arm64 TST gap failed the same test FIRST (arm64 is checked
before x86-64 and `assertEqual` stops at the first arch with gaps); the TST fix
in `bugs/FORMAL_the_flagged_fuzz_pool_does_not_draw_tst.md` removes the mask and
this row is the next failure.

## The exact next step

Make `call_sites` AST-based, the same way `_ast_encoder_refs` already is for the
FUZZ and AS columns (`ast.Attribute`/`ast.Name` whose `.attr`/`.id` is an encoder
name, over `LEVER_ROOTS[arch]`), and re-run
`python3 test_formal_isa_census.py`. The row disappears and no other row moves
(measured above). If a future encoder is genuinely reached through a spelling AST
cannot see — `getattr(A, "encode_x")` — it is not a form the emitter emits
literally either, so refusing to count it is the correct reading, not a hole.

**A second, unrelated red in the same file is NOT this one:** the stale
`encode_imul_r64_r64_imm` `BACKLOG` entry. It is already removed on `master`
(the entry's own comment there says so); it is only present on this branch's base
(`4113d50e`), so the merge resolves it.
