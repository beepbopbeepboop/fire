#!/usr/bin/env python3
"""DESIGN.html R3 guard: no NEW ad-hoc container-kind casts outside the
coercion chokepoint (gimple_gen_resolve.py).

`(MojoList *)`/`(MojoDict *)`/`(MojoSet *)`/`(MojoBytes *)` written directly
at a call site, instead of going through `_safe_coerce_emit`'s chokepoint,
defeats the R2 refusal added in commit 634852c: a hard reinterpret-cast
compiles clean and silences GCC exactly where the type checker would have
caught a wrong container-kind inference (see DESIGN.html's R3 measurement:
146 such sites existed, none through the chokepoint).

Retroactively banning all existing occurrences is a much larger, separate
migration (each site needs individual verification it's actually safe, or a
real fix if not — not something to do blind). This test instead FREEZES the
current, already-shipped set as a baseline and fails only on a NEW
occurrence — the same "grow-only allowlist" pattern compile_stdlib.py's
EXPECTED_FAILURES already uses. A genuinely new, deliberate cast belongs in
BASELINE_COUNT below with a comment explaining why the chokepoint doesn't
apply; an accidental new one should almost always be routed through
`gen._coerce_to_type`/`_safe_coerce_emit` instead.

NOTE: this greps raw text, so it also counts occurrences inside comments —
deliberately conservative (never LOWERS silently), not a precise AST-level
cast count.
"""
import glob
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
CAST_RE = re.compile(r'\((?:MojoList|MojoDict|MojoSet|MojoBytes) \*\)')

# Baseline as of commit 634852c (2026-09-13), the day the R2 chokepoint
# refusal shipped. Bump this ONLY for a new site with a comment justifying
# why it can't go through the chokepoint - not to silence a failure.
#
# Lowered from 169 -> 107 -> 33 -> 30 (2026-09-13, R3 migration pass):
# - 62 ad-hoc casts in gimple_gen_infra/calls/exprs/loops/methods/stmts.py
#   routed through gen._coerce_to_type (the R2 GIMPLE-statement chokepoint).
# - 74 more in gimple_cpp_core.py (the C++ fallback expression-string
#   lowering path, structurally different from the GIMPLE statement
#   emitter above - it builds inline C++ expression text, not GIMPLE
#   statements through `gen`) routed through a new sibling helper,
#   `_cpp_as()` in that file: a pure text-consolidation cast (R1 - one
#   function, not 74 independent `f"(MojoList *)(...)"` sites) with no
#   R2 refusal, since every site using it had already established the
#   value's real kind via a static-type branch before casting - it emits
#   byte-identical C++ to what was there before, just centralized.
# A further 3 fixed (33 -> 30) by handling the STATICALLY KNOWN dict/set
# cases in all()/any() and enumerate() for real (materialize via
# mojo_dict_keys/mojo_set_sorted instead of reinterpreting the header),
# and one narrow-scalar _coerce_to_bytes path. `set.update(a_list)` was
# also given a real per-element mojo_set_add_int/_str loop fix (does not
# change this count - it replaced a behavior bug, not a cast site). Every remaining site now
# carries an inline "DESIGN.html R3 exception" comment explaining why it
# is NOT routed through the chokepoint - either it has no `gen` in scope
# to route through (raw C source text / comments the regex also
# matches), or it is a genuine "no static proof, could really be a
# different container kind" site where the R2 chokepoint would turn a
# silent miscompile into a build crash for currently-working code (set.
# update(list), bytes.join(dict), the self-host-erasure-sensitive
# _lb_as_set, and the remaining boxed/untyped branches of all()/any()/
# enumerate()) - each needs its own runtime-guard or loop-based fix, not
# a mechanical swap; see bugs/CODEGEN_all_any_dict_set_miscompile.md for
# the one with a written-up fix plan.
#
# 30 -> 29 (R1 follow-up, same day): the dict/set-materialization shape
# above (all()/any()/enumerate()/str.join()/bytes.join()/shlex.join(), 5
# independent copies written one at a time during the R3 pass) consolidated
# into one shared gimple_gen_infra._materialize_as_list, per DESIGN.html R1
# ("consolidate duplicates" - this dogfoods that on duplication this same
# pass introduced). Then 29 -> 28: _materialize_as_list gained a DESIGN.html
# R5 runtime guard (mojo_is_registered_dict/_set) for the genuinely-boxed-
# handle case, closing bugs/CODEGEN_all_any_dict_set_miscompile.md for real
# across all 5 call sites at once; set.update(x) was refactored onto the
# same helper + a shared per-element mojo_set_add loop, replacing its own
# remaining ad-hoc cast. Also found (via a real crash: `a, b = some_dict`)
# and fixed 3 more genuine tuple/list-unpack sites that reach
# gen._coerce_to_type with a variable src that CAN be MojoDict*/MojoSet*
# in valid Python (unpacking a dict/set is real Python, not just an
# ambiguous boxed handle) - upgraded to _materialize_as_list too. Same for
# a 4th: `x[:] = some_dict` (slice-assign splice RHS - also real Python,
# splices in the dict's keys). Same for a 5th/6th: `bytes(a_dict)`/
# `bytearray(a_set)` of ints (also real Python - an iterable of ints is a
# valid bytes()/bytearray() source). Count unchanged throughout (already
# routed through the chokepoint).
BASELINE_COUNT = 28


def count_casts() -> int:
    total = 0
    for path in sorted(glob.glob(os.path.join(REPO, "gimple_*.py"))):
        if os.path.basename(path) == "gimple_gen_resolve.py":
            continue  # the chokepoint itself is allowed to cast
        with open(path) as f:
            total += len(CAST_RE.findall(f.read()))
    return total


def main() -> int:
    n = count_casts()
    if n > BASELINE_COUNT:
        print("Results: 0 passed, 1 failed")
        print(f"✗ {n} container-kind casts outside gimple_gen_resolve.py "
              f"(baseline {BASELINE_COUNT}, +{n - BASELINE_COUNT} new) - "
              f"route new container-kind coercions through "
              f"gen._coerce_to_type instead of an ad-hoc (MojoX *) cast, "
              f"or bump BASELINE_COUNT with a comment justifying why not")
        return 1
    if n < BASELINE_COUNT:
        print("Results: 1 passed, 0 failed")
        print(f"✓ {n} container-kind casts outside the chokepoint "
              f"(down from baseline {BASELINE_COUNT} - lower "
              f"BASELINE_COUNT to {n} to lock in the improvement)")
        return 0
    print("Results: 1 passed, 0 failed")
    print(f"✓ {n} container-kind casts outside the chokepoint (baseline, unchanged)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
