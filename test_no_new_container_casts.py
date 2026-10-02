#!/usr/bin/env python3
"""DESIGN.html R3 guard: no NEW ad-hoc container-kind casts outside the
coercion chokepoint (mojo/backend_gimple/emit_resolve.py).

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


def strip_comments(src: str) -> str:
    """The source with every COMMENT token removed.

    This scanner counts a *cast*, and before this it counted a cast written
    inside a comment — which is how the gate went red on a fix rather than on a
    regression. `1a7b1f4` replaced an ad-hoc `(MojoList *)s` that made a `set`
    read as a list, and then wrote down what it had replaced:

        #  `pp = (MojoList *)s;`, and `for x in box` then read

    Documenting the defect you removed is the opposite of reintroducing it, and
    the count went to 35 and the suite reported "+1 new". The baseline was then
    either bumped to 35, which records a lie, or left, which leaves the gate
    permanently red on a comment.

    `tokenize` rather than a regex, because the cheap version -- strip `#` to
    end of line -- also eats a `#` inside a string, and a source that mentions
    a cast inside a string literal is exactly the case where a text scan is
    most likely to be wrong in the direction that matters. A file that does not
    tokenize is returned unchanged, so the count degrades to the old behaviour
    rather than to nothing.
    """
    import io
    import tokenize
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                continue
            out.append(tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return src
    return " ".join(out)

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
# a mechanical swap; the one that had a written-up fix plan was
# bugs/CODEGEN_all_any_dict_set_miscompile.md, closed by the DESIGN.html R5
# runtime guard below and removed with that fix.
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
# 28 -> 34 (2026-09-26): NOT six new ad-hoc coercions, and not a
# chokepoint regression. This metric is a raw regex over file TEXT, so it
# also counts every match inside a COMMENT and every match inside a
# C-text string literal, and the 2026-09-13..26 work (generators, async
# units, the closure/env work) added both. Classified all 34 sites on the
# current tree: 17 are inside `#` comments (prose describing past
# container-cast bugs, e.g. emit_calls.py:99), 14 are inside emitted-C
# templates (`_mojo_repr_list/dict/pair` decls and the repr-dispatch
# `return _mojo_repr_dict((MojoDict *)(intptr_t)val);` text in
# module_gen.py, `(MojoBytes *)(uintptr_t)` in emit_calls.py, the
# generator-value unbox in coro.py), and 3 are real Python-level casts
# (emit_exprs.py:2468, emit_methods.py:4012, coro.py:3059) — all three of
# the pre-existing "already accounted for" kind, i.e. one site each in
# the mojoc-generated value-unbox and bytes paths, not new ad-hoc
# coercions introduced by the recent work. So the 6 new matches are text
# the metric cannot distinguish from a real cast, and the honest move is
# to record the true count rather than pretend the delta is 0. Lower this
# back toward the number of REAL sites (3) only together with a metric
# change that stops matching comments and C text — the metric itself is
# the weak link here, not the code.
# 34 -> 17 (2026-09-28, comment-aware counting).  NOT a drop in real casts: 18
# of the 34 were inside COMMENTS, so the old number was measuring prose. The
# scanner counted a cast written in a comment, which is how the gate went red
# on `1a7b1f4` — the commit that REMOVED an ad-hoc `(MojoList *)s` making a set
# read as a list, and then wrote down what it had removed. 17 is the count of
# casts that exist, and lowering the baseline is what makes the next one a
# regression rather than a new normal.
BASELINE_COUNT = 17


def count_casts() -> int:
    total = 0
    paths = sorted(glob.glob(os.path.join(REPO, "gimple_*.py")))
    paths += sorted(glob.glob(os.path.join(REPO, "mojo", "**", "*.py"),
                              recursive=True))
    for path in paths:
        base = os.path.basename(path)
        # the chokepoint itself is allowed to cast
        if base in ("emit_resolve.py", "gimple_gen_resolve.py"):
            continue
        with open(path) as f:
            total += len(CAST_RE.findall(strip_comments(f.read())))
    return total


def main() -> int:
    n = count_casts()
    if n > BASELINE_COUNT:
        print("Results: 0 passed, 1 failed")
        print(f"✗ {n} container-kind casts outside emit_resolve.py "
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
