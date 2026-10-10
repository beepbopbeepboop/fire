# FORMAL_the_published_surface_figures_are_behind_the_tree: `FORMAL.md` §1/§2.2/§6/§12 publish numbers the tree has outgrown, and TWO registered gate jobs are red on exactly that

**Area:** `FORMAL.md`'s published figures, and the two tests that check the tree
against them. **NOT** the backend: every figure below is a count of something
real, taken by the repository's own instruments, and the documents are what is
behind. **Status:** OPEN, measured 2026-10-05 on `work/formal27-5` at `7ac78995`
and **pre-existing there** — this branch changes no header, no
`build_stdlib_dylib.py`, no `FORMAL.md` and no `runtime/*.c`, which is §3.

**This is filed, not fixed, because the figure sweep is another branch's
project**: `1dd68a48` ("DOCS vs REALITY, part 1: the checkable figures, and an
instrument for them") and `ca50560f` ("part 2") are a worker's deliberate pass
over exactly these paragraphs, and a second pass from this branch would put two
workers' numbers into the integrator's merge for the same eight lines.

## 1. What was run, and what it said

```console
$ python3 test_formal_runtime_link.py
  runtime dylib: export table: 595 of 596 runtime entry points advertised
      arm64: 272 word-shaped, 216 of them exported by the runtime library,
             176 of those reachable without a heap handle (40 need one …)
  FAIL  arm64: 216 word-shaped entry points exported, FORMAL.md §6 phase 2 publishes 206
  FAIL  arm64: 176 reachable with no heap handle, FORMAL.md §6 phase 2 publishes 166
  FAIL  x86_64: 216 word-shaped entry points exported, FORMAL.md §6 phase 2 publishes 206
  FAIL  x86_64: 176 reachable with no heap handle, FORMAL.md §6 phase 2 publishes 166
  159 passed, 4 failed, 163 checks

$ python3 test_formal_doc_truth.py
  FAIL  FORMAL.md §2.2 publishes 668 entry points, runtime_abi() has 683
  FAIL  FORMAL.md §2.2 publishes 262 word-shaped entry points, runtime_abi() says 272
  FAIL  FORMAL.md §2.2 publishes 406 non-word entry points, runtime_abi() says 411
  FAIL  FORMAL.md §2.2 says fire_runtime.h declares 565 entry points, the header declares 580
  FAIL  FORMAL.md restates the non-word count as 406 and runtime_abi() says 411
  FAIL  FORMAL.md §1 says fire_runtime.c is 486 KB, it is 523 KB
  FAIL  FORMAL.md §12 says 51 examples, there are 52
  FAIL  272 word-shaped entry points, FORMAL.md §6 phase 2 publishes 262
  doc truth: PASS=425 FAIL=8
```

**Twelve failures, and ten of them are one number moving.** The runtime surface
grew by 15 entry points since the figures were published: `runtime_abi()` reads
**683** where §2.2 publishes 668, and the word-shaped subset **272** where §2.2
publishes 262. Everything downstream of that inherits the delta — 216 exported
where §6 publishes 206, 176 reachable where §6 publishes 166, 411 non-word
where §2.2 publishes 406 and restates 406.

**The other two are unrelated to the runtime and are the same kind of thing:**
`fire_runtime.c` is 523 KB where §1 says 486 KB, and `formal/examples/` holds
**52** `.mojo` files where §12 says 51.

**The two tests are registered with no `expect=`**, so this is a red the gate
reports rather than a declared state: `tools/suite.py` registers
`formal-runtime-link` and `formal-doc-truth` as ordinary jobs, and neither is
among the eight Lean-checking formal tests this round disabled.

## 2. Why this is worth a doc rather than a `git commit` of eight numbers

**Because the numbers are a function of the tree and the documents are not
watched.** §2.2's `668` and §6's `206`/`166` are read out of the headers by
`model.runtime_abi()` and out of the built dylib's export trie by
`macho_dylib_exports` — both of which move every time an entry point is added,
and entry points are added by ordinary work (`runtime/` and
`build_stdlib_dylib.py` last changed at `2d0f3c0b`, after `1dd68a48` published
the figures on 2026-10-04). **Nothing in the loop re-derives the published
figure, so the drift is invisible until a test happens to compare the two** —
and these two do, which is the only reason this is a doc and not a week of
silence. The `formal-runtime-link` job is the one that caught the export-side
half, and it caught it while building ~20 images, which is the most expensive
place in the tree to learn a paragraph is stale.

**THE NEXT STEP, concretely**, for whoever takes the figure sweep:

1. `python3 test_formal_doc_truth.py` and `python3 test_formal_runtime_link.py`
   name every figure and the value the tree actually has; update `FORMAL.md` to
   those, and update `bugs/FORMAL_known_limits.md` §3.1 (668/262, per
   `formal/build.py::_runtime_library_for`'s own note that the tree-level
   figures live in one place) and the §0.1/§0.3 tables of
   `bugs/FORMAL_runtime_library_on_the_link_line.md` in the same pass — those
   two are the same census and they are now at 272/216/176/40.
2. **Then decide whether the check should keep comparing against prose.** A
   document paragraph is a fine place to PUBLISH a figure and a poor place to
   be the oracle for one: this failure mode is a red that costs a build-heavy
   job to find, and it will recur every time the runtime grows. The
   content-addressed alternative is the shape `bugs/FORMAL_proof_coverage_
   census_2026-10-03.md` §0.8 already uses for the same problem in a different
   subject — a committed per-item ledger plus a ratchet, so the gate compares
   the tree against a RECORD and the document is prose that may be re-derived
   from it. That is a decision, not a patch, which is why it is written down
   rather than done.
3. Do NOT add `expect=` to either job. The two failures are a true statement
   about a stale document, and a marker would convert the next real drift into
   a declared state — the anti-rot half of `expect=` in `CLAUDE.md` is what makes
   a marker cost anything.

## 3. That it is pre-existing, measured rather than asserted

Neither figure can be moved by this branch's diff, and the argument is
structural rather than a re-run:

* `runtime_abi()` reads `runtime/*.h`; `macho_dylib_exports` reads the dylib
  `build_stdlib_dylib.runtime_dylib` builds from `runtime/*.c`. **This branch
  touches no file under `runtime/`, no `build_stdlib_dylib.py` and no
  `FORMAL.md`** — `git show --stat` for the branch is `formal/hostmods/re.mojo`,
  `formal/model.py`, `formal/build.py`, `test_re_formal.py`,
  `test_formal_hostmods_conformance.py`, `test_formal_runtime_link.py` and bug
  docs, and the two `formal/` edits are a refusal MESSAGE and two docstrings.
* `_published_phase2_surface()` reads `FORMAL.md` with two regexes, and the
  numbers it returns (206/166) are the ones printed by `git log -S` as
  introduced by `1dd68a48` on 2026-10-04.
* So both reds are functions of files this branch does not touch, and the
  measured tree values (683/272/411/580/523 KB/52) are what they are on
  `7ac78995`.

The one thing a reader should take from this as a *method* point: the reason
these two reds are easy to misattribute is that `formal-runtime-link` is a
20-image build-heavy job, so the first person to see it after a merge has no
cheap way to ask whether their branch did it. **The cheap way is
`git log -1 --date=short -- FORMAL.md runtime/ build_stdlib_dylib.py`**: if the
runtime moved more recently than the figures, the figures are behind, and no
build is needed to know it.
