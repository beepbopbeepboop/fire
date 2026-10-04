#!/usr/bin/env python3
"""`formal/hostmods/glob.mojo`, differential against CPython's own `glob`.

    python3 test_formal_glob.py [-v] [group ...]

Groups: `resolve`, `listing`, `hidden`, `escape`, `blob`, `absent`. With no
argument, all. Every group that builds an image builds it on BOTH backends.

WHAT IS BEING COMPARED, AND WHY THE ORDER TOO
----------------------------------------------
CPython's `glob.glob` documents "The order of the returned paths is
undefined. Sort them if you need a particular order", so a differential test
has to decide what it compares, and the honest answer here is THE WHOLE LIST IN
ORDER: both implementations walk `os.scandir`, which is `readdir` order, and
`formal/hostmods/os/__init__.mojo`'s `listdir` is the same `readdir` order, so
the two orders are the same order and there is nothing to be undefined about.
Every case below is compared as an exact list — not as a set, and not sorted —
and the comparison is what makes a reordering visible: a module that answered
the right paths in a different order is a different program from the one CPython
runs, and `test_formal_pathlib.py`'s corpus already showed what that costs when
it is the matcher rather than the walk.

THE FIXTURE TREE IS BUILT BY THIS FILE, AND EVERY DOT IS ON PURPOSE
------------------------------------------------------------------
`glob`'s rules are about names that are not there in an ordinary directory tree,
so a fixture without them tests nothing:

    <root>/a.txt  b.py  c.txtx  UP.TXT  'sp ace.txt'  .dotfile
    <root>/link.txt -> a.txt              (a symbolic link to a FILE)
    <root>/dangling.txt -> nowhere.txt    (a link whose target is not there)
    <root>/.hidden.txt                    (a hidden FILE)
    <root>/sub/c.txt  .hidden2.txt  d.md
    <root>/sub/deep/e.txt
    <root>/.hiddendir/f.txt               (a hidden DIRECTORY)
    <root>/empty/                         (a directory with nothing in it)

  * `.dotfile`, `.hidden.txt`, `.hiddendir/` and `dangling.txt` are what make
    the hidden rules and `lexists`-vs-`exists` observable at all;
  * `c.txtx` and `UP.TXT` are there so `*.txt` cannot pass by matching a
    SUFFIX — `c.txtx` must not match, and case is not folded;
  * `'sp ace.txt'` is a name with a space in it, which every step of this
    module has to carry without quoting anything;
  * `empty/` is what makes a directory that exists and matches nothing
    different from a directory that is not there;
  * `link.txt` and `dangling.txt` are the two link cases, and they are the ones
    that separate `lexists` from `exists`: CPython's `_glob0` asks `lexists`
    (so a pattern naming the dangling link matches) while `_glob1` does not ask
    about existence at all (it takes the names `scandir` gave).

THE ORACLE IS CPYTHON'S OWN `glob`, CALLED, NEVER TYPED
-------------------------------------------------------
Nothing in this file records what `glob` answers. Every case is computed twice —
once by this process's `glob` and once by an image built through the formal
backend and executed — and the two have to agree, paths, count and order. A
table of answers for a directory walk is a table that is wrong the moment
somebody adds a file to the fixture, and one that is wrong the moment somebody
reorders the walk.

The corpus is read in ONE build per backend: the module is compiled once, so a
defect in it is reported once with its message rather than once per case, and
the twenty-odd cases cost one image rather than twenty.
"""

import argparse
import re
import os
import platform
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
HOSTMODS = os.path.join(HERE, "formal", "hostmods")
GLOB_MODULE = os.path.join(HOSTMODS, "glob.mojo")
BUILD_TIMEOUT = 1800
RUN_TIMEOUT = 300
REC = "@@"

# The export set, which is a CLAIM and is checked as one. A name here that the
# module does not declare is a call site nothing answers; a name the module
# declares that is not here is surface this tree has to keep working.
EXPORTS = {"escape", "glob", "glob_free", "has_magic"}

TEMP = None
ROOT = None


class Failure(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Failure(msg)


def backends():
    """The architectures to build for.

    BOTH, always: `gimple_codegen.py` and `myinterpreter.py` are separately
    maintained lowerings of one AST (`CLAUDE.md`), so an answer that agrees on
    one architecture says nothing about the other. This module is a recursive
    directory walk with a `malloc`'d blob index, which is exactly the shape where
    a register-width difference shows up as a silently wrong answer rather than as
    a refusal.

    A host with no x86-64 support returns one name and `main` says so on the
    screen, rather than the x86-64 half passing over quietly.
    """
    if platform.machine() in ("arm64", "aarch64"):
        return ["arm64", "x86_64"]
    return ["x86_64"]


def build(src, name, backend=None):
    tmp = os.path.join(TEMP, name + ".mojo")
    out = os.path.join(TEMP, f"{name}.{backend}" if backend else name)
    with open(tmp, "w") as f:
        f.write(src)
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove", "-o", out]
    if backend:
        cmd.append(f"--backend={backend}")
    cmd.append(tmp)
    r = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    check(r.returncode == 0,
          f"build failed{(f' on --backend={backend}' if backend else '')}: "
          f"{(r.stderr or r.stdout).strip()[-600:]}")
    check(os.path.isfile(out), f"no image at {out}")
    return out


def run(out):
    r = subprocess.run([out], capture_output=True, timeout=RUN_TIMEOUT,
                       cwd=HERE)
    check(r.returncode == 0,
          f"image {os.path.basename(out)} exited {r.returncode}: "
          f"{(r.stderr or b'').decode('utf-8', 'replace').strip()[-300:]}")
    return r.stdout.decode("latin-1")


def literal(s: str) -> str:
    """A Mojo string literal for `s`.

    Fixture paths come from `tempfile`, so they are not under this test's
    control and have to be escaped rather than trusted: a path with a quote or a
    backslash in it would end the literal and read its tail as bare names, which
    is a failure in the FIXTURE rather than in the module. The module's own
    corpus (a space in a filename) is inside a directory this test chose.
    """
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def records(text):
    """`<key>:` header records and the paths that follow each, as a dict.

    The two-byte separator and the `:` header are what make an EMPTY answer
    visible: `glob("no-such-thing")` is `[]`, and a bare path list could not be
    told from a missing case at all. `test_formal_html.py` gives the same
    argument for its brackets. The key is alphanumeric because the `escape` group
    numbers its two corpora apart (`e0` for `escape`, `m0` for `has_magic`) and
    one counter for both would make a dropped case look like a shifted one.
    """
    out = {}
    cur = None
    for chunk in text.split(REC):
        if not chunk:
            continue
        head, sep, _val = chunk.partition(":")
        if sep and head and head.replace("_", "").isalnum():
            cur = head
            out[cur] = []
            continue
        if cur is None:
            raise Failure(f"path before any header: {chunk!r}")
        out[cur].append(chunk)
    return out


# ── the fixture ────────────────────────────────────────────────────────────

def build_fixture(root):
    """The tree above, created at `root`. Returns nothing; it is a fixture."""
    for d in ("sub", "sub/deep", ".hiddendir", "empty"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    for f in ("a.txt", "b.py", "c.txtx", "UP.TXT", "sp ace.txt", ".dotfile",
              ".hidden.txt", "sub/c.txt", "sub/.hidden2.txt", "sub/d.md",
              "sub/deep/e.txt", ".hiddendir/f.txt"):
        with open(os.path.join(root, f), "w") as fh:
            fh.write(f)
    link = os.path.join(root, "link.txt")
    if not os.path.lexists(link):
        os.symlink("a.txt", link)
    dangling = os.path.join(root, "dangling.txt")
    if not os.path.lexists(dangling):
        os.symlink("nowhere.txt", dangling)


# ── the corpus ─────────────────────────────────────────────────────────────
#
# `(pattern, recursive, include_hidden, why)`, with the pattern relative to the
# fixture root and `ROOT` substituted for `%R`. A case's `why` is not decoration:
# it is what a reader looks at when that case is the one that fails, and every
# rule CPython has that this module transcribes has at least one case whose `why`
# names it.

def cases():
    r = ROOT
    return [
        # ── one component, no magic in the dirname
        ("%R/*.txt", 0, 0, "the shape 11 of this repository's 15 callers spell"),
        ("%R/*.py", 0, 0, "a different extension, same walk"),
        ("%R/*.txtx", 0, 0, "NOTHING: `*.txt` must not match `c.txtx` by suffix"),
        ("%R/*.TXT", 0, 0, "case is not folded: `*.txt` must not match `UP.TXT`"),
        ("%R/*", 0, 0, "every visible entry, files and directories alike"),
        ("%R/?.txt", 0, 0, "`?` is exactly one byte"),
        ("%R/[ab]*", 0, 0, "a bracket set"),
        ("%R/[!a]*", 0, 0, "a NEGATED bracket set, CPython's `[!...]` spelling"),
        ("%R/[a-c]*", 0, 0, "a range inside the set"),
        ("%R/[]x]*", 0, 0, "a literal `]` first in the set"),
        ("%R/sp*.txt", 0, 0, "a name with a space in it"),
        ("%R/l*.txt", 0, 0, "the symbolic link, which `scandir` lists"),
        ("%R/d*.txt", 0, 0, "the DANGLING link: `scandir` lists it, so `*.txt` "
                            "matches it and only `_glob0` would ask `exists`"),
        # ── no magic at all: the existence branch
        ("%R/a.txt", 0, 0, "no magic and it is there: the pattern ITSELF"),
        ("%R/no-such-file.txt", 0, 0, "no magic and it is not there: nothing"),
        ("%R/empty", 0, 0, "no magic, a directory: the pattern itself"),
        ("%R/sub", 0, 0, "no magic, a nested directory"),
        ("%R/a.txt/", 0, 0, "a trailing separator on a FILE matches nothing"),
        ("%R/sub/", 0, 0, "a trailing separator keeps the separator in the answer"),
        # ── magic in the dirname, which is `_iglob`'s recursion
        ("%R/*/*.txt", 0, 0, "one level of dirname magic"),
        ("%R/*/*", 0, 0, "two levels, and the intermediate answer is dironly"),
        ("%R/*/deep/*", 0, 0, "a literal final component under a magic dirname"),
        ("%R/*/nothing*", 0, 0, "magic dirname, nothing at the leaf"),
        ("%R/no-such-dir/*", 0, 0, "a dirname that is not there: nothing"),
        # ── `**`
        ("%R/**", 0, 0, "`**` WITHOUT recursive is just `*`, one level"),
        ("%R/**/*.txt", 1, 0, "the shape 4 of this repository's callers spell"),
        ("%R/**", 1, 0, "`**` recursive: the tree, INCLUDING its own empty "
                         "first answer, and the file names at every depth"),
        ("%R/sub/**/*.md", 1, 0, "a `**` under a literal dirname, matching one "
                                 "file two levels down"),
        ("%R/**", 1, 1, "`**` recursive with include_hidden: the hidden rule"),
        ("%R/*.txt", 0, 1, "include_hidden on a one-component pattern"),
        ("%R/.*", 0, 0, "a hidden PATTERN sees the hidden entries"),
        ("%R/.*", 0, 1, "…and with include_hidden as well"),
        ("%R/sub/.*", 0, 0, "a hidden pattern in a subdirectory"),
    ]


HIDDEN_CASES = [
    # The two hidden rules are DIFFERENT in CPython and this corpus asks them
    # separately, because a module that reconciled them would agree with CPython
    # on a tree with no dotfiles in it. See the module docstring.
    ("%R/*", 0, 0, "no dotfiles at all without include_hidden"),
    ("%R/*", 0, 1, "every dotfile with it"),
    ("%R/.*", 0, 0, "a hidden pattern sees them WITHOUT include_hidden"),
    ("%R/**", 1, 0, "`**` recursive never yields a hidden entry, even though "
                    "its pattern is `**`"),
    ("%R/**", 1, 1, "…and does with include_hidden"),
    ("%R/**/.*", 1, 0, "a hidden FINAL component under `**`: the names come "
                       "from `_rlistdir`, which filters on include_hidden alone"),
    ("%R/**/.*", 1, 1, "…and with include_hidden"),
]


def pattern(src: str) -> str:
    return src.replace("%R", ROOT)


def program(backend, corpus, tag):
    """One image: every case's whole answer, in order.

    Flat rather than a helper function, and that is forced rather than chosen: a
    container cannot be passed to a function parameter on this path with its
    KIND intact (`len(paths)` inside a callee is refused as `len()` of an `int`,
    measured — the `-> List[String]` on `glob` is read at the CALL SITE and does
    not survive the parameter), so each case binds its own local and prints it
    there.
    """
    lines = ["import glob", "", "def main() -> int:"]
    for k, (pat, rec, hid, _why) in enumerate(corpus):
        lines.append(f'    printf("{REC}{k}:@@")')
        lines.append(f"    var p{k} = glob.glob({literal(pattern(pat))}, "
                     f"{rec}, {hid})")
        lines.append(f'    for x in p{k}:')
        lines.append(f'        printf("%s{REC}", x)')
    lines.append("    return 0")
    return records(run(build("\n".join(lines) + "\n", tag, backend)))


def compare(corpus, got, backend):
    """`corpus` against CPython, in order, with the count from the header."""
    import glob as CP
    bad = []
    for k, (pat, rec, hid, why) in enumerate(corpus):
        want = CP.glob(pattern(pat), recursive=bool(rec),
                       include_hidden=bool(hid))
        # `str(k)`: `records` keys on the header TEXT (the `escape` group needs
        # `e0` and `m0` to be different keys), so a case number arrives as a
        # string. Comparing against the int found no record at all and reported
        # every case as missing.
        mine = got.get(str(k))
        if mine is None:
            bad.append((k, pat, why, "no record", want))
            continue
        if mine != want:
            bad.append((k, pat, why, mine, want))
    if bad:
        k, pat, why, mine, want = bad[0]
        raise Failure(
            f"[{backend}] {len(bad)} of {len(corpus)} case(s) differ from "
            f"CPython; first: case {k} {pat!r} ({why})\n"
            f"    image {mine!r}\n"
            f"    CPython {want!r}")
    total = sum(len(got.get(str(k), ())) for k in range(len(corpus)))
    return total


# ── group: resolve ─────────────────────────────────────────────────────────

def group_resolve(tmpdir, verbose):
    """`import glob` finds this file, it is out of `HOST_MODELLED`, and its
    exports are the four names this test calls.

    The tier check is the one that matters: `formal/imports.py`'s rule is that a
    name LEAVES `HOST_MODELLED` by being WRITTEN, because an entry left behind
    after the module that answers it is on disk refuses a file with a statement
    that is no longer true, and a false statement is worse than a conservative
    one.
    """
    check(os.path.isfile(GLOB_MODULE),
          f"no Mojo source for glob at {GLOB_MODULE}")
    sys.path.insert(0, HERE)
    import formal.imports as I
    got = I.resolve_module_path("glob")
    check(got is not None and os.path.samefile(got, GLOB_MODULE),
          f"import glob resolves to {got!r}, not {GLOB_MODULE!r}")
    tier = I.host_module_tier("glob")
    check(tier == "",
          f"glob is still in HOST_MODELLED (tier={tier!r}); its Mojo source "
          f"exists, so the entry is now a false statement about the target")
    have = set(I.module_exports(GLOB_MODULE)) if hasattr(I, "module_exports") \
        else None
    if have is None:
        have = _exports_from_source()
    check(have == EXPORTS,
          f"formal/hostmods/glob.mojo exports {sorted(have)}, expected "
          f"{sorted(EXPORTS)}. A name here that a caller cannot reach is a "
          f"silent absence, and a name there that no caller wants is surface "
          f"this tree has to keep true.")
    check(not os.path.isfile(os.path.join(HERE, "glob.mojo")),
          "glob.mojo is at the repository root, which four independent "
          "resolvers search — see _HOSTMODS_ROOT")
    if verbose:
        print(f"    import glob -> {os.path.relpath(got, HERE)}, "
              f"host_module_tier={tier!r}, exports={sorted(have)}")
    return True, (f"resolves to {os.path.relpath(got, HERE)}, out of "
                  f"HOST_MODELLED, exports {sorted(EXPORTS)}")


def _exports_from_source():
    """The names `formal/hostmods/glob.mojo` publishes, read from the PARSED
    module rather than from a list here."""
    import fire_compiler as F
    import formal.imports as I
    names = set()
    for st in I.module_statements(GLOB_MODULE):
        if isinstance(st, F.FunctionDef) and st.name:
            names.add(st.name)
    # `doc/ABI.md`'s export rule excludes a leading underscore, which is what
    # keeps the module's internals out of its surface.
    return {n for n in names if not n.startswith("_")}


# ── group: listing ─────────────────────────────────────────────────────────

def group_listing(tmpdir, verbose):
    """The corpus, every case's whole answer in order, against CPython's own."""
    corpus = cases()
    total = 0
    for backend in backends():
        total += compare(corpus, program(backend, corpus, "glob_listing"),
                         backend)
    if verbose:
        print(f"    {len(corpus)} cases over {len(backends())} backends, "
              f"each case a whole ordered answer")
    return True, (f"{total} paths over {len(corpus)} cases agree with CPython "
                  f"in count AND order on {len(backends())} backend(s)")


# ── group: hidden ──────────────────────────────────────────────────────────

def group_hidden(tmpdir, verbose):
    """The two hidden-file rules, asked separately.

    They are different rules in CPython 3.14 and the corpus is built so a module
    that implemented either one of them passes the other's cases: `_glob1`
    filters hidden NAMES unless the PATTERN is hidden, `_rlistdir` filters
    hidden ENTRIES on `include_hidden` alone, so `**` recursive never yields a
    dotfile even though its pattern is `**`.
    """
    corpus = HIDDEN_CASES
    total = 0
    for backend in backends():
        total += compare(corpus, program(backend, corpus, "glob_hidden"),
                         backend)
    if verbose:
        print(f"    {len(corpus)} dotfile cases over {len(backends())} backends")
    return True, (f"{total} paths over {len(corpus)} hidden-file cases agree "
                  f"with CPython on {len(backends())} backend(s)")


# ── group: escape ──────────────────────────────────────────────────────────

ESCAPE_CASES = [
    ("", "nothing to escape"),
    ("a.py", "nothing to escape"),
    ("*", "one metacharacter"),
    ("?", "the other one"),
    ("[", "the third one, which is what makes an unterminated set interesting"),
    ("*.py", "the shape the corpus's own paths have"),
    ("a*b?c[d]e", "all three, interleaved"),
    ("***", "three in a row, so each gets its own brackets"),
    ("a[bc]d", "a bracket SET, which `escape` does not escape: only the "
               "opening bracket is a metacharacter and CPython wraps only it"),
    ("[a-z]", "a range, and CPython leaves it alone"),
    ("a b/c", "a separator and a space"),
    ("café/*.py", "multi-byte UTF-8 before a metacharacter"),
    (".hidden", "a leading dot is NOT a metacharacter"),
    ("a\\b*", "a backslash, which `escape` leaves alone"),
]

HAS_MAGIC_CASES = [
    ("", "the empty pattern has no magic"),
    ("a.py", "no magic"),
    ("*.py", "a star"),
    ("a?b", "a question mark"),
    ("a[b", "an unterminated bracket is STILL magic"),
    ("[abc]", "a bracket set"),
    ("a/b/*.c", "the star is in the last component"),
    ("a/b/", "a trailing separator is not magic"),
    ("café", "a multi-byte name with no metacharacter"),
]


def escape_program(backend, tag):
    """One image: `escape` and `has_magic` over both corpora."""
    lines = ["import glob", "", "def main() -> int:"]
    for k, (raw, _why) in enumerate(ESCAPE_CASES):
        lines.append(f'    printf("{REC}e{k}:@@")')
        lines.append(f'    printf("%s{REC}", glob.escape({literal(raw)}))')
    for k, (raw, _why) in enumerate(HAS_MAGIC_CASES):
        # The header and the value are SEPARATE records, like `escape`'s: a
        # `%d` inside the header made the value a second parse of the header's
        # own text rather than a recorded answer.
        lines.append(f'    printf("{REC}m{k}:{REC}%d{REC}", glob.has_magic('
                     f'{literal(raw)}))')
    lines.append("    return 0")
    return records(run(build("\n".join(lines) + "\n", tag, backend)))


def as_image_view(s: str) -> str:
    """`s` as the image's OWN view of the same bytes.

    `run` reads the image's stdout as latin-1, which is the only way to get a
    byte into a Python `str` without an encoding choice of its own, and it is
    what `test_formal_html.py` does for the same reason. So for a corpus entry
    with a byte above 0x7F in it the two sides are the same BYTES and different
    `str`: `escape("café")` is `café` here and comes back as `cafÃ©`, and
    comparing those directly reports a difference that is not one.

    The module is byte-transparent and CPython is code-point-transparent, which
    is the property being tested, so the oracle is put in the image's view:
    encode the answer and read it back the way `run` read the image. Every
    ASCII entry is unchanged by this, which is why it is a function over the
    whole answer rather than a mask for the two non-ASCII cases.
    """
    return s.encode("utf-8").decode("latin-1")


def group_escape(tmpdir, verbose):
    """`escape` and `has_magic`, against CPython's own, on both backends."""
    import glob as CP
    bad = []
    total = 0
    for backend in backends():
        got = escape_program(backend, "glob_escape")
        for k, (raw, why) in enumerate(ESCAPE_CASES):
            total += 1
            mine = "".join(got.get(f"e{k}", []))
            want = as_image_view(CP.escape(raw))
            if mine != want:
                bad.append((backend, "escape", raw, why, mine, want))
        for k, (raw, why) in enumerate(HAS_MAGIC_CASES):
            total += 1
            got_m = got.get(f"m{k}")
            if got_m is None or len(got_m) != 1:
                bad.append((backend, "has_magic", raw, why, got_m,
                            1 if CP.has_magic(raw) else 0))
                continue
            mine = int(got_m[0])
            want = 1 if CP.has_magic(raw) else 0
            if mine != want:
                bad.append((backend, "has_magic", raw, why, mine, want))
    if bad:
        b = bad[0]
        raise Failure(f"{len(bad)} of {total} answer(s) differ from CPython; "
                      f"first: [{b[0]}] {b[1]}({b[2]!r}) ({b[3]}) image "
                      f"{b[4]!r} CPython {b[5]!r}")
    if verbose:
        print(f"    {len(ESCAPE_CASES)} escape + {len(HAS_MAGIC_CASES)} "
              f"has_magic cases x {len(backends())} backends")
    return True, (f"{total} escape/has_magic answers agree with CPython on "
                  f"{len(backends())} backend(s)")


# ── group: blob ────────────────────────────────────────────────────────────

def group_blob(tmpdir, verbose):
    """`len`, `[i]` and `for` over the answer, and `glob_free`.

    The three Python-level spellings are what the module's `-> List[String]` buys
    and what every caller in this repository writes (`sorted(glob.glob(…))`,
    `for p in glob.glob(…)`, `[os.path.basename(p) for p in glob.glob(…)]`), so
    they are tested together with the count they must agree with — a module that
    declared the wrong container kind would answer a plausible wrong `len` and
    refuse the `for`.

    `glob_free` is checked on an answer, on an EMPTY answer and on 0, because
    all three are shapes a caller has and 0 is the one where a release that
    dereferences its argument would fault.
    """
    lines = [
        "import glob",
        "",
        "def main() -> int:",
        f"    var p = glob.glob({literal(pattern('%R/*.py'))}, 0, 0)",
        '    printf("len=%d\\n", len(p))',
        '    printf("first=[%s]\\n", p[0])',
        '    printf("last=[%s]\\n", p[len(p) - 1])',
        "    var n = 0",
        "    for x in p:",
        "        n = n + 1",
        '        printf("item%d=[%s]\\n", n, x)',
        '    printf("counted=%d\\n", n)',
        '    printf("freed=%d\\n", glob.glob_free(p))',
        f"    var e = glob.glob({literal(pattern('%R/no-such-thing*'))}, 0, 0)",
        '    printf("empty_len=%d freed=%d\\n", len(e), glob.glob_free(e))',
        '    printf("zero_freed=%d\\n", glob.glob_free(0))',
        "    return 0",
    ]
    import glob as CP
    want = CP.glob(pattern("%R/*.py"))
    bad = []
    for backend in backends():
        got = run(build("\n".join(lines) + "\n", "glob_blob", backend))
        parsed = {}
        # `key=value` PAIRS, not one per line: two of the lines above carry two
        # pairs, and a parser that took `line.partition("=")` read
        # `empty_len=0 freed=0` as the value `0 freed=0`. The keys are `[a-z_]+`
        # and the values run to the next key or the end of the line, which is
        # what makes `first=[a.txt]` and `last=[b.txt]` survive intact.
        for line in got.splitlines():
            for k, v in re.findall(r"([a-z_]+)=(\[[^\]]*\]|\S*)", line):
                parsed[k] = v
        checks = [
            ("len", str(len(want))),
            ("first", f"[{want[0]}]"),
            ("last", f"[{want[-1]}]"),
            ("counted", str(len(want))),
            ("empty_len", "0"),
            ("freed", "0"),
            ("zero_freed", "0"),
        ]
        for k, w in checks:
            if parsed.get(k) != w:
                bad.append((backend, k, parsed.get(k), w))
        items = [ln for ln in got.splitlines() if ln.startswith("item")]
        if items != [f"item{i + 1}=[{q}]" for i, q in enumerate(want)]:
            bad.append((backend, "items", items, want))
    if bad:
        b = bad[0]
        raise Failure(f"{len(bad)} answer(s) wrong; first: [{b[0]}] {b[1]} "
                      f"image {b[2]!r} CPython {b[3]!r}")
    if verbose:
        print(f"    len/[i]/for/free over {len(want)} answer(s) on "
              f"{len(backends())} backends")
    return True, (f"len, [i], for and glob_free agree with CPython over "
                  f"{len(want)} path(s) on {len(backends())} backend(s)")


# ── group: absent ──────────────────────────────────────────────────────────

def group_absent(tmpdir, verbose):
    """The names this module does NOT have, refused with a reason.

    Pinned because an absent name and a wrong answer look the same to a caller
    only if nothing checks. Each is refused NAMING ITSELF, so a caller that wants
    one is told which one and why rather than getting a link error — and `iglob`
    is the one a reader expects to find, because CPython's `glob` is the eager
    wrapper around it.
    """
    for name, arg in (("iglob", '"*.py"'), ("glob0", '"d", "n"'),
                      ("glob1", '"d", "n"'), ("glob2", '"d", "**"')):
        src = ("import glob\n\ndef main():\n"
               f'    printf("%lld\\n", glob.{name}({arg}))\n')
        tmp = os.path.join(TEMP, "absent.mojo")
        out = os.path.join(TEMP, "absent")
        with open(tmp, "w") as f:
            f.write(src)
        r = subprocess.run([sys.executable, FIRE, "build", "--formal",
                            "--no-prove", "-o", out, tmp],
                           capture_output=True, text=True,
                           timeout=BUILD_TIMEOUT, cwd=HERE)
        msg = (r.stderr or r.stdout)
        check(r.returncode != 0,
              f"glob.{name} built; it is not supposed to exist, and a "
              f"silently-approximated name is worse than a refusal")
        check(name in msg,
              f"the refusal for glob.{name} does not NAME it: "
              f"{msg.strip()[-200:]}")
    if verbose:
        print("    iglob, glob0, glob1, glob2 each refused by name")
    return True, "4 absent names each refused by name"


GROUPS = {
    "resolve": group_resolve,
    "listing": group_listing,
    "hidden": group_hidden,
    "escape": group_escape,
    "blob": group_blob,
    "absent": group_absent,
}


def main():
    global TEMP, ROOT
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", choices=sorted(GROUPS))
    args = ap.parse_args()
    names = args.groups or list(GROUPS)
    need_tree = any(n in names for n in ("listing", "hidden", "blob"))
    with tempfile.TemporaryDirectory(prefix="globtest") as td:
        TEMP = td
        ROOT = os.path.join(td, "tree")
        if need_tree:
            build_fixture(ROOT)
        npass = nfail = 0
        for nm in names:
            try:
                _ok, msg = GROUPS[nm](td, args.verbose)
                print(f"PASS {nm:10} {msg}")
                npass += 1
            except Failure as e:
                print(f"FAIL {nm:10} {e}")
                nfail += 1
            except Exception as e:  # noqa: BLE001
                print(f"ERROR {nm:9} {type(e).__name__}: {e}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                nfail += 1
        print(f"\nformal glob: PASS={npass} FAIL={nfail} "
              f"(backends: {', '.join(backends())})")
        return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())