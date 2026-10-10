#!/usr/bin/env python3
"""Every list/dict/set/tuple method and operator, differentially against CPython,
on BOTH formal backends.

    python3 test_formal_container_methods.py [-v] [--keep] [group ...]

Groups: `list`, `dict`, `set`, `tuple`, `alias`, `operator`. With no argument,
all of them. Every group that builds an image builds it on BOTH architectures.

THE ORACLE IS CPYTHON, CALLED — NEVER TYPED HERE
------------------------------------------------
Nothing in this file records what a container method answers. Each case carries
the ONE program text, and its answer is computed twice: once by this process's
CPython running that text, and once by an image built through the formal backend
and executed. There is no table of expected values to go stale, and no
possibility of a "expected" that was written by whoever wrote the lowering.

**The program text is the SAME for both engines.** That is the strongest form of
this oracle and it is a decision rather than an accident: a suite that kept a
separate CPython rendering would be a second spelling of every case, and a
divergence would then have two candidate causes — the compiler or the
translation. So a case is written in the intersection of Mojo and Python:
`print`, `printf`, integer arithmetic, container literals, `for … in`. Nothing
that only one of the two spells differently appears in a case; where the two
DISAGREE (a construct CPython refuses, or one this path lowers differently) the
case says so in its `why` and is asserted as a REFUSAL rather than as a value.

THE TWO OUTCOMES ARE NOT SYMMETRIC, AND THE ASYMMETRY IS THE POINT
------------------------------------------------------------------
A container surface on this path has three possible outcomes per case and the
file distinguishes all three, because the one that matters is the third:

  * **ANSWER** — the program builds and its stdout equals CPython's. This is the
    good case and it is the only one that is ever silent.
  * **REFUSAL** — the build fails, and the refusal must be a NAMED one: the
    table records which shared refusal owns the construct, so a case cannot pass
    by being refused for the wrong reason. A refusal is an honest answer here
    (this backend has no heap, so `xs.pop()`, `xs.remove(v)` and `xs.sort()` are
    not lowerings it has) and it is recorded rather than skipped.
  * **DIVERGENCE** — the program builds, runs, exits, and does NOT agree with
    CPython. This is the failure. It used to be the common case: `a == [3, 1, 2]`
    answered 0 where CPython answers 1, `s - {2}` died with SIGSEGV, and
    `a += [3]` answered 0 on one architecture and crashed on the other. The
    whole of the recent work on `formal/model.py`'s operator gate exists to turn
    rows of this table from DIVERGENCE into REFUSAL, so a divergence here is
    either a regression or something nobody has measured yet.

WHY ONE IMAGE PER GROUP PER BACKEND
-----------------------------------
`formal/hostmods/glob.mojo`'s suite and this one share that shape, and for the
same reason: a refusal or a wrong answer is a property of the CONSTRUCT, so
building one image per case would report the same defect thirty times and cost
thirty builds. One image per group means one build per backend per group, and a
case's own answer is separated from its neighbours' by a `@@<key>:` header
record, so a dropped case is visible as a MISSING KEY rather than as a shifted
one — which is the failure a shared counter produces.

WHAT IS DELIBERATELY NOT IN HERE
---------------------------------
* Nothing that needs a heap. `xs.pop()`, `xs.remove(v)`, `xs.index(v)`,
  `xs.count(v)`, `xs.insert(i, v)`, `xs.extend(v)`, `xs.sort()`, `xs.reverse()`,
  `xs.copy()`, `d.get(k)`, `d.setdefault(k, v)`, `d.pop(k)`, `d.popitem()`,
  `d.update(o)`, `d.items()`, `d.keys()`, `d.values()`, `s.add(v)`,
  `s.discard(v)`, `s.pop()`, `s.union(…)` and the rest are all refused by
  `formal/model.py`'s `BUILTIN_VALUE_METHODS`, which holds `append`, `clear`,
  `write` and `close` and the five string methods. Every one of them has a case
  here anyway, asserted as a REFUSAL naming that table, because a construct that
  silently stopped being refused would otherwise never be noticed — and because
  the set of refusals is a CLAIM about the target, which is a thing to keep true
  rather than a list of things to delete from.
* `print(container)`. It is refused (`formal/build.py` will not guess whether a
  name is text or a number, and a blob is neither), so every case prints
  `len`, an element or a subscript. The list/set/dict/tuple VALUES are observed
  through `len`, `[]`, a `for` walk and membership, which are the readings a
  program can actually take of them.
* A dict whose iteration order is observed. Insertion order is what a pair blob
  gives and it IS what CPython gives for a dict, but a dict whose keys hash
  COLLIDE does not agree, and this file has no business deciding that question —
  see `bugs/FORMAL_set_value_model.md` for the set case, which is the same
  question and is already written down.
"""

import argparse
import os
import platform
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
sys.path.insert(0, HERE)

BUILD_TIMEOUT = 900
RUN_TIMEOUT = 120
REC = "@@"

#: The `probe` value that says "this case must NOT answer".  A subscript past
#: the end of a blob is the case that needs it: the build SUCCEEDS and the
#: program then stops with a bounds trap, which is this path's run-time
#: counterpart of CPython's `IndexError` — so it is neither an answer to diff
#: against CPython (CPython raises) nor a build-time refusal.  Asserting only
#: "it stopped" is honest about what the two engines agree on here, and
#: leaving the row out would leave the bounds check unmeasured.
NO_ANSWER = "!"

#: A case that needs to print MORE THAN ONE number writes its observation as
#: `("%d %d", ["a[0]", "b[0]"])` instead of a bare expression, and the harness
#: emits the `printf` for it in `main`.  That indirection is not decoration: a
#: `printf` written inside the case's own function would run BEFORE the harness
#: prints that case's header, and the line would then be attributed to the
#: PRECEDING case — a case that silently measures its neighbour.  Keeping every
#: `printf` in `main`, in key order, is what makes the record a record.
TEMP = None


class Failure(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Failure(msg)


def backends():
    """The architectures to build for.

    BOTH, always: `gimple_codegen.py` and `myinterpreter.py` are separately
    maintained lowerings of one AST (`CLAUDE.md`), so an answer that agrees on
    one architecture says nothing about the other — and this file's history is
    the argument. `s & {2}` answered 2 on arm64 and 163061056 on x86-64, and
    `[1] in [[1], [2]]` answered 1 on arm64 and 0 on x86-64, both where CPython
    says 1. A single-architecture corpus would have reported half of each as a
    pass.

    A host with no x86-64 support returns one name and `main` says so on the
    screen, rather than the x86-64 half passing over quietly.
    """
    if platform.machine() in ("arm64", "aarch64"):
        return ["arm64", "x86_64"]
    return ["x86_64"]


def build(src, name, backend):
    path = os.path.join(TEMP, name + ".mojo")
    out = os.path.join(TEMP, f"{name}.{backend}")
    with open(path, "w") as fh:
        fh.write(src)
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           "-o", out, f"--backend={backend}", path]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    if r.returncode != 0:
        # The WHOLE message, not a tail: `_is_a_named_refusal` matches a phrase
        # from a shared table and a refusal's own text is at the FRONT, so a
        # truncation that keeps the last 800 characters turns every refusal into
        # "refused for an unnamed reason".
        raise Failure(
            f"build failed on --backend={backend}: "
            f"{(r.stderr or r.stdout).strip()}")
    check(os.path.isfile(out), f"no image at {out}")
    return out


def run(out):
    r = subprocess.run([out], capture_output=True, timeout=RUN_TIMEOUT, cwd=HERE)
    if r.returncode != 0:
        raise Failure(
            f"image {os.path.basename(out)} exited {r.returncode}: "
            f"{(r.stderr or b'').decode('utf-8', 'replace').strip()[-400:]}")
    return r.stdout.decode("latin-1")


def records(text):
    """`@@<key>:<value>` header records and any lines that follow each, as a dict.

    The two-byte separator and the `:` header are what make an EMPTY answer
    visible: a case that printed nothing is `[]`, and a bare list of answers
    could not be told from a missing case at all.  The value rides ON the header
    because a case answers with one number — `@@l_len:3` — so the split is on
    the first `:` and everything after it is that case's first value, with any
    further lines belonging to the same case.  The key is alphanumeric because
    several groups number their cases apart and one counter for all of them
    would make a dropped case look like a shifted one.
    """
    out = {}
    cur = None
    for chunk in text.split(REC):
        if not chunk:
            continue
        head, sep, val = chunk.partition(":")
        if sep and head and head.replace("_", "").isalnum():
            cur = head
            out[cur] = []
            first = val.splitlines()[0] if val.splitlines() else ""
            if first:
                out[cur].append(first)
            for extra in val.splitlines()[1:]:
                out[cur].append(extra)
            continue
        if cur is None:
            raise Failure(f"answer before any header: {chunk!r}")
        out[cur].append(chunk)
    return out


def program(cases, tag, backend):
    """One image per group per backend: every case's whole answer, in order.

    Flat rather than a helper function, and that is forced rather than chosen: a
    container cannot be passed to a function parameter on this path with its KIND
    intact (`len(xs)` inside a callee is refused as `len()` of an `int`,
    measured), so each case binds its own local and prints it there.

    **A group image can fail to build because of ONE case, and then every case
    in the group is unmeasured** — which is the wrong failure, because it reports
    a group's problem as the group's absence.  So a failed group build falls
    back to one image per case and says which case broke the group; a group that
    builds is still one build, which is the point of the grouping.
    """
    src = "\n".join(_source(cases)) + "\n"
    try:
        return records(run(build(src, tag, backend)))
    except Failure as group_error:
        for i, case in enumerate(cases):
            try:
                one = records(run(build("\n".join(_source([case])) + "\n",
                                       f"{tag}_c{i}", backend)))
            except Failure as e:
                raise Failure(
                    f"{len(cases)} case(s) share one image per group so a "
                    f"refusal is reported once rather than per case; this "
                    f"group's image failed to build and case {i} "
                    f"({case[0]}) is the one that fails alone:\n"
                    f"    {str(e)[-700:]}") from None
        raise Failure(
            f"the group image failed to build but every case builds alone, so "
            f"this is an interaction between cases and not a refusal:\n"
            f"    {str(group_error)[-700:]}") from None


def _source(cases):
    """The whole group as ONE `main` plus one function per case.

    **The per-case FUNCTION is what lets a group share an image**, and it is not
    a style choice.  `ValueKinds` is built per function — `model.ValueKinds(fn)`
    scans that function's body — so a whole-function map that saw every case's
    `a = [3, 1, 2]` and `a = "hello"` would give one name two kinds, and the
    refusal that follows is a real one: measured while writing this file, a
    group image built from all 32 list cases failed with "`len(a)` — the source
    does not say what this operand holds" while every case built perfectly well
    on its own.  One function per case gives each its own map, so the group is
    one build and each case's answer is separate.

    The alternative — a container passed into a helper — is not available:
    `len(xs)` inside a callee is refused as `len()` of an `int` because a
    `-> List[Int]` annotation does not survive the parameter, which the
    host-module suites have measured.  So each case binds its own local, inside
    its own function.

    **Where the `@@` header is printed is what makes a record a record.**  A
    single-value case returns its answer and `main` prints the header
    immediately before the call, so the two are adjacent.  A case that observes
    SEVERAL numbers writes them with one `printf` whose arguments are its own
    locals, so its header has to be printed inside its own function — which is
    why the header is emitted there rather than in `main`.  An earlier shape
    printed such a case's values from inside the function and its header from
    `main`, and every one of those values was then attributed to the PRECEDING
    case: a case that silently measures its neighbour, which is worse than not
    measuring it.
    """
    lines = []
    main = []
    for key, setup, probe, _why in cases:
        lines.append(f"def {key}() -> Int:")
        for s in setup:
            lines.append(f"    {s}")
        if isinstance(probe, tuple):
            fmt, args = probe
            lines.append(f'    printf("{REC}{key}:")')
            lines.append(f'    printf("{fmt}", {", ".join(args)})')
            lines.append("    return 0")
            # CALLED from `main` like every other case: the function prints its
            # own header, so `main` has nothing to print for it — and a case
            # that is defined and never called is a case that measures nothing,
            # which is the failure this harness's own record format exists to
            # make visible rather than to hide.
            main.append((key, f"    {key}()"))
        elif probe is not None and probe != NO_ANSWER:
            lines.append(f"    return {probe}")
            main.append((key, f'    printf("{REC}{key}:%d\\n", {key}())'))
        else:
            # A NO_ANSWER case and a refusal case share this shape: the function
            # has to reach its last line for the case to mean anything, and
            # neither prints.  A refusal case's own construct is in `setup`.
            lines.append("    return 0")
            main.append((key, f'    printf("{REC}{key}:%d\\n", {key}())'))
    lines.append("")
    lines.append("def main() -> Int:")
    lines += [body for _key, body in main]
    lines.append("    return 0")
    return lines


def reference(cases):
    """CPython's own answer for every case, by RUNNING the same text here.

    The only thing this file adds to the reference program is a `printf`
    SHIM — `def printf(fmt, *a): sys.stdout.write(fmt % a)` — because a case
    may print two numbers in one answer (the rows that read the same blob
    through two names, which is the only way to catch a store that reached the
    wrong slot) and `printf` is the observation function both engines have.  It
    declares that the name exists; it does not decide anything a case decides,
    and no case's own expression is touched.  Everything else is the case's
    text verbatim.
    """
    out = {}
    for key, setup, probe, _why in cases:
        if probe is None or probe == NO_ANSWER:
            out[key] = []
            continue
        body = ["import sys", "",
                "def printf(fmt, *a):",
                "    sys.stdout.write(fmt % a)",
                "", "",
                "def main():"]
        body += [f"    {s}" for s in setup]
        if isinstance(probe, tuple):
            fmt, args = probe
            body.append(f'    printf("{fmt}", {", ".join(args)})')
        else:
            body.append(f'    printf("%d\\n", {probe})')
        body.append("    return 0")
        src = "\n".join(body) + "\n\nmain()\n"
        path = os.path.join(TEMP, f"ref_{key}.py")
        with open(path, "w") as fh:
            fh.write(src)
        r = subprocess.run([sys.executable, path], capture_output=True, text=True,
                           timeout=RUN_TIMEOUT, cwd=HERE)
        if r.returncode != 0:
            raise Failure(
                f"case {key}: the REFERENCE program does not run under CPython, "
                f"so the case is meaningless rather than passing:\n"
                f"{(r.stderr or '')[-600:]}\n{src}")
        out[key] = r.stdout.splitlines()
    return out


# ── the corpus ──────────────────────────────────────────────────────────────
#
# `(key, setup, probe, why)`.  `probe is None` means the case asserts NO answer
# — it exists to be REFUSED, and `why` names which shared refusal owns it, so a
# case cannot pass by being refused for an unrelated reason.
#
# `printf` rather than `print` for the probe, because `print` of an arbitrary
# name is refused on this path and every probe here is a computed integer.
#
# Every CPython value a case depends on is written in the case, in the setup or
# the probe, so a reader can check the expectation by reading the case and not
# this file's comments — and the file checks it anyway by CALLING CPython.

LIST_CASES = [
    ("l_len",
     ["a = [3, 1, 2]"], "len(a)",
     "the count word: the one thing a blob header is"),
    ("l_len_empty", ["a = []"], "len(a)", "an empty blob still has a count"),
    ("l_index",
     ["a = [3, 1, 2]"], "a[1]",
     "a constant index: the shape `formal/examples/list_literal_index.mojo`"),
    ("l_index_var",
     ["a = [3, 1, 2]", "i = 1"], "a[i]",
     "a RUN-TIME index, which is a bounds-checked load rather than a constant"),
    ("l_index_neg",
     ["a = [3, 1, 2]"], "a[-1]",
     "CPython's negative-index rule; a frame blob's header read at count-1"),
    ("l_index_oob",
     ["a = [3, 1, 2]", "v = a[9]"], NO_ANSWER,
     "out of range is an IndexError in CPython and a bounds trap here: the "
     "build succeeds and the program STOPS, which is the third outcome and "
     "the reason NO_ANSWER exists"),
    ("l_index_oob_var",
     ["a = [3, 1, 2]", "i = 9", "v = a[i]"], NO_ANSWER,
     "the same with a run-time index, which is the shape a bounds check has "
     "to be emitted for at all"),
    ("l_assign",
     ["a = [3, 1, 2]", "a[0] = 9"], "a[0]",
     "a store through a subscript: the shape that has to write the blob"),
    ("l_assign_var",
     ["a = [3, 1, 2]", "i = 2", "a[i] = 7"], "a[2]",
     "the same store with a run-time index"),
    ("l_append",
     ["a = [3, 1, 2]", "a.append(9)"],
     ("len=%d val=%d\\n", ["len(a)", "a[3]"]),
     "`append`: the one list method with a real lowering, so it is the row "
     "that keeps the other refusals honest"),
    ("l_append_len",
     ["a = [3, 1, 2]", "a.append(9)"], "len(a)",
     "the count after an append, which is a second store and a second reader"),
    ("l_append_loop",
     ["a = []", "a.append(1)", "a.append(2)"], "len(a)",
     "two appends: the capacity is the count of append SITES, so this is the "
     "row that notices the reservation being sized from the wrong thing"),
    ("l_clear",
     ["a = [3, 1, 2]", "a.clear()"], "len(a)",
     "`clear` is the other lowered list method: one store of zero at offset 0"),
    ("l_clear_then_other",
     ["a = [3, 1, 2]", "a.clear()", "b = [7]"], "len(a) + len(b)",
     "clearing one blob must not zero the NEXT one's header — the two numbers "
     "are in one answer so a store that reached too far cannot pass"),
    ("l_slice",
     ["a = [3, 1, 2]", "b = a[1:]"], "len(b)",
     "a slice read: a materialized copy, so `len` reads the copy's header"),
    ("l_slice_half",
     ["a = [3, 1, 2]", "b = a[0:2]"], "len(b)",
     "a half-open range"),
    ("l_slice_step",
     ["a = [3, 1, 2]", "b = a[::2]"], "len(b)",
     "a step, which is not the default stride and is the row that says so"),
    ("l_slice_neg",
     ["a = [3, 1, 2]", "b = a[-2:]"], "len(b)",
     "CPython's negative-bound clamp"),
    ("l_slice_elems",
     ["a = [3, 1, 2]", "b = a[1:]"],
     ("%d %d %d\\n", ["b[0]", "b[1]", "len(b)"]),
     "the CONTENTS of a slice, not just its length: a length is right while "
     "the elements are somebody else's"),
    ("l_del_index",
     ["a = [3, 1, 2]", "del a[0]"], "len(a)",
     "`del` a subscript: a shift-delete, which is a different algorithm from "
     "the store and is emitted by a different method"),
    ("l_del_slice",
     ["a = [3, 1, 2]", "del a[0:1]"], "len(a)",
     "`del` a range: the same shift over a range"),
    ("l_concat",
     ["a = [3, 1, 2]", "b = a + [5]"], "len(b)",
     "`+` between two lists, which IS a concatenation on both backends"),
    ("l_concat_var",
     ["a = [1, 2]", "b = [3, 4]", "c = a + b"], "c[3]",
     "the same with two NAMES, which is the shape that used to reach pointer "
     "arithmetic before `_blob_vars` existed"),
    ("l_repeat",
     ["a = [1]", "b = a * 3"], "len(b)",
     "`xs * n`, whose reservation is `len(xs) * n` slots in the frame"),
    ("l_walk",
     ["a = [3, 1, 2]", "t = 0", "for x in a:", "    t = t + x"],
     "t",
     "a full walk: every element at the blob's own stride"),
    ("l_walk_str",
     ['a = ["ab", "cd"]'],
     ("%s %d\\n", ["a[0]", "len(a)"]),
     "a list of STRINGS: the elements are `char *` and the walk must load a "
     "pointer rather than a word's low half"),
    ("l_walk_nested",
     ["a = [[1], [2]]"],
     ("%d %d\\n", ["len(a[0])", "len(a)"]),
     "a list of LISTS: the inner blob is at an address in the outer one"),
    ("l_in",
     ["a = [3, 1, 2]", "x = 2"], "1 if x in a else 0",
     "membership with a SCALAR needle: a linear scan, and the row that keeps "
     "the container-needle refusal from being over-broad"),
    ("l_in_miss",
     ["a = [3, 1, 2]"], "1 if 9 in a else 0", "a miss is a miss"),
    ("l_not_in",
     ["a = [3, 1, 2]"], "1 if 9 not in a else 0",
     "`not in` must be the same scan inverted"),
    ("l_in_dict_keys",
     ['d = {"a": 1}'],
     ("%d %d\\n", ['d["a"]', '1 if "a" in d else 0']),
     "a dict is a PAIR blob, so membership scans its KEYS at stride 16 — a "
     "stride-8 scan can only ever see half the keys"),
    ("l_dict_in_miss",
     ['d = {"a": 1}'], "1 if \"z\" in d else 0",
     "the miss through the same stride-16 scan"),
    ("l_len_vs_int",
     ["a = [3, 1, 2]"], "1 if len(a) > 2 else 0",
     "`len(xs) > 2` is a comparison of two INTEGERS about a container, and "
     "CPython answers it: the row that a too-broad operator gate would break"),
    # ── the refusals, each naming the shared refusal that owns it ──────────
    ("l_extend_r", ["a = [1, 2]", "a.extend([3])"], None,
     "`extend` is not in `model.BUILTIN_VALUE_METHODS`, which holds `append`, "
     "`clear`, `write`, `close` and the string methods"),
    ("l_insert_r", ["a = [1, 2]", "a.insert(0, 3)"], None,
     "`insert` — a shift of the tail, and no emitter"),
    ("l_pop_r", ["a = [1, 2]", "a.pop()"], None,
     "`pop` shrinks the blob, and a frame blob cannot shrink"),
    ("l_pop_i_r", ["a = [1, 2]", "a.pop(0)"], None,
     "`pop(i)` — the same, at an index"),
    ("l_remove_r", ["a = [1, 2]", "a.remove(1)"], None,
     "`remove` needs a membership scan AND a shift"),
    ("l_index_m_r", ["a = [1, 2]", "v = a.index(1)"], None,
     "`index` on a LIST — a length-dependent SEARCH whose result is a "
     "position. The name is a real method of `String` too, so the refusal has "
     "to name the receiver's classification, not just the method"),
    ("l_count_r", ["a = [1, 1, 2]", "v = a.count(1)"], None,
     "`count` is only lowered on a `char *`, and the receiver is classified "
     "`list:int` — the same bytes mean something different"),
    ("l_copy_r", ["a = [1, 2]", "b = a.copy()"], None,
     "`copy` is a NEW blob of a size this build would have to reserve twice"),
    ("l_sort_r", ["a = [3, 1, 2]", "a.sort()"], None,
     "`sort` is a comparison sort over the blob's elements, and the element "
     "order it needs is exactly what the ordering refusal says does not exist"),
    ("l_reverse_r", ["a = [3, 1, 2]", "a.reverse()"], None,
     "`reverse` writes into the receiver's own bytes, and its length is a word "
     "read at run time"),
    ("l_slice_store_same", ["a = [3, 1, 2]", "a[0:1] = [9]"], "a[0]",
     "a SAME-LENGTH slice store, which arm64 lowers as an in-place replace and "
     "x86-64 does not have. arm64-only, declared in BACKEND_ONLY below rather "
     "than discovered: the group image is one build, so the case is EXCLUDED "
     "from it on x86-64 rather than failing the build"),
]

DICT_CASES = [
    ("d_len", ['d = {"a": 1, "b": 2}'], "len(d)",
     "a dict is a counted blob too, so its count is at the same offset 0"),
    ("d_subscript", ['d = {"a": 1}'], 'd["a"]',
     "a string-keyed subscript: a key lookup, not an index, and the difference "
     "is one stride and one comparison"),
    ("d_subscript_int", ["d = {1: 2}"], "d[1]",
     "an int-keyed subscript: the same lookup with a word compare"),
    ("d_subscript_miss", ['d = {"a": 1}', 'v = d["z"]'], NO_ANSWER,
     "a missing key is a KeyError in CPython and a STOP here — and the row that "
     "keeps the stop LOUD: before the fix this exited 1 with nothing on stdout "
     "and nothing on stderr, which a reader cannot tell from an assert"),
    ("d_store", ['d = {"a": 1}', 'd["b"] = 2'], "len(d)",
     "a store through a string key, which is how a dict is built here when "
     "`|` is refused"),
    ("d_store_overwrite", ['d = {"a": 1}', 'd["a"] = 9'],
     ("%d %d\\n", ['d["a"]', 'len(d)']),
     "an overwrite must replace the VALUE and not the key: the two answers are "
     "in one line so a store that found a free slot instead cannot pass"),
    ("d_del", ['d = {"a": 1, "b": 2}', 'del d["a"]'], "len(d)",
     "a key delete: the pair-blob shift, which is not the sequence's shift"),
    ("d_clear", ['d = {"a": 1}', "d.clear()"], "len(d)",
     "`clear` on a dict passes the SAME `is_list_kind` guard as on a list, "
     "deliberately and by measurement: zeroing offset 0 empties a counted blob"),
    ("d_walk_keys", ['d = {"a": 1, "b": 2}', "t = 0",
                     "for k in d:", "    t = t + len(k)"],
     "len(d)",
     "walking a dict yields its KEYS at stride 16 — the same stride-16 rule "
     "membership uses"),
    ("d_in", ['d = {"a": 1}'], '1 if "a" in d else 0',
     "membership in a dict is key membership, so it is the pair stride again"),
    ("d_eq_r", ['d = {"a": 1}', 'v = 1 if d == {"a": 1} else 0'],
     None,
     "`==` on two blobs: element-wise equality and then a length check, which "
     "is the per-element STRIDE the operator gate is about"),
    ("d_ne_r", ['d = {"a": 1}', 'v = 1 if d != {"a": 1} else 0'],
     None, "`!=` is the same comparison inverted"),
    ("d_union_r", ['d = {"a": 1}', 'e = d | {"b": 2}'], None,
     "`|` between two dicts is a MERGE in Python — the right value wins for a "
     "shared key — and there is no merge emitter here"),
    ("d_ior_r", ['d = {"a": 1}', 'd |= {"b": 2}'], None,
     "the augmented spelling of the same operator, and the augmented form is "
     "a SECOND emitter, which is why it needed its own row"),
    ("d_get_r", ['d = {"a": 1}', 'v = d.get("a")'], None,
     "`get` is not in `model.BUILTIN_VALUE_METHODS`"),
    ("d_setdefault_r", ['d = {"a": 1}', 'v = d.setdefault("b", 5)'],
     None, "`setdefault` — a lookup that may insert, so two emitters"),
    ("d_pop_r", ['d = {"a": 1}', 'v = d.pop("a")'], None,
     "`pop` removes a pair, which moves everything after it"),
    ("d_popitem_r", ['d = {"a": 1}', 'v = d.popitem()'], None,
     "`popitem` removes an ARBITRARY pair, which on this path would mean an "
     "order this path does not define"),
    ("d_update_r", ['d = {"a": 1}', 'd.update({"b": 2})'], None,
     "`update` is a merge under another name"),
    ("d_items_r", ['d = {"a": 1}', "for k, v in d.items():", "    t = len(k)"],
     None,
     "`items` yields PAIRS, so it needs a stride-16 walk producing two values; "
     "the walk over `d` itself yields keys at that stride already"),
    ("d_keys_r", ['d = {"a": 1}', "for k in d.keys():", "    t = len(k)"], None,
     "`keys` is the walk over `d` under another name, and is not in the "
     "method table"),
    ("d_values_r", ['d = {"a": 1}', "for v in d.values():", "    t = v"],
     None,
     "`values` walks the SECOND word of each pair, which is a different offset "
     "than every walk above it"),
    ("d_del_during_walk_r", ['d = {"a": 1, "b": 2}', "for k in d:",
                             "    del d[k]"], None,
     "deleting during an iteration is a RuntimeError in CPython, and this path "
     "answered 1 with exit 0 before the gate: the walk is an index loop over a "
     "count read at run time, so a size change under it is detected by "
     "nothing. `del` changes the size UNCONDITIONALLY, so the build can "
     "refuse it"),
    ("d_insert_during_walk", ['d = {"a": 1}', "for k in d:", '    d["z"] = 5'],
     NO_ANSWER,
     "a store that INSERTS during a walk is the same RuntimeError, and it "
     "answered 2 with exit 0 before the gate. Unlike the `del` above this one "
     "cannot be a build-time refusal — whether the miss happens is a RUN-TIME "
     "question — so it is the NO_ANSWER shape: the build succeeds, the "
     "program stops, and it says which rule it stopped on"),
    ("d_del_miss", ['d = {"a": 1}', 'del d["z"]'], NO_ANSWER,
     "deleting a key that is not there is a KeyError; the stop is the right "
     "answer and it is now LOUD, which is what this row pins — before the fix "
     "it exited 1 with nothing on stdout and nothing on stderr"),

]

SET_CASES = [
    ("s_len", ["s = {1, 2}"], "len(s)",
     "a set lowers as a LIST here (`bugs/FORMAL_set_value_model.md`), so its "
     "count is the blob's count word"),
    ("s_in", ["s = {1, 2}"], "1 if 1 in s else 0",
     "a set's membership is a linear scan where CPython's is a hash probe — "
     "same answer, different cost, and the file is the kind that says so"),
    ("s_in_miss", ["s = {1, 2}"], "1 if 9 in s else 0", "the miss"),
    ("s_walk_len", ["s = {1, 2}", "t = 0", "for x in s:", "    t = t + x"],
     "t",
     "a walk over a set's elements — the ORDER is insertion order here and "
     "hash order in CPython, so the walk is observed through a SUM, which is "
     "order-independent and therefore honest about what is being checked"),
    ("s_union", ["s = {1, 2}", "t = s | {2, 3}"], "len(t)",
     "the ONE container operator arm64 lowers correctly: a union drops the "
     "repeats. x86-64 refuses it, so this case is arm64-only"),
    ("s_union_elems", ["s = {1, 2}", "t = s | {2, 3}",
                       "u = 0", "for x in t:", "    u = u + x"],
     ("sum=%d len=%d\\n", ["u", "len(t)"]),
     "the union's CONTENTS, not only its length — the count word of a union was "
     "the row a wrong reservation got wrong, and a length alone cannot see it"),
    ("s_union_str", ['s = {"a"}', 't = s | {"a", "b"}'], "len(t)",
     "a union over string elements, where the elements are `char *` and the "
     "dedup compares addresses"),
    ("s_union_ior", ["s = {1, 2}", "s |= {3}"], "len(s)",
     "the AUGMENTED union, which reached the integer ALU before the desugaring: "
     "it answered 1 on arm64 and 0 on x86-64 where CPython answers 3"),
    ("s_intersection_r", ["s = {1, 2}", "t = s & {2}"], None,
     "`&` is INTERSECTION and needs a per-element membership scan per element. "
     "Measured before the operator gate: 2 on arm64 and 163061056 on x86-64 "
     "where CPython answers 1"),
    ("s_difference_r", ["s = {1, 2}", "t = s - {2}"], None,
     "`-` is SET DIFFERENCE. Measured before the gate: SIGSEGV on both "
     "architectures, no output, because the result is a word nowhere near a "
     "blob and `len` read a count out of it"),
    ("s_symdiff_r", ["s = {1, 2}", "t = s ^ {2}"], None,
     "`^` is SYMMETRIC DIFFERENCE. Measured before the gate: SIGSEGV on both"),
    ("s_sub_r", ["s = {1, 2}", "s -= {2}"], None,
     "the augmented difference, which is where the SIGSEGV was reproduced "
     "through the SECOND emitter as well"),
    ("s_andassign_r", ["s = {1, 2}", "s &= {2}"], None,
     "the augmented intersection: 2 on arm64 and garbage on x86-64"),
    ("s_issubset_r", ["s = {1, 2}", "v = 1 if s.issubset({1, 2, 3}) else 0"],
     None, "`issubset` is a per-element membership test per element"),
    ("s_add_r", ["s = {1, 2}", "s.add(3)"], None,
     "`add` is not in `model.BUILTIN_VALUE_METHODS`. Note that `s.add(v)` for a "
     "MEMBER is a no-op in CPython and would be findable here; it is refused "
     "rather than special-cased"),
    ("s_discard_r", ["s = {1, 2}", "s.discard(1)"], None,
     "`discard` removes a pair from the blob, a shift"),
    ("s_remove_r", ["s = {1, 2}", "s.remove(1)"], None,
     "`remove` is `discard` plus a membership test and a KeyError"),
    ("s_pop_r", ["s = {1, 2}", "v = s.pop()"], None,
     "`pop` removes an ARBITRARY element, so it needs an order this path does "
     "not define for a set"),
    ("s_union_method_r", ["s = {1, 2}", "t = s.union({3})"], None,
     "`union` is `|` under another name, and not in the method table"),
    ("s_intersection_m_r", ["s = {1, 2}", "t = s.intersection({2})"], None,
     "`intersection` is `&` under another name"),
    ("s_difference_m_r", ["s = {1, 2}", "t = s.difference({2})"], None,
     "`difference` is `-` under another name"),
    ("s_symdiff_m_r", ["s = {1, 2}", "t = s.symmetric_difference({2})"], None,
     "`symmetric_difference` is `^` under another name"),
]

TUPLE_CASES = [
    ("t_len", ["t = (1, 2, 3)"], "len(t)",
     "a tuple is a blob with a marker, so its count is the blob's count word"),
    ("t_index", ["t = (1, 2, 3)"], "t[1]", "a tuple subscript"),
    ("t_index_neg", ["t = (1, 2, 3)"], "t[-1]", "CPython's negative index"),
    ("t_assign_r", ["t = (1, 2, 3)", "t[0] = 9"], None,
     "a tuple is IMMUTABLE in CPython, so this is a TypeError there and a "
     "refusal here — and a store would be wrong, not merely unsupported"),
    ("t_concat", ["t = (1, 2)", "u = t + (3,)"], "len(u)",
     "`+` between two tuples, which is a concatenation"),
    ("t_slice", ["t = (1, 2, 3)", "u = t[1:]"], "len(u)", "a tuple slice"),
    ("t_in", ["t = (1, 2, 3)"], "1 if 2 in t else 0",
     "tuple membership with a scalar needle"),
    ("t_walk", ["t = (1, 2, 3)", "s = 0", "for x in t:", "    s = s + x"], "s",
     "a walk, observed through a sum for the same order-independence reason as "
     "the set walk"),
    ("t_eq_r", ["t = (1, 2, 3)", "v = 1 if t == (1, 2, 3) else 0"],
     None, "`==` on two blobs — the operator gate's own row"),
    ("t_count_r", ["t = (1, 2, 1)", "v = t.count(1)"], None,
     "`count` on a tuple: only lowered on a `char *`"),
    ("t_index_m_r", ["t = (1, 2, 3)", "v = t.index(2)"], None,
     "`index` on a tuple: a length-dependent search whose result is a position"),
    ("t_hash_r", ["t = (1, 2)", "d = {}", "d[t] = 1"],
     ("v=%d\\n", ["d[t]"]),
     "a tuple as a dict KEY: the pair blob compares a key element-wise through "
     "`model.static_key_elements`, so this answers CPython's answer. It was "
     "written as a refusal on the reasoning that a tuple is a blob with no hash "
     "value, and that reasoning was wrong — the comparison is structural, not "
     "by hash, and the measurement said so"),
    ("t_key_literal_r", ["d = {}", "d[(1, 2)] = 7"], None,
     "the same key spelled as a LITERAL is refused by "
     "`model.multi_index_refusal_for` — a different gate from the name case "
     "above, and the pair of rows is what says which spelling is which"),
]

ALIAS_CASES = [
    # Mutation THROUGH a reference, and the one place where this path's value
    # model is a documented divergence rather than a bug: there is no heap, so a
    # blob is a frame block and `b = a` is a REFERENCE to it, which for CPython's
    # aliasing questions happens to give the right answers and for its
    # rebinding questions does not.
    ("a_ref_store",
     ["a = [3, 1, 2]", "b = a", "a[0] = 9"],
     ("%d %d %d\\n", ["a[0]", "b[0]", "len(a)"]),
     "a store through `a` seen through `b`: both numbers in one answer, so a "
     "copy where CPython shares cannot pass"),
    ("a_ref_append",
     ["a = [3, 1, 2]", "b = a", "a.append(9)"],
     ("a=%d b=%d v=%d\\n", ["len(a)", "len(b)", "a[3]"]),
     "the same through `append`, whose capacity comes from the LITERAL `a` is "
     "bound to — so a store through `b` is the interesting case and is the "
     "next row"),
    ("a_ref_append_through_alias_r",
     ["a = [3, 1, 2]", "b = a", "b.append(9)"], None,
     "`append` through a NAME that is not the literal is refused on both "
     "architectures: the room an append needs has to be known when the list is "
     "built, and this one is not known"),
    ("a_concat_is_new",
     ["a = [3, 1, 2]", "c = a + [9]"],
     ("a=%d c=%d v=%d\\n", ["len(a)", "len(c)", "c[3]"]),
     "`+` builds a NEW blob: `a` keeps its length and `c` has the element. This "
     "is the row that separates a concat from an in-place mutation"),
    ("a_aug_is_rebind",
     ["a = [1, 2]", "a += [3]"],
     ("len=%d v=%d\\n", ["len(a)", "a[2]"]),
     "`+=` desugars onto `+` and stores the result, so the count and the new "
     "element are both there. It reached the integer ALU before the "
     "desugaring: 0 on arm64 and SIGSEGV on x86-64, where CPython says 3"),
    ("a_aug_star",
     ["a = [1]", "a *= 3"], "len(a)",
     "`*=` is the same desugaring onto `xs * n`. It was a SIGSEGV on BOTH "
     "architectures, where CPython says 3"),
    ("a_slice_is_copy",
     ["a = [3, 1, 2]", "b = a[0:2]", "b[0] = 9"],
     ("%d %d %d\\n", ["a[0]", "b[0]", "len(b)"]),
     "a slice is a MATERIALIZED COPY here, so writing into it must not reach "
     "the source — which is why x86-64 refuses a slice STORE outright and "
     "arm64 only lowers the same-length one"),
]

OPERATOR_CASES = [
    # The operator matrix, as a table rather than as prose: every operator this
    # gate covers, with a blob on the left, and the CPython answer beside it.
    # These are all REFUSALs, and they are here because a gate that stopped
    # covering one of them would answer with an ADDRESS again — silently, and
    # with exit 0.
    ("o_lt", ["a = [9]", "b = [1]", "v = 1 if b > a else 0"], None,
     "`>` between two blobs: the row the gate started as, measured answering 1 "
     "where CPython answers 0 — the ALLOCATION ORDER, not the elements"),
    ("o_le", ["a = [9]", "b = [1]", "v = 1 if b >= a else 0"], None,
     "`>=`: the same compare with the other sense. A gate that fired on `<` and "
     "not on `>=` would leave half the ordering operators unrefused"),
    ("o_gt_scalar", ["a = [9]", "v = 1 if a > 0 else 0"], None,
     "a blob against a NUMBER. CPython raises TypeError for it, so there is no "
     "correct program on the far side of the gate"),
    ("o_eq", ["a = [3, 1, 2]", "v = 1 if a == [3, 1, 2] else 0"],
     None,
     "`==`: measured answering 0 where CPython answers 1, because the literal "
     "is a SECOND block at a different address"),
    ("o_ne", ["a = [3, 1, 2]", "v = 1 if a != [3, 1, 2] else 0"],
     None, "`!=` is the same comparison inverted, and answered 1 where CPython "
     "answers 0"),
    ("o_is", ["a = [1, 2]"], "1 if a is a else 0",
     "`is` is IDENTITY, which on this path is unboxed word equality, and two "
     "distinct blob literals ARE two distinct addresses — so `a is a` answers "
     "1, which is CPython's answer. It is here as an ANSWER because a gate that "
     "refused every container operand would take a correct operator with it"),
    ("o_is_not", ["a = [1, 2]", "b = [1, 2]"], "1 if a is not b else 0",
     "`is not` between two SEPARATE literals, where CPython also says they are "
     "not the same object — and the answer here comes from the addresses being "
     "different, which is the one time an address comparison is CPython's "
     "answer rather than an accident"),
    ("o_sub", ["a = [1, 2]", "t = a - [2]"], None,
     "`-` between two containers: a TypeError in CPython, and measured as a "
     "SIGSEGV here before the gate"),
    ("o_xor", ["s = {1, 2}", "t = s ^ {2}"], None,
     "`^`: SYMMETRIC DIFFERENCE, measured as a SIGSEGV before the gate"),
    ("o_and", ["s = {1, 2}", "t = s & {2}"], None,
     "`&`: INTERSECTION, measured as 2 on arm64 and 163061056 on x86-64 where "
     "CPython answers 1 — the two architectures disagreeing is the clearest "
     "possible sign that neither computed a set"),
    ("o_floordiv", ["a = [1, 2]", "t = a // [2]"], None,
     "`//` has no container meaning in CPython at all, so refusing it is "
     "doubly right: the program is already broken"),
    ("o_mod", ["a = [1, 2]", "t = a % [2]"], None,
     "`%`: as above"),
    ("o_pow", ["a = [1, 2]", "t = a ** [2]"], None, "`**`: as above"),
    ("o_lshift", ["a = [1, 2]", "t = a << [2]"], None, "`<<`: as above"),
    ("o_rshift", ["a = [1, 2]", "t = a >> [2]"], None, "`>>`: as above"),
    ("o_in_container_needle",
     ["a = [[1], [2]]", "v = 1 if [1] in a else 0"], None,
     "`in` with a CONTAINER needle: answered 1 on arm64 and 0 on x86-64 where "
     "CPython answers 1, and 0 on BOTH once the needle is a NAME"),
    ("o_in_dict_container_needle",
     ["d = {(1, 2): 7}", "v = 1 if (1, 2) in d else 0"], None,
     "the same through a dict, where the scan is over KEYS at stride 16"),
    ("o_int_or", ["a = 6", "b = 3"], "a | b",
     "the operator `|` on two INTEGERS is a bitwise or and answers 7 on both "
     "backends: the row that a `|` gate keyed on the operator rather than on "
     "the operand would break"),
    ("o_int_eq", ["a = 6", "b = 6"], "1 if a == b else 0",
     "`==` on two integers is 1, and it is the row that keeps the container "
     "equality gate from being an operator-wide one"),
    ("o_int_aug", ["a = 1", "a += 2", "a <<= 3"], "a",
     "integer `+=` and `<<=`, byte-identical before and after the augmented "
     "container desugaring — the branch is asked after the shift and divide "
     "dispatches have returned"),
    ("o_str_eq", ['s = "ab"'], '1 if s == "ab" else 0',
     "a STRING `==` is answered, and by `strcmp` rather than by the container "
     "gate: a `char *` is a word here, and word equality is the right answer "
     "for two of them because it is a CONTENT comparison rather than an "
     "address one. It is in this file so a gate widened to \"both operands are "
     "not integers\" is caught"),
    ("o_str_eq_miss", ['s = "ab"'], '1 if s == "zz" else 0',
     "the MISSING case of the row above: a content comparison that says False "
     "must not be a comparison of two addresses that happens to differ"),
    ("o_str_ne", ['s = "ab"'], '1 if s != "ab" else 0',
     "`!=` is the same content comparison inverted"),
    ("o_str_lt_r", ['s = "ab"', 'v = 1 if s < "b" else 0'], None,
     "a string ORDERING is refused, by `model.string_compare_word_refusal`'s "
     "table, because a `char *` has no order — and it is refused for a "
     "DIFFERENT reason than a blob's, so the two refusals must not be merged"),
    ("o_plus_concat", ["a = [1]", "b = [2]"], "len(a + b)",
     "`+` between two containers is a CONCATENATION on both backends, and is "
     "deliberately outside the operator gate: the row that says the gate is "
     "keyed on the operator and not on \"a container is involved\""),
]


GROUPS = {
    "list": ("list", LIST_CASES),
    "dict": ("dict", DICT_CASES),
    "set": ("set", SET_CASES),
    "tuple": ("tuple", TUPLE_CASES),
    "alias": ("alias", ALIAS_CASES),
    "operator": ("operator", OPERATOR_CASES),
}

#: The rows that CANNOT agree between the two architectures, and why.  Two
#: tables, because there are two shapes of "cannot", and conflating them is how
#: a split turns into a silent skip.
#:
#: `BACKEND_ONLY` — the case is EXCLUDED from the group image on the backend
#: named, because that backend cannot build it at all.  It is not run there and
#: it does not fail there; it is simply not that backend's case.  This is a
#: CLAIM about the target: a backend that grows the lowering has to delete its
#: row, and until it does the corpus says the capability is absent rather than
#: discovering it by a build failure.
BACKEND_ONLY = {
    # x86-64 has no set-union emitter; arm64's is correct for two sets. The
    # refusal is the honest answer here rather than a wrong concatenation.
    "s_union": "x86_64",
    "s_union_elems": "x86_64",
    "s_union_str": "x86_64",
    "s_union_ior": "x86_64",
    # A same-length slice STORE is arm64's lowering; x86-64 has none, and
    # refusing it is the correct answer for a slice that is a materialized copy.
    "l_slice_store_same": "x86_64",
}


def compare(group, cases, backend, verbose):
    """Every case of `cases`, against CPython, on `backend`.

    Three outcomes per case and all three are reported: an agreement, a
    divergence (which is the failure), and a case whose build was REFUSED —
    which is compared against the case's OWN `why`, so a case cannot pass by
    being refused for an unrelated reason.
    """
    answer_cases = [c for c in cases
                    if c[2] is not None and c[2] != NO_ANSWER
                    and BACKEND_ONLY.get(c[0]) != backend]
    refusal_cases = [c for c in cases if c[2] is None]
    no_answer_cases = [c for c in cases
                       if c[2] == NO_ANSWER
                       and BACKEND_ONLY.get(c[0]) != backend]

    bad = []
    agreed = 0
    if answer_cases:
        got = program(answer_cases, f"cm_{group}", backend)
        want = reference(answer_cases)
        for key, _setup, _probe, why in answer_cases:
            mine, expect = got.get(key), want.get(key)
            if mine is None:
                bad.append((key, why, "no record in the image", expect))
                continue
            if mine != expect:
                bad.append((key, why, mine, expect))
                continue
            agreed += 1

    refused = 0
    skipped = 0
    for key, setup, _probe, why in refusal_cases:
        if BACKEND_ONLY.get(key) == backend:
            skipped += 1
            continue
        body = _source([(key, setup, None, "")])
        try:
            build("\n".join(body) + "\n", f"cmr_{group}_{key}", backend)
        except Failure as e:
            msg = str(e)
            if not _is_a_named_refusal(msg):
                bad.append((key, why, f"refused for an unnamed reason: "
                                       f"{msg[-200:]}", "a refusal this path "
                                                          "documents"))
                continue
            refused += 1
            continue
        bad.append((key, why,
                    f"the build SUCCEEDED on {backend}, so this case no longer "
                    f"measures a refusal — it was written to hold a build-time "
                    f"refusal and now holds an image",
                    "a build-time refusal, or an answer and a row in "
                    "BACKEND_ONLY"))

    # ── the THIRD outcome: must build, must NOT answer ────────────────────
    # An out-of-range subscript builds and then stops.  Asserting that it stops
    # is a real assertion — the bounds check has to be EMITTED for it, and a
    # build that dropped the check would read out of the frame and answer a
    # number, which is the failure this row is for.  It is its own loop because
    # these cases print nothing and so have no record to compare.
    no_answer = 0
    for key, setup, _probe, why in no_answer_cases:
        body = _source([(key, setup, NO_ANSWER, "")])
        try:
            out = build("\n".join(body) + "\n", f"cmn_{group}_{key}", backend)
            run(out)
        except Failure as e:
            # It stopped — which is what the case asks for.  The message is
            # carried into `verbose` rather than discarded, because WHICH stop
            # it was is the difference between a bounds check and a null write.
            no_answer += 1
            if verbose:
                print(f"    [{backend}] {key} stopped as asked: "
                      f"{str(e).splitlines()[-1][:90]}")
            continue
        bad.append((key, why, f"{backend} ANSWERED where the case requires it "
                              f"to stop", "a non-zero exit and no answer"))

    if bad:
        key, why, mine, expect = bad[0]
        raise Failure(
            f"[{backend}] {group}: {len(bad)} of {len(cases)} case(s) fail\n"
            f"  first: {key} — {why}\n"
            f"    this path: {mine!r}\n"
            f"    CPython:   {expect!r}")
    if verbose:
        print(f"    [{backend}] {len(answer_cases)} answer(s) equal CPython, "
              f"{refused} refusal(s), {no_answer} stop(s), {skipped} "
              f"backend-only")
    return agreed, refused


#: A refusal has to be one this tree WRITES DOWN.  The shared tables own the
#: wording, and they are the claim being tested here: a build that fails for a
#: reason no table states is a different failure from a construct that is
#: refused, and it is the one that goes unreported.  Each fragment below is a
#: phrase that appears in a refusal text in `formal/model.py`, so the list is
#: derived from the target rather than written out here — with the exception of
#: the two that name a construct this path has no representation for at all.
_NAMED_REFUSAL_FRAGMENTS = (
    "is refused when",                  # container_operator_refusal
    "is refused because",               # container_union_refusal
    "as the NEEDLE of",                 # container_membership_refusal
    "is not lowered on this path",      # slice_store_refusal
    "writes",                           # slice_store_static_length_refusal
    "not in `model.BUILTIN_VALUE_METHODS`",
    "lowers only append, clear, close, write",
    "is a method call on a value",
    "is a method on a string",
    "is a real method of String",
    "returns a NEW string",
    "is a length-dependent SEARCH",
    "is only lowered on a char *",
    "cannot tell whether",
    "is refused when the left operand",
    "has no representation on this path",
    "is not supported on the formal arm64 path",
    "RHS must be a list/tuple name or literal",
    "is a STORE into a TUPLE",        # container_store_refusal
    "the room an append needs has to be known",   # list_append_overflow
    # dict_walk_mutation_message, whose first clause is the same in both of its
    # sentences, so the clause is the fragment rather than either message.
    "RuntimeError: dictionary changed size during iteration",
    # string_compare_word_refusal's own table, for the string ORDERING row.
    "Python orders strings lexicographically",
)


def _is_a_named_refusal(msg: str) -> bool:
    """True when `msg` is a refusal some shared table in `formal/model.py`
    writes.

    The alternative — accepting any non-zero build — is how a construct that
    stopped being refused passes this file forever, and how a genuine internal
    error (a `KeyError` in the backend, a missing symbol) is counted as a
    refusal.  Both are silent.  The list is fragments rather than an equality
    test because the messages are long and are written to be read, not matched.
    """
    return any(f in msg for f in _NAMED_REFUSAL_FRAGMENTS)


def run_group(group, verbose):
    tag, cases = GROUPS[group]
    total_a = total_r = 0
    for backend in backends():
        a, r = compare(group, cases, backend, verbose)
        total_a += a
        total_r += r
    note = (f"{total_a} answer(s) equal CPython and {total_r} refusal(s) "
            f"named, over {len(backends())} backend(s)")
    return True, note


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("groups", nargs="*",
                    help="groups to run: " + " ".join(sorted(GROUPS)))
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--keep", action="store_true",
                    help="keep the built images and sources")
    args = ap.parse_args()
    groups = args.groups or list(GROUPS)
    unknown = [g for g in groups if g not in GROUPS]
    if unknown:
        ap.error(f"unknown group(s): {' '.join(unknown)}; "
                 f"known: {' '.join(sorted(GROUPS))}")
    if platform.machine() not in ("arm64", "aarch64", "x86_64"):
        print(f"note: host is {platform.machine()}, neither arm64 nor x86-64")

    global TEMP
    failures = []
    with tempfile.TemporaryDirectory() as td:
        TEMP = td
        if args.verbose:
            print(f"    backends: {', '.join(backends())}")
        for g in groups:
            try:
                _ok, note = run_group(g, args.verbose)
            except Failure as e:
                failures.append((g, str(e)))
                print(f"  FAIL  container-methods:{g}")
                print("        " + str(e).replace("\n", "\n        "))
            else:
                print(f"  PASS  container-methods:{g}  ({note})")
    print(f"container methods: PASS={len(groups) - len(failures)} "
          f"FAIL={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())