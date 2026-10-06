# DOCS: two committed tools rank the same host-import rows with different columns, and two documents draw the same conclusion from them

**Status: OPEN, measured, not started.** Found 2026-10-05 while consolidating
`bugs/`'s formal documents (`work/formal38-docs-consolidation`, claim
`project38:docs-consolidation`). **Not fixed here on purpose, and the reason is
the shape rather than the size:** the two tools are separate REGISTERED gate
jobs with their own test files, and `tools/suite.py` is another lane's write
set. See "Why this was not merged" below — it is a two-tool merge, not a
two-document merge, and doing half of it would leave exactly the duplication
CLAUDE.md forbids.

## The two tools

| tool | lines | input | columns it produces | pins itself in |
|---|---:|---|---|---|
| `tools/formal_host_import_wall.py` | 418 | a sweep log | `reach` (files whose closure names the module), `alone` (files for which it is the ONLY name) | `test_formal_host_import_wall.py` |
| `tools/formal_host_import_shapes.py` | 582 | a sweep log | `files`, `live` (how many of those files still SPELL the module in this tree), `needs` (the use's shape: `WORD` `FIELD` `SUBSCRIPT` `CONCAT` `FSTRING` `BARE` `DECORATOR` `MODULE` `STAR` `DEAD`), `tier` | `test_formal_host_import_shapes.py` |

Both are in `tools/suite.py`, both take the same input, and both rank the same
rows. Between them they are cited by name from **12 `.py` files**, none of them
in a place a docs consolidation may cheaply rewrite: `formal/admitted.py`,
`formal/imports.py`, `consolidate_string_pool.py`,
`tools/formal_chain_probe.py`, `tools/formal_field_walk_differential.py`,
`test_formal_host_import_shapes.py`, `test_formal_host_import_wall.py`,
`test_formal_hostmods_census.py`, `test_formal_fnmatch.py`,
`test_formal_dylib.py`, `test_formal_imports.py`,
`test_formal_sweep_truth.py` and `test_module_cache.py` — plus the `jit/arm64.py`
and `test_formal_interop.py` citations of the shapes document's §3 below.

## The two documents, and the identical conclusion

| document | what it concluded |
|---|---|
| `FORMAL_the_host_import_wall_is_at_its_honest_floor.md` (391 lines) | the 203-file host-import row, ranked by `reach`/`alone`, leaves **six named capabilities** — a run-time-length container, an interpreter's own namespace, module state, a host process, a first-class callable, a `struct tm` — and every row above ~4 files is one of those or out of reach. It is a **TOOL** (`formal_host_import_wall.py`) and its §3's walk is pinned. |
| `FORMAL_a_call_result_field_access_has_no_representation.md` (277 lines) | the same rows re-ranked over `sweep-arm-13.txt` by `needs`, concluding **"it is not reachable by writing a `formal/hostmods/` module"** — a narrower claim, and the two new shapes it adds are `MODULE` (a module OBJECT used as a value) and `BARE` (a module-level name with no call on its chain, which is a fact about the CALLER). Its §3 is cited from **eleven `.py` files** as the authority for what a host-import use IS. |

**Both end at the same place: the remaining rows are a capability question, not
a `formal/hostmods/` question.** And the overlap is not only the conclusion —
`reach`/`alone` answers "could ANY module move this row", while `files`/`live`/
`needs` answers "what do the files actually ask for, and do they still ask",
so `live` is strictly more informative than `reach` about whether a row is
already dead, and `needs` is strictly more informative about what the fix would
have to be.

## Why the DOCUMENTS were not merged here

Because merging them means deleting one of the two §3 references, and the two
are not interchangeable:

* `FORMAL_the_host_import_wall_is_at_its_honest_floor.md`'s §3 walk is **the
  instrument's own definition of its columns** — it is where `reach` and `alone`
  come from, and the tool's docstring points back at it.
* `FORMAL_a_call_result_field_access_has_no_representation.md`'s §3 is **the
  definition of the shape vocabulary** (`WORD` `FIELD` `SUBSCRIPT` `CONCAT`
  `FSTRING` `BARE` `DECORATOR` `MODULE` `STAR` `DEAD`), cited once each from
  ten `.py` files this task does not claim: `formal/admitted.py`,
  `jit/arm64.py`, `consolidate_string_pool.py`, `tools/formal_chain_probe.py`,
  `tools/formal_field_walk_differential.py`, `test_formal_interop.py`,
  `test_formal_host_import_shapes.py`, `test_formal_hostmods_census.py`,
  `test_formal_fnmatch.py`, `test_formal_dylib.py` and `test_module_cache.py`.
  Rewriting eleven sites across files this task does not claim, to save one
  document, is the wrong trade — and it would make the merge the larger change
  rather than the smaller one.

**A reader is not actually lost, and that is the test that decided it:** each
document's first section says which tool produced its table and what the columns
mean, so the second one is found from the first in one hop.

## The exact next step

**Merge the TOOLS, not the documents, and let the documents follow.** In this
order, each step landing on its own:

1. **`tools/formal_host_import_shapes.py` absorbs `formal_host_import_wall.py`'s
   two columns.** `reach` is a superset question of `live` (`live ⊆ files`, and
   a name can be reached without being spelled), and `alone` needs `reach` to
   compute, so the wall tool's walk is the primitive and the shapes tool's
   classification is the layer on top. One tool, four column pairs
   (`files`/`live`/`needs`/`tier` + `reach`/`alone`), one table.
2. **Keep `test_formal_host_import_wall.py` as the acceptance test for the
   merged tool's `reach`/`alone` output** and add its two columns to
   `test_formal_host_import_shapes.py`'s pins; delete the wall test only when
   `tools/suite.py`'s job is repointed, which is the same commit.
3. **`tools/suite.py`: one job instead of two**, `mem='tiny'`, same `extra`
   list. That step needs whoever owns the registry — not this claim.
4. **Then the documents.** `FORMAL_the_host_import_wall_is_at_its_honest_floor.md`
   becomes the §3 the surviving tool points at, and
   `FORMAL_a_call_result_field_access_has_no_representation.md` keeps the shape
   vocabulary and its eleven citations, with one new section saying where the
   `reach`/`alone` numbers now live. Two documents, two non-overlapping jobs:
   "what do the rows need" and "could any module move them".

**What to check before starting**, so the next reader does not re-derive it:

* **`alone` is the column that decided the original document**, and it is the one
  with no substitute: "this module is the ONLY name in the set" is what says no
  host module will ever move the row, and `files - reach` is not that. Measured
  on the corpus: `abc` 236 reach / 0 alone, `importlib` 236 / 0, `builtins` 18 / 2
  — the biggest rows by `reach` are the ones with no `alone` files at all, and a
  ranking that dropped the column would rank them as work.
* **`live` is the column that catches a dead row** and neither other column can:
  `itertools` (14 files) and `datetime` (2) are CLOSED on the shapes tool and
  would both look live to a `files`-only ranking, because the sweep log records
  what a BUILD asked for, not what the tree still spells.
* **The two tools disagree about the input's scope.** The wall doc's 203-file row
  is over an earlier log; the shapes doc's 220 host-import lines are over
  `sweep-arm-13.txt`. Merging the tools must NOT merge the two numbers into one
  row — they are measurements of two rounds, and `bugs/FORMAL_sweep_work_map.md`
  §1.3 is where the round-over-round movement belongs.

**The one thing NOT to do:** delete either document and re-point its citations
without merging the tools first. That is the duplication this project already
pays for once — `bugs/DOCS_merge_left_citations_of_the_docs_the_branches_
deleted.md` records 289 bare citations of documents that were deleted, and 64 of
the number it quoted were the tool's own inverted existence test reporting LIVE
documents as dangling.