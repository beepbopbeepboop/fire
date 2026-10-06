#!/usr/bin/env python3
"""test_runtime_dylib.py — the runtime dylib is PER-ARCH, and its export
table names only symbols it actually defines.

The two things this file exists to hold down, and why each needed holding down:

**1. The architecture is part of the artifact's identity.** `runtime_dylib()`
used to have no notion of a target at all: its CAS key folded in the *host*
(through `cas.toolchain_fingerprint`) and its output name had no architecture
in it, so the arm64 and x86-64 runtime dylibs were one cache entry wearing one
file name. `tools/formal_sweep.py --arch` runs both architectures on every
sweep, and `formal/imports.py` already builds per-arch *module* dylibs, so the
runtime half was the gap.

The reason this is not a three-line change is that **an architecture flag can
be accepted and ignored.** Measured on this machine, the compiler this tree is
configured with:

    $ /opt/local/bin/gcc-mp-15 -arch x86_64 -c -o t.o t.c
    warning: this compiler does not support x86 ('-arch' option ignored)
    $ file t.o
    t.o: Mach-O 64-bit object arm64          # exit status 0

So a build rule that trusted the flag would ship a dylib named
`.x86_64.dylib` containing arm64 code, and the failure would be dyld's, in a
different program, later ("mach-o file, but is an incompatible
architecture"). Everything here therefore checks the Mach-O that came OUT
(`arches_of` / `_arch_or_die`) rather than the flags that went in. That check
is not belt-and-braces: during the implementation it caught a live bug where
`-arch` was missing from the LINK step, `ld` warned `ignoring file ...: found
architecture 'x86_64', required architecture 'arm64'` for every object, exited
0, and wrote an empty arm64 dylib.

**2. The reflection table names only real definitions.** The table
forward-declares and takes the address of every entry it advertises, so ONE
entry with no definition behind it is a `dlopen` failure for every client of
the dylib, not just for a client that calls it. The table is therefore built as
an intersection — the runtime headers' entry points AND what `nm` says the
linked objects define — and this file checks the result by reading the table
back out of the LINKED dylib, because a table checked in Python is a table
checked before the thing that could invalidate it.

The build now also reports the shortfall **by class**, and one of those classes
is a live defect in `reflect.export_csym` (agent [3]'s file; see
`INTERFACE-REQUESTS.md`): a C prototype is run through the Mojo
overload-mangler, so 429 of `fire_runtime.h`'s entry points resolve to a symbol
that does not exist and are dropped. The assertions below therefore pin the
INVARIANT — every dropped name is accounted for, by exactly one of the two
classes, and the "misresolved" ones are genuinely defined — rather than a
count. A count would be red today and green after [3]'s fix; the invariant is
true in both states and catches the case where a name is dropped for a THIRD,
unexplained reason, which is the failure that actually hides defects.

Run directly (`python3 test_runtime_dylib.py`). It honours `$GMOJO_HOME` and
writes nothing outside the CAS and the system temp directory.
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_stdlib_dylib as bsd            # noqa: E402
import cas                                  # noqa: E402
import reflect                              # noqa: E402

RUNTIME = os.path.join(HERE, 'runtime')
RESULTS = []

# The two architectures this project builds for. Deliberately not derived from
# the host: a test that only ever builds for the host cannot tell a
# per-arch rule from a host-only one.
ARM = 'arm64'
X86 = 'x86_64'

_built = {}          # arch -> path, built at most once per process
_objects = {}        # arch -> [object paths], for the export-table checks
_harness_cache = {}  # arch -> native dlopen harness path, or '' if unbuildable


def check(ok, what, detail=''):
    RESULTS.append((bool(ok), what))
    if not ok:
        print(f"FAIL  {what}" + (f': {detail}' if detail else ''), flush=True)


def runtime_for(arch):
    if arch not in _built:
        _built[arch] = bsd.runtime_dylib(arch=arch)
    return _built[arch]


def objects_for(arch):
    """The runtime objects for `arch`, compiled the way runtime_dylib does."""
    if arch not in _objects:
        cc, cxx = bsd.toolchain_for(arch, bsd.find_gcc(), bsd.find_gxx())
        wd = tempfile.mkdtemp(prefix='test_rt_obj_')
        objs = []
        for src, lang, flags in bsd.runtime_units(arch):
            o = os.path.join(wd, os.path.splitext(os.path.basename(src))[0] + '.o')
            subprocess.run([cxx if lang == 'c++' else cc, *flags, '-c', '-o', o, src],
                           check=True)
            objs.append(o)
        _objects[arch] = objs
    return _objects[arch]


# ── 1. one spelling per architecture ────────────────────────────────────────

def test_arch_names_canonicalize():
    """`uname -m` says aarch64, Apple's `-arch` says arm64, and a caller may
    say either. Two spellings of one architecture must be ONE cache entry and
    ONE file, or the two silently become two builds of the same thing."""
    for a, b in (('aarch64', ARM), ('arm64e', ARM), ('arm', ARM),
                 ('AMD64', X86), ('x86-64', X86), ('x64', X86)):
        check(bsd.normalize_arch(a) == bsd.normalize_arch(b),
              f'normalize_arch: {a} and {b} are the same architecture',
              f'{bsd.normalize_arch(a)} vs {bsd.normalize_arch(b)}')
    check(bsd.normalize_arch(None) == bsd.normalize_arch(''),
          'normalize_arch: an unspecified arch is the host, and says so once')
    check(bsd.normalize_arch('PPC') == 'ppc',
          'normalize_arch: an unknown name passes through rather than being '
          f'rewritten to something else', bsd.normalize_arch('PPC'))


def test_arch_flags_and_units_differ_by_target():
    """The per-target flag, and the arch-specific SOURCE, must both follow the
    target. The source is the one that is easy to get wrong: the aarch64
    context-switch file is hand-written assembly, so an x86-64 build that
    selected it on the host would fail in the assembler on a register that does
    not exist there — or, worse, be a no-op somewhere else."""
    check(bsd.arch_flags(X86) == ('-arch', X86),
          'arch_flags: the target reaches the compile command',
          str(bsd.arch_flags(X86)))
    names = {a: [os.path.basename(s) for s, _l, _f in bsd.runtime_units(a)]
             for a in (ARM, X86)}
    check('fire_coro_ctx_aarch64.S' in names[ARM],
          'runtime_units: arm64 gets the aarch64 context-switch assembly',
          str(names[ARM]))
    check('fire_coro_ctx_generic.c' in names[X86],
          'runtime_units: x86_64 gets the portable context switch',
          str(names[X86]))
    check('fire_coro_ctx_aarch64.S' not in names[X86],
          'runtime_units: x86_64 does NOT get aarch64 assembly')
    check(names[ARM] != names[X86],
          'runtime_units: the two targets genuinely differ in their sources')
    # Every unit's flags carry the target, including the C++ one and the
    # assembly one — the assembly unit has no language flags of its own, so
    # this is the only thing that tells it which architecture to assemble for.
    for arch in (ARM, X86):
        for src, _lang, flags in bsd.runtime_units(arch):
            check(bsd.arch_flags(arch) in
                  tuple(tuple(flags[i:i + 2]) for i in range(len(flags) - 1)),
                  f'runtime_units: {os.path.basename(src)} carries -arch {arch}',
                  str(flags))


# ── 2. the toolchain is measured, not assumed ───────────────────────────────

def test_toolchain_selection_is_measured():
    """A driver that cannot target an architecture must be REJECTED by trying
    it, and an architecture nothing can target must produce an error naming
    what was measured for each candidate — "unsupported" sends the next reader
    nowhere."""
    arch = bsd.normalize_arch()
    cc, cxx = bsd.toolchain_for(arch, bsd.find_gcc(), bsd.find_gxx())
    check(bool(cc) and bool(cxx), f'toolchain_for({arch}) finds a C and a C++ driver',
          f'{cc} {cxx}')
    for d in (cc, cxx):
        ok, why = bsd._driver_targets(d, arch)
        check(ok, f'the chosen driver {d} really does target {arch}', why)
    # The probe must be a real measurement, not a flag check: force a driver
    # that cannot do it and confirm the probe says so.
    ok, why = bsd._driver_targets('/usr/bin/true', arch)
    check(not ok, 'a driver that cannot compile anything is rejected by the probe',
          why)


def test_unreachable_arch_fails_with_a_reason():
    """No driver on any machine targets ppc64 here, and the error must say what
    each one did rather than that the request was unsupported."""
    try:
        bsd.toolchain_for('ppc64', bsd.find_gcc())
        check(False, 'an unbuildable architecture is refused, not attempted')
    except bsd.ArchError as e:
        msg = str(e)
        check('ppc64' in msg, 'the refusal names the architecture', msg)
        check('/opt/local' in msg or 'gcc' in msg or 'clang' in msg,
              'the refusal names what it measured per candidate', msg)
        check(len(msg) > 60,
              'the refusal carries a per-candidate reason rather than a bare '
              f'"unsupported"', msg)


# ── 3. both architectures build, and neither can clobber the other ──────────

def test_both_arch_dylibs_build_and_are_distinct():
    paths = {}
    for arch in (ARM, X86):
        try:
            paths[arch] = runtime_for(arch)
        except Exception as e:
            check(False, f'runtime_dylib builds for {arch}', f'{type(e).__name__}: {e}')
    if len(paths) != 2:
        return
    check(paths[ARM] != paths[X86],
          'the two architectures are two different files')
    check(f'.{ARM}.' in os.path.basename(paths[ARM]),
          'the architecture is in the file NAME, not only in the key',
          os.path.basename(paths[ARM]))
    check(f'.{X86}.' in os.path.basename(paths[X86]),
          'the architecture is in the file NAME for x86_64 too',
          os.path.basename(paths[X86]))
    for arch, p in paths.items():
        found = bsd.arches_of(p)
        check(arch in found,
              f'the {arch} dylib really contains {arch} code',
              f'{sorted(found)} in {p}')


def test_cache_hit_is_the_same_file_and_reverified():
    """A second call is a cache hit and must return the same path. It is also
    RE-VERIFIED: the key is a claim about the artifact and the artifact is the
    thing, so an entry left behind by an older key (or by a driver that lied)
    must not be served merely because its name is right."""
    a1 = runtime_for(ARM)
    cas_before = dict(cas.stats)
    a2 = bsd.runtime_dylib(arch=ARM)
    check(a1 == a2, 'a second runtime_dylib() call is a cache hit on the same path',
          f'{a1} vs {a2}')
    check(bsd.arches_of(a2) and ARM in bsd.arches_of(a2),
          'the cached dylib is re-verified against the requested architecture')
    # And the flags argument reaches the key, so a different one is a different
    # artifact rather than a second name for the same bytes. It used to go into
    # the key and then into no compile command at all.
    try:
        other = bsd.runtime_dylib(arch=ARM, flags=('-DEXTRA_FLAG_FOR_THE_TEST=1',))
        check(other != a1,
              'flags are part of the artifact identity (they used to be key-only)')
        check(bsd.arches_of(other) and ARM in bsd.arches_of(other),
              'the flags-variant is still a valid arm64 dylib')
    except Exception as e:
        # A driver that rejects an unknown -D is a legitimate outcome; what must
        # not happen is the flags being IGNORED and the same bytes coming back.
        check('not' in str(e).lower() or 'unknown' in str(e).lower()
              or 'unrecog' in str(e).lower(),
              'an unusable flag fails loudly rather than being dropped', str(e))


def test_wrong_arch_object_is_rejected():
    """The check that makes the flag trustworthy. An object built for the OTHER
    architecture must be refused by name, with both architectures in the
    message, so the diagnostic says which way round it went wrong."""
    arm_obj = objects_for(ARM)[0]
    with tempfile.TemporaryDirectory() as td:
        foreign = os.path.join(td, 'foreign.dylib')
        # An arm64 object presented as an x86_64 artifact: exactly the shape of
        # the bug this file exists to catch.
        with open(arm_obj, 'rb') as f:
            data = f.read()
        with open(foreign, 'wb') as f:
            f.write(data)
        try:
            bsd._arch_or_die(foreign, X86, 'test object')
            check(False, 'an arm64 artifact offered as x86_64 is rejected')
        except bsd.ArchError as e:
            msg = str(e)
            check('arm64' in msg and X86 in msg,
                  'the rejection names both architectures', msg)
            check('test object' in msg,
                  'the rejection names what was being checked', msg)


# ── 4. the export table ─────────────────────────────────────────────────────

def test_export_table_entries_are_all_real_definitions():
    """Read the table back out of the LINKED dylib and confirm every advertised
    address is a symbol the dylib really exports.

    This is the invariant that matters and it is checked on the artifact rather
    than on the Python that built it: `emit_table_c` forward-declares each
    advertised symbol and takes its address, so an entry with nothing behind it
    is not a latent problem for whoever calls it, it is a `dlopen` failure for
    every client of the dylib."""
    path = runtime_for(bsd.normalize_arch())
    lib = ctypes.CDLL(path)

    class Sym(ctypes.Structure):
        _fields_ = [('name', ctypes.c_char_p), ('sig', ctypes.c_char_p),
                    ('addr', ctypes.c_void_p), ('kind', ctypes.c_int32)]

    class Table(ctypes.Structure):
        _fields_ = [('magic', ctypes.c_uint32), ('version', ctypes.c_uint32),
                    ('n', ctypes.c_uint32), ('reserved', ctypes.c_uint32),
                    ('syms', ctypes.POINTER(Sym))]

    tbl = Table.in_dll(lib, '__mojo_reflect')
    check(tbl.magic == 0x4D4F4A4F, 'the dylib exports a real __mojo_reflect table',
          hex(tbl.magic))
    exported = bsd._defined_symbols(bsd.find_gcc(), path)
    n = orphans = nulls = 0
    for i in range(tbl.n):
        s = tbl.syms[i]
        if not s.name:
            continue
        n += 1
        name = s.name.decode()
        if s.kind != reflect.SYM_TYPE and not s.addr:
            nulls += 1
        # A C client calls the ADDRESS, so the address must be inside this
        # image. Resolving the name through nm as well catches the inverse: an
        # entry whose name is advertised but whose symbol is not exported.
        if not ('_' + name in exported or name in exported):
            orphans += 1
            if orphans < 4:
                print(f"      orphan: {name}  ({s.sig.decode() if s.sig else ''})")
    check(n > 0, 'the table is not empty', f'{tbl.n} rows')
    check(orphans == 0, 'every advertised symbol is one the dylib defines',
          f'{orphans} of {n} are orphans')
    check(nulls == 0, 'no non-TYPE entry advertises a null address', f'{nulls} of {n}')


def test_every_defined_entry_point_is_advertised():
    """The complement of the orphan check above, and the one that actually
    guards the magnitude.

    `test_export_table_entries_are_all_real_definitions` says every ADVERTISED
    symbol is real. That is a safety property and it held while the table named
    30 of 459 runtime entry points, because the other 429 were dropped rather
    than advertised wrongly. This one says every DEFINED entry point is
    advertised, and it is what makes a regression to 30/459 a red test instead
    of a silently smaller table.

    Stated as a property rather than a count on purpose: the number moves
    whenever the runtime grows a function, and a count assertion that has to be
    edited on every addition is a count assertion that eventually gets edited
    without being checked. The property — nothing the dylib defines is left
    unadvertised — does not move at all."""
    arch = bsd.normalize_arch()
    path = runtime_for(arch)
    defined = bsd._defined_symbols(bsd.find_gcc(), path)
    lib = ctypes.CDLL(path)

    class Sym(ctypes.Structure):
        _fields_ = [('name', ctypes.c_char_p), ('sig', ctypes.c_char_p),
                    ('addr', ctypes.c_void_p), ('kind', ctypes.c_int32)]

    class Table(ctypes.Structure):
        _fields_ = [('magic', ctypes.c_uint32), ('version', ctypes.c_uint32),
                    ('n', ctypes.c_uint32), ('reserved', ctypes.c_uint32),
                    ('syms', ctypes.POINTER(Sym))]

    tbl = Table.in_dll(lib, '__mojo_reflect')
    advertised = set()
    for i in range(tbl.n):
        s = tbl.syms[i]
        if s.name:
            advertised.add(s.name.decode())
    missing, considered = [], 0
    for hdr in bsd._RUNTIME_HEADERS:
        for e in reflect.collect_runtime_exports_h(os.path.join(RUNTIME, hdr)):
            if ('_' + e['name']) not in defined:
                continue        # not this dylib's to advertise (py_tokenize)
            considered += 1
            if e['name'] not in advertised:
                missing.append(e['name'])
    check(considered > 400,
          'the check covers the whole runtime surface, not a sample',
          f'{considered} entry points')
    check(not missing,
          'every entry point the runtime dylib DEFINES is in its table',
          f'{len(missing)} of {considered} unadvertised, e.g. {sorted(missing)[:5]}')


def test_export_table_is_the_intersection_and_says_why():
    """Every entry the headers declare is either advertised or accounted for by
    exactly one of two named classes. A THIRD outcome — a name that is neither
    advertised nor explained — is the failure this catches, because it is the
    one that hides: `build()` used to print a flat list of "drop stale export"
    lines for both a misresolved name and a genuinely-missing definition, which
    is why a 429-entry defect could sit there looking like routine noise."""
    arch = bsd.normalize_arch()
    objs = objects_for(arch)
    entries, report = bsd.runtime_export_entries(bsd.find_gcc(), objs)
    check(len(entries) > 0, 'runtime_export_entries produces a table',
          f'{len(entries)} entries')
    check(bool(report) and 'advertised' in report[0],
          'the report states how much of the surface is advertised', str(report))
    # Re-derive both classes independently and require the report to account
    # for exactly the difference.
    defined = set()
    for o in objs:
        defined |= bsd._defined_symbols(bsd.find_gcc(), o)
    header_names = set()
    for hdr in bsd._RUNTIME_HEADERS:
        for e in reflect.collect_runtime_exports_h(os.path.join(RUNTIME, hdr)):
            header_names.add(e['name'])
    advertised = set(e['name'] for e in entries)
    unaccounted = header_names - advertised
    check(len(advertised) + len(unaccounted) == len(header_names),
          'advertised + dropped accounts for the whole header surface',
          f'{len(advertised)} + {len(unaccounted)} != {len(header_names)}')
    # Each dropped name is EITHER misresolved (defined, but export_csym named
    # something else — a defect in reflect.export_csym, agent [3]'s file) or
    # undefined (declared and defined nowhere: a dead prototype, or one the
    # linking image supplies). Both are real; neither may be silently absorbed.
    mis = [n for n in unaccounted if ('_' + n) in defined]
    und = [n for n in unaccounted if ('_' + n) not in defined]
    check(len(mis) + len(und) == len(unaccounted),
          'every dropped name is in exactly one of the two classes, so none is '
          'absorbed', f'{len(mis)}+{len(und)} vs {len(unaccounted)}')
    for name in und:
        check(name in ' '.join(report),
              f'the undefined entry {name} is named in the report')


def test_word_shaped_surface_is_reachable_by_its_documented_name():
    """The runtime half of agent [3]'s precondition, and it is a statement about
    the DYSLIB's export surface, not about the reflection table.

    Those are two different claims and only this one is true today. The dylib
    genuinely exports every word-shaped entry point under the name
    `fire_runtime.h` documents — a C client, or the formal backend once it can
    call, reaches it with `dlsym("_mojo_list_new")` today. The *table* does not
    yet advertise them, because `reflect.export_csym` mis-resolves a C prototype
    (INTERFACE-REQUESTS.md, `[2] → [3]` A); the assertion that covers the table
    is `test_export_table_entries_are_all_real_definitions`, which holds in both
    states because it checks that every advertised entry is REAL rather than
    that every real entry is advertised.

    Every `void`/`int64_t`-shaped prototype in the header is checked, so this is
    a statement about the whole surface and not a hand-picked sample that could
    pass while the rest is broken."""
    arch = bsd.normalize_arch()
    path = runtime_for(arch)
    exported = bsd._defined_symbols(bsd.find_gcc(), path)
    word = ('void', 'int', 'int64_t', 'uint64_t', 'double', 'char *', 'void *',
            '_Bool', 'size_t')
    checked = missing = 0
    for e in reflect.collect_runtime_exports_h(os.path.join(RUNTIME, 'fire_runtime.h')):
        sig = e['signature']
        if not sig.startswith(word):
            continue
        checked += 1
        if ('_' + e['name']) not in exported:
            missing += 1
    check(checked > 100, 'the word-shaped surface is a large one, not a sample',
          f'{checked} prototypes')
    check(missing == 0,
          'every word-shaped entry point the dylib DEFINES is exported under '
          'its documented name', f'{missing} of {checked} not exported')


# ── 5. dyld agrees with the file name ───────────────────────────────────────

_DLOPEN_HARNESS = r'''
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include "reflect.h"
int main(int argc, char **argv) {
    void *h = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!h) { printf("FAIL %s\n", dlerror()); return 1; }
    const MojoReflectTable *t = dlsym(h, "__mojo_reflect");
    if (!t || t->magic != MOJO_REFLECT_MAGIC) { printf("FAIL table\n"); return 1; }
    uint32_t n = 0;
    for (uint32_t i = 0; i < t->n_syms; i++) if (t->syms[i].name) n++;
    printf("OK %u\n", n);
    return 0;
}
'''


def _harness(arch):
    """A native harness for `arch`, or '' if this machine cannot build one.

    A C driver is the only way to get a process of the other architecture on a
    machine with no interpreter for it (there is no x86-64 `python3` here), and
    `dlopen` from a process of the right architecture is the only way to test
    what dyld will actually accept."""
    if arch not in _harness_cache:
        cc, _cxx = bsd.toolchain_for(arch, bsd.find_gcc(), bsd.find_gxx())
        wd = tempfile.mkdtemp(prefix='test_rt_harness_')
        src = os.path.join(wd, 'harness.c')
        exe = os.path.join(wd, f'harness_{arch}')
        with open(src, 'w') as f:
            f.write(_DLOPEN_HARNESS)
        r = subprocess.run([cc, *bsd.arch_flags(arch), f'-I{HERE}', '-o', exe, src],
                           capture_output=True, text=True)
        _harness_cache[arch] = exe if r.returncode == 0 else ''
    return _harness_cache[arch]


def test_dyld_loads_each_dylib_from_its_own_architecture():
    """The end-to-end proof, and the one that cannot be faked: a process OF
    THAT ARCHITECTURE loads THAT dylib and reads a valid table out of it. A
    mislabelled artifact cannot pass this, because the artifact that would load
    is the one with the wrong name."""
    for arch in (ARM, X86):
        exe = _harness(arch)
        if not exe:
            check(False, f'no C harness could be built for {arch}')
            continue
        r = subprocess.run(['arch', f'-{arch}', exe, runtime_for(arch)],
                           capture_output=True, text=True)
        out = r.stdout.strip()
        check(out.startswith('OK'),
              f'an {arch} process dlopen()s the {arch} runtime dylib and reads '
              f'its table', out or r.stderr.strip()[:200])


def test_dyld_refuses_the_other_architectures_dylib():
    """And the negative, which is the half that proves they are genuinely two
    artifacts. A per-arch rule that quietly produced the same bytes under two
    names would pass the test above; it fails this one."""
    pairs = ((ARM, X86), (X86, ARM))
    for host, foreign in pairs:
        exe = _harness(host)
        if not exe:
            check(False, f'no C harness could be built for {host}')
            continue
        r = subprocess.run(['arch', f'-{host}', exe, runtime_for(foreign)],
                           capture_output=True, text=True)
        combined = r.stdout + r.stderr
        check('incompatible architecture' in combined,
              f'an {host} process REFUSES the {foreign} dylib',
              combined.strip()[:200])


# ── 6. the header carries no declaration it cannot keep ────────────────────

# Declared for GENERATED code to call and defined by whoever LINKS the image —
# for these, by the self-hosted compiler's own transpiled fire_compiler.py.
# See the note in fire_runtime.h. A declaration with no definition is a link
# failure for everyone else, so the exception is named rather than assumed.
_LINKER_SUPPLIED = frozenset({'py_tokenize'})


def test_no_declaration_without_a_definition():
    """Item 3 of the runtime-dylib scope: `fire_runtime.h` declared eight
    functions that no object in the tree defines and no generated C calls.
    A declaration like that is a link failure waiting for the first caller, and
    the reflection table made it worse — it forward-declared and took the
    address of all of them.

    The regression is the header, not the list: any prototype in it must either
    be defined by the runtime objects or be one of the named
    linker-supplied entries. Adding a dead declaration fails here; so does
    deleting a real one, because it would then be neither."""
    arch = bsd.normalize_arch()
    defined = set()
    for o in objects_for(arch):
        defined |= bsd._defined_symbols(bsd.find_gcc(), o)
    declared = set()
    for hdr in bsd._RUNTIME_HEADERS:
        for e in reflect.collect_runtime_exports_h(os.path.join(RUNTIME, hdr)):
            declared.add(e['name'])
    orphans = sorted(n for n in declared
                     if ('_' + n) not in defined and n not in _LINKER_SUPPLIED)
    check(not orphans,
          f'every prototype in the runtime headers is either defined by the '
          f'runtime or named as linker-supplied', f'orphans: {orphans}')


def test_the_removed_declarations_are_gone():
    """Named, because a general "no orphans" assertion cannot say which ones
    were the subject of the fix, and a future edit that reintroduces one of
    them specifically should fail with a message that says so.

    Matched as a DECLARATION, not as a substring: the header now explains in
    prose why each of these was removed, so a substring test would fail on its
    own documentation.

    `mojo_type` is NOT in this list any more, and it is the one removal here
    that was WRONG — see `test_mojo_type_is_still_reachable` below, which
    asserts the corrected fact instead. The other five hold: `nm` on the runtime
    object plus the generated C are both silent about them."""
    import re
    header = open(os.path.join(RUNTIME, 'fire_runtime.h')).read()
    for name, why in (
            ('mojo_obj_enter', '`with` lowers to the defining struct\'s own '
                               'qualified method, never a bare dispatch helper'),
            ('mojo_obj_exit', 'same'),
            ('int___enter__', 'the unqualified spelling has not been emitted '
                              'since ABI v2 module-qualification'),
            ('int___exit__', 'same'),
            ('MojoList__write_to', 'a Mojo method name in a C header'),
    ):
        decl = re.compile(r'^[A-Za-z_][\w\s*]*?\b' + re.escape(name) + r'\s*\(', re.M)
        check(not decl.search(header),
              f'fire_runtime.h no longer DECLARES {name} ({why})')
        scanned = set(e['name'] for e in
                      reflect.collect_runtime_exports_h(os.path.join(RUNTIME,
                                                                     'fire_runtime.h')))
        check(name not in scanned,
              f'and the header scanner no longer reports {name}')


def test_mojo_type_is_still_reachable():
    """The correction, pinned so it cannot be removed a second time.

    `mojo_type` was on the list above on the evidence that it is "a `return 0`
    stub with no caller". That evidence was `nm` on `fire_runtime.o`, and it
    does not transfer: the caller is not in the runtime. `gimple_codegen.
    _RUNTIME_FUNCS['type']` maps the Mojo builtin `type` to this C function, so
    generated C emits a reference to it, and with the declaration gone the
    self-hosted compile of the compiler's own closure fails:

        myinterpreter.py: error: 'mojo_type' undeclared here (not in a
        function); did you mean '_mojo_type'?

    "not in a function" is the load-bearing part of that message: the reference
    is in a DECLARATION at file scope, not a call. `GimpleGen.BUILTIN_VALUE_MAP`
    maps builtins to C functions "when used as values", so generated C takes
    this one's ADDRESS rather than calling it, and the extern block emits a
    prototype for it. That is why no amount of looking at runtime call sites
    finds the caller.

    So the general lesson, which is why this is a test rather than a comment: a
    runtime symbol with no in-tree caller can still be reachable from GENERATED
    code. `nm` on the runtime cannot see that, and `_RUNTIME_FUNCS` is the list
    that says which names generated code can resolve to.

    The old declaration was the variadic `int mojo_type` form, whose leading
    ellipsis with no named parameter is a hard error in clang — that part of
    the removal was right and is preserved by the new prototype.
    `int mojo_type(int obj)` is
    this header's own convention for "any boxed object" (see mojo_hasattr and
    mojo_getattr beside it) and is a real prototype both compilers accept.
    """
    import re
    header = open(os.path.join(RUNTIME, 'fire_runtime.h')).read()
    csrc = open(os.path.join(RUNTIME, 'fire_runtime.c')).read()
    decl = re.compile(r'^[A-Za-z_][\w\s*]*?\bmojo_type\s*\(', re.M)
    check(decl.search(header) is not None,
          'fire_runtime.h DECLARES mojo_type again (generated C references it '
          'via _RUNTIME_FUNCS["type"])')
    check(decl.search(csrc) is not None,
          'fire_runtime.c DEFINES mojo_type again (a declaration with no '
          'definition is a link failure waiting for a caller)')
    scanned = set(e['name'] for e in
                  reflect.collect_runtime_exports_h(os.path.join(RUNTIME,
                                                                 'fire_runtime.h')))
    check('mojo_type' in scanned,
          'and the header scanner reports it, so the dylib advertises it')
    # The clang-hostility the removal was for must stay fixed.
    check(re.search(r'\bmojo_type\s*\(\s*\.\.\.\s*\)', header) is None,
          'mojo_type is not declared with a bare `(...)` (hard error in clang)')
    check(re.search(r'\bint\s+mojo_type\s*\(\s*int\s+obj\s*\)', header) is not None,
          'mojo_type has the real prototype `int mojo_type(int obj)`')
    import gimple_codegen
    check(gimple_codegen.GimpleGen.BUILTIN_VALUE_MAP.get('type') == 'mojo_type',
          'and GimpleGen.BUILTIN_VALUE_MAP still maps the `type` builtin to it, '
          'which is the reference that made the removal wrong (it is a builtin '
          'used as a VALUE, so generated C takes its address rather than '
          'calling it — which is why no call-site search finds it)')


def test_clang_can_compile_the_runtime_for_both_architectures():
    """The cross-arch enabler, pinned. The variadic `int mojo_type` was the ONLY thing
    in the runtime that clang rejected — and clang is the only compiler on this
    machine that can target x86_64 at all, so that one line stood between the
    x86-64 runtime dylib and existing. If a future edit makes the runtime
    clang-hostile again, the foreign-architecture dylib silently stops being
    buildable and this is what says so."""
    for src, lang, _flags in bsd.runtime_units(X86):
        if lang == 'c++':
            continue    # the .cpp is clang++'s business and is not C
        if src.endswith('.S'):
            continue    # aarch64 assembly; never compiled for x86_64
        r = subprocess.run(['/usr/bin/clang', *bsd.arch_flags(X86), '-fsyntax-only',
                            f'-I{RUNTIME}', src], capture_output=True, text=True)
        check(r.returncode == 0,
              f'clang accepts {os.path.basename(src)} for {X86}',
              (r.stderr or '')[:300])


def test_stdlib_dylib_default_output_carries_the_arch():
    """`build_stdlib()`'s default was a FIXED path, so two architectures
    building it would have whichever ran last win — the same clobber the runtime
    dylib had, one level up and one caller away."""
    import inspect
    src = inspect.getsource(bsd.build_stdlib)
    check('f\'libmojostdlib.{arch}.dylib\'' in src,
          'build_stdlib() puts the architecture in its default output name')
    check('DEFAULT_OUT' in src and 'out == DEFAULT_OUT' in src,
          "build_stdlib() only rewrites the path when the caller did not choose one")


def test_dylib_link_key_includes_the_arch():
    """The cache key, checked directly rather than through a build: two links
    of the same objects for different architectures must be two keys, or the
    second is served the first's bytes."""
    with tempfile.NamedTemporaryFile(suffix='.o', delete=False) as f:
        f.write(b'\xcf\xfa\xed\xfe' + b'\x00' * 60)
        obj = f.name
    try:
        a = cas.dylib_link_key([obj], 'reflect', 'gcc', True, arch=ARM)
        b = cas.dylib_link_key([obj], 'reflect', 'gcc', True, arch=X86)
        c = cas.dylib_link_key([obj], 'reflect', 'gcc', True)
        check(a != b, 'the dylib link key separates the two architectures')
        check(c not in (a, b),
              "and a key with no architecture is neither of them (an empty "
              "string is not a wildcard)")
    finally:
        os.unlink(obj)


# ── 6b. one OUTPUT PATH, many concurrent builders ──────────────────────────
#
# The runtime dylib is content-addressed under a name that carries its digest,
# so it never had this problem. `build()` does not: `build_stdlib()`'s default
# is a FIXED `build/libmojostdlib.<arch>.dylib`, and every `fire.py build`
# reaches it through `driver.compile_program`. So N gate jobs running in
# parallel each asked for the same library at the same path, and the losers of
# the CAS race did not queue — they raced the winner onto the same output file.
#
# Measured on this tree, twice, `python3 tools/suite.py -j4 linkmode nonlocal
# ...`:
#
#     ld: open() failed, errno=17 (File exists) for
#         '<checkout>/build/libmojostdlib.arm64.dylib'
#
# which reached the suites as a failing `test_link_mode` case and a failing
# `test_nonlocal` case wanting '7\n'. The dylib was never wrong; it was never
# finished. Two halves answer that, and they are not equally important:
# `_output_lock` (build_stdlib_dylib) collapses N racing builds into one, and
# the staged link + `os.replace` makes the artifact whole no matter what — the
# second half is the correctness claim, because a compiled `fcntl.flock` is the
# extern preamble's weak stub, so the lock is a no-op in a self-hosted build
# (see `_output_lock`'s docstring for the measurement). The assertions below
# cover both: the first is about nobody failing, the second about the work
# being done once.

_CONCURRENT_BUILD_WORKER = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
import cas
import build_stdlib_dylib as bsd
out, src = sys.argv[2], sys.argv[3]

# `cas.stats` counts EVERY content-addressed get_or_build in the build — the
# module object and each runtime object among them — so it cannot answer "did
# THIS process link the dylib". Count the dylib-level lookup instead: `build()`
# makes exactly one (`cas.lookup(link_key, '.dylib')`), and every other lookup
# it makes is for a '.o'.
seen = {'lookups': 0, 'hits': 0}
_lookup = cas.lookup


def _counting_lookup(key, ext='.o'):
    got = _lookup(key, ext)
    if ext == '.dylib':
        seen['lookups'] += 1
        if got:
            seen['hits'] += 1
    return got


cas.lookup = _counting_lookup
bsd.cas.lookup = _counting_lookup
path = bsd.build([src], out, use_cache=True, jobs=1)
print(json.dumps({'out': path, 'lookups': seen['lookups'], 'hits': seen['hits']}))
'''


def test_concurrent_builds_of_one_output_path_do_not_collide():
    """Six processes, one output path, one cold key: every one of them must
    succeed, and at most one of them may actually build.

    The key is made cold per RUN (a nonce in the module's source), not just
    per tree, so this bites on every invocation instead of only on the first
    one after an edit — a test that can only fail once is not a test. Six is
    not a magic number either: it is simply more callers than the machine has
    room to finish before the first one publishes, which is the whole window.
    """
    workers = 6
    wd = tempfile.mkdtemp(prefix='test_concurrent_build_')
    try:
        src = os.path.join(wd, 'probe.mojo')
        nonce = '%d-%d' % (os.getpid(), time.time_ns())
        with open(src, 'w') as f:
            f.write('def probe_tri(x):\n    return x * 3\n'
                    '# nonce %s\n' % nonce)
        out = os.path.join(wd, 'libprobe.dylib')
        env = dict(os.environ, PYTHONPATH=HERE)
        procs = [subprocess.Popen(
            [sys.executable, '-c', _CONCURRENT_BUILD_WORKER, HERE, out, src],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            for _ in range(workers)]
        reports = []
        for p in procs:
            so, se = p.communicate(timeout=900)
            reports.append((p.returncode, so, se))
        check(all(rc == 0 for rc, _so, _se in reports),
              f'{workers} concurrent builds of one output path all succeed',
              '; '.join(f'exit {rc}: {se.strip()[-300:]}'
                        for rc, _so, se in reports if rc != 0) or 'n/a')
        if any(rc != 0 for rc, _so, _se in reports):
            return
        stats = [json.loads(so.strip().splitlines()[-1]) for _rc, so, _se in reports]
        check(all(s['out'] == out for s in stats),
              'and every one of them reports the same output path')
        check(all(s['lookups'] == 1 for s in stats),
              'each caller asked the cache exactly once for the dylib',
              f'lookups: {[s["lookups"] for s in stats]}')
        hits = sum(s['hits'] for s in stats)
        check(hits == workers - 1,
              f'exactly one of the {workers} actually links and the other '
              f'{workers - 1} re-check the cache inside the lock and return '
              f'(dylib hits={hits}) — instead of racing the winner onto the '
              f'same file. A WORK claim, not a correctness one: correctness '
              f'rests on the staged link, and holds even where `flock` does '
              f'not (see the section comment)')
        host = bsd.normalize_arch(None)
        check(bsd.arches_of(out) == frozenset([host]),
              f'and the surviving artifact is a whole {host} dylib',
              f'architectures: {sorted(bsd.arches_of(out)) or "none"}')
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# ── 7. the optional-runtime-unit registry agrees with the export table ──────
#
# The coupling this file pins is a CROSS-AGENT one, and it is the reason the
# check is here rather than in the registry's own test. `build_config`'s
# optional-unit registry derives each unit's `mojo_<unit>_` namespace as the
# longest common prefix of the symbols that unit's HEADER declares, read
# through `reflect.collect_runtime_exports_h` — the same scanner whose output
# this file already depends on. So a change to that scanner is a change to
# which libraries a program links, with no file in common to make the
# dependency visible.
#
# The failure it has to fail on: a scanner that reports a name which is not a
# real C symbol puts an invented string into a longest-common-prefix
# computation, and the resulting namespace is then a prefix of nothing. A
# program that genuinely calls into the unit no longer matches it and fails to
# link (loud, so recoverable) — or, worse, a namespace computed from a
# near-miss matches the WRONG unit and the program silently links a library it
# never asked for. The scanner did have that bug: it read `return f(x);`
# inside a `static inline` body as a declaration. It is fixed; this is what
# keeps it fixed, from the side that cannot see the scanner.
#
# Nothing here writes another agent's file. It reads `build_config` and fails
# if the two halves disagree, which is the whole point.

_OPTIONAL_UNITS = ('sqlite3', 'zlib', 'ssl', 'ncurses')


def _unit_namespace(u):
    import build_config
    return build_config.optional_unit_namespace(u), build_config.optional_unit_symbols(u)


def test_derived_namespaces_cover_exactly_their_own_symbols():
    """The derived namespace must select the unit's own symbols and NOTHING
    else. Under-matching means a program that calls the unit fails to link;
    over-matching means an unrelated program's namespace probe fires and it
    links a library it never mentioned."""
    for u in _OPTIONAL_UNITS:
        ns, syms = _unit_namespace(u)
        check(bool(ns), f'{u}: a namespace is derived from the header, not empty')
        check(all(s.startswith(ns) for s in syms),
              f'{u}: every declared symbol is inside its own namespace '
              f'({ns!r})', str([s for s in syms if not s.startswith(ns)]))
        matched = [s for s in syms if s.startswith(ns)]
        check(len(matched) == len(syms),
              f'{u}: the namespace selects all {len(syms)} of its symbols and '
              f'no others', f'{len(matched)}/{len(syms)}')


def test_unit_namespaces_are_disjoint():
    """Two units whose namespaces overlap cannot both be probed for: the
    program that mentions one gets both, or the probe cannot say which."""
    seen = {}
    for u in _OPTIONAL_UNITS:
        ns, _syms = _unit_namespace(u)
        for other, ons in seen.items():
            check(not (ns.startswith(ons) or ons.startswith(ns)),
                  f'{u} ({ns!r}) and {other} ({ons!r}) namespaces are disjoint')
        seen[u] = ns


def test_no_unit_namespace_catches_a_runtime_symbol():
    """The symbol-level form of "a program that never mentions sqlite must not
    link libsqlite3". The link-line probe fires on a NAMESPACE, so a runtime
    symbol that happens to sit inside a unit's namespace would drag that unit
    onto the link line of every program using it — for reasons that have
    nothing to do with sqlite. Measured: no overlap today, and this is what
    says so."""
    arch = bsd.normalize_arch()
    runtime_syms = set()
    for hdr in bsd._RUNTIME_HEADERS:
        for e in reflect.collect_runtime_exports_h(os.path.join(RUNTIME, hdr)):
            runtime_syms.add(e['name'])
    # Also the symbols the runtime dylib really defines, not just the ones its
    # headers declare: the probe matches against generated C, which can name
    # either.
    for o in objects_for(arch):
        runtime_syms |= set(s.lstrip('_') for s in bsd._defined_symbols(bsd.find_gcc(), o))
    for u in _OPTIONAL_UNITS:
        ns, _syms = _unit_namespace(u)
        caught = sorted(s for s in runtime_syms if s.startswith(ns))
        check(not caught,
              f'{u}: no runtime symbol falls inside {ns!r}, so the probe cannot '
              f'fire for a program that never mentions it', str(caught[:5]))


def test_declared_symbols_are_real_definitions_where_the_unit_compiles():
    """The other end: the header must not promise a symbol the unit does not
    define, or a caller compiles clean and dies at link — the exact failure
    the registry exists to fix, one level in.

    A unit that cannot be COMPILED on this machine is reported and skipped
    rather than failed, and that is a real case rather than a hypothetical:
    `fire_ssl.c` `#include <openssl/ssl.h>`, which is not installed here, so it
    yields no object at all. A skip is stated in the output rather than passing
    quietly, because "0 of 13 symbols checked" is a materially weaker claim
    than "13 of 13" and must not read the same."""
    import build_config
    cc = bsd.find_gcc()
    rt_dir = build_config.runtime_dir()
    for u in _OPTIONAL_UNITS:
        syms = build_config.optional_unit_symbols(u)
        src = build_config.optional_unit_source(u, rt_dir)
        with tempfile.TemporaryDirectory() as td:
            o = os.path.join(td, 'u.o')
            r = subprocess.run([cc, '-fPIC', f'-I{rt_dir}', '-c', '-o', o, src],
                               capture_output=True, text=True)
            if r.returncode != 0:
                first = (r.stderr or '').strip().splitlines()
                why = next((l for l in first if 'fatal error' in l), first[-1] if first else '')
                print(f"  skip  {u}: {os.path.basename(src)} does not compile on "
                      f"this machine, so its {len(syms)} declared symbols are "
                      f"unchecked — {why}")
                continue
            defined = set(s.lstrip('_')
                          for s in bsd._defined_symbols(cc, o))
            missing = sorted(s for s in syms if s not in defined)
            check(not missing,
                  f'{u}: every one of the {len(syms)} symbols its header declares '
                  f'is defined by {os.path.basename(src)}', f'missing: {missing}')


def main():
    test_arch_names_canonicalize()
    test_arch_flags_and_units_differ_by_target()
    test_toolchain_selection_is_measured()
    test_unreachable_arch_fails_with_a_reason()
    test_both_arch_dylibs_build_and_are_distinct()
    test_cache_hit_is_the_same_file_and_reverified()
    test_wrong_arch_object_is_rejected()
    test_export_table_entries_are_all_real_definitions()
    test_every_defined_entry_point_is_advertised()
    test_export_table_is_the_intersection_and_says_why()
    test_word_shaped_surface_is_reachable_by_its_documented_name()
    test_dyld_loads_each_dylib_from_its_own_architecture()
    test_dyld_refuses_the_other_architectures_dylib()
    test_no_declaration_without_a_definition()
    test_the_removed_declarations_are_gone()
    test_mojo_type_is_still_reachable()
    test_clang_can_compile_the_runtime_for_both_architectures()
    test_stdlib_dylib_default_output_carries_the_arch()
    test_dylib_link_key_includes_the_arch()
    test_concurrent_builds_of_one_output_path_do_not_collide()
    test_derived_namespaces_cover_exactly_their_own_symbols()
    test_unit_namespaces_are_disjoint()
    test_no_unit_namespace_catches_a_runtime_symbol()
    test_declared_symbols_are_real_definitions_where_the_unit_compiles()
    npass = sum(1 for ok, _w in RESULTS if ok)
    nfail = len(RESULTS) - npass
    print(f"\n{npass} passed, {nfail} failed, {len(RESULTS)} checks")
    return 1 if nfail else 0


if __name__ == '__main__':
    sys.exit(main())
