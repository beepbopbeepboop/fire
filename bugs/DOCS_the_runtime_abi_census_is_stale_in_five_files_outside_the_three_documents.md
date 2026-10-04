# DOCS_the_runtime_abi_census_is_stale_in_five_places_outside_the_docs_i_fixed

**Status: open, not fixed.** Found while checking FORMAL.md / `doc/ABI.md` /
`OPUS.md` against the code (branch `work/formal24-docs-truth`). Everything in
those three documents is corrected and pinned by `test_formal_doc_truth.py`;
this is the residue in files that branch's write set did not include, plus the
one *code* defect the audit turned up.

**Not a duplicate** of `bugs/DOCS_deleted_bug_doc_still_cited_in_three_places.md`
(that one is about a doc deleted with its fix and still cited), of
`bugs/FORMAL_known_limits.md` §"Two numbers from the round-1 brief" (that one
records a *correction*, and the census it corrects to is itself now stale), or
of the four other `bugs/DOCS_*` files.

## The number

`formal.model.runtime_abi()` reads every header in `runtime/` through
`reflect.collect_runtime_exports_h` and is the authority. Measured on this tree
(`python3 -c "import formal.model as M; a=M.runtime_abi(); ..."`):

| | count |
|---|---|
| entry points, 11 headers | **668** |
| word in, word out | **262** |
| a box crosses the boundary | **406** |
| `fire_sqlite3.h` word-shaped | **16 of 22** |

Per header: `fire_runtime.h` 565, `fire_sqlite3.h` 22, `fire_ncurses.h` 18,
`fire_python.h` 15, `fire_async_runtime.h` 13, `fire_ssl.h` 13, `fire_coro.h` 7,
`fire_metal.h` 6, `fire_zlib.h` 6, `fire_coro_ctx.h` 3, `fire_wd.h` 0.

## Where the stale figures live

Every one of these is a COMMENT or a bug doc, not a check — which is why nothing
went red. `test_formal_doc_truth.py` reads the three documents and nothing else.

1. **`formal/model.py:14682`**, in the comment above `_runtime_header_dir`:
   *"the shape answers the same question for all **546** entry points the headers
   declare"*. The number is 668. This is the most annoying of the five because
   it is the comment explaining why a constant was deleted, one screen from the
   function that produces the count.

2. **`build_stdlib_dylib.py:1148`** and **`:1461`**: *"measured at **433** of
   `fire_runtime.h`'s **459** entry points today"* and *"with `fire_runtime.h`'s
   459 entry points, only 26 survive `build_stdlib()`'s `nm` cross-check, and
   433 are dropped"*. Both denominators are stale (459 -> 565). Whether the
   *numerator* 26 is still 26 is NOT re-measured here — it needs a stdlib dylib
   build, which is a heavy run, so treat "433 dropped, 26 survive" as unverified
   rather than as known-wrong. If it is re-measured, the ratio is the thing worth
   publishing, not the two absolute numbers.

3. **`test_runtime_header_scan.py`** — **and this one is NOT a defect, so do not
   "fix" it.** Checked and cleared: its live assertion at `:404` is
   `('fire_runtime.h', 565)`, which is correct, and the long ladder of 459 /
   456 / 448 / 450 / ... in the comments is a deliberate record of successive
   headers — the file says so ("Three different numbers have been asserted here
   and all three were right on the tree that produced them, which is why this is
   measured rather than adjusted"). A dated ladder is history, and history with
   a date is what a stale figure is not.

   The one line worth touching is the module docstring's *"After the fix: 459 /
   22 / 6 / 13 / 18 / 15"*, which is undated and so reads as the scanner's
   current output rather than as the 2026-09 state it records. One date on that
   line and nothing else.

4. **`bugs/FORMAL_known_limits.md:925-940`**: *"**223 of 546** is what a link line
   converts into working code with no backend change at all. For
   `mojo_sqlite3_*` it is **18 of 22**."* Both numbers are stale (223 -> 262;
   546 -> 668; 18 -> 16). This paragraph is the *correct* correction of an older
   brief — the reasoning about the scanner mis-scoring `char *f` as returning
   `char` is right and worth keeping — so the fix is to the three figures, not
   the argument.

5. **`formal/build.py:17004`**, in `_runtime_library_for`'s docstring:
   *"the difference is **51** entry points on this tree"* and
   *"`build_config.OPTIONAL_RUNTIME_UNITS`"* — the latter names a symbol that does
   not exist; the table is `_OPTIONAL_RUNTIME_UNITS`, read through
   `optional_unit_names()`. The 51 is the WORD-CALL difference for a *particular
   program*, not the whole word-shaped surface, so it is a number about a case
   rather than about the tree; measured over all 262 word-shaped entry points the
   figure is 56 (`262` word-shaped, `206` exported by the runtime dylib).

## Exact next step

One commit, comment-only except for item 3:

* re-measure with `python3 -c "import formal.model as M; a=M.runtime_abi(); print(len(a), sum(1 for e in a.values() if e['word']))"`
  and put `668 / 262 / 406` in items 1, 2, 4 and 5;
* for item 2's numerator, run the stdlib dylib build once and read the number
  the tool already reports, rather than deriving it — the claim is "only 26 of
  them survive", and 26 is the figure a reader acts on;
* for item 3, add the date to one docstring line and change nothing else;
* then extend `test_formal_doc_truth.py`'s `CITATIONS` idea to these files, or
  (better) make the census itself a printed figure with a test that compares it,
  so a comment cannot carry a second copy of a count at all. That is the change
  that stops this whole class rather than this instance.

## And one real CODE defect, found by the same audit

`formal/model.py::optional_none_word` gives the WRONG REASON for two payload
types it correctly refuses.

```python
>>> M.optional_none_word('Float32', {})
(None, "is an `Optional[Float32]`, and this target has no word to spell `None` as
        for it: it is a struct whose fields this build does not compile, so the
        words it can hold are not known here. ...")
>>> M.optional_none_word('DType', {})
(None, "... it is a struct whose fields this build does not compile ...")
```

Both spellings start with an uppercase letter, and the function's last branch is
`if decls is not None and base[:1].isupper(): return (None, ... "struct whose
fields this build does not compile" ...)`. `Float32` is a SCALAR that
`SCALAR_TYPE_WIDTHS` does not carry — and the function's OWN docstring says so
("`Float32` is absent from the table, and that table's own comment is the reason
why") — so it falls through to the branch meant for a struct of another module.
`DType` is a type tag, not a struct either.

It is not a wrong VERDICT: both are refused, which is correct, and `doc/ABI.md`'s
niche table lists both as refused, which is also correct. It is a wrong
EXPLANATION in a user-facing refusal message — "it is a struct whose fields this
build does not compile" is a claim about a layout the compiler has not read, sent
to a user who wrote a float. The same message would be right for
`SomeOtherModule`'s struct and wrong for `Float32`, and nothing distinguishes
them.

Fix: make the scalar row the authority for a name `SCALAR_TYPE_WIDTHS` or
`FLOAT_TYPE_CTORS` knows about, and restrict the "struct of another module" reason
to names this module's `decls` does not declare **and** that no scalar table
claims. `bugs/FORMAL_optional_needs_a_niche.md` is the subject's own doc and is
claimed by another branch, so this is filed separately rather than appended
there.