import os
import platform


def _which(name):
    """`shutil.which`, by hand, and the reason is the self-hosted binary.

    `shutil` is not one of the modules compiled into it, and a call on an
    uncompiled module RAISES (`emit_methods`' module-marker rule), so the
    `_which('gcc-15')` below took `mojoc` down on its first `find_gcc()`
    with `NotImplementedError: shutil.which: module 'shutil' is not compiled
    into this binary` — after the Python path had been answering it with a bare
    0, which is not `which`'s answer and only worked because the MacPorts
    fallback below it happens to be the right compiler on the machine that
    measured it.

    `os` IS compiled, so the PATH walk is spelled here: an empty entry and `.`
    both mean the current directory, per `shutil`'s own POSIX behaviour, and a
    non-executable file is not a match.
    """
    for d in (os.environ.get('PATH', '') or os.defpath).split(os.pathsep):
        if not d:
            d = '.'
        candidate = os.path.join(d, name)
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def find_gcc() -> str:
    """Find gcc binary: prefer gcc-15 in PATH, fallback to MacPorts gcc-mp-15, then gcc.

    The `-> str` annotations on find_gcc/find_gxx are load-bearing for the
    SELF-HOSTED build, not documentation.  build_config is compiled into
    `mojoc`, and a compiler-module function reachable through
    mojo/backend_gimple/module_gen.py's imported-symbol extern block is
    declared TWICE from two independent inferences: `module_loader`'s text
    scan, which defaults an unannotated `def` to `int64_t`, and the function
    body's own returns, which say `char *`.  When both land in one translation
    unit the hard gcc error is

        conflicting types for 'build_config_find_gcc'; have 'char *(void)'

    and `make mojoc` fails.  Measured, and it is what stopped this registry the
    first time round -- that bug's doc is deleted with its fix, and what it
    was filed against is the error above.  The
    annotation makes the scanner agree with the body.  Anything added to this
    module needs one for the same reason.
    """
    if _which('gcc-15'):
        return 'gcc-15'
    if platform.system() == 'Darwin':
        gcc_mp15 = '/opt/local/bin/gcc-mp-15'
        if os.path.exists(gcc_mp15):
            return gcc_mp15
    return 'gcc'

def find_gxx() -> str:
    """Find g++ binary: prefer g++-15 in PATH, fallback to MacPorts g++-mp-15, then g++.

    Mirrors find_gcc()'s exact fallback chain. Used as the final LINK driver
    (not for ordinary .c compiles, which stay on gcc) whenever a build
    includes at least one C++-derived object file — e.g. the coroutine-based
    generator codegen path (see BACKLOG-CODEGEN.md / the generator-support
    milestones), which emits real C++20 `co_yield` code compiled by g++ and
    linked into an otherwise all-C -fgimple program."""
    if _which('g++-15'):
        return 'g++-15'
    if platform.system() == 'Darwin':
        gxx_mp15 = '/opt/local/bin/g++-mp-15'
        if os.path.exists(gxx_mp15):
            return gxx_mp15
    return 'g++'

# Delegate to module_loader for stdlib path
from module_loader import STDLIB_PATH, TEST_PATH

# ---------------------------------------------------------------------------
# Optional runtime units
# ---------------------------------------------------------------------------
# runtime/ holds six C translation units.  Only fire_runtime.c is in a build
# path.  The other four whose headers are `#include`d UNCONDITIONALLY into
# every generated translation unit (mojo/backend_gimple/module_gen.py) and
# whose signatures all sit in gimple_codegen._KNOWN_SIGS had no build rule at
# all, so a program calling any of them compiled clean and died at link with
# `Undefined symbols ... _mojo_sqlite3_open`.  This table is that missing
# build rule, and `referenced_optional_runtime_units` is the probe the link
# pipelines use.  (That doc is deleted with its fix.)
#
# fire_python.c is deliberately NOT here.  Its entire surface is behind
# `#if USE_PYTHON 0` stubs, so linking it would trade a loud link error for a
# silent NULL from every mojo_python_* call -- and its header is not
# `#include`d either, so the failure stays loud.  That is the better default.
#
# `ssl` IS here even though OpenSSL is not installed on every machine that has
# this compiler, and that is a decision rather than an oversight.  A registry
# row is a build RULE, not a claim that the dependency is present: fire_ssl.h
# is `#include`d unconditionally, so a program calling mojo_ssl_new has a
# prototype whether or not we can satisfy it.  With the row, such a program
# gets `optional runtime compile failed (ssl, .../fire_ssl.c): fatal error:
# openssl/ssl.h: No such file` -- which names the unit, the file and the
# missing dependency, and tells the user what to install.  Without it, the same
# program gets `Undefined symbols ... _mojo_ssl_new`, which names none of those
# and points at the wrong layer.  A registry that silently dropped a unit whose
# system library happens to be missing would also break that unit for the
# machines that DO have it.  So the row stays, the diagnostic is actionable
# (hence the dev-package column), and the failure stays loud.
#
# THE SHAPE OF THIS TABLE IS LOAD-BEARING, not stylistic.  build_config is
# compiled by the self-hosted backend into `mojoc`, and there a NESTED
# container is not usable: reading an element of a nested list is lowered to
# `mojo_list_get_int` regardless of the element's real type, so a registry of
# `(unit, source, header, ['-lssl', '-lcrypto'])` silently compares a string
# element against an int and returns a garbage link flag.  Measured, not
# assumed.  Hence: a flat tuple of flat tuples of flat STRINGS, every field
# unpacked with an index, and the link flags kept as one space-separated
# string rather than a list.
# Every row has SEVEN fields, and _unit_field indexes positionally, so a
# short row is an IndexError rather than a default. That is deliberate: the
# uniform-tuple shape is what keeps this table readable by the self-hosted
# backend (see the note above), and a helper that silently returned '' for a
# missing field would hide a genuinely short row instead of failing on it.
# Fields 5 and 6 are empty for every unit that is plain C built by the
# build-wide compiler.
_OPTIONAL_RUNTIME_UNITS = (
    # unit  source         header            link flags         dev pkg      cc     cc flags
    ('sqlite3', 'fire_sqlite3.c', 'fire_sqlite3.h', '-lsqlite3', 'libsqlite3-dev', '', ''),
    ('zlib', 'fire_zlib.c', 'fire_zlib.h', '-lz', 'zlib1g-dev', '', ''),
    ('ssl', 'fire_ssl.c', 'fire_ssl.h', '-lssl -lcrypto', 'libssl-dev', '', ''),
    ('ncurses', 'fire_ncurses.c', 'fire_ncurses.h', '-lncurses', 'libncurses-dev', '', ''),
    # GPU offload. The odd one out in this table on purpose: it is
    # Objective-C, because the generated `.ci` is compiled `gcc -fgimple -x c`
    # and gimple has no `@autoreleasepool` / `id<MTLLibrary>` -- so this unit
    # is the ONLY place Metal is touched, reached from generated C through the
    # plain C API in its header. Hence the per-unit compiler and flags
    # (fields 5 and 6): the portable gcc-mp-15 this build uses everywhere else
    # rejects the file outright ("expected identifier or '(' before '^' token"
    # from NSObjCRuntime.h, and no -fobjc-arc at all), and ARC is load-bearing
    # rather than stylistic -- the device/library/queue are file-scope
    # statics, and without ARC they are autoreleased and can be freed under
    # the library while a later dispatch still uses them.
    #
    # Linking Foundation+Metal only when the generated C actually references
    # mojo_metal_* is the same rule as every row above: a program with no
    # kernels must not acquire a GPU-framework dependency.
    #
    # The `mojo_metal_` PREFIX is load-bearing, not a naming preference.
    # `referenced_optional_runtime_units` probes the generated C for the unit's
    # namespace, and this registry's own source is inlined into every module
    # that imports build_config -- so a namespace of `fire_metal_` matches this
    # table's own `'fire_metal.m'` / `'fire_metal.h'` filename strings as a
    # prefix, and every such module then drags Metal onto its link line.
    # Measured, not predicted: test_sqlite3_runtime.py's "compiling a module
    # that imports build_config pulls in NO optional unit (their symbols are in
    # the generated C only as string data)" check fails on it. `mojo_<lib>_` is
    # the convention every other row already follows, so the C API follows it.
    ('metal', 'fire_metal.m', 'fire_metal.h',
     '-framework Foundation -framework Metal', '', 'clang', '-fobjc-arc'),
)


def runtime_dir() -> str:
    """This checkout's runtime/ directory.

    module_loader.TEST_PATH is its own `os.path.join(HERE, 'runtime')` --
    literally the runtime directory, and already the established way the rest
    of the tree locates it (fire.py and driver.py each recompute the same
    path from their own `__file__`).  Reading it beats a `__file__` here: a
    module compiled into the self-hosted binary has no `__file__` attribute,
    and a module-level `__file__` read is how that backend dies with
    `AttributeError: __file__` (mojo/backend_gimple/emit_infra.py).  A
    function, not a module global, for the same reason.

    Every function below also accepts an explicit `rt_dir`, which is what
    the two link pipelines pass -- they each already resolved it for the
    runtime compile they are doing anyway."""
    return TEST_PATH


def _unit_field(unit: str, index: int) -> str:
    """Field `index` of `unit`'s registry row, or '' if there is no such
    unit.  Index loop with `_as_str`-equivalent guards rather than a dict of
    unit->row: a module-level dict is opaque int64_t to the self-hosted
    backend, so `TABLE[unit]` there is a NULL dereference."""
    i = 0
    while i < len(_OPTIONAL_RUNTIME_UNITS):
        row = _OPTIONAL_RUNTIME_UNITS[i]
        if row[0] == unit:
            return row[index]
        i = i + 1
    return ''


def optional_unit_names() -> list:
    """Every optional runtime unit this build knows how to link, in registry
    order.  The list `referenced_optional_runtime_units` draws from."""
    out = []
    i = 0
    while i < len(_OPTIONAL_RUNTIME_UNITS):
        out.append(_OPTIONAL_RUNTIME_UNITS[i][0])
        i = i + 1
    return out


def optional_unit_source(unit: str, rt_dir: str = None) -> str:
    """Absolute path of `unit`'s C translation unit."""
    if not rt_dir:
        rt_dir = runtime_dir()
    return os.path.join(rt_dir, _unit_field(unit, 1))


def optional_unit_header(unit: str, rt_dir: str = None) -> str:
    """Absolute path of `unit`'s header -- the authority on what the unit
    actually exports."""
    if not rt_dir:
        rt_dir = runtime_dir()
    return os.path.join(rt_dir, _unit_field(unit, 2))


def optional_unit_libs(unit: str) -> list:
    """`unit`'s link flags, as a list.  Split from the registry row here, once,
    so no caller has to know the row stores them space-separated."""
    out = []
    spec = _unit_field(unit, 3)
    if spec:
        for flag in spec.split(' '):
            if flag:
                out.append(flag)
    return out


def optional_unit_cc(unit: str) -> str:
    """The compiler to build `unit` with, or '' for the build's default.

    Metal is Objective-C and the default gcc cannot parse it, so this is not
    a hypothetical knob -- see the registry row. Returning '' rather than a
    default name keeps the callers free of unit-specific conditionals."""
    return _unit_field(unit, 5)


def optional_unit_cc_flags(unit: str) -> list:
    """Extra compile flags for `unit`, as a list. Split from the registry row
    here, once, so no caller has to know the row stores them space-separated."""
    out = []
    spec = _unit_field(unit, 6)
    if spec:
        for flag in spec.split(' '):
            if flag:
                out.append(flag)
    return out


def optional_unit_dev_package(unit: str) -> str:
    """The system development package that provides `unit`'s headers, named in
    the diagnostic when the unit's own compile fails.  Empty if unknown."""
    return _unit_field(unit, 4)


def optional_unit_symbols(unit: str, rt_dir: str = None) -> list:
    """Every public symbol `unit`'s own header declares, as a flat list of
    names.

    DERIVED, never hand-copied: read out of the header via
    `reflect.collect_runtime_exports_h` -- the same scanner build_stdlib_dylib
    uses to build the stdlib dylib's reflection table, so a symbol added to
    fire_sqlite3.h is in this list the moment it is declared, with no second
    edit here to fall out of date.  (That scanner is also what `formal/`
    consumes for the same reason; forking it would give the three a
    different answer to the same question.)"""
    import reflect
    out = []
    for entry in reflect.collect_runtime_exports_h(optional_unit_header(unit, rt_dir)):
        out.append(entry['name'])
    return out


def optional_unit_namespace(unit: str, rt_dir: str = None) -> str:
    """The `mojo_<unit>_` namespace, as the longest common prefix of the
    symbols the unit's own header declares.  Deriving it from the exports
    rather than spelling it out is the point: a hand-written prefix is a
    hand-maintained fact about a header, and that is the rot this table
    removes."""
    syms = optional_unit_symbols(unit, rt_dir)
    if not syms:
        return ''
    ns = syms[0]
    i = 1
    while i < len(syms):
        other = syms[i]
        n = 0
        while n < len(ns) and n < len(other) and ns[n] == other[n]:
            n = n + 1
        ns = ns[:n]
        i = i + 1
    return ns


def _strip_c_literals_and_comments(c_code: str) -> str:
    """`c_code` with every string literal, character literal and comment
    blanked out (replaced by a space, so offsets and line structure survive).

    `_called_in_c_code` decides "is this a call, or just a mention?" by
    checking that the name is not preceded by a quote. That works when a
    string literal mentions the name directly -- `_KNOWN_SIGS['x']` becomes
    `"x"` in the output, quote adjacent to name -- but it FAILS when the
    literal CONTAINS a call-shaped fragment, because then the quote is at the
    start of the literal and the character immediately before the name is an
    ordinary space:

        static char * _slit_91 = "  _mg_have = (int64_t) mojo_metal_init(src);";

    The name is followed by `(` and preceded by a space, so the probe reads it
    as a real call. This is not hypothetical: it is what the compiler's own
    closure produces, because a code generator that emits C from Python string
    templates necessarily has those templates in its own source, and compiling
    the compiler inlines them as `_slit_N` initializers. Measured -- the
    "compiling a module that imports build_config pulls in NO optional unit"
    check in test_sqlite3_runtime.py failed on exactly this.

    Removing literals cannot lose a real reference: a symbol that is called is
    called from CODE, so it is never inside a literal. This only ever removes
    false positives, which is the direction the probe already prefers ("loud
    beats quiet"). Comments go for the same reason and by the same argument.

    A full C lexer is more than this needs. The only constructs that can
    hide text from the probe are literals and comments, the scan only has to
    be correct about where they END, and the file is generated -- unbalanced
    quotes are not a state this has to survive.
    """
    out = []
    i = 0
    n = len(c_code)
    while i < n:
        c = c_code[i]
        # Line comment, or a '/' that cannot be a comment (kept verbatim so
        # a stray slash in an expression does not swallow the rest of it).
        if c == '/' and i + 1 < n and c_code[i + 1] == '/':
            j = c_code.find('\n', i)
            if j < 0:
                j = n
            out.append(' ')
            i = j
            continue
        if c == '/' and i + 1 < n and c_code[i + 1] == '*':
            j = c_code.find('*/', i + 2)
            j = n if j < 0 else j + 2
            out.append(' ')
            i = j
            continue
        if c in ('"', "'"):
            quote = c
            j = i + 1
            while j < n:
                if c_code[j] == '\\':
                    j += 2
                    continue
                if c_code[j] == quote:
                    j += 1
                    break
                j += 1
            out.append(' ')
            i = j
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def _called_in_c_code(c_code: str, sym: str) -> bool:
    """True if `c_code` contains a CALL (or a prototype) of `sym`, as opposed
    to merely mentioning the name.

    A bare substring test is not good enough, and the tree proves it.
    `gimple_codegen._KNOWN_SIGS` carries all 59 optional-unit signatures as
    STRING KEYS, so any build that compiles the compiler itself -- i.e. every
    `make mojoc` -- has all four units' symbol names sitting in the generated C
    as string-literal data.  A substring probe therefore matches ssl, sqlite,
    zlib and ncurses for a program that calls none of them, and the cost is
    that the project's own compiler cannot be built without four system
    development packages installed.  (Measured: `fire.py build fire.py` on a
    machine with no OpenSSL tried to compile fire_ssl.c, because
    `_KNOWN_SIGS['mojo_ssl_context_new']` is a string in the output.)

    So the test is call-SHAPED: the name must be followed by `(`, allowing the
    whitespace this codegen puts before the argument list, and must not be
    preceded by a quote -- which is what distinguishes a call from the
    `"mojo_ssl_context_new"` dict key above.  A comment or a docstring cannot
    false-positive either, because a docstring reaches the generated C as a
    `_slit_N = "..."` initializer, i.e. quoted.

    The failure direction is deliberate.  A name that is used but NOT in this
    call shape -- taken by address with no prototype, say -- is MISSED, and a
    missed unit is a loud `Undefined symbols` at link.  A name that is
    mentioned in passing is not matched, and a spurious unit is a needless
    build dependency.  Loud beats quiet, so the imprecision is on the quiet
    side.  The fully robust answer is for the codegen to record the symbols it
    actually emitted calls to, which is a change in gimple_codegen, not here.
    """
    i = 0
    n = len(c_code)
    ln = len(sym)
    while i < n:
        i = c_code.find(sym, i)
        if i < 0:
            return False
        prev = c_code[i - 1] if i > 0 else ''
        k = i + ln
        while k < n and c_code[k] in ' \t':
            k = k + 1
        if k < n and c_code[k] == '(' and prev != '"' and prev != "'":
            return True
        i = i + ln
    return False


def referenced_optional_runtime_units(c_code: str, rt_dir: str = None) -> list:
    """Names of the optional runtime units that `c_code` actually CALLS.

    This is the same probe `fire.py`/`driver.py` already apply three times
    each -- for the generator .cpp, for fire_async_runtime.cpp and for the
    coroutine runtime -- extended to the units that had no rule at all: does
    the generated C call into this runtime's namespace?  If yes, compile the
    unit and link it with its libraries; if no, the program never mentions
    sqlite and must not drag libsqlite3 onto its link line.

    The per-symbol test is `_called_in_c_code`, and it is the whole point of
    this function rather than a refinement: see its docstring for why a bare
    "does the namespace appear" test matches every unit in the tree.
    """
    # String literals and comments are REMOVED before probing. See
    # _strip_c_literals_and_comments for why that is necessary rather than
    # merely tidier: a call-shaped fragment inside a string literal is
    # invisible to the "is it preceded by a quote" test, because the quote is
    # at the START of the literal and can be hundreds of characters away from
    # the name.
    c_code = _strip_c_literals_and_comments(c_code)
    hits = []
    for unit in optional_unit_names():
        ns = optional_unit_namespace(unit, rt_dir)
        if not ns or ns not in c_code:
            continue
        for sym in optional_unit_symbols(unit, rt_dir):
            if _called_in_c_code(c_code, sym):
                hits.append(unit)
                break
    return hits


def optional_unit_compile_failed(unit: str, source: str, stderr: str) -> str:
    """The one diagnostic both link pipelines print when an optional unit does
    not compile.

    It lives here, next to the registry, rather than being written twice in
    fire.py and driver.py because the two DID drift once: driver.py raised a
    bare CalledProcessError (subprocess.run(check=True)) on the path
    `fire.py build` normally takes, while fire.py named the unit.  An exception
    is loud and exits non-zero, so neither was silent -- but a traceback in
    place of the compiler's own message, on the common path, is a worse
    diagnostic than the one sitting three files away.  One definition, both
    callers.

    The overwhelmingly common cause is a system development package that is
    not installed -- fire_ssl.c does `#include <openssl/ssl.h>`, so on a
    machine without OpenSSL a program referencing mojo_ssl_* cannot build.  The
    dev package is named for that reason: the error the user can act on is
    "install this", and the registry already knows which one."""
    hint = optional_unit_dev_package(unit)
    lines = [f"optional runtime compile failed ({unit}, {source}):"]
    lines.append(stderr.strip())
    if hint:
        lines.append(f"  this unit needs {unit}'s system headers; install the "
                     f"development package ({hint}) and rebuild")
    return '\n'.join(lines)


__all__ = ['find_gcc', 'find_gxx', 'STDLIB_PATH', 'runtime_dir',
           'optional_unit_names', 'optional_unit_source',
           'optional_unit_cc', 'optional_unit_cc_flags',
           'optional_unit_header', 'optional_unit_libs',
           'optional_unit_dev_package', 'optional_unit_symbols',
           'optional_unit_namespace',
           'referenced_optional_runtime_units',
           'optional_unit_compile_failed']
