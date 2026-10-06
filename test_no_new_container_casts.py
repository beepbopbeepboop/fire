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

NOTE: this is a TEXT scan, so it also counts a cast spelled inside emitted-C
template strings -- which is deliberate, because those are casts the GENERATED
program really executes. Prose is not: `strip_prose` drops comments and
docstrings, so a cast written in documentation cannot make this go red. It is
still not a precise AST-level cast count.
"""
import glob
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
CAST_RE = re.compile(r'\((?:MojoList|MojoDict|MojoSet|MojoBytes) \*\)')


def strip_prose(src: str) -> str:
    """The source with every COMMENT and every DOCSTRING removed.

    This scanner counts a *cast*, and the two classes of text it used to count
    instead are both PROSE -- documentation of a cast, not a cast. Both have
    already made the gate red on a fix rather than on a regression, which is
    the whole reason the filter is a filter and not a comment saying the
    metric is approximate.

    **Comments.** `1a7b1f4` replaced an ad-hoc `(MojoList *)s` that made a
    `set` read as a list, and then wrote down what it had replaced:

        #  `pp = (MojoList *)s;`, and `for x in box` then read

    Documenting the defect you removed is the opposite of reintroducing it, and
    the count went to 35 and the suite reported "+1 new". The baseline was then
    either bumped to 35, which records a lie, or left, which leaves the gate
    permanently red on a comment.

    **Docstrings.** The same thing one layer out, and the 2026-10-04 merge
    bumped the baseline for two of them (see the ledger's last entry). A
    docstring cannot execute, so `(MojoList *)1` inside one is a quotation.
    Three such sites are on this tree, all of them the same habit: a module
    documenting the chokepoint spells a cast because the chokepoint's subject
    IS a cast --
    `emit_calls.py`'s `_bind_callable_element_param` docstring (why a lambda's
    forward declaration and its definition have to agree on
    `int64_t f(MojoList *)`), `_carry_elem_types`'s docstring (which names the
    bare cast whose missing element typing that function exists to carry), and
    `emit_exprs.py`'s `_literal_slot_kinds` docstring (the `(MojoList *)1`
    that `mojo_repr_list_kinds`'s `'l'` arm rendered a slot's integer through).
    That cast came out of the `*expr`-spread-in-a-display family, whose doc is
    deleted with its fix, so it is named here by the mechanism rather than by a
    path: the spread's OPERAND was not lowered through the slot-kind walk, so a
    literal that should have been a value arrived as a bare address.

    The rule is "a LOGICAL LINE that is a lone STRING token", not "a string
    literal", because the two pull in opposite directions here. An
    emitted-C template is a string used as an OPERAND and it MUST keep
    counting -- it is a cast the generated program really executes:

        gen._new_val(
            'MojoList *',
            '(MojoList *)0')

    and there the second string sits alone on its PHYSICAL line while sharing
    its LOGICAL line with the other two tokens. `tokenize` marks the
    difference (NL inside brackets, NEWLINE at the end of the statement), so
    grouping by logical line counts the template and drops the docstring.

    The removal is by CHARACTER SPAN over the original text, not by rejoining
    token strings with spaces, and that detail is what keeps the metric able
    to see a REAL Python-level cast: `( MojoList * ) x` does not match
    `CAST_RE`, so a token-joining filter would silently make this test blind to
    exactly the thing it exists to catch. Every cast it counts today happens to
    sit inside an emitted-C string, but "happens to" is not a property to
    build a guard on.

    `tokenize` rather than a regex for the comment half, because the cheap
    version -- strip `#` to end of line -- also eats a `#` inside a string, and
    a source that mentions a cast inside a string literal is exactly the case
    where a text scan is most likely to be wrong in the direction that
    matters. A file that does not tokenize is returned unchanged, so the count
    degrades to the old, conservative behaviour rather than to nothing.
    """
    import io
    import tokenize

    def prose_spans():
        """(start, end) offsets of every COMMENT and every docstring."""
        spans = []
        line = []

        def end_statement():
            # a lone STRING statement is a docstring: prose, so drop it whole
            if len(line) == 1 and line[0][1] == tokenize.STRING:
                spans.append((line[0][2], line[0][3]))
            line.clear()

        try:
            for tok in tokenize.generate_tokens(io.StringIO(src).readline):
                if tok.type == tokenize.COMMENT:
                    spans.append((tok.start, tok.end))
                    continue
                if tok.type == tokenize.NEWLINE:
                    end_statement()
                    continue
                if tok.type in (tokenize.NL, tokenize.INDENT, tokenize.DEDENT,
                                tokenize.ENDMARKER):
                    continue
                line.append((tok.string, tok.type, tok.start, tok.end))
            end_statement()
        except (tokenize.TokenError, IndentationError, SyntaxError):
            return None
        return spans

    spans = prose_spans()
    if spans is None:
        return src
    starts = [0]
    for text in src.split('\n'):
        starts.append(starts[-1] + len(text) + 1)
    out = []
    last = 0
    for (srow, scol), (erow, ecol) in spans:
        at = starts[srow - 1] + scol
        stop = starts[erow - 1] + ecol
        out.append(src[last:at])
        last = stop
    out.append(src[last:])
    return "".join(out)


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
# CODEGEN_all_any_dict_set_miscompile, closed by the DESIGN.html R5
# runtime guard below and removed with that fix.
#
# 30 -> 29 (R1 follow-up, same day): the dict/set-materialization shape
# above (all()/any()/enumerate()/str.join()/bytes.join()/shlex.join(), 5
# independent copies written one at a time during the R3 pass) consolidated
# into one shared gimple_gen_infra._materialize_as_list, per DESIGN.html R1
# ("consolidate duplicates" - this dogfoods that on duplication this same
# pass introduced). Then 29 -> 28: _materialize_as_list gained a DESIGN.html
# R5 runtime guard (mojo_is_registered_dict/_set) for the genuinely-boxed-
# handle case, closing CODEGEN_all_any_dict_set_miscompile for real
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
# 17 -> 19 (2026-10-04, merge of ten branches).  NOT two new ad-hoc
# coercions: both new matches are PROSE, and both are in emit_calls.py's own
# notes about this very chokepoint — `int64_t f(MojoList *)` in the docstring
# explaining why a lambda's forward declaration and its definition have to
# agree, and `(MojoList *)x` in `_carry_elem_types`'s docstring, which names
# the bare cast whose missing element typing that function exists to carry.
# A file that explains the chokepoint cannot be written without spelling a cast,
# which is the metric's known weakness (it greps TEXT; see the note above the
# scanner) and not a second reason to stop recording the number. No Python-level
# cast was added: `strip_prose` output differs from master's only on those
# two lines.
#
# 19 -> 17 (2026-10-04, the scanner drops docstrings).  The bump above was
# correct ABOUT the two sites and wrong about what to do with them: both are
# DOCSTRINGS, which `strip_comments` did not remove, and the fix for a
# docstring is not a baseline bump -- the bump records a quotation as if it
# were a cast, and the ceiling it locks in is then wrong for every future file
# too. A later merge added a third such site (`_literal_slot_kinds`'s
# `(MojoList *)1`), which is what the "+1 new" of the 2026-10-04 gate was: not a
# cast, the same sentence a third time.
#
# So `strip_comments` became `strip_prose`, which drops a LOGICAL LINE that is
# a lone STRING as well as a COMMENT, and the baseline goes back to the count
# it had before the bump -- 17, the number of cast spellings the generator can
# actually execute. Nothing is lost: the emitted-C template strings that are
# real casts share a logical line with the tokens around them and still count
# (the unit check below proves exactly that, on all four shapes), and a
# docstring cannot reach the generated C. Both prior entries stay in this
# ledger because the 34 -> 17 one is what established that the metric may be
# lowered at all, and this one is what it costs to keep counting.
#
# 17 -> 19 (2026-10-05, the merge of work/bugs7-1).  These two ARE casts, which
# is what separates them from the two entries above, and both are the same
# deliberate shape as a neighbour that was already in the baseline:
#
#   * `emit_exprs.py`'s `_lower_percent_dict`: the RHS of `<template> % <dict>`
#     coerced to the `MojoDict *` its callee declares, as `gen._new_val(
#     'MojoDict *', f"(MojoDict *){rv}")`. It is the TWIN of the LHS line above
#     it, `(char *){lv}`, which has been a baseline site since the 34 -> 17
#     entry counted real casts -- same call, same parameter position, one
#     operand typed correctly and one not. It cannot go through
#     `_coerce_to_type`: that helper emits a temp through `_safe_coerce_emit`,
#     and the function's own docstring records that the inline-in-argument
#     form is the one GIMPLE has been shown to ACCEPT at this position while
#     the temp form was not. Emitting the boxed word straight through was a
#     build failure ("passing argument 2 of 'mojo_str_format_dict' makes
#     pointer from integer without a cast"), and the chokepoint is not what
#     stands between that and a correct build here.
#   * `module_gen.py`'s generated `_mojo_repr_list`: the pair predicate gained
#     `mojo_is_tuple((MojoList *)(intptr_t)_e)` beside the
#     `mojo_list_len((MojoList *)(intptr_t)_e)` and
#     `_mojo_repr_pair((MojoList *)(intptr_t)_e)` already there. Three sites of
#     one expression in one generated-C template; splitting the count to keep
#     the number down would be the metric lying. There is no `gen` in scope at
#     all -- this is C the GENERATED PROGRAM executes, in a template string,
#     which is the class the scanner's own note says it counts deliberately.
#
# So: 19 is again a mix, and again recorded rather than pretended away. The
# difference from the 19 above is the mix's composition -- nothing here is
# PROSE, so `strip_prose` is not what these two survived.
#
# 19 -> 17 (2026-10-05, the merge of `work/merge-gate28` and
# `work/merge-formal27b`). THREE casts left, and the direction matters: the tree
# this merge started from measured 20 against this same ledger, so it was RED by
# one before anything here ran, and the merge is a net reduction rather than a
# move. What left:
#
#   * `emit_calls.py`'s `_lower_builtin_len`, TWO of them. The boxed-value
#     length question now goes through `emit_infra._len_of_boxed`, which
#     fetches its subject with `gen._ensure_local` -- the existing chokepoint
#     for "give me this value in a temp of MY type" -- instead of building the
#     temp by casting the word at a `(MojoList *)`. That is the same
#     consolidation `_ensure_local` was added for, and it is also a BUILD fix
#     rather than a taste one: `_new_val` casts bare integer literals only, so
#     a boxed value declared as some other scalar (`coro.py`'s `int pinfo`)
#     emitted a non-trivial conversion that `-fgimple`'s verifier rejects.
#   * `module_gen.py`'s generated `_mojo_repr_dict`: its six-arm value chain is
#     gone, so the `(MojoDict *)`/`(MojoList *)` coercions that chain spelled at
#     each arm are calls to `mojo_dict_slot_repr` instead.
#
# Nothing was re-spelled to escape the scanner: the count is read out of the
# source with `strip_comments`, and a cast that moved to another line would move
# to another line in this number too.
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
            total += len(CAST_RE.findall(strip_prose(f.read())))
    return total


def check_the_scanner_separates_casts_from_prose() -> int:
    """The metric's own unit check: one cast, four places to spell it.

    A grow-only allowlist is only worth anything if "+1" means "+1 cast", so
    the filter that decides what counts is itself a test — and it is the one
    place where getting the filter wrong would be invisible, because every
    other assertion in this file is about a number in some OTHER file.

    Returns the number of failures (0 when the filter behaves).
    """
    cases = (
        ("# (MojoSet *)x in a comment", 0),
        ('    """(MojoDict *)x in a docstring."""\n', 0),
        ('x = "(MojoBytes *)x in a string operand"\n', 1),
        ('y = (MojoList *)x\n', 1),
        ('z = gen._new_val(\n    "MojoList *",\n'
         '    "(MojoList *)0",\n)\n', 1),
    )
    bad = 0
    for src, want in cases:
        got = len(CAST_RE.findall(strip_prose(src)))
        if got != want:
            bad += 1
            print(f"✗ strip_prose: {got} cast(s) in {src.strip()!r}, "
                  f"want {want}")
    return bad


def main() -> int:
    n = count_casts()
    fails = check_the_scanner_separates_casts_from_prose()
    if fails:
        print("Results: 0 passed, 1 failed")
        print(f"✗ the scanner cannot tell a cast from prose ({fails} bad "
              f"case(s)); the baseline above is meaningless until it can")
        return 1
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
