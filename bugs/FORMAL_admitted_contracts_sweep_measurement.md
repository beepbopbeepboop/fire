# What the admitted contracts did and did NOT move in the sweep — the measurement, with its caveats

**Status: the measurement for the `sweep5:admitted-hostmods` change. Nothing here
is a claim that coverage improved; `FORMAL.md`'s rule about the reach split applies
directly and the honest answer is that the HEADLINE DID NOT MOVE.**

## What I ran

Two trees, the same 30 files, the same tool, the same arch. The baseline is pinned
by SHA because `master` moved while this branch was being written (see
`FORMAL_relative_import_export_is_not_underscore_filtered.md` for why that matters):

    git archive 24068a01 | tar -x -C .tmp/opencode/base     # the commit I started at
    python3 tools/formal_sweep.py --no-stdlib --arch arm64 -j4 <30 files>   # in each

The 30 files are the first 30 of `git ls-files '*.py' | xargs grep -l '^\s*\(import
subprocess\|from subprocess import\)'` — sorted, so the set is reproducible rather
than picked.

## What I saw

| | baseline `24068a01` | this branch |
|---|---|---|
| files whose REPORTED blocker is `subprocess` | **8** | **0** |
| files in `not-answerable/host-import` (of 30) | 15 | 15 |
| `codegen coverage` | "no file could be answered" | "no file could be answered" |

    baseline: not-answerable/host-import by module: subprocess x8, shutil x2,
              atexit x1, collections x1, glob x1, stat x1, tempfile x1
    this branch: not-answerable/host-import by module: tempfile x5,
              datetime (CPython stdlib) x2, glob x2, shutil x2, atexit x1,
              collections x1, enum x1, stat x1

## THE HONEST READING, and it is much smaller than it looks

**`subprocess` stopped being the reported blocker for 8 files, and NONE of those 8
now builds.** Each of them imports something else with no model — `tempfile`,
`glob`, `shutil`, `enum`, `collections`, `stat`, `datetime`, `atexit` — so each is
still `not-answerable/host-import` and the class counts are unchanged. The class
COUNT did not move and the headline did not move, and `FORMAL.md`'s rule is the
reason that is the right outcome rather than a disappointing one: *"moving the
first group into the denominator would improve the headline without anyone writing
code"*. This change moved no file into any rate.

The tally's shape also changed, and that part is an ARTEFACT worth naming rather
than reading as progress: `tempfile` went x1 → x5 and `glob` x1 → x2 while the total
stayed at 15. The build reports the LAST unresolvable import in a file's statement
list, so which module gets named for a given file depends on the order the imports
happen to be written in — and adding `subprocess.mojo` changes which modules are in
`HOST_MODULES` at all. So the per-module breakdown after this change is measuring a
different thing than the one before it, and only the `subprocess x8 → 0` row is a
like-for-like comparison.

## What a file that DOES build looks like, measured

`.tmp/opencode/sp2.mojo` — four lines, `import subprocess` and `return
subprocess.run("ls -l")`:

    fire.py build --formal --backend=arm64
      Built: …/sp2_arm64.aout  [arm64/macho]
      trust: 7 admitted host contract(s) — a claim of trust, not a proof:
        subprocess.call — assumes of the host: the child's exit status, an integer in 0..255, …
        … (all seven)
      Proof: …/sp2_arm64_proof.lean  [13 declaration(s) ADMITTED a sorry — the file
        typechecks, it is not a proof]

    .tmp/opencode/sp2_arm64.aout ; echo $?
      subprocess: subprocess.run is an ADMITTED contract on this target
      subprocess: this image does not run a second process; the answer is
      subprocess: not computed, and no number here is a child's status.
      125

and the same on `--backend=x86_64` (9 sorries — the x86-64 generator admits a
smaller set, which is its own standing property, not something this change
introduced).

    python3 tools/formal_sweep.py --no-stdlib --arch arm64 sp2.mojo seven.mojo
      BUILT-WITH-ADMITTED-CONTRACTS: sp2.mojo  (7 admitted host contract(s) from subprocess)
      [arm64] 2 files: PASS=1 not-pass=1
      codegen coverage: 1/2 = 50.0%
      (1 pass + 1 built-with-admitted-contracts + 0 codegen + 0 codegen/dependency = 2)

## Why zero of the 30 reach `pass`, and what that is about

Every one of them is a real Python file in this tree, and each is blocked by a
module that has no model yet. Of the blockers named above, four are another
worker's claim and are being written right now — `collections`, `enum`, `stat` and
`shutil` belong to `sweep5:hostmods-core` / `sweep5:hostmods-more`. `tempfile`,
`glob` and `datetime` have nobody. So the next step on those 30 files is not more
admitted contracts; it is the models other workers are already landing, and then
these files move to `codegen` or `codegen/dependency` — a gap in the BACKEND, with
an owner — which is where they should have been all along.

## What this change is worth, stated without the inflation

Not coverage. Three things a coverage number cannot see:

1. **A file that imports `subprocess` is no longer refused for importing
   `subprocess`.** Its diagnostic now names the module that is actually missing,
   which is the difference between "this target cannot" and "this is missing".
2. **The trust is now countable and per-file.** 15 named `sorry`s in the Lean
   model, a `trust:` line per build, a class in the sweep that is in the
   denominator and not the numerator, and a ratchet that fails in both
   directions. Before this, a proof's only admission about the host was
   `lib/ProofLib.lean`'s row 6 — every extern call step, unnamed and unlocated.
3. **The next host module is now cheap.** Writing `tempfile.mojo` is
   `formal/hostmods/glob.mojo` plus a declaration per admitted call; there is no
   machinery left to design, and the machinery that exists is
   `formal/admitted.py`, which reads the declaration out of the Mojo source.
