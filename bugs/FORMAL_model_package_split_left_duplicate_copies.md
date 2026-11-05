# FORMAL_model_package_split_left_duplicate_copies: formal/model/ holds the module three times

Found while merging master into `work/fix-merge-bug-formal-formal-a-for-range-target-may` (2026-11-03).

## What I saw

Commit 31ca1c149 ("Reorganize formal/model.py into formal/model/*.py") and 98d73dec4 turned
`formal/model.py` into a one-line shim (`from .model import *`) and put the code under
`formal/model/`:

- `formal/model/__init__.py` — the full module, 56,158 lines. This is the one Python imports.
- `formal/model/_model_original.py` — a second full copy, 55,922 lines. Nothing imports it.
- `formal/model/f00_*.py` … `f11_*.py` — 13 fragments (3,000–8,000 lines each). `f01`'s head is
  `from . import *` followed by a re-typed copy of the CFG section. Nothing imports them either.

So the same code exists in three places, and an edit to one is invisible to the other two.
CLAUDE.md forbids parallel implementations ("consolidate duplicates rather than maintaining
parallel implementations"). The same comment edit had to be applied to `__init__.py` and
`_model_original.py` by hand during the merge, and the fragments were only patched textually.

## Expected

One module, one file per concern. `formal/model/__init__.py` is the module; the dead copies and
the fragments that are not imported are deleted, and any real split is done as an import-level
split of ONE source, not a copy.

## Next step

1. `git grep -n "_model_original\|formal\.model\.f[0-9]"` across the tree: confirm nothing imports
   the copies (as of master 12c00f81b, nothing does).
2. Diff each `f*.py` fragment against the matching region of `__init__.py`. Anything that exists
   only in a fragment is a real divergence and must be merged into `__init__.py` first.
3. `git rm formal/model/_model_original.py formal/model/f*.py`, then `make check` (the
   `formal/model` tests read the module via `formal.model`).
4. `python3 tools/dangling_doc_refs.py --ratchet` — the fragments carry the citations that
   `tools/dangling_refs_baseline.py` counts, so deleting them lowers the ratchet.

## Related

`bugs/FORMAL_a_for_range_target_may_be_read_when_the_range_is_empty.md` was removed by the
fix that merged here; its citations in the package copies were rewritten to name the bug.
