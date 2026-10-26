#!/usr/bin/env python3
"""Self-host compile guard.

fire.py must compile *itself* to a fully linked binary with zero GCC errors,
zero internal compiler errors (ICEs), and no undefined symbols. This is the
`./fire.py --jit fire.py` path.

It must then also COMPILE: the produced binary is run over a two-line program
and the generated `.ci` is checked for real output. The second half is not
redundant with the first. A self-hosted compiler whose own analysis helper was
emitted as the `weak` "unavailable in compiled mode" stub links perfectly,
exits 0, and emits a `.ci` containing nothing but that diagnostic — so the
compile+link check above is structurally blind to the whole class, and a green
`selfhost` step coexisted with a `mojoc` that could compile nothing at all.
`run_produced_binary`'s docstring has the real instance.

build_executable() performs the same compile_to_gimple -> gcc -fgimple -> link
sequence the JIT uses and returns True only if every step exited 0.

There are two halves, and they fail for unrelated reasons. The static one
(`closure_coroutines_are_lowerable`) is a parse plus one AST transform over
every module of the self-host closure, and asks whether each generator in it
is a shape the compiled path can lower IN PLACE — because a module of this
closure that lowers its generators into a separate companion translation unit
compiles to an object whose coroutine symbols nothing defines, which is a
LINK failure in the self-host executable and nothing else. It runs first
because it costs milliseconds and the build it guards costs minutes. The
build half is the historical one.
"""
import os
import re
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.abspath(__file__))

# The smallest input that exercises the whole self-hosted compile path: a
# module's worth of statements, a function, a call and a print. Two lines is
# enough and is deliberately the smallest thing that used to crash — see
# `run_produced_binary` below.
TWO_LINE = "x = 1\nprint(x)\n"


def build(td: str) -> str:
    """Self-compile fire.py into `td`, returning the binary path."""
    sys.path.insert(0, REPO)
    import fire
    main_src = os.path.join(REPO, "fire.py")
    src = open(main_src).read()
    out = os.path.join(td, "mojo_selfhost")
    ok = fire.build_executable(main_src, src, output=out)
    if not ok or not os.path.exists(out):
        return ""
    return out


def build_scratch_is_private_and_removed() -> bool:
    """`build_executable`'s intermediates must not be visible outside one build.

    They were named off a bare module basename, so all six of them landed in
    the process's CWD: two builds of two modules sharing a basename
    (`a/gen.py` and `b/gen.py`, or the same `foo.py` in two temp trees) both
    wrote `gen.ci` / `gen.o` / `gen_gen.cpp` / `gen_gen.o` into one shared
    directory and neither took a lock, and `tools/suite.py` runs jobs `-j18`
    out of a common checkout, so that is a wrong-artifact race the gate can
    reach and not only a human. The litter half is deterministic and is what
    this asserts: a `test_py314_full.py` sweep run from the repository root
    left `grammar_snippet_gen.cpp` there, which is how two such files got
    committed before .gitignore covered the other five intermediates.

    Two modules with the SAME basename in two directories, each built with its
    output beside it, from a third directory standing in for the CWD: the
    CWD must be untouched afterwards and each output directory must hold the
    executable and nothing else. The two programs print different values, so a
    crossed scratch shows up as a wrong answer and not only as a stray file.
    """
    sys.path.insert(0, REPO)
    import fire
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as root:
        cwd_dir = os.path.join(root, "cwd")
        outs = []
        for i, want in enumerate(("41", "42")):
            d = os.path.join(root, f"d{i}")
            os.makedirs(d)
            mod = os.path.join(d, "gen.py")
            with open(mod, "w") as f:
                f.write(f"x = 1\nprint(x + {int(want) - 1})\n")
            outs.append((d, os.path.join(d, "out"), mod, want))
        os.makedirs(cwd_dir)
        os.chdir(cwd_dir)
        try:
            for d, out, mod, _want in outs:
                if not fire.build_executable(
                        mod, open(mod).read(), output=out, quiet=True):
                    print(f"  ✗ build_executable({mod}) failed")
                    return False
        finally:
            os.chdir(cwd)
        leftover = sorted(os.listdir(cwd_dir))
        if leftover:
            print(f"  ✗ build_executable left {leftover} in the CWD; its "
                  "intermediates belong beside the artifact, not wherever "
                  "the caller happened to be standing")
            return False
        for d, out, _mod, want in outs:
            beside = sorted(os.listdir(d))
            if beside != ["gen.py", "out"]:
                print(f"  ✗ {d} holds {beside} after the build; expected "
                      "just the source and the executable")
                return False
            r = subprocess.run([out], capture_output=True, text=True,
                               timeout=120)
            if r.returncode != 0 or r.stdout.strip() != want:
                print(f"  ✗ {out} printed {r.stdout.strip()!r} "
                      f"(rc={r.returncode}), want {want!r} — the two "
                      "same-basename builds crossed")
                return False
    return True


# The AST attributes a node's children can hang off. A fixed list, walked
# explicitly, because there is no generic `__dict__` to iterate: every
# attribute name here is a source-level spelling the parser actually produces.
_CHILD_ATTRS = ('body', 'args', 'value', 'func', 'iterable', 'obj', 'left',
                'right', 'operand', 'target', 'elt', 'key', 'results',
                'statements', 'expr', 'handlers', 'finalbody', 'orelse',
                'ifs', 'decorator_list', 'defaults')


def _unlowered_coroutines(stmts: list) -> list:
    """Every generator / `async def` in `stmts`, by bare name.

    An explicit-stack walk, and deliberately NOT a generator: the thing this
    file exists to look for is a generator in the self-host closure, so a
    generator function here would be one more instance of it (see
    `mojo/middle/coro.py::_walk`'s own note for the same conversion, and
    `run_produced_binary`'s for the class). The depth cap is a backstop, not a
    shape anyone expects to hit: the deepest node in a parsed module body is a
    handful of levels down.
    """
    import fire_compiler as N
    found = []
    stack = [(s, 0) for s in reversed(stmts)]
    while stack:
        node, depth = stack.pop()
        if node is None or depth > 80:
            continue
        if isinstance(node, N.FunctionDef) and (node.is_generator
                                                or getattr(node, 'is_async', False)):
            found.append(node.name)
        for attr in _CHILD_ATTRS:
            sub = getattr(node, attr, None)
            if sub is None or isinstance(sub, (str, int, float, bool, bytes)):
                continue
            if isinstance(sub, list):
                for item in reversed(sub):
                    if not isinstance(item, (str, int, float, bool, bytes)):
                        stack.append((item, depth + 1))
            else:
                stack.append((sub, depth + 1))
    return found


def dylib_module_path_refuses_a_generated_cpp() -> bool:
    """`compile_module_to_c` must REFUSE a module whose coroutine definitions
    it cannot link, rather than return a `.c` that references them.

    `closure_coroutines_are_lowerable` above is the invariant that keeps this
    unreachable for the two module lists that ship; this is the other half.
    That check asserts "every generator in this closure lowers in place", and
    an assertion that the exposure is absent is not the same as a refusal when
    it is not: `gen.generated_cpp` is dropped on the floor, the module's `.c`
    keeps the `extern` declarations and the calls, and the object references
    `_mojogen_*` symbols nothing defines. In a dylib that links anyway
    (`-undefined dynamic_lookup`) and every client falls back to source with no
    diagnostic; in an executable it is a link failure. See
    bugs/CODEGEN_dylib_module_path_drops_generated_cpp.md.
    """
    sys.path.insert(0, REPO)
    from build_stdlib_dylib import (_DylibGeneratedCppError,
                                    compile_module_to_c)
    # A DECORATED generator: the A3 stack-switch lowering refuses it outright
    # (`coro._eligible` returns `(False, 'decorated')`), so the C++20 emitter
    # takes it and `generated_cpp` is the only place its definitions exist.
    src = ("def deco(f):\n    return f\n\n"
           "@deco\n"
           "def gen(n):\n"
           "    for i in range(n):\n"
           "        yield i * i\n")
    ok = False
    try:
        compile_module_to_c(src, 'gen_probe.py', 'gen_probe')
    except _DylibGeneratedCppError as e:
        ok = 'gen_probe' in str(e) and 'generated_cpp' in str(e)
    except Exception as e:                       # a different failure entirely
        print(f"  ✗ dylib module path: expected _DylibGeneratedCppError, got "
              f"{type(e).__name__}: {e}")
    # ...and a module with NO generator must still compile: the refusal has to
    # cost nothing on the module lists that ship (measured: 0 such modules).
    plain = "def f(n):\n    return n + 1\n"
    try:
        c = compile_module_to_c(plain, 'plain_probe.py', 'plain_probe')
    except Exception as e:
        ok = False
        print(f"  ✗ dylib module path: a generator-free module stopped "
              f"compiling: {type(e).__name__}: {e}")
    print(f"  dylib module path refuses an unlinkable generated_cpp: {ok}")
    return ok


def closure_coroutines_are_lowerable() -> bool:
    """No module of the self-host closure may contain a generator the
    compiled path cannot lower in place.

    Two backends lower a generator, and only one of them puts the definitions
    where a link can find them:

      * the A3 stack-switch lowering (`mojo/middle/coro.py`, the default)
        rewrites the generator into a plain function plus four tiny
        `_start`/`_resume`/`_value`/`_destroy` trampolines emitted into the
        module's OWN `.c`, so nothing else has to be compiled or linked;
      * the C++20 coroutine emitter puts them in a SEPARATE companion
        translation unit, `GimpleGen.generated_cpp`, which a build path has to
        compile and put on its link line.

    `build_stdlib_dylib.compile_module_to_c` — the per-module compile every
    dylib build, and therefore every self-host build, goes through — returns
    the `.c` and discards `generated_cpp`. So a module in this closure that
    the A3 lowering REFUSES compiles into an object referencing coroutine
    symbols nothing defines, and the self-host executable fails to LINK:

        Undefined symbols for architecture arm64:
          "__mojogen_build_stdlib_dylib__output_lock_start",
          "__mojogen_build_stdlib_dylib__output_lock_resume"

    which is how `mojoc`, `selfhost` and `bootstrap-stage2-cc` went red over
    one `@contextlib.contextmanager` (the A3 eligibility check refuses a
    DECORATED generator outright — `coro._eligible` returns
    `(False, 'decorated')` for it — measured).

    So the invariant to enforce is not "no `yield` anywhere" — this closure has
    generators on purpose and they lower fine — but "every one of them is a
    shape the A3 pass claims". That is exactly what running the pass and
    looking at what is left measures, and it is why this is a parse plus one
    AST transform rather than a grep: a grep cannot tell a generator the
    compiler can lower from one it cannot.

    Deliberately FIRST in `run()`, before the several-minute self-compile: this
    half is a pure static check, so a violation should be reported in
    milliseconds rather than after a build that is going to fail at link.
    """
    sys.path.insert(0, REPO)
    import cas
    import mojo.middle.coro as coro
    import gimple_codegen
    from gimple_codegen import GimpleGen, Parser, py_tokenize

    checked = 0
    offenders = []
    fell_back = []
    for name in cas.selfhost_inputs():
        if not name.endswith('.py'):
            continue
        path = os.path.join(cas.HERE, name)
        if not os.path.isfile(path):
            continue
        checked += 1
        with open(path, encoding='utf-8', errors='replace') as f:
            src = f.read()
        stmts = Parser(py_tokenize(src)).with_filename(path).parse_module()
        lowered, _meta = coro.lower(stmts)
        left = _unlowered_coroutines(lowered)
        if not left:
            continue
        # Left behind by A3 is NECESSARY but not SUFFICIENT for the link
        # failure this guard exists to catch. What actually breaks the link is
        # a generator the C++20 path then CLAIMS: its definitions go into the
        # companion .cpp that `compile_module_to_c` discards. A generator the
        # C++ path also refuses makes the whole module RAISE, and the caller
        # falls back to interpreting it from source -- no .c, no dangling
        # reference, nothing to link.
        #
        # The first version of this check reported the A3 leftover alone and
        # was wrong on exactly that distinction: it named
        # `mojo/middle/infra_infer.py`'s `_each_binding`/`walk`, which
        # `compile_module_to_c` refuses outright --
        #
        #     RuntimeError: cannot compile module: function(s) _each_binding,
        #     walk (generator function(s), contain a `yield`/`yield from`)
        #
        # -- verified by calling `compile_module_to_c` on it, which raises and
        # emits no C at all. So the guard was red on a tree with no link error
        # in it, which is the one thing a guard must never be: it teaches the
        # reader to ignore it.
        #
        # So ask the C++ path directly, per leftover generator, which is the
        # only thing that decides it. Cheap because it runs only on the two or
        # three generators A3 declines, not on all {checked} modules.
        gen = GimpleGen(emit_entry_points=False, module_name=name)
        gen._current_filename = path
        claimed = []
        refused = []
        for _fn in _find_functions(lowered, set(left)):
            try:
                gen._gen_cpp_generator_unit(_fn)
                claimed.append(_fn.name)
            except Exception:
                refused.append(_fn.name)
        if claimed:
            offenders.append((name, claimed))
        if refused:
            fell_back.append((name, refused))
    print(f"  self-host closure: {checked} modules, every generator/async "
          f"lowered in place or its module refused whole: {not offenders}")
    for name, left in offenders:
        print(f"  ✗ {name}: the C++20 coroutine path claims "
              f"{', '.join(sorted(set(left)))}, and that path's definitions "
              f"live in a companion .cpp this build does not link (see "
              f"bugs/CODEGEN_dylib_module_path_drops_generated_cpp.md)")
    for name, left in fell_back:
        print(f"  · {name}: {', '.join(sorted(set(left)))} declined by BOTH "
              f"backends, so the module refuses and is interpreted from "
              f"source — safe, nothing to link")
    return not offenders


def _find_functions(stmts, names: set) -> list:
    """The top-level FunctionDefs in `stmts` whose name is in `names`.

    Deliberately top-level only. The C++ generator unit is translated for a
    MODULE's own top-level generators; a nested `def`'s generator is reached
    through its enclosing function's body, and looking for it here would
    report a name the C++ path never claimed and so never dropped."""
    import fire_compiler as N
    out = []
    for _s in stmts:
        if isinstance(_s, N.FunctionDef) and getattr(_s, 'name', '') in names:
            out.append(_s)
    return out


def run_produced_binary(exe: str, td: str) -> tuple:
    """Compile a two-line program with the freshly built self-hosted compiler
    and report `(exit_status, ci_bytes, unsupported_stub_hits)`.

    This is the end-to-end regression for the class of bug where the
    self-hosted binary *builds and links cleanly* — so `run()` above is
    green — and then cannot compile anything, because one of its own
    analysis helpers was emitted as the `weak` "unavailable in compiled
    mode" stub. A stub returns nothing, so every `for node in <stub>(...)`
    in the compiled compiler iterated zero times and the whole
    self-hosted codegen pass became a no-op. The result was a `.ci` file
    containing nothing but that diagnostic, repeated once per call, with
    exit status 0 — a silent wrong answer that no exit code reports and
    that the compile+link check is structurally blind to.

    The real instance: `mojo/middle/lambdareduce.py`'s `_walk` /
    `_walk_body` were `yield`/`yield from` generators, which do not
    survive self-compilation, so `./mojoc --dump-full` on a TWO-LINE
    program produced a 164-byte `.ci` that was entirely
    `"_walk: unavailable in compiled mode"`. `mojo/middle/coro.py`'s
    identically-named `_walk` had already been converted to an accumulator
    function for the same class of reason (see its docstring); this makes
    the two agree.

    Asserted on the CONTENT, not the exit status, for that reason.
    """
    prog = os.path.join(td, "probe.mojo")
    with open(prog, "w") as f:
        f.write(TWO_LINE)
    r = subprocess.run([exe, "--dump-full", prog], cwd=td,
                       capture_output=True, text=True, timeout=300)
    ci = os.path.join(td, "probe.ci")
    text = ""
    if os.path.exists(ci):
        with open(ci) as f:
            text = f.read()
    return (r.returncode, len(text),
            text.count("unavailable in compiled mode"))


def pinned_prototypes_match_their_definitions() -> bool:
    """Every hand-written C DECLARATION of a self-host function must match it.

    Generated code `#include`s `runtime/fire_runtime.h`, so a declaration in
    it is what gcc checks every call against — and it is reached BEFORE the
    closure's own forward declaration. A function in
    `GimpleGen._NO_OVERLOAD_MANGLE` keeps its bare C name, so those are the
    ones a caller can reach by that name, and a mismatch is a hard error twice
    over: "too many arguments" at every call site, and "conflicting types" at
    the definition.

    Nothing notices when the definition grows a parameter. Measured: giving
    `py_tokenize` a defaulted `filename` changed its C arity from one to two,
    and because the self-host MATERIALIZES a default at every call site it
    emitted `py_tokenize (src, 0)` for all 45 callers in the closure while
    the header still said one — 25 "too many arguments to function
    'py_tokenize'; expected 1, have 2", plus the "conflicting types", and the
    whole self-host build down. A DEFAULT parameter is the sharp case: at
    every call site it looks like nothing changed.

    `GimpleGen._KNOWN_SIGS` is deliberately NOT checked, because its
    parameter list is not a declaration. Its only two readers use it to
    coerce ARGUMENT TYPES at a call site (`emit_infra.py`'s `_emit_call`) and
    to take a RETURN type (`emit_exprs.py`); neither emits a prototype, so a
    stale arity there is a coercion imprecision and not a build break —
    `interpret_and_execute` is one today (2 in the table, 3 defined) and has
    been harmless for the whole table's life.

    Only declarations that RESOLVE to a definition in the closure are
    checked, and this is a parse plus a dict lookup for the same reason the
    coroutine check is: the thing it guards costs minutes to find out the
    hard way.
    """
    sys.path.insert(0, REPO)
    import cas
    import gimple_codegen
    from fire_compiler import Parser, py_tokenize

    # Real definitions: name -> declared parameter count, over the closure.
    defs = {}
    for name in cas.selfhost_inputs():
        if not name.endswith('.py'):
            continue
        path = os.path.join(cas.HERE, name)
        if not os.path.isfile(path):
            continue
        with open(path, encoding='utf-8', errors='replace') as f:
            src = f.read()
        for s in Parser(py_tokenize(src)).with_filename(path).parse_module():
            if getattr(s, 'name', None) and hasattr(s, 'params'):
                defs.setdefault(s.name, len(s.params))

    # Every declaration in the header, as (name -> parameter count).
    table = {}
    hdr = os.path.join(cas.HERE, 'runtime', 'fire_runtime.h')
    pinned = gimple_codegen.GimpleGen._NO_OVERLOAD_MANGLE
    with open(hdr, encoding='utf-8', errors='replace') as f:
        for line in f:
            m = re.match(r'\s*\S+\s*\**\s*(\w+)\s*\(([^)]*)\)\s*;', line)
            if not m:
                continue
            fname, params = m.group(1), m.group(2).strip()
            if fname not in pinned or fname not in defs or params in ('void', ''):
                continue
            table[fname] = len([p for p in params.split(',') if p])

    offenders = []
    for name, declared in table.items():
        if defs[name] != declared:
            offenders.append((name, declared, defs[name]))
    print(f"  self-host closure: {len(defs)} functions, {len(table)} of them "
          f"declared in fire_runtime.h under a pinned C name; every such "
          f"declaration matches its definition: {not offenders}")
    for name, declared, actual in sorted(offenders):
        print(f"  ✗ {name}: fire_runtime.h declares {declared} parameter(s), "
              f"fire_compiler.py defines it with {actual} — generated code "
              f"will not compile against it")
    return not offenders


def run() -> tuple:
    """(static_ok, scratch_ok, build_ok). The static half first and separately,
    so its verdict is a line of its own in the tally rather than a `False`
    that reads like a build failure; the scratch check next because it is the
    only one that does not need the closure."""
    static_ok = closure_coroutines_are_lowerable() and \
        dylib_module_path_refuses_a_generated_cpp() and \
        pinned_prototypes_match_their_definitions()
    scratch_ok = build_scratch_is_private_and_removed()
    if not scratch_ok:
        return static_ok, False, False
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        try:
            exe = build(td)
            if not exe:
                return static_ok, scratch_ok, False
            rc, nbytes, stubs = run_produced_binary(exe, td)
            print(f"  self-hosted compiler on a two-line program: "
                  f"exit={rc} ci_bytes={nbytes} stub_hits={stubs}")
            if rc != 0:
                print("  ✗ the self-hosted binary did not exit 0")
                return static_ok, scratch_ok, False
            if stubs:
                print(f"  ✗ {stubs} of the self-hosted compiler's own "
                      "functions were emitted as 'unavailable in compiled "
                      "mode' stubs — its analysis passes are no-ops")
                return static_ok, scratch_ok, False
            if nbytes < 200:
                print(f"  ✗ the self-hosted binary produced a {nbytes}-byte "
                      ".ci for a two-line program; expected real output")
                return static_ok, scratch_ok, False
            return static_ok, scratch_ok, True
        finally:
            os.chdir(cwd)


def main() -> int:
    try:
        static_ok, scratch_ok, build_ok = run()
    except Exception as e:
        print(f"Results: 0 passed, 3 failed")
        print(f"✗ self-host build raised: {e}")
        return 1
    passed = ((1 if static_ok else 0) + (1 if scratch_ok else 0)
              + (1 if build_ok else 0))
    failed = 3 - passed
    print(f"Results: {passed} passed, {failed} failed")
    if not static_ok:
        print("✗ a module of the self-host closure holds a generator the "
              "compiled path cannot lower in place — its coroutine symbols "
              "would be referenced and never defined")
    if not scratch_ok:
        print("✗ fire.py's build intermediates are not confined to the build "
              "that writes them")
    if not build_ok:
        print("✗ self-host compile/link regressed (GCC error, ICE, undefined "
              "symbol, or the produced binary cannot compile)")
    if not build_ok:
        return 1
    print("✓ every generator in the self-host closure lowers in place, the "
          "self-host compiles + links clean, and the produced binary compiles "
          "a two-line program to real output")
    return 0


if __name__ == "__main__":
    sys.exit(main())
