#!/usr/bin/env python3
"""`formal/hostmods/html.mojo`, differential against CPython's `html.escape`.

    python3 test_formal_html.py [-v] [group ...]

Groups: `resolve`, `escape`, `bytes`, `absent`. With no argument, all. Every
group that builds an image builds it on BOTH backends.

WHY THIS FILE IS MOSTLY ABOUT ORDER
-----------------------------------
`html.escape` is five `str.replace` calls and the only thing interesting about
it is that the ORDER is load-bearing: `&` is replaced FIRST, so the `&` that the
later replacements introduce is never itself replaced. An implementation that
replaced `&` last agrees with CPython on every string containing no `&` and
disagrees on every string containing one — and this function exists FOR strings
containing `<`, `>`, `&` and quotes, so "agrees on the easy strings" is not a
property that means anything here.

The corpus is built out of that: `"&amp;"`, `"&lt;"`, `"&&&"` and `"&amp;lt;"`
are four of the twenty-two cases, and a reordered module fails all four. Every
other case is there so that the reordering cannot be the only thing being
tested: a module that got the order right and the byte set wrong would pass
those four and fail the rest.

`bytes` is the other half and it exists because the module indexes its expansion
table BY BYTE. A multi-byte UTF-8 sequence must be copied through untouched
(CPython's `str.replace` operates on code points and no code point here is one of
the five), so the corpus carries UTF-8 and the byte sweep covers 0x80..0xFF —
which is the range where a module that expanded "any byte above 0x7F" would go
wrong on real text.

A corpus byte cannot be spelled directly (a string literal's escapes are not
decoded on this path, `bugs/FORMAL_string_literal_escape_is_not_decoded.md`),
so the MASK below is the corpus's own alphabet and `unmask` is the Mojo half.
Every case is ASCII or a UTF-8 sequence of ASCII-printable-plus-high-bytes, and
the mask is stated rather than assumed — it is the same idea as
`test_formal_json.py`'s and `test_formal_textwrap.py`'s.

THE ORACLE IS CPython'S OWN `html.escape`, CALLED, NEVER TYPED
--------------------------------------------------------------
Nothing in this file records what `escape` answers. Every case is computed twice
— once by this process's `html` and once by an image built through the formal
backend and executed — and the two have to agree. A table of answers for a
function that is five substitutions is a table that is wrong the moment someone
transposes a character, which is the one mistake a byte-oriented module cannot be
allowed to make.
"""

import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
HOSTMODS = os.path.join(HERE, "formal", "hostmods")
HTML_MODULE = os.path.join(HOSTMODS, "html.mojo")
BUILD_TIMEOUT = 900
RUN_TIMEOUT = 120
REC = "@@"

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
    one architecture says nothing about the other. This module is a byte-indexed
    table walk, which is exactly the shape where a register-width difference
    shows up as a silently wrong answer rather than as a refusal.

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


def records(text):
    """`<index>:[<value>` records, as `(index, value)` pairs.

    Bracketed value and a two-byte separator, for the reasons
    `test_formal_textwrap.py` gives: the mask escapes every `@` in the corpus as
    `~a`, so a masked case cannot contain `@@`, and the bracket makes an EMPTY
    answer visible — which matters here because `escape("")` is `""` and a bare
    record could not be told from a missing one.
    """
    got = []
    for rec in text.split(REC):
        if not rec:
            continue
        head, sep, val = rec.partition(":[")
        if not sep:
            raise Failure(f"record with no bracket: {rec!r}")
        if not val.endswith("]"):
            raise Failure(f"record with no closing bracket: {rec!r}")
        got.append((int(head), val[:-1]))
    return got


# ── the mask ───────────────────────────────────────────────────────────────
#
# `mask` is the Python half and `UNMASK` below is the Mojo half; the two must
# agree, which `test_formal_sweep_truth`-style drift would otherwise hide. Only
# the bytes a Mojo literal cannot hold go through here, plus the two metacharacters.

def mask(b: bytes) -> str:
    out = []
    for c in b:
        if c == 0x7E:
            out.append("~~")
        elif c == 0x40:
            out.append("~a")
        elif c == 0x09:
            out.append("~t")
        elif c == 0x0A:
            out.append("~n")
        elif c == 0x0D:
            out.append("~r")
        elif c == 0x22:
            out.append("~q")
        elif c == 0x5C:
            out.append("~b")
        elif 0x20 <= c <= 0x7E:
            out.append(chr(c))
        else:
            out.append("~x%02x" % c)
    return "".join(out)


UNMASK = '''
def html_byte(s, i) -> int:
    if i >= strlen(s):
        return 256
    var q: Pointer[UInt8] = s + i
    return q.value()

def html_put(dst, at, v) -> int:
    var p: Pointer[UInt8] = dst + at
    p.value() = v
    return at + 1

def html_hexdig(c) -> int:
    if c >= 48 and c <= 57:
        return c - 48
    if c >= 97 and c <= 102:
        return c - 87
    if c >= 65 and c <= 70:
        return c - 55
    return 0

def unmask(t) -> str:
    var out: Pointer[UInt8] = malloc(4 * strlen(t) + 1)
    var u = 0
    var i = 0
    while i < strlen(t):
        var c = html_byte(t, i)
        if c != 126:
            u = html_put(out, u, c)
            i = i + 1
        elif html_byte(t, i + 1) == 126:
            u = html_put(out, u, 126)
            i = i + 2
        elif html_byte(t, i + 1) == 116:
            u = html_put(out, u, 9)
            i = i + 2
        elif html_byte(t, i + 1) == 110:
            u = html_put(out, u, 10)
            i = i + 2
        elif html_byte(t, i + 1) == 114:
            u = html_put(out, u, 13)
            i = i + 2
        elif html_byte(t, i + 1) == 97:
            u = html_put(out, u, 64)
            i = i + 2
        elif html_byte(t, i + 1) == 113:
            u = html_put(out, u, 34)
            i = i + 2
        elif html_byte(t, i + 1) == 98:
            u = html_put(out, u, 92)
            i = i + 2
        else:
            u = html_put(out, u, html_hexdig(html_byte(t, i + 2)) * 16
                         + html_hexdig(html_byte(t, i + 3)))
            i = i + 4
    html_put(out, u, 0)
    return out
'''


# ── the corpus ─────────────────────────────────────────────────────────────
#
# The four `&`-bearing cases are the ORDER, and the comment on each says which
# reordering it catches.

CASES = [
    # nothing to do
    (b"", "empty string"),
    (b"plain", "no special character"),
    (b"a/b/c.txt", "a path"),
    (b"line one", "a space"),
    # one character each, both `quote` values
    (b"&", "ampersand alone"),
    (b"<", "less-than alone"),
    (b">", "greater-than alone"),
    (b'"', "double quote alone"),
    (b"'", "single quote alone"),
    # THE ORDER: `&` first, so the `&` a later replacement introduces is never
    # itself replaced
    (b"&amp;", "an already-escaped ampersand"),
    (b"&lt;", "an already-escaped less-than"),
    (b"&gt;", "an already-escaped greater-than"),
    (b"&quot;", "an already-escaped double quote"),
    (b"&#x27;", "an already-escaped single quote"),
    (b"&&&", "three ampersands"),
    (b"&amp;lt;", "an escape of an escape"),
    (b"&#62;", "a numeric reference"),
    (b"&x3e;", "a hex reference without a hash"),
    (b"&notit;", "a named reference that is NOT expanded by escape"),
    # everything at once, both `quote` values
    (b"a<b>c&d\"e'f", "all five, quote=1"),
    (b"a<b>c&d\"e'f", "all five, quote=0"),
    # the metacharacters, so a mask bug shows here rather than nowhere
    (b'a"b\\c', "quote and backslash"),
    (b"~~", "the tilde the mask escapes"),
    # whitespace and a tab, which a converter's help text carries
    (b"a\tb\nc\r\nd", "tab, LF and CRLF"),
    # multi-byte UTF-8, which the byte-indexed expansion table must copy
    # through untouched (the module's docstring's last section)
    ("café — naïve".encode("utf-8"), "multi-byte UTF-8, quote=1"),
    ("café — naïve".encode("utf-8"), "multi-byte UTF-8, quote=0"),
    (b"\xc3\xa9", "a single high byte (0xC3 0xA9)"),
    (b"\xe2\x80\x94", "an em dash in UTF-8"),
]


def program(backend):
    """One program: every case at `quote=1` and at `quote=0`, over the corpus.

    Both values for every case rather than a subset, because `quote` is the
    parameter a cross-dylib default cannot supply
    (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`) and a module
    that ignored it would agree with CPython on every `quote=1` case — which is
    the value CPython defaults to, and therefore the value most callers use.

    One build for the corpus: the module is compiled once, so 32 cases x 2
    values cost one build and a defect in the module is reported once with its
    message rather than 64 times as a timeout.
    """
    lines = ["import html", "", UNMASK, "", "def main():"]
    n = 0
    for k, (raw, _why) in enumerate(CASES):
        lines.append(f"    var t{k} = unmask({mask_literal(raw)})")
        lines.append(f'    printf("%lld:[%s]@@", {2 * n}, html.escape(t{k}, 1))')
        lines.append(f'    printf("%lld:[%s]@@", {2 * n + 1}, '
                     f'html.escape(t{k}, 0))')
        n += 2
    return records(run(build("\n".join(lines) + "\n", "html_escape", backend)))


def mask_literal(raw: bytes) -> str:
    """A Mojo string literal for the already-masked `raw`.

    `"` and `\\` are the only two the mask can have left, and it escapes both, so
    this is belt and braces — and it is a function rather than an inline f-string
    because the masked text is what goes in and the escaping must not happen
    twice.
    """
    m = mask(raw)
    return '"' + m.replace("\\", "\\\\").replace('"', '\\"') + '"'


def bytes_program(backend):
    """Every byte 1..255, through both `quote` values.

    The exhaustive sweep that `escape`'s corpus only samples. It is the group
    that says the expansion table is indexed correctly and touches nothing else:
    a module that expanded a byte it should not (say, treating every byte above
    0x7F as a lead byte) agrees with CPython on all 22 corpus cases and fails
    here at 0x80.

    Read as latin-1, because that is the only way to get byte `b` into a Python
    `str` without an encoding choice of its own — and CPython's `escape` then
    operates on those code points, which is the comparison the module's byte
    table is making.
    """
    vals = list(range(1, 256))
    lines = ["import html", "", UNMASK, "", "def main():"]
    for idx, c in enumerate(vals):
        lines.append(f"    var b{idx}: Pointer[UInt8] = malloc(2)")
        lines.append(f"    html_put(b{idx}, 0, {c})")
        lines.append(f"    html_put(b{idx}, 1, 0)")
        lines.append(f'    printf("%lld:[%s]@@", {2 * idx}, '
                     f'html.escape(b{idx}, 1))')
        lines.append(f'    printf("%lld:[%s]@@", {2 * idx + 1}, '
                     f'html.escape(b{idx}, 0))')
    return records(run(build("\n".join(lines) + "\n", "html_bytes", backend)))


# ── group: resolve ─────────────────────────────────────────────────────────

def group_resolve(tmpdir, verbose):
    """`import html` finds this file, and it is out of `HOST_MODELLED`.

    And the diagnostic that used to be wrong about it is gone with the entry:
    `html` was in NEITHER tier on 2026-10-03, which made
    `unresolvable_import_error` say "not a stdlib or sibling module, and no
    such file exists" to `tools/md2html.py` — a false statement about a name
    CPython ships. That is the sentence
    `bugs/FORMAL_host_import_row_ranked_by_module_2026-10-03.md` §3 measured, and
    the classification it led to is what this module now answers.
    """
    check(os.path.isfile(HTML_MODULE),
          f"no Mojo source for html at {HTML_MODULE}")
    sys.path.insert(0, HERE)
    import formal.imports as I
    got = I.resolve_module_path("html")
    check(got is not None and os.path.samefile(got, HTML_MODULE),
          f"import html resolves to {got!r}, not {HTML_MODULE!r}")
    tier = I.host_module_tier("html")
    check(tier == "",
          f"html is still in HOST_MODELLED (tier={tier!r}); its Mojo source "
          f"exists, so the entry is now a false statement about the target")
    check(I._HOSTMODS_ROOT == HOSTMODS,
          f"the hostmods root moved to {I._HOSTMODS_ROOT!r}")
    check(not os.path.isfile(os.path.join(HERE, "html.mojo")),
          "html.mojo is at the repository root, which four independent "
          "resolvers search — see _HOSTMODS_ROOT")
    if verbose:
        print(f"    import html -> {os.path.relpath(got, HERE)}, "
              f"host_module_tier={tier!r}")
    return True, f"resolves to {os.path.relpath(got, HERE)}, out of HOST_MODELLED"


# ── group: escape ──────────────────────────────────────────────────────────

def group_escape(tmpdir, verbose):
    """`escape` over the corpus at both `quote` values, each CPython's own."""
    import html as CP
    bad = []
    total = 0
    for backend in backends():
        got = program(backend)
        # One flat list in the SAME order the program emitted: case k contributes
        # records 2k (quote=1) and 2k+1 (quote=0), so the record's position IS
        # the case and no index field is needed.
        want = []
        for raw, _why in CASES:
            s = raw.decode("latin-1")
            want.append(CP.escape(s, True))
            want.append(CP.escape(s, False))
        check(len(got) == len(want),
              f"escape[{backend}]: image reported {len(got)} of {len(want)} "
              f"records; excess {got[len(want):][:3]}")
        for n, (_idx, val) in enumerate(got):
            total += 1
            if val != want[n]:
                case = CASES[n // 2][0]
                why = CASES[n // 2][1]
                quote = 1 if n % 2 == 0 else 0
                bad.append((backend, case, why, quote, val, want[n]))
    detail = ""
    if bad:
        b = bad[0]
        detail = (f"; first: [{b[0]}] {b[1]!r} ({b[2]}) quote={b[3]} image "
                  f"{b[4]!r} CPython {b[5]!r}")
    check(not bad, f"{len(bad)} of {total} answer(s) differ from CPython"
          + detail)
    if verbose:
        print(f"    {len(CASES)} cases x 2 quote values x {len(backends())} "
              f"backends = {total} answers, each against CPython's escape")
    return True, (f"{total} html.escape answers agree with CPython on "
                  f"{len(backends())} backend(s)")


# ── group: bytes ───────────────────────────────────────────────────────────

def group_bytes(tmpdir, verbose):
    """Every byte 1..255 through both `quote` values, each CPython's own.

    The exhaustive half. It is a separate group from `escape` rather than more
    cases in it because it is a different CLAIM: `escape`'s corpus says the
    ORDER is right and the byte set is right on the characters that matter,
    this says the table is indexed right for every byte there is.
    """
    import html as CP
    vals = list(range(1, 256))
    bad = []
    total = 0
    for backend in backends():
        got = bytes_program(backend)
        want = []
        for c in vals:
            s = chr(c)
            want.append(CP.escape(s, True))
            want.append(CP.escape(s, False))
        check(len(got) == len(want),
              f"bytes[{backend}]: image reported {len(got)} of {len(want)} "
              f"records")
        for n, (_idx, val) in enumerate(got):
            total += 1
            if val != want[n]:
                c = vals[n // 2]
                quote = 1 if n % 2 == 0 else 0
                bad.append((backend, c, quote, val, want[n]))
    detail = ""
    if bad:
        b = bad[0]
        detail = (f"; first: [{b[0]}] byte 0x{b[1]:02x} quote={b[2]} image "
                  f"{b[3]!r} CPython {b[4]!r}")
    check(not bad,
          f"{len(bad)} of {total} per-byte answer(s) differ from CPython"
          + detail)
    if verbose:
        print(f"    {len(vals)} bytes x 2 quote values x {len(backends())} "
              f"backends = {total} answers")
    return True, (f"{total} per-byte html.escape answers agree with CPython "
                  f"on {len(backends())} backend(s)")


# ── group: absent ──────────────────────────────────────────────────────────

def group_absent(tmpdir, verbose):
    """The names this module does NOT have, refused with a reason.

    Pinned because an absent name and a wrong answer look the same to a caller
    only if nothing checks — and `unescape` is the one a reader expects to find,
    because `escape` without `unescape` looks like half a module. Each is refused
    NAMING ITSELF, so a caller that wants one is told which one and why rather
    than getting a link error.
    """
    for name, arg in (("unescape", '"&amp;"'), ("HTMLParser", ""),
                      ("html5", ""), ("entities", "")):
        src = ("import html\n\ndef main():\n"
               f'    printf("%lld\\n", html.{name}({arg}))\n')
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
              f"html.{name} built; it is not supposed to exist, and a "
              f"silently-approximated name is worse than a refusal")
        check(name in msg,
              f"the refusal for html.{name} does not NAME it: "
              f"{msg.strip()[-200:]}")
    # And the one that is NOT absent, at both `quote` values, so the parameter
    # is pinned as an INT rather than as a boolean: CPython's default is True
    # and a cross-dylib default is not applied, so `escape(s, 1)` is what a
    # caller writes for it.
    #
    # The probe string CONTAINS a quote character, which is the whole point and
    # which the first version of this assertion got wrong: it used `"a&b"`,
    # where `quote=0` and `quote=1` answer the SAME thing because there is no
    # quote to expand — so the assertion passed on a module that ignored the
    # parameter completely, which is the failure it was written to catch. A
    # probe for a flag has to contain the thing the flag is about.
    import html as CP
    probe = 'a&b"c'
    # The probe goes into a Mojo LITERAL, so its own `"` has to be escaped —
    # and the first version did not, so the literal ended at the quote and the
    # `c` after it was read as a bare name ("'c' has no home").
    lit = probe.replace("\\", "\\\\").replace('"', '\\"')
    src = ("import html\n\ndef main():\n"
           f'    var t = "{lit}"\n'
           '    printf("[%s][%s]\\n", html.escape(t, 1), '
           'html.escape(t, 0))\n')
    out = build(src, "html_quote")
    got = run(out).strip()
    want = f"[{CP.escape(probe, True)}][{CP.escape(probe, False)}]"
    check(got == want,
          f"escape at quote=1/0 on {probe!r}: image {got!r}, CPython {want!r}")
    if verbose:
        print("    unescape, HTMLParser, html5, entities each refused by name; "
              "and escape's quote parameter pinned at both values")
    return True, ("4 absent names each refused by name, and escape's quote "
                  "parameter pinned at 1 and 0")


GROUPS = {
    "resolve": group_resolve,
    "escape": group_escape,
    "bytes": group_bytes,
    "absent": group_absent,
}


def main():
    global TEMP
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", choices=sorted(GROUPS))
    args = ap.parse_args()
    names = args.groups or list(GROUPS)
    with tempfile.TemporaryDirectory(prefix="htmltest") as td:
        TEMP = td
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
                nfail += 1
        print(f"\nformal html: PASS={npass} FAIL={nfail} "
              f"(backends: {', '.join(backends())})")
        return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())