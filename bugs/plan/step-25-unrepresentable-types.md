# plan/step-25: `Error` stays unrepresentable: make the refusal true, pin it on both backends
**Status: DONE (verified by agent, work landed)**

Class: mid      Size: S      Depends: none      Blocks: 27a
Source: `bugs/FORMAL_known_limits.md` §3 table row "`constructing X has no representation`" (3 files: `std/testing/prop/{__init__,random,runner}.mojo`; NOT 6 — the draft's number was wrong)

## Current state (measured; file:line verified 2026-11-05)
- P0: `python3 -c "import formal.model"` must succeed (HEAD fails: `NameError: threading`, `formal/model/layout.py:3155`; fix with `import threading` as a separate first commit if still so).
- `UNREPRESENTABLE_TYPE_CTORS` is at `formal/model/types.py:200` (contains `Error`, `StringRef`, `Span`, ...). The wording is the single function `unrepresentable_type_ctor_refusal` (types.py:~213), final branch ~line 270: "constructing {X} has no representation on this path: this image has no declaration of {X} to construct — it is not a struct in this module or in anything it imports ... a formal value is one 64-bit word." `type_constructor_prefers_local_struct` is types.py:1106 (arity override for a locally declared struct; `Error()` in a file declaring a 2-field `Error` stays refused).
- Both codegens use the shared reader (`arm64_codegen.py:12005-12018`, `x86_64_codegen.py:13280-13286`).
- Existing pin: `test_formal_run.py:4820` `byref_refuse_unrepresentable_type_constructor` (`Error(r)` with a struct argument, needle `is a real type this path has no representation`). No row with a literal argument `Error("boom")` — the doc claims it is refused with an equally accurate message but nothing pins it. `test_formal_optional.py` has no `Error` row.
- Truth of the sentence "this image has no declaration of Error": in the three stdlib files `Error` comes from the builtin prelude, which the formal path does not import, so the sentence is true OF THESE FILES. It would be false in a file that does import a module declaring `struct Error` — that case is handled by the arity override above, not by this message.

## Decisions already made (made, not open)
- REFUSAL, not a representation. Reason: `Error` = `String` + `Optional[StackTrace]` is >1 word; a heap/boxed `Error` needs the exception-object storage design, which is step-27a's memo. A representation built here would pre-empt that decision. Step-27a consumes this refusal as its baseline.
- No code change to `types.py` unless Work order 1 finds the message false for some case.

## Work order
1. Measure the 3 files on both architectures with the sweep restricted to them (stdlib subtree `std/testing`): `python3 tools/memslot.py --gb 8 --label t -- python3 tools/formal_sweep.py --stdlib <stdlib root, see module_loader.STDLIB_PATH> --stdlib-subtrees std/testing --arch arm64 -j 1`, then `--arch x86_64`. Record per file: class + first sentence. Check `--help` for flag spelling.
2. If any of the 3 is refused with this text but declares/imports a struct `Error`, the message is false for it: change the final branch of `unrepresentable_type_ctor_refusal` to say only what was checked, and add that file's shape as a row. Otherwise no change.
3. Add rows to `test_formal_run.py` next to :4820 (copy its tuple shape exactly, `(name, source, "refuse:<needle>", None)`), needle `is a real type this path has no representation`... use the SAME needle as the existing row so the shared-text rule applies on both backends:
   - `byref_refuse_error_literal_argument`: `def main(n: Int) -> Int:\n    var e = Error("boom")\n    return 0\n`
   - `byref_refuse_error_no_argument`: `var e = Error()`.
   - `local_two_field_error_struct_keeps_refusal_arity`: a file declaring `struct Error` with 2 fields and calling `Error()` (zero args IS a construction per types.py:1190, so expect it to BUILD) — measure first; if it builds, make it a plain build row, if refused, a refuse row. Whatever is measured is the pin.
4. `bugs/FORMAL_known_limits.md` §3 row: replace "3 — ... (`Error`, at depth)" with the measured file list and add "pinned by <row names>".

## Do NOT
- Do not remove `Error` from `UNREPRESENTABLE_TYPE_CTORS` or add a boxed representation.
- Do not touch `DType`/`String()` handling: their over-refusal guards must stay green (`test_formal_run.py` rows named `dtype`/`string_empty`; grep them).
- Do not change the message to name a shape (String + Optional[StackTrace]) the image cannot see.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py byref_refuse_unrepresentable_type_constructor byref_refuse_error_literal_argument byref_refuse_error_no_argument
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_optional.py
```

## Done when
- [ ] the new rows pass on both backends with the identical text
- [ ] `test_formal_optional.py` still passes; DType/String() guards untouched
- [ ] §3 row corrected with measured files

## If stuck
If `Error("boom")` is not refused by this path at all on one backend (a drift), write the two verdicts into §3 and stop; do not invent a representation.
