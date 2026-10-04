#!/usr/bin/env python3
"""What `lib/` actually rests on: `#print axioms` over EVERY declaration in it.

    python3 test_formal_axioms.py [-v]

## Why this is a separate file from `test_formal_admitted.py`

`test_formal_admitted.py` owns the TEXT census (`LIBRARY_TRUST`, and the
`native_decide` ratchet that says which declarations may carry one) and needs no
Lean, which is why it is registered `mem='tiny'` with no `prooflib` dep and runs
in ten seconds.  This one needs the built library — 30 MB of `.olean` — so it
belongs in the `proofs` bucket beside the other Lean-checking tests.  It is the
measurement that file's own header says it cannot make, and
`bugs/FORMAL_native_decide_axiom.md` step 1 is this file.

## What it measures, and the two things only Lean can decide

`formal/admitted.py::library_trust` counts `native_decide`/`bv_decide` SITES in
the source.  That is what a text scan can decide, and it is what the other file
pins.  Two things it cannot decide, and this file is both of them:

1. **TRANSITIVITY.**  `#print axioms` reports what a declaration's proof term
   closes over, so a theorem with no tactic site of its own still reports every
   axiom its callees' proofs used.  A theorem proved from a `native_decide`d
   lemma is invisible to a source scan and completely visible here.
2. **WHETHER A SITE RAN AT ALL.**  A tactic in a losing branch of
   `first | … | …` leaves no axiom.  So the site count can be an OVER-count, and
   `group_census` checks the two against each other in both directions: every
   axiom Lean's report names must belong to a site the census found, and the
   number of distinct axioms must EQUAL the number of sites.

## The name is not `Lean.ofReduceBool`

`bugs/FORMAL_native_decide_axiom.md` predicted that `#print axioms` would report
`Lean.ofReduceBool`, and on the pinned toolchain (leanprover/lean4:v4.32.2) it
does NOT.  `ofReduceBool` is deprecated there — "in-kernel native reduction is
deprecated; assert native evaluations with axioms instead" — and each USE of a
reflection tactic elaborates to a FRESH axiom named after the DECLARATION that
used it:

    'work_step_mov._native.native_decide.ax_1_1'
    'arm64_flag_ge._native.bv_decide.ax_1_7'

The `_1_7` counts reflection uses in the whole MODULE, so deleting one site's
axiom renumbers every later one in the file, which is why no row here pins an
index.  A census that grepped for `ofReduceBool` would have called a library
that reaches an axiom at every one of its 686 sites CLEAN.
`formal/lean.py::GENERATED_AXIOM_RE` is the shape that is actually matched, and
`formal/lean.py::AXIOM_FOUNDATION` — `propext`, `Quot.sound`,
`Classical.choice` — is the rest of what a Lean proof may legitimately rest on.

## The groups

  census    every declaration in `lib/` was asked, every answer parsed, and the
            axiom set is exactly `AXIOM_FOUNDATION` plus one generated axiom per
            counted site — no more, no fewer, none unattributed
  headline  eight named theorems, pinned by how many generated axioms they
            reach, as the BEFORE and AFTER of the 2026-10-04 replacement
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_formal_dylib import TestFailure, check  # noqa: E402  (one failure type)
from formal import admitted as A                  # noqa: E402
from formal import lean as L                      # noqa: E402

# Import order matters and is the library's own: `ProofLib` first because every
# other module imports it, `Contracts` last because it imports `Refine` too.
LIBRARY_MODULES = ("ProofLib", "Refine", "X86", "work", "Contracts")
FOUNDATION = set(L.AXIOM_FOUNDATION)

# The theorems whose axiom set this campaign CHANGED, plus the three that keep
# theirs, pinned by the NUMBER of generated axioms each reaches.  Eight rows
# rather than 43, because a table of every replaced theorem name is a list
# nobody can read; the global claim is `group_census`, which covers all 513
# declarations and needs no table at all.
#
# Zero is the headline.  `work_step_mov`'s whole proof is an `hne_ret` that used
# to be a `native_decide` refuting `0xd65f03c0 &&& 0xffe00000 = 0x2a00fa00` — a
# CLOSED proposition over literals, so `decide` discharges it and the KERNEL
# checks it.  `arm64_step_cmp_reg_n31_reads_zero` is the row to read first: it is
# the `SUBS X0, X31, X1` word, seven sites of that shape at seven masks, and it
# is the theorem that says the shifted-register `SUB`/`SUBS` forms read `Rn` of
# 31 as the ZERO register — which is what a `NEG` is, and what this tree's
# predecessor had wrong: the row was `arm64_step_cmp_sp_reads_sp` and it
# asserted the opposite, from an encoding clang does not even emit for
# `cmp sp, x16`.  The row is named after the WORD rather than after the
# mnemonic for that reason, and `test_formal_call_proof_gen.py`'s
# `TestRegister31` is where the machine was asked which one it is.
#
# The two non-zero counts are named rather than left open, because the SHAPE is
# the finding: `work_step_movk`'s 57 `bv_decide` sites are each a `∀ w, …` over a
# 32-bit word, which is the one shape in this tree that `decide` cannot take,
# and the three that keep one `native_decide` are ground `runExport`/`InImage`
# evaluations whose reasons are in `test_formal_admitted.py`'s
# `NATIVE_DECIDE_ALLOWED`.
HEADLINE = {
    ("Contracts", "Contracts.spec_triple_ne_identity"): 0,
    ("X86", "lowMask_eight"): 0,
    ("ProofLib", "work_step_mov"): 0,
    ("ProofLib", "arm64_step_cmp_reg_n31_reads_zero"): 0,
    ("ProofLib", "arm64_step_neg_reads_zero_rn"): 0,
    ("ProofLib", "arm64_step_mul"): 0,
    ("ProofLib", "work_step_movk"): 57,
    ("ProofLib", "DylibExport.Semantics_refutable"): 1,
    ("ProofLib", "DylibExport.backward_branch_run_none"): 1,
    # The one site in `lib/` that reaches no axiom at all, and the reason the
    # census above is a bound rather than an equality.  See
    # `SITES_NEEDING_NO_AXIOM`.
    ("X86", "x86_call_ret_restores_rip"): 0,
}

# A `bv_decide` site that produces NO generated axiom, and the reason.
#
# Measured, not assumed, and it is the reason the central assertion below is a
# `>=`-shaped bound rather than an equality.  Lean discharges
# `∀ w : UInt64, w &&& 0xFFFFFFFFFFFFFFFF = w` INSIDE THE KERNEL — the mask is
# all ones, so the bit-blast normalises `w &&& allOnes` to `w` and the
# reflection needs no assertion at all.  Three identical `bv_decide` proofs of
# exactly that statement, asked directly, each report
# `[propext, Classical.choice, Quot.sound]` and no `._native.bv_decide.…`.
#
# So a `bv_decide` SITE is an UPPER BOUND on an axiom, and `lib/` currently has
# one site of the kind.  This table is what makes that a number rather than a
# tolerance: a site added here is a finding in its own right (a `bv_decide` that
# needs no axiom is a debt that was never owed), and a site removed from here
# without a `bv_decide` disappearing is the site count having started to lie.
SITES_NEEDING_NO_AXIOM = {
    ("X86", "x86_call_ret_restores_rip"):
        "lib/X86.lean:2491 — `∀ w, w &&& 0xFFFFFFFFFFFFFFFF = w`, which Lean "
        "discharges in the kernel because the mask is all ones. Measured: three "
        "identical `bv_decide` proofs of that statement reach only propext, "
        "Classical.choice and Quot.sound.",
}

# Declarations `#print axioms` CANNOT be asked about, and why.  Lean's parser
# reads the trailing `'` of `mem_read_two_writes_adjacent'` as the opening of a
# character literal, so the command names a different constant and answers
# `Unknown constant` — a fact about the COMMAND, not about the declaration, and
# the shape that `group_census` would otherwise have to read as "the generated
# file did not elaborate".
#
# It is a suffix rather than a list because the suffix IS the rule; it is applied
# once, in `_library_declarations`, and `group_census` checks that none of the
# dropped declarations carries a tactic site — so if somebody puts a `bv_decide`
# in one of them the count below stops closing and the test says which
# declaration made it unable to.
UNASKABLE_SUFFIX = "'"


def _library_declarations():
    """`({module: (askable names…)}, {module: (unaskable names…)})` for `lib/`.

    `A._declarations` rather than a second scanner, because there is one answer
    to this question in the tree and two of them would be two things that can be
    wrong.  The split is `UNASKABLE_SUFFIX` and nothing else, and
    `group_census` checks the half that is dropped.

    **`private` is dropped too, and that drop is checked rather than assumed.**
    Lean mangles a `private` declaration's name, so `#print axioms <its name>` is
    an `Unknown constant` — which `group_census` reads as "the generated file did
    not elaborate" and fails on.  So the question this has to answer is whether
    any PRIVATE declaration carries a tactic site, because then its axioms exist
    and cannot be named and `group_census`'s per-declaration arithmetic could not
    close.  `lib/` has one `private` declaration (`private def stmtsSize`) and it
    has no site, which is a fact about this tree and not a fact about `private`.
    """
    lib = A.lean_dir(HERE)
    askable, dropped = {}, {}
    for mod in LIBRARY_MODULES:
        path = os.path.join(lib, mod + ".lean")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            code = A.lean_code_regions(f.read())
        yes, no = [], []
        for _line, name, public in A._declarations(code):
            if not public:
                no.append(name)
            elif name.endswith(UNASKABLE_SUFFIX):
                no.append(name)
            else:
                yes.append(name)
        askable[mod] = tuple(yes)
        if no:
            dropped[mod] = tuple(no)
    return askable, dropped


def _dropped_with_sites(dropped):
    """`{module: {name: lines…}}` for the dropped declarations that carry a site.

    Must be empty, and it is the reason `dropped` is returned rather than
    discarded inside `_library_declarations`: a declaration whose axioms cannot be
    asked about but which HAS them would make the central arithmetic here
    unclosable, and the only honest report of that is to fail.
    """
    lib = A.lean_dir(HERE)
    out = {}
    for mod, names in dropped.items():
        with open(os.path.join(lib, mod + ".lean"), encoding="utf-8") as f:
            code = A.lean_code_regions(f.read()).split("\n")
        decls = A._declarations("\n".join(code))
        for i, (line, name, _public) in enumerate(decls):
            if name not in names:
                continue
            last = decls[i + 1][0] if i + 1 < len(decls) else len(code) + 1
            at = tuple(n for n in range(line, last)
                       if A._TACTIC_RE.search(code[n - 1]))
            if at:
                out.setdefault(mod, {})[name] = at
    return out


def _ask(per_mod, verbose):
    """`(run, {(module, name): axioms | None})` for every declaration in `lib/`.

    `ensure_library` first, for the reason CLAUDE.md records about a shared
    expensive dependency: a check-then-act on `lib/*.olean` without it is a cache
    stampede, and `ensure_library` takes the exclusive `flock`, re-checks inside
    it, and writes through a private temp.  When the tree's library is already
    current that is a stat rather than a build, which is what makes this cheap to
    re-run and what the `prooflib` dependency is for.

    Every declaration is asked, not only the ones the census attributes a site
    to, because TRANSITIVITY is one of the two things this file exists to see.
    """
    lean = L.find_lean(HERE)
    lib = A.lean_dir(HERE)
    started = time.monotonic()
    L.ensure_library(lean, lib)
    if verbose:
        print(f"    library ready in {time.monotonic() - started:.1f}s")
    names = [(mod, n) for mod in sorted(per_mod) for n in per_mod[mod]]
    run, got = L.print_axioms(
        lean, lib, list(LIBRARY_MODULES), [n for _m, n in names],
        wall_s=L.library_bounds()[0], cpu_s=L.library_bounds()[1],
        mem_mb=L.LEAN_MEMORY_MB)
    return run, {(m, n): got.get(n) for m, n in names}


def _own_axioms(got):
    """`{declaration: (axiom, …)}` — what each declaration's OWN PROOF contributed.

    **`#print axioms` is transitive**, so one axiom appears in the answer for the
    theorem that created it AND for every theorem that calls it, and counting per
    ANSWER rather than per AXIOM multiplies: asked about all 600 declarations,
    `mem_read_bytes_write_same`'s two axioms appear 3 times and
    `work_step_str_uoff`'s 66 appear twice.  So this is built from the set of
    DISTINCT axioms, each charged to the declaration it is NAMED AFTER
    (`GENERATED_AXIOM_RE`).  That is also the number `SITES_NEEDING_NO_AXIOM`,
    `NATIVE_DECIDE_REPLACED` and `HEADLINE` are all talking about, which is why
    one function computes it for all of them.

    Keyed by bare declaration name, not by `(module, name)`: the axiom's own name
    carries whatever qualification the DECLARATION had, and a module's
    contributions are already separated by the axiom being distinct.
    """
    own = {}
    seen = set()
    for axioms in got.values():
        if axioms is None:
            continue
        for ax in axioms:
            if ax in FOUNDATION or ax in seen:
                continue
            seen.add(ax)
            m = L.GENERATED_AXIOM_RE.match(ax)
            if m:
                own.setdefault(m.group("decl"), []).append(ax)
    return {k: tuple(v) for k, v in own.items()}


def _census_site_names():
    """`(qualified, bare)` name sets the text census attributes a site to.

    Both, because the axiom's own name carries whatever qualification the
    DECLARATION had and the census carries the qualification the MODULE gave it,
    and those agree today (`DylibExport.backward_branch_run_none`) but do not
    have to: a declaration at `lib/ProofLib.lean`'s top level produces
    `work_step_mov._native.…` with no module in it.  Matching on either is what
    lets the check report an unattributed axiom rather than a mismatch of
    spellings, which is the same distinction `test_formal_admitted.py` makes
    when it refuses to treat an unknown declaration as a clean one.
    """
    qualified, bare = set(), set()
    for per in A.library_trust_by_declaration(A.lean_dir(HERE)).values():
        for name, (n, _lines) in per.items():
            if n:
                qualified.add(name)
                bare.add(name.rsplit(".", 1)[-1])
    return qualified, bare


def group_census(per_mod, dropped_names, got, verbose):
    """Every axiom in `lib/` belongs to a counted site, and says which theorem.

    Six checks, each a way the correspondence can break that the others cannot
    see:

      * a declaration the census names that Lean reported NOTHING for is a
        disagreement — an `Unknown constant`, so the generated file did not
        elaborate — rather than a clean answer.  Without this a wholesale
        failure reports "no axioms anywhere" and PASSES, which is not a
        hypothetical: an `import A B C` line left four of the five modules
        unimported and 230 of 513 declarations missing, all of them in the
        modules that did NOT import;
      * an axiom matching neither `AXIOM_FOUNDATION` nor `GENERATED_AXIOM_RE` is
        something the text census cannot see at all, and is reported by name;
      * a generated axiom whose owner the census attributes NO site to is the
        site count being an UNDER-count;
      * PER DECLARATION, the number of axioms named after a theorem equals its
        own site count less `SITES_NEEDING_NO_AXIOM`.  This is the check with the
        most teeth: it says *which* theorem's site is unaccounted for rather than
        only that the totals differ, and it is local, so a change in one theorem
        cannot be absorbed by another;
      * and a declaration this file could not ASK about — private, or a name
        ending in `'` — carrying a site, whose axioms exist and cannot be named,
        so the arithmetic could not close at all.
    """
    qualified, bare = _census_site_names()
    per_decl = A.library_trust_by_declaration(A.lean_dir(HERE))
    sites = sum(n for per in per_decl.values() for n, _lines in per.values())
    missing = sorted(k for k, v in got.items() if v is None)
    own = {name: len(axs) for name, axs in _own_axioms(got).items()}
    generated = {}
    unknown, unattributed = [], []
    for (mod, name), axioms in sorted(got.items()):
        if axioms is None:
            continue
        for ax in axioms:
            if ax in FOUNDATION:
                continue
            m = L.GENERATED_AXIOM_RE.match(ax)
            if not m:
                unknown.append(f"{mod}.{name} reaches {ax}, which is neither a "
                               f"foundation axiom nor a per-use "
                               f"`._native.<tactic>.ax_N_M`")
                continue
            generated[ax] = m.group("decl")
            if m.group("decl") not in qualified and m.group("decl") not in bare:
                unattributed.append(
                    f"{mod}.{name} reaches {ax}, whose owner "
                    f"{m.group('decl')} has no tactic site in the text census")

    dropped = _dropped_with_sites(dropped_names)
    bad = []
    if missing:
        shown = ", ".join(f"{m}.{n}" for m, n in missing[:8])
        bad.append(f"{len(missing)} declaration(s) the text census names that "
                   f"Lean reported nothing for — an `Unknown constant` means the "
                   f"generated file did not elaborate, so every other number "
                   f"here would be vacuous:\n      {shown}")
    bad += unknown[:8] + unattributed[:8]
    for (mod, name), why in sorted(SITES_NEEDING_NO_AXIOM.items()):
        if (mod, name) not in got:
            bad.append(f"{mod}.{name}: named in SITES_NEEDING_NO_AXIOM as a "
                       f"site that produces no axiom, and Lean reported nothing "
                       f"for it — so the entry has lost its subject")
    for mod in sorted(per_decl):
        for name, (n, lines) in sorted(per_decl[mod].items()):
            credit = sum(1 for (m2, _n2) in SITES_NEEDING_NO_AXIOM
                         if m2 == mod and _n2 == name)
            have = own.get(name, 0)
            if have != n - credit:
                bad.append(
                    f"{mod}.{name}: {n} tactic site(s) at {lines} and "
                    f"{have} axiom(s) named after it, with {credit} site(s) "
                    f"credited by SITES_NEEDING_NO_AXIOM. Every site produces "
                    f"exactly one axiom — `formal/lean.py::GENERATED_AXIOM_RE` "
                    f"— so this is a site that ran without one, or one that has "
                    f"no site.")
    bad += [f"{mod}.{name}: a declaration `#print axioms` cannot be spelled for "
            f"(private, or its name ends in `{UNASKABLE_SUFFIX}`) with "
            f"{len(at)} tactic site(s) at {at}, so its axiom exists and cannot "
            f"be asked about, and the count above cannot close"
            for mod, per in sorted(dropped.items()) for name, at in sorted(per.items())]
    check(not bad, "the axiom census and the text census disagree:\n    "
                   + "\n    ".join(bad))
    if verbose:
        for ax, decl in sorted(generated.items())[:10]:
            print(f"    {ax}  (owner {decl})")
        print(f"    … {len(generated)} generated axiom(s) in all")
    credit = len(SITES_NEEDING_NO_AXIOM)
    return True, (f"{len(got)} declaration(s) asked; {len(generated)} generated "
                  f"axiom(s) for {sites} counted site(s), every axiom "
                  f"attributable to a declaration the census names and every "
                  f"theorem's own count equal to its sites less the "
                  f"{credit} `bv_decide` site(s) Lean discharges in the kernel; "
                  f"none of the "
                  f"{sum(len(v) for v in dropped_names.values())} declaration(s) "
                  f"this file could not ask about carries a site; nothing "
                  f"outside {sorted(FOUNDATION)}")


def group_headline(got, verbose):
    """Eight named theorems, pinned by the axioms THEIR OWN PROOFS contribute.

    A pinned row that has moved is the `expect=`-marker discipline applied to a
    MEASUREMENT rather than to a test: `work_step_mov` contributing nothing but
    the foundation axioms IS the claim the 63 replacements bought, so a row that
    has stopped holding is either a regression or a reason the measurement moved,
    and either way a reader has to be told which rather than finding a smaller
    number with nothing saying where it went.

    **OWN**, not REACHED, and the distinction is the whole of what this file adds
    over the text census.  A theorem's `#print axioms` list is transitive, so
    `x86_call_ret_restores_rip` reports the two axioms its callee
    `mem_read_bytes_write_same` created even though its own `bv_decide` created
    none — and a row counting "reached" would say 2 for a theorem that added
    nothing to the library.  So each row counts the axioms NAMED AFTER it, which
    is the number `SITES_NEEDING_NO_AXIOM` and `NATIVE_DECIDE_REPLACED` are also
    talking about.  The count is of GENERATED axioms, so the foundation is not
    part of it and a change in how `simp`/`decide` elaborate cannot move a row.
    """
    own = _own_axioms(got)
    bad = []
    for (mod, name), want in sorted(HEADLINE.items()):
        if (mod, name) not in got:
            bad.append(f"{mod}.{name}: Lean reported nothing for a declaration "
                       f"this file names, so the row cannot be checked at all")
            continue
        have = len(own.get(name, ()))
        if have != want:
            bad.append(f"{mod}.{name} contributes {have} axiom(s) of its own "
                       f"and this row pins {want}. If a replacement was "
                       f"reverted, say so in the commit and move the number; if "
                       f"the theorem grew a `bv_decide`, that is the row to "
                       f"read and the site count moves with it.")
    check(not bad, "a pinned axiom count moved:\n    " + "\n    ".join(bad))
    if verbose:
        for (mod, name), want in sorted(HEADLINE.items()):
            print(f"    {mod}.{name}: {len(own.get(name, ()))} of its own, "
                  f"pinned {want}; reaches "
                  f"{len([a for a in (got.get((mod, name)) or ()) if a not in FOUNDATION])}")
    return True, (f"{len(HEADLINE)} theorem(s) pinned, "
                  f"{sum(1 for v in HEADLINE.values() if v == 0)} of them to "
                  f"ZERO axioms of their own")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    if L.find_lean(HERE) is None:
        print("lean not found (see ./lean-toolchain) — this measurement cannot "
              "run, and it is NOT a pass.")
        return 1
    per_mod, dropped_names = _library_declarations()
    try:
        run, got = _ask(per_mod, args.verbose)
    except RuntimeError as e:
        print(f"the library build failed: {e}")
        return 1
    if run.exceeded:
        print(f"the `#print axioms` run did not finish: {run.exceeded}. That is "
              f"NOT a verdict on lib/.")
        return 1
    failed = passed = 0
    for name, fn in (("census", group_census), ("headline", group_headline)):
        try:
            _ok, note = (fn(got, args.verbose) if fn is group_headline
                     else fn(per_mod, dropped_names, got, args.verbose))
        except TestFailure as e:
            failed += 1
            print(f"  FAIL  {name}\n        {e}")
            continue
        except Exception as e:                                  # noqa: BLE001
            failed += 1
            print(f"  ERROR {name}\n        {type(e).__name__}: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
            continue
        passed += 1
        print(f"  PASS  {name}\n        {note}")
    print(f"\n#print axioms over lib/: rc={run.returncode} "
          f"wall={run.wall_s:.1f}s cpu={run.cpu_s:.1f}s "
          f"peak={run.peak_rss / (1 << 30):.2f}GB  PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())