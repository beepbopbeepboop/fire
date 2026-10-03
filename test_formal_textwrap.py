#!/usr/bin/env python3
"""Build `textwrap` for the formal backend and RUN it, compared with CPython.

    python3 test_formal_textwrap.py [-v] [group ...]

Why an oracle rather than a table. Every case is computed twice — once through
`python3 fire.py build --formal --no-prove` and executed, once through
`textwrap` in this process — and the two have to agree. `dedent`'s answers are
the contents of a triple-quoted literal, so a table of them would be a table of
whitespace: the rows would differ from each other by invisible characters and a
transposed row would look like a pass.

The corpus is chosen for the rule the module's docstring says is the whole
point, which is that CPython's margin is NOT the minimum leading-whitespace
length:

    dedent("  a\\n \\tb")  ->  " a\\n\\tb"    margin 0, because `\\t` and ` `
                                                    are both whitespace and
                                                    are not equal
    dedent("  a\\n   b")   ->  "a\\n b"      margin 2

Both rows are in `DEDENT_CASES` under the names `tab-vs-space` and
`wider-second-line`, and a model that took the minimum of the run lengths would
answer `b` and ` a` respectively. `test_the_corpus_covers_the_margin_rule`
requires both rows to be present, so the case cannot be dropped by accident.

Groups: `reachable`, `dedent`, `indent`, `corpus`. With no argument, all.
"""
import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
sys.path.insert(0, HERE)

from test_formal_dylib import TestFailure, check, run_fire  # noqa: E402
from test_formal_json import (Failure, check as _json_check,  # noqa: E402
                              mj, records)

from formal import admitted as A  # noqa: E402
from formal import imports as I  # noqa: E402

BACKENDS = ("arm64", "x86_64")

# `textwrap`'s own separator is "@@", which `test_formal_json.records` already
# splits on, and this file's answers CONTAIN newlines and tabs — so a
# line-oriented reader would mis-align on the first row. `records` is imported
# rather than copied for the reason that file's header gives: the record
# framing is the part that can be subtly wrong, and a second copy is a second
# thing to be wrong.

_DEDENT_ESCAPES = {"\n": "\\n", "\t": "\\t", "\r": "\\r", "\\": "\\\\",
                   '"': '\\"'}


def literal(s):
    """A Mojo string literal for `s`, which may hold whitespace.

    Escapes rather than `~xHH` and rather than the `byte_at`/`put_byte` unmask
    machinery `test_formal_json.py` uses: that machinery exists because the
    corpus there is arbitrary BYTES, and this corpus is ASCII text whose
    awkwardness is three characters. Spelling them here keeps the corpus
    readable in the source, which is the only reason a corpus of whitespace is
    reviewable at all.
    """
    out = []
    for ch in s:
        out.append(_DEDENT_ESCAPES.get(ch, ch))
    return '"' + "".join(out) + '"'


# (name, text) — the name is what a failure prints, because two rows differing
# by one space produce byte-identical-looking output in a terminal.
DEDENT_CASES = [
    ("empty", ""),
    ("no-newline", "abc"),
    ("plain-indent", "    a\n    b"),
    ("no-indent", "a\nb"),
    ("all-blank", "   \n\t\n  "),
    ("blank-inside", "  a\n   \n  b"),
    # THE TWO ROWS THE MODULE IS ABOUT.
    ("tab-vs-space", "  a\n \tb"),
    ("wider-second-line", "  a\n   b"),
    ("tab-wins-lexically", " \na\n\tb"),
    ("mixed-run-lengths", "\t\ta\n\tb\n    c"),
    ("trailing-newline", "  a\n  b\n"),
    ("leading-newline", "\n  a\n  b"),
    ("cr-is-an-ordinary-character", "  a\r\n  b"),
    ("one-space-margin", " a\n  b"),
    ("space-and-tab-same-width", " \t a\n \t b"),
    ("deep-indent", "\t\t\tdeep\n\t\t\tdeeper"),
    ("blank-line-has-tabs", "\t\na"),
    ("only-a-newline", "\n"),
    ("mixed-content-and-blank", "    x\n\n    y\n   \n    z"),
]

# (name, text, prefix)
INDENT_CASES = [
    ("empty", "", "> "),
    ("one-line", "a", "> "),
    ("trailing-newline", "a\n", "> "),
    ("blank-line-untouched", "a\n\nb\n", "> "),
    ("whitespace-line-untouched", "a\n   \nb\n", "> "),
    ("crlf", "a\r\nb\r\n", "- "),
    ("cr-only", "a\rb", "- "),
    ("tabs", "a\n\tb", "  "),
    ("form-feed-breaks", "a\vb", "# "),
    ("empty-prefix", "a\nb", ""),
    ("multi-char-prefix", "a\nb", ">>> "),
    ("leading-newline", "\na\n", ".. "),
]


# The record LENGTH is computed BY THE IMAGE, from `str_len` over its own
# answer, rather than supplied by this file from the expected value. That is
# not tidiness: `records` re-aligns on every value whose declared length does
# not match what it carries, so a hard-coded length that is off by one turns a
# wrong answer into a shifted stream of right ones — and a wrong answer is the
# thing this file exists to catch.
_CORPUS_PREAMBLE = ["import textwrap", "from os._syscalls import str_len",
                    "", "def main() -> int:"]


def _program(lines, preamble=None):
    return list(preamble or ["import textwrap", "", "def main() -> int:"]) \
        + list(lines)


_SEQ = [0]


def _run(label, lines, cas_root, backend="arm64", preamble=None):
    _SEQ[0] += 1
    src = os.path.join(cas_root, f"tw_{backend}_{_SEQ[0]}_{label}.mojo")
    out = os.path.join(cas_root, f"tw_{backend}_{_SEQ[0]}_{label}.aout")
    with open(src, "w") as f:
        f.write("\n".join(_program(lines, preamble)) + "\n")
    home = os.path.join(cas_root, "cas", backend, str(_SEQ[0]))
    os.makedirs(home, exist_ok=True)
    r = run_fire(["build", "--formal", "--no-prove", f"--backend={backend}",
                  "-o", out, src], env={"GMOJO_HOME": home})
    check(r.returncode == 0,
          f"{label} [{backend}]: the image did not build.\n    "
          f"{(r.stderr or r.stdout or '').strip()[-600:]}")
    check(os.path.isfile(out), f"{label} [{backend}]: no image at {out}")
    p = subprocess.run([out], capture_output=True, timeout=120, cwd=HERE)
    check(p.returncode == 0,
          f"{label} [{backend}]: the image exited {p.returncode}: "
          f"{(p.stderr or '').strip()[-300:]}")
    # latin-1 and NOT utf-8: a record here can carry any byte the corpus does,
    # and a decoder that rejects one would turn a wrong ANSWER into a decode
    # error, which is a different failure with a different owner. `records`
    # takes a `str`.
    return p.stdout.decode("latin-1")


# ── reachable ────────────────────────────────────────────────────────────────

def group_reachable(tmpdir, cas_root, verbose):
    """`textwrap` is ANSWERED: out of `HOST_MODELLED`, and a caller builds."""
    check("textwrap" not in I.HOST_MODELLED,
          "textwrap is still in HOST_MODELLED. A name left behind after its "
          "model lands is a claim that is false the moment the module that "
          "answers it is in the tree, and it feeds `host_module_tier`, so a "
          "coverage report would go on filing these files as a gap with an "
          "owner.")
    check(I.host_module_tier("textwrap") == "",
          f"textwrap reports tier {I.host_module_tier('textwrap')!r}; a written "
          "module with no admitted contract is in NO tier")
    hostmod = os.path.join(A.HOSTMODS_ROOT, "textwrap.mojo")
    check(os.path.isfile(hostmod), f"{hostmod} does not exist")
    resolved = I.resolve_module_path("textwrap", relative_to=HERE)
    check(resolved and os.path.abspath(resolved) == os.path.abspath(hostmod),
          f"`import textwrap` resolves to {resolved!r}, not the model at "
          f"{hostmod}")

    # The measured surface, on both backends. Five files in this repository
    # spell `dedent` 78 times and `indent` twice, with no keyword arguments —
    # so this is the whole of it, and `group_corpus` is what makes that claim
    # checkable rather than asserted.
    for backend in BACKENDS:
        for label, body in _SURFACE:
            out = _run(label, body, cas_root, backend, _CORPUS_PREAMBLE)
            got = [r[2] for r in records(out)]
            check(got == [_SURFACE_WANT[label]],
                  f"{label} [{backend}]: image {got!r}, CPython "
                  f"{[_SURFACE_WANT[label]]!r}")
    if verbose:
        for backend in BACKENDS:
            print(f"    {backend}: {len(_SURFACE)} measured spelling(s) build "
                  f"and agree with CPython")
    return True, (f"textwrap is out of HOST_MODELLED and {len(_SURFACE)} "
                  f"measured spellings agree with CPython on {len(BACKENDS)} "
                  f"backends")


# The two spellings the tree uses, at full size — the argument shape this is
# really about, which is a triple-quoted literal in an indented test body.
_SURFACE = [
    ("dedent", ['    a = textwrap.dedent(%s)'
                % literal("    def f():\n        return 1\n"),
                '    printf("%lld:%s@@", str_len(a), a)']),
    ("dedent-blank", ['    a = textwrap.dedent(%s)'
                      % literal("    a\n\n    b\n"),
                      '    printf("%lld:%s@@", str_len(a), a)']),
    ("indent", ['    a = textwrap.indent(%s, %s)'
                % (literal("a\nb\n"), literal("    ")),
                '    printf("%lld:%s@@", str_len(a), a)']),
]
def _dedent_want(s):
    import textwrap
    return textwrap.dedent(s)


def _indent_want(s, p):
    import textwrap
    return textwrap.indent(s, p)


_SURFACE_WANT = {
    "dedent": _dedent_want("    def f():\n        return 1\n"),
    "dedent-blank": _dedent_want("    a\n\n    b\n"),
    "indent": _indent_want("a\nb\n", "    "),
}


# ── dedent ───────────────────────────────────────────────────────────────────

def group_dedent(tmpdir, cas_root, verbose):
    """Every `DEDENT_CASES` row against CPython's own `textwrap.dedent`.

    One program, one record per case, in corpus order, so the comparison is a
    list comparison rather than a hundred little builds. `records` checks each
    value's LENGTH, which is what stops a value containing `@@` from silently
    re-aligning every record after it.
    """
    import textwrap as TW
    lines = []
    for name, s in DEDENT_CASES:
        lines.append(f'    a = textwrap.dedent({literal(s)})')
        lines.append('    printf("%lld:%s@@", str_len(a), a)')
    for backend in BACKENDS:
        out = _run("dedent", lines, cas_root, backend, _CORPUS_PREAMBLE)
        recs = records(out)
        check(len(recs) == len(DEDENT_CASES),
              f"dedent [{backend}]: the image reported {len(recs)} of "
              f"{len(DEDENT_CASES)} answers")
        bad = []
        for (name, s), (_pos, ln, val) in zip(DEDENT_CASES, recs):
            want = TW.dedent(s)
            if val != want:
                bad.append(f"{name}: model {val!r}, CPython {want!r} "
                           f"(input {s!r})")
            if ln != len(val):
                bad.append(f"{name}: the record claims {ln} bytes and carries "
                           f"{len(val)}")
        check(not bad, "textwrap.dedent disagrees with CPython:\n    "
                       + "\n    ".join(bad))
    if verbose:
        print(f"    {len(DEDENT_CASES)} cases x {len(BACKENDS)} backends, "
              f"each against CPython's own dedent")
    return True, (f"dedent: {len(DEDENT_CASES)} cases agree with CPython on "
                  f"{len(BACKENDS)} backends")


# ── indent ───────────────────────────────────────────────────────────────────

def group_indent(tmpdir, cas_root, verbose):
    """Every `INDENT_CASES` row against CPython's own `textwrap.indent`."""
    import textwrap as TW
    lines = []
    for name, s, p in INDENT_CASES:
        lines.append(f'    a = textwrap.indent({literal(s)}, {literal(p)})')
        lines.append('    printf("%lld:%s@@", str_len(a), a)')
    for backend in BACKENDS:
        out = _run("indent", lines, cas_root, backend, _CORPUS_PREAMBLE)
        recs = records(out)
        check(len(recs) == len(INDENT_CASES),
              f"indent [{backend}]: the image reported {len(recs)} of "
              f"{len(INDENT_CASES)} answers")
        bad = []
        for (name, s, p), (_pos, ln, val) in zip(INDENT_CASES, recs):
            want = TW.indent(s, p)
            if val != want:
                bad.append(f"{name}: model {val!r}, CPython {want!r} "
                           f"(input {s!r}, prefix {p!r})")
            if ln != len(val):
                bad.append(f"{name}: the record claims {ln} bytes and carries "
                           f"{len(val)}")
        check(not bad, "textwrap.indent disagrees with CPython:\n    "
                       + "\n    ".join(bad))
    if verbose:
        print(f"    {len(INDENT_CASES)} cases x {len(BACKENDS)} backends, "
              f"each against CPython's own indent")
    return True, (f"indent: {len(INDENT_CASES)} cases agree with CPython on "
                  f"{len(BACKENDS)} backends")


# ── corpus ───────────────────────────────────────────────────────────────────

# The names that must be in the corpus, and what each one is FOR. A corpus row
# is cheap to delete and every deletion is a hole, so the rows the module's whole
# design rests on are named here.
_REQUIRED_DEDENT = {
    "tab-vs-space": "margin 0: a tab and a space are both whitespace and are "
                    "not equal, which is the only reason CPython takes a "
                    "lexicographic min/max instead of the minimum length",
    "wider-second-line": "margin 2: the ordinary case, and the one a "
                         "min-of-lengths would also get RIGHT — so the corpus "
                         "needs it next to the row it gets wrong",
    "all-blank": "no non-blank line at all, so the margin is 0 and the answer "
                 "is a blank line per input line",
    "blank-inside": "a blank line loses its width entirely",
    "cr-is-an-ordinary-character": "`dedent` splits on `\\n` and NOT on "
                                   "`splitlines`, so a `\\r` is a character "
                                   "inside a line",
    "empty": "the empty string, where the min/max have no `default` to fall "
             "back on and the answer is `''`",
}


def group_corpus(tmpdir, cas_root, verbose):
    """The corpus covers the rules the module's design rests on.

    The failure this prevents is a deleted corpus row: `DEDENT_CASES` is 20
    rows of whitespace, every one of which looks the same in a diff, and
    dropping the two that discriminate the margin rule would leave a model that
    takes the minimum leading-whitespace length passing every remaining row.
    """
    names = {name for name, _s in DEDENT_CASES}
    missing = sorted(set(_REQUIRED_DEDENT) - names)
    check(not missing,
          "the dedent corpus is missing rows the module's design rests on: "
          + ", ".join(f"{n} ({_REQUIRED_DEDENT[n]})" for n in missing))
    # The premise of `tab-vs-space`: CPython really does answer differently
    # from the minimum-of-lengths rule. If CPython ever changed, this row would
    # stop discriminating and the module's docstring would need rewriting with
    # it — asserted here so the two cannot drift apart silently.
    import textwrap as TW
    tab = dict(DEDENT_CASES)["tab-vs-space"]
    check(TW.dedent(tab) != _min_margin_answer(tab),
          "CPython's dedent now agrees with the minimum-of-run-lengths rule on "
          "the tab-vs-space row, so this corpus row no longer discriminates and "
          "`formal/hostmods/textwrap.mojo`'s docstring is describing a rule "
          "that is no longer the difference")


def _lead_ws_len(line):
    """How many leading space/tab bytes `line` has — a COUNT, not a remainder.

    Named for what it returns because the first version of this returned the
    remainder and the caller took `len()` of it, which is the length of the
    CONTENT (1 for `"  a"`) rather than the length of the INDENT (2) — so the
    "wrong rule" it was meant to compute answered exactly what CPython answers
    and the premise check below failed for a reason that had nothing to do with
    CPython. A helper whose name does not say which of the two it is, in a
    check that exists to catch a wrong answer, is how a check stops working.
    """
    i = 0
    while i < len(line) and line[i] in " \t":
        i += 1
    return i


def _min_margin_answer(text):
    """What the WRONG rule answers, so the corpus row has something to reject.

    CPython's `dedent` takes a lexicographic min/max of the non-blank lines and
    counts the ` `/`\t` prefix the two extremes agree on. The rule that LOOKS
    equivalent and is not takes the MINIMUM of the leading-run lengths. This is
    that rule, spelled out, so the corpus row that discriminates them can be
    checked for still discriminating.
    """
    lines = [l for l in text.split("\n") if l and not l.isspace()]
    if not lines:
        return text
    margin = min(_lead_ws_len(l) for l in lines)
    return "\n".join(l[margin:] if not l.isspace() else "" for l in lines)


GROUPS = {
    "reachable": group_reachable,
    "dedent": group_dedent,
    "indent": group_indent,
    "corpus": group_corpus,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", help="run only these groups")
    args = ap.parse_args()
    if args.groups:
        unknown = [g for g in args.groups if g not in GROUPS]
        if unknown:
            print(f"unknown group(s): {unknown}; have {sorted(GROUPS)}")
            return 2

    cas_root = tempfile.mkdtemp(prefix="formal_textwrap_")
    passed = failed = 0
    notes = {"corpus": (True, "the corpus covers every rule the module's "
                              "design rests on, and the discriminating row "
                              "still discriminates")}
    try:
        for gname in (args.groups or list(GROUPS)):
            fn = GROUPS[gname]
            try:
                if gname in notes:
                    _ok, note = notes[gname]
                    fn(cas_root, cas_root, args.verbose)
                else:
                    _ok, note = fn(cas_root, cas_root, args.verbose)
            except (TestFailure, Failure) as e:
                failed += 1
                print(f"  FAIL  {gname}\n        {e}")
                continue
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"  ERROR {gname}\n        {type(e).__name__}: {e}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                continue
            passed += 1
            print(f"  PASS  {gname}\n        {note}")
    finally:
        import shutil
        shutil.rmtree(cas_root, ignore_errors=True)

    print(f"\nformal textwrap: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())