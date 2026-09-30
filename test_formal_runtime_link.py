#!/usr/bin/env python3
"""test_formal_runtime_link.py -- agent [5]'s coverage for the gimple runtime's
C library on a FORMAL link line.

FORMAL.md phase 2 decided, for every one of the runtime's entry points, whether
a formal image could call it: every type crossing the boundary is one 64-bit
word AND the symbol is on the link line. The first half was decided and
nothing more happened, because the second half was false for all of them -- a
formal image linked libSystem and nothing else. The library was never missing
(`build_stdlib_dylib.runtime_dylib` has built a per-architecture `-dynamiclib`
exporting the whole `mojo_*` namespace for the gimple path all along); it was
never on a FORMAL link line. This file covers putting it there, and the two
things that had to become true for putting it there not to be worse than the
refusal it replaces.

What is pinned here, and why each of these is a thing that could silently
change:

1. **A word-shaped call builds, links and RUNS with the right answer.** Not
   "is not refused": the image is executed and its exit code and stdout are
   checked, on both architectures. A refusal replaced by an image that builds
   and computes the wrong number is the failure this whole programme is about,
   and it is invisible to every check that stops at the compiler's exit code.

2. **The image really carries the library**, read back out of the finished
   Mach-O with `otool -L` -- a tool that is not this repository and does not
   share its assumptions. `result["linked_dylibs"]` is the build's own account
   of itself and would happily report a library it did not emit.

3. **The refusal surface did not move.** The box surface (321 entry points,
   `MojoList *` in an argument or a `void *` in a return) is still refused and
   still names the TYPE. And the two families this change ADDED to it: the
   floating-point entry points, and the ones whose pointer parameter the callee
   dereferences. Both were admitted by the previous rule and both are silent
   wrong answers -- `mojo_div_double` was measured returning 2 for an answer of
   1 -- so linking the library without closing them would have converted a
   refusal into a lie.

4. **The link line is the DYLIB'S OWN export table**, read from its export
   trie, and not a second copy of what the headers declare. The two differ in
   both directions on this tree and the test asserts both, because a map built
   from the headers would pass every "the call works" check above and still
   offer a client a name the library does not define.

5. **The bind audit was not weakened.** 478 names now count as provided, which
   is a lot of new green; the audit still has to fire on a name outside them.

6. **A program that names nothing in the runtime links nothing.** Every
   dependency is a load command, a load command moves the entry point, and the
   entry point moves every address in the image, so "always link it" would
   re-emit the whole coverage sweep for nothing.

7. **A module dylib that calls into the runtime carries the load command too.**
   Its bind stream gives `mojo_strlen` an ordinal into ITS OWN dependency list;
   without the load command the ordinal names whatever library happens to sit
   at that position, and the library links, passes the audit, and calls the
   wrong function.

No Lean and no proofs. `prove=False` throughout, and that is not a shortcut:
`formal/arm64_proof_gen.py` currently raises `ValueError: unsupported:
recursion argument bound` for ANY program containing a call, which is agent
[2]'s scope and is recorded in FORMAL.md 11.1. Nothing here can assert anything
about a proof until that lands, and pretending otherwise would be a test that
passes vacuously -- the exact failure the census was built to catch.
"""
import os
import subprocess
import sys
import tempfile

# This file lives IN the repository root, so HERE is already the root.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import formal.build as B
import formal.model as M

RESULTS = []


def check(ok, what, detail=''):
    RESULTS.append((bool(ok), what))
    if not ok:
        print(f"FAIL  {what}" + (f': {detail}' if detail else ''), flush=True)
    return bool(ok)


REPORT = []


def report(line):
    REPORT.append(line)
    print(f"      {line}", flush=True)


# ── building and running a formal image ─────────────────────────────────────

WORK = tempfile.mkdtemp(prefix='formal_rtlink_')


def build(source, name, arch='arm64', fmt='macho', **kw):
    """compile_formal on `source`, returning the result dict.

    `prove=False` for the reason in this file's docstring. Output goes under
    WORK so two architectures of the same program do not collide, which is the
    same one-repo-root collision the operating contract names.
    """
    path = os.path.join(WORK, name + '.mojo')
    with open(path, 'w') as f:
        f.write(source)
    ext = '.elf' if fmt == 'elf' else '.aout'
    out = os.path.join(WORK, f"{name}.{arch}.{fmt}{ext}")
    kw.setdefault('prove', False)
    kw.setdefault('check', False)
    return B.compile_formal(path, output=out, arch=arch, fmt=fmt, **kw)


def build_expecting_refusal(source, name, **kw):
    """The refusal message for `source`, or '' if it built.

    '' and the message are different outcomes and the caller says which it
    wanted: a test that only checked "did not crash" would pass on either.
    """
    try:
        build(source, name, **kw)
    except B.FormalBuildError as e:
        return str(e)
    return ''


def run(result, timeout=60):
    """(exit code, stdout) for a built image, or (None, detail) if it would not
    start at all -- which is its own answer and has to be distinguishable from
    a wrong one."""
    try:
        p = subprocess.run([result["path"]], capture_output=True, text=True,
                           timeout=timeout)
    except OSError as e:
        return None, f'could not execute: {e}'
    return p.returncode, p.stdout


def prepass(source, name='prepass'):
    """What `_runtime_word_calls` finds in `source` -- the question "would this
    program make this build link the runtime library?", asked directly.

    Asked directly because for a program that is REFUSED there is no result
    dict to read a link line out of, and the pre-pass's answer is the thing
    under test: it must be empty for a program that links nothing, including
    one whose call never gets as far as being made.
    """
    path = os.path.join(WORK, name + '.mojo')
    with open(path, 'w') as f:
        f.write(source)
    with open(path) as f:
        stmts = B.parse_module(f.read(), filename=path)
    functions, _structs, _symbols, _slots = B._prepare_functions(
        stmts, synthetic=True)
    return B._runtime_word_calls(functions)


# The program the whole change is about. `mojo_strlen` takes and returns one
# word, `mojo_print` takes a `char *` (a string IS an interned `char *` on this
# path) and returns nothing -- so every type crossing this boundary is one
# word, which is the whole of phase 2's rule.
STR_CALL = (
    "def main():\n"
    "    mojo_print(\"linked\")\n"
    "    return mojo_strlen(\"hello\")\n"
)


# ── 1. the call works, and the answer is right ──────────────────────────────

def test_word_shaped_call_links_and_runs():
    for arch in ('arm64', 'x86_64'):
        r = build(STR_CALL, 'strcall', arch=arch)
        libs = [os.path.basename(p) for p in r["linked_dylibs"]]
        check(len(r["linked_dylibs"]) == 1 and 'libmojostdlib' in libs[0],
              f"{arch}: the runtime library is on the link line", str(libs))
        check(arch in libs[0],
              f"{arch}: the library on the link line is FOR this architecture",
              libs[0])
        rc, out = run(r)
        check(rc == 5,
              f"{arch}: mojo_strlen('hello') answers 5 (the image's exit code)",
              f'exit {rc!r}, stdout {out!r}')
        check('linked' in out,
              f"{arch}: mojo_print's output reaches stdout", repr(out))


def test_image_carries_the_load_command():
    # `otool -L` is not this repository. If the build's own report of its link
    # line and an unrelated tool disagree, the tool is right.
    r = build(STR_CALL, 'otool')
    try:
        p = subprocess.run(['otool', '-L', r["path"]], capture_output=True,
                           text=True, timeout=60)
    except OSError:
        report('otool is unavailable; the load-command check is skipped')
        return
    lines = [ln.strip().split(' ')[0] for ln in p.stdout.splitlines()[1:]]
    named = [ln for ln in lines if ln and 'libmojostdlib' in ln]
    check(len(named) == 1,
          "the finished Mach-O carries exactly one libmojostdlib load command",
          str(lines))
    check(any(ln == '/usr/lib/libSystem.B.dylib' for ln in lines),
          "and still carries libSystem", str(lines))
    if named:
        check(os.path.exists(named[0]),
              "the library dyld is told to load is actually on disk", named[0])


# ── 2. the refusal surface, which must not have moved ──────────────────────

def test_box_surface_still_refused():
    # A REAL list literal, which is the point: there is nothing wrong with this
    # program's list, and the call is still unanswerable, because it is not
    # asking this path's question.
    msg = build_expecting_refusal(
        "def main():\n"
        "    var xs = [1, 2, 3]\n"
        "    return mojo_list_len(xs)\n", 'box')
    check(msg != '', 'a MojoList * argument is still refused')
    check('MojoList *' in msg, 'and the refusal names the type', msg[:200])
    check('mojo_list_len' in msg, 'and names the entry point', msg[:120])
    # The return-position box: a `void *` the caller would have to read.
    msg = build_expecting_refusal(
        "def main():\n"
        "    var db = mojo_sqlite3_open(\":memory:\")\n"
        "    return 0\n", 'boxret')
    check(msg != '', 'a void * return is still refused')
    check('mojo_sqlite3_open' in msg, 'and names the entry point', msg[:120])


def test_float_surface_refused():
    # The measured one. On this path a Float64 is truncated toward zero on the
    # way in, so the image used to hand `mojo_div_double` the integer 2 in X0
    # and it read that bit pattern as a double: the program returned 2 where
    # the answer is 1. A refusal is the correct outcome and a wrong answer is
    # not, so the float scalars are out of the word set.
    msg = build_expecting_refusal(
        "def main():\n"
        "    var x: Float64 = 2.5\n"
        "    return mojo_div_double(x, x)\n", 'flt')
    check(msg != '', 'a double-typed runtime call is refused')
    check('floating-point' in msg,
          'and the refusal says the word is not a floating-point value',
          msg[-400:])
    check('integer' in msg, 'and says what a value on this path IS', msg[-400:])


def test_dereferenced_pointer_refused():
    # `mojo_set_argv(int, const char **)` and `mojo_regex_lastgroup(const char
    # **, int, const int64_t *)` write THROUGH the pointer they are handed.
    # This path can hand over a string and an opaque handle; it cannot name a
    # location to be written, because a list lives in a frame that is reclaimed
    # when the frame returns and there is no allocator.
    for name in ('mojo_set_argv', 'mojo_regex_lastgroup'):
        entry = M.runtime_abi_entry(name)
        check(entry is not None, f'{name} is in the header table')
        if entry is None:
            continue
        check(not entry['word'], f'{name} is not word-shaped', entry['signature'])
        msg = M.gimple_runtime_refusal(name)
        check('DEREFERENCES' in msg,
              f'{name} is refused as a pointer the callee dereferences',
              msg[-400:])
    msg = build_expecting_refusal(
        "def main():\n"
        "    return 0\n", 'noop')          # a build that must still succeed
    check(msg == '', 'the negative-control program still builds')


def test_both_architectures_agree():
    # The refusal is one function in formal/model.py precisely so the two
    # architectures cannot drift; this is the check that they have not, and it
    # goes through CODEGEN on both rather than through the shared function --
    # asking the function twice would agree by construction and prove nothing.
    msgs = {}
    for arch in ('arm64', 'x86_64'):
        for src, tag in (
                ("def main():\n    var xs = [1]\n    return mojo_list_len(xs)\n",
                 'mojo_list_len'),
                ("def main():\n    var x: Float64 = 1.5\n"
                 "    return mojo_div_double(x, x)\n", 'mojo_div_double')):
            m = build_expecting_refusal(src, f'agree_{tag}', arch=arch)
            check(m != '', f'{arch}: {tag} is refused', m[:120])
            msgs.setdefault(tag, {})[arch] = m
    for tag, per in msgs.items():
        check(per.get('arm64') == per.get('x86_64'),
              f'both architectures refuse {tag} in the same words',
              f"{per.get('arm64', '')[:80]!r} vs {per.get('x86_64', '')[:80]!r}")


# ── 3. only when it is needed ───────────────────────────────────────────────

def test_a_program_naming_nothing_links_nothing():
    r = build("def main():\n    return 0\n", 'plain')
    check(r["linked_dylibs"] == [],
          'a program that names no runtime entry point links no library',
          str(r["linked_dylibs"]))
    # And the same for one that names a name OUTSIDE the runtime, which is the
    # other shape the pre-pass has to get right: `mojo_`-prefixed is not
    # sufficient, DECLARED-IN-THE-HEADER is.
    r = build("def mojo_thing():\n    return 1\n\n"
              "def main():\n    return mojo_thing()\n", 'localmojo')
    check(r["linked_dylibs"] == [],
          "a local function spelled mojo_* does not drag the library in",
          str(r["linked_dylibs"]))
    rc, _ = run(r)
    check(rc == 1, 'and it still computes its own answer', repr(rc))
    # A name in the namespace that no header declares is NOT enough either: it
    # is refused (there is no signature to check), and asking for a library it
    # could not bind from is the mistake this pre-pass has to avoid making.
    check(prepass("def main():\n    return mojo_thing()\n") == [],
          'an undeclared mojo_* name does not drag the library in',
          str(prepass("def main():\n    return mojo_thing()\n")))
    msg = build_expecting_refusal(
        "def main():\n    return mojo_thing()\n", 'undeclared')
    check('no header in runtime/ declares it' in msg,
          'and the call is still refused for lack of a declaration', msg[:200])
    # The positive control for the pre-pass itself, so "always empty" is not
    # how the two checks above pass.
    check(prepass(STR_CALL) == ['mojo_print', 'mojo_strlen'],
          'the pre-pass finds the everyday word surface',
          str(prepass(STR_CALL)))


def test_word_shaped_but_not_exported_links_nothing():
    # The gate is TWO questions, and this is the case where they disagree.
    # `runtime_dylib` links `runtime_units(arch, None)` — the core runtime, the
    # coroutine runtime, the async scheduler — and not the OPTIONAL units
    # `fire_sqlite3.c` / `fire_ssl.c` / `fire_zlib.c` / `fire_ncurses.c`, which
    # the gimple path compiles on demand. So `mojo_sqlite3_close` is
    # word-shaped and the library does not define it, and putting 478 names on
    # this image's link line would change nothing about the verdict.
    amap = B.runtime_library('arm64', 'macho')["map"]
    check('mojo_sqlite3_close' not in amap,
          'the runtime library does not export mojo_sqlite3_close (measured)')
    src = ("def main():\n"
           "    var db = mojo_sqlite3_open(\":memory:\")\n"
           "    mojo_sqlite3_close(db)\n"
           "    return 0\n")
    check('mojo_sqlite3_close' in prepass(src),
          'but the pre-pass does name it — word-shaped is the first half only',
          str(prepass(src)))
    msg = build_expecting_refusal(src, 'sqlitenolib')
    check('mojo_sqlite3_open' in msg,
          'and the refusal is the box one, from the return type', msg[:200])
    # A program whose ONLY runtime call is the missing one links nothing, and
    # is told exactly that.
    src2 = "def main():\n    mojo_sqlite3_close(1)\n    return 0\n"
    check(B._runtime_library_for([], 'arm64', 'macho')[0] is None,
          'a program naming no runtime call at all links nothing')
    msg = build_expecting_refusal(src2, 'sqlonly2')
    check('one whose library does not export this name' in msg,
          'and a word-shaped name the library does not export is refused as '
          'such, naming the situation rather than blaming the mechanism',
          msg[:400])


def test_elf_is_still_refused():
    # `build_elf` carries one `lib_name` and no dependency list, so an ELF
    # image genuinely cannot name a second library. The refusal is the honest
    # answer, and `runtime_library` says so by returning None rather than by
    # pretending.
    check(B.runtime_library('arm64', 'elf') is None,
          'runtime_library declines to invent an ELF dependency')
    msg = build_expecting_refusal(STR_CALL, 'elf', fmt='elf')
    check(msg != '', 'a mojo_* call on an ELF image is still refused')
    check('nothing on this image\'s link line' in msg,
          'and the refusal says the link line is what is missing', msg[:400])


# ── 4. the link line is the dylib's OWN table ───────────────────────────────

def test_link_line_is_the_dylibs_exports():
    from build_stdlib_dylib import runtime_dylib
    for arch in ('arm64', 'x86_64'):
        dylib = runtime_dylib(arch=arch)
        trie = B.macho_dylib_exports(dylib)
        cnames = {B._c_export_name(n) for n in trie}
        cnames.discard(None)
        amap = B.runtime_library(arch, 'macho')["map"]
        abi = set(M.runtime_abi())
        # The two differ in BOTH directions on this tree, which is the whole
        # reason the map is read out of the artifact.
        extra = sorted(cnames - abi)
        check(len(extra) >= 5,
              f'{arch}: the dylib exports names no header declares',
              str(sorted(extra)))
        check(all(n in amap for n in extra),
              f'{arch}: and the link line offers them anyway — it is the '
              f"dylib's table, not the header's", str(sorted(extra)[:5]))
        missing = sorted(abi - cnames)
        check(len(missing) >= 5,
              f'{arch}: headers declare names the dylib does not export',
              str(sorted(missing)[:5]))
        check(all(n not in amap for n in missing),
              f'{arch}: and the link line does not claim them')
        check(not any(n.startswith('__Z') for n in amap),
              f'{arch}: C++ mangled names are not in the map — no program '
              f'can spell one')
        # Every word-shaped entry point the library really provides is offered,
        # which is the number the phase-2 payoff is measured in.
        word = {n for n, e in M.runtime_abi().items() if e['word']}
        linked = word & set(amap)
        check(linked >= {'mojo_strlen', 'mojo_print', 'mojo_c_getenv'},
              f'{arch}: the everyday word surface is on the link line',
              str(sorted(word - linked)[:5]))
        handles = [n for n in sorted(linked)
                   if any(M._parse_ctype(p, is_param=True) == ('void', 1)
                          for p in (M._split_params(M.runtime_abi_entry(n)['params']) or []))]
        report(f"{arch}: {len(word)} word-shaped, {len(linked)} of them exported "
               f"by the runtime library, {len(linked) - len(handles)} of those "
               f"reachable without a heap handle ({len(handles)} need one the "
               f"path cannot obtain)")


def test_manifest_round_trips():
    from build_stdlib_dylib import runtime_dylib
    dylib = runtime_dylib(arch='arm64')
    manifest = B.dylib_manifest_path(dylib)
    check(os.path.exists(manifest),
          'the runtime library has an export manifest beside it, as any linked '
          'library does', manifest)
    loaded = B.load_dylib_manifests([dylib])[0]
    check(loaded["install_name"] == os.path.abspath(dylib),
          'and the manifest names the real location, not its @rpath install name',
          loaded["install_name"])
    check(len(loaded["map"]) == len(loaded["exports"]),
          'every export contributes a callee mapping',
          f"{len(loaded['map'])} vs {len(loaded['exports'])}")
    signed = [e for e in loaded["exports"]
              if M.runtime_abi_entry(e["name"]) is not None]
    check(all(e["signature"] for e in signed),
          'every export a header declares carries that declaration')
    check(all(e["symbol"] == e["name"] for e in loaded["exports"]),
          "and the bind spelling is the C name, not the Mach-O one")


# ── 5. the audit still fires ────────────────────────────────────────────────

def test_bind_audit_not_weakened():
    amap = B.runtime_library('arm64', 'macho')["map"]
    check(len(amap) > 400,
          'the link line now accounts for hundreds of names', str(len(amap)))
    check(B._audit_bound_symbols(['mojo_strlen'], amap, 'image') == [],
          'a name the library provides is accounted for')
    bad = B._audit_bound_symbols(
        ['mojo_strlen', 'mojo_not_a_runtime_entry_point_anywhere'], amap, 'image')
    check(bad == ['mojo_not_a_runtime_entry_point_anywhere'],
          'and one it does not is still reported', str(bad))
    # And it is not the `mojo_` prefix doing the work: a non-runtime name
    # outside the map and outside the C library is reported too.
    check(B._audit_bound_symbols(['zzz_no_such_provider'], amap, 'image') ==
          ['zzz_no_such_provider'],
          'a name outside the map and outside libSystem is reported')


# ── 6. a module dylib carries it too ────────────────────────────────────────

def test_module_dylib_carries_the_load_command():
    path = os.path.join(WORK, 'modcall.mojo')
    with open(path, 'w') as f:
        f.write("def width(s):\n    return mojo_strlen(s)\n")
    out = os.path.join(WORK, 'modcall.dylib')
    B.compile_formal_dylib([path], output=out, arch='arm64', prove=False,
                           check=False)
    with open(out, 'rb') as f:
        data = f.read()
    check(b'libmojostdlib.arm64' in data,
          'a module dylib that binds mojo_strlen names the runtime library in '
          'its own load commands, so its bind ordinal resolves')
    # …and the library it names is the one that exists.
    p = subprocess.run(['otool', '-L', out], capture_output=True, text=True)
    named = [ln.strip().split(' ')[0] for ln in p.stdout.splitlines()[1:]
             if 'libmojostdlib' in ln]
    check(len(named) == 1 and os.path.exists(named[0]),
          'and it is on disk', str(named))
    # A library that names nothing in the runtime does not carry it.
    path2 = os.path.join(WORK, 'modplain.mojo')
    with open(path2, 'w') as f:
        f.write("def triple(n):\n    return n * 3\n")
    out2 = os.path.join(WORK, 'modplain.dylib')
    B.compile_formal_dylib([path2], output=out2, arch='arm64', prove=False,
                           check=False)
    with open(out2, 'rb') as f:
        check(b'libmojostdlib' not in f.read(),
              'a module dylib that names no runtime entry point does not')


# ── 7. the word rule, by the cases that moved it ────────────────────────────

# Every entry point whose word-shapedness this change removed, with the reason.
# Asserted by NAME and by reason rather than as a count: a count alone passes
# when the wrong twelve moved, which is the failure a coverage number has.
LOST = {
    'mojo_div_double': 'a floating-point value',
    'mojo_div_float': 'a floating-point value',
    'mojo_make_float': 'a floating-point value',
    'mojo_max_double': 'a floating-point value',
    'mojo_min_double': 'a floating-point value',
    'mojo_python_to_double': 'a floating-point value',
    'mojo_repr_float': 'a floating-point value',
    'mojo_sqlite3_bind_double': 'a floating-point value',
    'mojo_sqlite3_column_double': 'a floating-point value',
    'mojo_sum_double': 'a floating-point value',
    'mojo_set_argv': 'DEREFERENCES',
    'mojo_regex_lastgroup': 'DEREFERENCES',
}


def test_word_rule_moved_only_where_measured():
    for name, why in LOST.items():
        entry = M.runtime_abi_entry(name)
        check(entry is not None, f'{name} is still in the header table')
        if entry is None:
            continue
        check(not entry['word'], f'{name} is no longer word-shaped',
              entry['signature'])
        check(why in M.gimple_runtime_refusal(name),
              f"{name} is refused as {why}",
              M.gimple_runtime_refusal(name)[-300:])
    # …and the rule did not move for anything else. `void *` as an ARGUMENT is
    # still admitted, on the reachability argument formal/model.py states: the
    # only producers of a handle are `void *`-returning entry points, and those
    # are refused, so a well-typed program here cannot produce a bad one. That
    # is a judgement recorded in the source, and this asserts it is still in
    # force rather than silently dropped.
    for name in ('mojo_max_int', 'mojo_min_int', 'mojo_sum_int'):
        entry = M.runtime_abi_entry(name)
        if entry is not None:
            check(entry['word'],
                  f'{name} (a void * argument) is still admitted', name)
    check('float' not in M._WORD_SCALARS and 'double' not in M._WORD_SCALARS,
          'the floating-point scalars are not values on this path')
    check('int64_t' in M._WORD_SCALARS,
          'and the integer scalars still are')


def main():
    test_word_shaped_call_links_and_runs()
    test_image_carries_the_load_command()
    test_box_surface_still_refused()
    test_float_surface_refused()
    test_dereferenced_pointer_refused()
    test_both_architectures_agree()
    test_a_program_naming_nothing_links_nothing()
    test_word_shaped_but_not_exported_links_nothing()
    test_elf_is_still_refused()
    test_link_line_is_the_dylibs_exports()
    test_manifest_round_trips()
    test_bind_audit_not_weakened()
    test_module_dylib_carries_the_load_command()
    test_word_rule_moved_only_where_measured()
    npass = sum(1 for ok, _w in RESULTS if ok)
    nfail = len(RESULTS) - npass
    print(f"\n{npass} passed, {nfail} failed, {len(RESULTS)} checks")
    return 1 if nfail else 0


if __name__ == '__main__':
    sys.exit(main())
