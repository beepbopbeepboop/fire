# Gate: rthdrscan red again at master tip — three unledgered declarations

**Job:** `rthdrscan` (`python3 tools/suite.py rthdrscan` → `test_runtime_header_scan.py`).
Filed 2026-11-12 from `work/bug-gate-rthdrscan-3`, after the bug:gate-rthdrscan fix
landed on that branch (10b735c35, 7e76766da).

## What was run

Read-only measurement of master tip `35e261a02` (no checkout of master; the
headers were pulled from git objects into a scratch dir and the scan's header
directory pointed at it):

```
for f in $(git ls-tree --name-only master runtime/ | grep '\.h$'); do
  git show master:$f > .tmp/master-headers/$(basename $f)
done
# formal.model.builtins._runtime_header_dir = lambda: '.tmp/master-headers'
```

`runtime_abi()` over the scratch headers reports, on master tip:

- **939** entry points (this branch's tree: **936**)
- **430** word-shaped (branch: **428**)
- **509** not word-shaped (branch: **508**)
- `fire_runtime.h` scans to **829** declarations (branch: **826**)

## What was seen

Three declarations landed on master after this branch's merge base (`b1619eb92`),
in `364787542` ("codegen: unpack a capturing re.sub lambda into (fn, env)
instead of refusing it") and its integration `07fd000c0`, none of which moved
the census ladder or the quoted figures:

- `int mojo_word_contains(int64_t container, int64_t needle);` — word-shaped
- `MojoList *mojo_word_as_list(int64_t w);` — box-shaped (`MojoList *`)
- `char *mojo_word_as_text(int64_t w);` — word-shaped (a `char *` return is a
  word under the `_ctype_is_word` return rule)

Master's own tree is red on this job right now: its ladder (`test_runtime_header_scan.py`)
pins **822** and its FORMAL.md §2.2 quotes **933 / 823 / 426 / 507**, against a
live scan of **829 / 939 / 430 / 509**. The same drift will appear on the
merged tree when this branch lands on top of master tip (this branch's
`runtime/` is byte-identical to `b1619eb92`; only FORMAL.md/`formal/`/
`build_stdlib_dylib.py` quotes and the ladder were moved, to 826 / 936 / 428 /
508 — measured and green on this branch).

## What was expected

A declaration on master bumps the ladder and the quoted census in the same
commit (that is the check's whole point), so `rthdrscan` is green on master and
stays green for every merged branch.

## Exact next step

After this branch is integrated onto current master (or at any sync point),
run `python3 test_runtime_header_scan.py --fix` from the repo root: it rewrites
the ladder (`('fire_runtime.h', 826)` → `829`) and every quoted figure (total
936 → 939, fire_runtime.h 826 → 829, word 428 → 430, box 508 → 509, plus the
§3.2/§5/§6 rest statements in FORMAL.md and the three docstrings in
`formal/build.py`, `formal/model/builtins.py` (×2) and `build_stdlib_dylib.py`)
from the live scan. Then add a ladder rung recording the three names above
(tagged-word container ops from the re.sub capturing-lambda work), run
`python3 tools/memslot.py --gb 8 --label rthdrscan -- python3 tools/suite.py rthdrscan`
and commit. If `--fix` leaves prose that no longer matches (e.g. FORMAL.md's
"`fire_runtime.h` alone grew by 115"), update that sentence by hand in the
same commit.

Do not fix this by editing the three declarations; they are the re.sub lane's
landed work and are correct as declared. The fix is the census rung, nothing
else.
