#!/usr/bin/env python3
"""Monomorphization engine — MODULE_CACHE_DESIGN.md stage 5.

A generic is not one symbol; each instantiation is. When a client uses
`Generic[ConcreteType]`, we compute a content key over (template identity,
concrete type args, comptime params), look it up in the shared CAS, and on a
miss instantiate → compile → publish. Instantiate once, ever: the next client or
build faults the instantiation in. This is the "compile cost = sum of *unique*
instantiations, not TU × instantiations" property — the thing C++ gets wrong.

The substitution here is intentionally simple (textual over a single-`fn`
template) — enough to prove the keying + cache mechanism end to end. The real
engine is AST-driven and hooks the existing whole-program analysis in
`DispatchSolver` (gimple_codegen.py); the *cache contract* it relies on is this
module's `instantiate()`.
"""
import os
import re
import tempfile
import subprocess

import cas
from build_config import find_gcc, find_gxx
from gimple_codegen import GimpleGen
from mojo_compiler import py_tokenize, Parser

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, 'runtime')
_OBJ_FLAGS = ('-fgimple', '-fPIC', f'-I{RUNTIME}')
_CPP_FLAGS = ('-std=c++20', '-fPIC', f'-I{RUNTIME}')

_FN_HEAD = re.compile(r'\b(?:fn|def)\s+(\w+)\s*\[([^\]]*)\]')
# Generalized head: a `fn` or `struct` template with `[type params]`.
_HEAD = re.compile(r'\b(fn|def|struct)\s+(\w+)\s*\[([^\]]*)\]')


def safe_suffix(s: str) -> str:
    """Encode a type-arg string into a valid C identifier fragment: parametric
    args like `List[Int]` contain `[`/`]`/`,`/spaces, which are illegal in a C
    symbol, so map every non-[A-Za-z0-9_] char to `_` (review finding #4)."""
    return re.sub(r'[^A-Za-z0-9_]', '_', s)


def mangle(name: str, type_args: dict) -> str:
    """Stable monomorphized symbol name, e.g. box_id + {T:Int64} -> box_id_Int64.
    Suffixes are sanitized to valid C identifiers."""
    suffix = '_'.join(safe_suffix(str(type_args[k])) for k in sorted(type_args))
    return f"{name}_{suffix}" if suffix else name


def _check_no_value_shadow(src: str, type_params) -> None:
    """Raise if a type parameter is also used as a *binding name* (a `var`/`for`
    target or an assignment target). Textual substitution would then rewrite that
    value identifier to a type name — a silent miscompile (review finding #3). A
    type used as a constructor (`T()`) or in a type position is fine; only bindings
    are unsafe, and bindings shadowing a type parameter are pathological, so we
    fail loudly rather than emit wrong code."""
    for tp in type_params:
        e = re.escape(tp)
        if re.search(rf'\b(?:var|for)\s+{e}\b', src) or \
           re.search(rf'(?m)^\s*{e}\s*=(?!=)', src):
            raise ValueError(
                f"monomorphize: type parameter {tp!r} is used as a value/binding "
                f"name; cannot textually instantiate this template")


def _shadowed_spans(src: str, tp: str) -> list:
    """[start, end) char spans of any NESTED `fn`/`def NAME[...]` inside
    `src` whose OWN bracket-parameter list re-declares `tp` as one of ITS
    parameters — e.g. test_tracing.mojo's real shape: `def test_tracing
    [level, enabled]():` containing `async def test_tracing_add_two_of_them
    [enabled: Bool](...): ...`, itself containing `async def test_tracing_add
    [enabled: Bool, lhs: Int](...): ...` — THREE independent `enabled`
    bindings, only the outermost of which `monomorphize_source`'s caller is
    actually substituting.

    Blindly whole-word-substituting `tp` (e.g. `enabled` -> `True`)
    everywhere in `src`, as `monomorphize_source` did before this method
    existed, would rewrite a NESTED function's own bracket-parameter
    DECLARATION too (`[enabled: Bool, ...]` -> `[True: Bool, ...]`) — not a
    reference, a declaration -- producing flatly invalid Mojo syntax
    (`True` is not a legal parameter name), a real, hand-verified
    corruption risk this method exists to prevent (see bugs/CODEGEN_
    comptime_bracket_parametrized_function_calls_silently_wrong.md's
    test_tracing.mojo analysis, "monomorphizer substitutes level/enabled
    textually across the WHOLE extracted block — including inside test_
    tracing_add's own nested bracket declaration").

    Every span found here must be excluded from `tp`'s OUTER substitution
    (both the declaration AND the rest of that nested function's own body,
    where `tp` refers to the nested, independently-bound parameter, not the
    outer template's) — but is still exposed to substitution for any OTHER
    type param name that ISN'T shadowed there (`monomorphize_source` calls
    this once per type param, independently)."""
    spans = []
    e = re.escape(tp)
    # `async\s+` prefix optional: `async def NAME[...]` (a nested coroutine
    # with its own bracket params — test_tracing.mojo's real shape) is just
    # as much a re-declaration as a plain `def`/`fn`.
    for m in re.finditer(rf'(?m)^([ \t]*)(?:async\s+)?(?:fn|def)\s+\w+\s*\[[^\]]*\b{e}\b[^\]]*\]', src):
        indent = len(m.group(1))
        start = m.start()
        # End of this nested function: the first later line (blank lines
        # don't count) whose own indentation is <= this nested def's own
        # indentation — i.e. a dedent back to the enclosing scope or
        # beyond. No such line means the nested function runs to EOF.
        #
        # Searches the ORIGINAL `src` from `m.end()` via `Pattern.finditer`'s
        # own `pos` argument — NOT `src[m.end():]` (a fresh, sliced string).
        # `(?m)^` matches at an actual line start (position 0, or right
        # after a real `\n`) in whatever string it's matched against; a
        # slice starting mid-line (right after the declaration's own `]`,
        # e.g. still on the same line as `(a: Int, b: Int) -> Int:`) makes
        # ITS OWN start look like a false line-start to the regex engine,
        # which matched immediately there with indent=0 -- collapsing every
        # nested function's protected span down to just its own declaration
        # line and leaving its actual BODY (where the shadowed name is also
        # used, e.g. `test_tracing_add[enabled, 1](a)` inside `test_tracing
        # _add_two_of_them`'s body) still exposed to the outer substitution.
        # A hand-verified real bug caught by directly inspecting this
        # method's own span output against test_tracing.mojo's exact shape.
        end = len(src)
        _line_start_re = re.compile(r'(?m)^([ \t]*)\S')
        for lm in _line_start_re.finditer(src, m.end()):
            if len(lm.group(1)) <= indent:
                end = lm.start()
                break
        spans.append((start, end))
    return spans


def _sub_outside_spans(pattern: str, repl: str, src: str, spans: list) -> str:
    """`re.sub(pattern, repl, src)`, except inside `spans` (each an
    [start, end) char range, e.g. from `_shadowed_spans`) which are copied
    through untouched. `spans` need not be sorted or non-overlapping on
    entry (this method sorts and merges overlaps itself) — `_shadowed_spans`
    can return overlapping ranges for deeply-nested shadowing chains."""
    if not spans:
        return re.sub(pattern, repl, src)
    merged = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    out = []
    pos = 0
    for s, e in merged:
        out.append(re.sub(pattern, repl, src[pos:s]))
        out.append(src[s:e])   # untouched: a nested, shadowed scope
        pos = e
    out.append(re.sub(pattern, repl, src[pos:]))
    return ''.join(out)


def monomorphize_source(template_src: str, type_args: dict) -> tuple:
    """Specialize a single `fn` OR `struct` generic template for concrete type
    args. Returns (mangled_name, concrete_source). Textual substitution: drop the
    `[params]` block, rename the definition, and replace each type-param
    identifier with its concrete type as a whole word — except inside a
    NESTED function that re-declares (shadows) that same type-param name as
    its own independent bracket parameter (see `_shadowed_spans`)."""
    m = _HEAD.search(template_src)
    if not m:
        raise ValueError("monomorphize: no generic `fn`/`struct name[...]` found")
    kind, name = m.group(1), m.group(2)
    mangled = mangle(name, type_args)

    # Guard against substituting a type param that's also used as a binding name
    # (silent miscompile otherwise — review finding #3).
    _check_no_value_shadow(template_src, list(type_args.keys()))

    # Drop the [type-params] block and rename the definition (fn or struct).
    src = template_src[:m.start()] + f"{kind} {mangled}" + template_src[m.end():]
    # Substitute each type parameter with its concrete type (whole-word),
    # skipping any nested scope that shadows this specific name.
    for tp, concrete in type_args.items():
        spans = _shadowed_spans(src, tp)
        src = _sub_outside_spans(rf'\b{re.escape(tp)}\b', str(concrete), src, spans)
    return mangled, src


def compile_fn(fn_src: str, gcc: str = None) -> tuple:
    """Compile a concrete (non-generic) single-`fn` source to a CAS-cached object,
    keyed by its content. Used for overload instances (slice 4). Returns
    (object_path, hit)."""
    gcc = gcc or find_gcc()
    m = re.search(r'\b(?:fn|def)\s+(\w+)', fn_src)
    name = m.group(1) if m else 'fn'
    key = cas.instantiation_key(fn_src, {'__fn__': name}, None, gcc, _OBJ_FLAGS)

    def build():
        gen = GimpleGen(emit_entry_points=False, module_name=name)
        c = gen.gen_module(Parser(py_tokenize(fn_src)).parse_module())
        wd = tempfile.mkdtemp(prefix='mojo_ovl_')
        cf, of = os.path.join(wd, name + '.c'), os.path.join(wd, name + '.o')
        with open(cf, 'w') as f:
            f.write(c)
        subprocess.run([gcc, *_OBJ_FLAGS, '-c', '-o', of, cf], check=True)
        with open(of, 'rb') as f:
            return f.read()

    return cas.get_or_build(key, '.o', build)


_IN_PROGRESS: set = set()
# Current nesting depth of instantiation builds (for the optional MOJO_ELAB_LOG
# diagnostic). Deep-but-finite concrete cascades are fine; the thing that must
# never happen is instantiating with non-concrete (symbolic) type args, which is
# guarded at the call site (GimpleGen._elaborate_generic_call / _is_concrete_type_arg).
ELAB_DEPTH: list = [0]


def instantiate(template_src: str, type_args: dict, comptime_args: dict = None,
                gcc: str = None) -> tuple:
    """Instantiate template_src for type_args, via the shared CAS.
    Returns (mangled_name, object_path_or_None, hit, cpp_object_path_or_None)
    — both object results are PATHS into the CAS (cas.get_or_build's own
    return convention: an artifact path, not its bytes), matching the
    existing `object_path_or_None` contract exactly.

    `cpp_object_path` is non-None exactly when the instantiated template
    contains a nested `async def`/generator this codegen compiles to a real
    C++20 coroutine translation unit (GimpleGen.generated_cpp, populated by
    the SAME gen_module() call that produces the ordinary GIMPLE `.c` side —
    see gen_module's own preamble-assembly step) — test_locks.mojo's/test_
    tracing.mojo's own shape (`test_tracing[level, enabled]()` containing
    `async def test_tracing_add[...](...): ...`). Compiled with g++ (C++20)
    into its own object, CAS-cached under the SAME instantiation key as the
    `.c` side but a distinct `.cpp.o` extension (cas.get_or_build's `(key,
    ext)` pair already supports this — no new storage layer needed, just a
    second extension under the identical key). The caller must link this
    object in (in addition to the `.o`) via a C++-aware link driver
    (g++, or gcc + `-lstdc++`) — see gimple_codegen.py's `_link_needs_cxx`
    and driver.py's own handling of it.

    Before this, `build()` only ever asked for `gen`'s ordinary `.c` output
    — `gen.generated_cpp` was silently discarded entirely, so ANY generic
    whose body needed a coroutine translation unit either corrupted (via
    monomorphize_source's blind textual substitution touching a nested,
    shadowed bracket-parameter declaration — see monomorphize_source's own
    `_shadowed_spans` handling) or produced a `.c` that referenced an
    async-unit symbol nothing ever defined (an undefined-symbol link
    failure, or — before gimple_codegen.py's own upfront nested-async
    detection was added — a much worse SILENT placeholder-`0` miscompile;
    see bugs/CODEGEN_comptime_bracket_parametrized_function_calls_
    silently_wrong.md's test_tracing.mojo analysis)."""
    gcc = gcc or find_gcc()
    mangled, concrete = monomorphize_source(template_src, type_args)
    key = cas.instantiation_key(template_src, type_args, comptime_args, gcc, _OBJ_FLAGS)

    _log = os.environ.get('MOJO_ELAB_LOG')
    if _log:
        with open(_log, 'a') as _f:
            _re_entrant = ' RE-ENTRANT' if key in _IN_PROGRESS else ''
            _f.write(f"{ELAB_DEPTH[0]:3d} instantiate {mangled}  targs={type_args}{_re_entrant}\n")

    # Recursive generic (e.g. a self-referential instantiation, or a mutual cycle
    # A→B→A): the symbol is already being built by an outer frame. Return it without
    # rebuilding to break the cycle — the outer frame contributes the .o; this
    # reference just needs the (already-known) mangled symbol. Its signature is
    # recovered from the concrete source by the caller, not from the object.
    if key in _IN_PROGRESS:
        return mangled, None, True, None

    # Smuggled out of build() (cas.get_or_build's contract is a single
    # bytes-returning build_fn keyed by one (key, ext) pair — the cpp side,
    # when present, is published separately below via a second, explicit
    # cas.publish/lookup pair under the SAME key but a different ext,
    # rather than teaching cas.get_or_build a multi-artifact return shape
    # for this one caller).
    _cpp_bytes: dict = {}

    def build():
        # The instantiated function is already uniquely named (mangled); don't
        # overload-suffix it, or the caller's reference (info['symbol'] = mangled)
        # won't match the definition.
        wd = tempfile.mkdtemp(prefix='mojo_inst_')
        # Several of gen_module's own passes (notably the "Async closures/
        # functions NESTED INSIDE A TOP-LEVEL FUNCTION" pass — a nested
        # `async def` with its OWN comptime bracket params, test_tracing.
        # mojo's real `test_tracing_add[enabled, lhs](...)`/`test_tracing_
        # add_two_of_them[enabled](...)` shape) are gated on `self.
        # _current_filename` being a REAL, readable path (`if _gsrc:` after
        # `open(self._current_filename).read()`) — they re-read the source
        # textually (for a bracket-parameter type-annotation scan
        # `monomorphize_source` doesn't preserve in the AST). Previously
        # never set here at all, so EVERY such pass silently no-opped for
        # an elaborated fragment specifically (never for an ordinary
        # top-level module compile, which always sets this) — a nested
        # async-with-comptime-params inside a generic fell all the way
        # through to gen_module's own final "still unsupported" whole-
        # module refusal, honest but wrong (the mechanism to actually
        # compile it already existed, it just never saw this source at
        # all). Write the CONCRETE (already-monomorphized) source to a
        # real file and point `_current_filename` at it — the exact same
        # convention module_may_have_supported_generator/build_executable
        # use for the top-level module's own file.
        mfile = os.path.join(wd, mangled + '.mojo')
        with open(mfile, 'w') as f:
            f.write(concrete)
        gen = GimpleGen(emit_entry_points=False, module_name=mangled, no_mangle={mangled})
        gen._current_filename = mfile
        c = gen.gen_module(Parser(py_tokenize(concrete)).with_filename(mfile).parse_module())
        cfile, ofile = os.path.join(wd, mangled + '.c'), os.path.join(wd, mangled + '.o')
        with open(cfile, 'w') as f:
            f.write(c)
        subprocess.run([gcc, *_OBJ_FLAGS, '-c', '-o', ofile, cfile], check=True)
        if gen.generated_cpp:
            gxx = find_gxx()
            cppfile = os.path.join(wd, mangled + '_async.cpp')
            cppofile = os.path.join(wd, mangled + '_async.o')
            with open(cppfile, 'w') as f:
                f.write(gen.generated_cpp)
            subprocess.run([gxx, *_CPP_FLAGS, '-c', '-o', cppofile, cppfile], check=True)
            with open(cppofile, 'rb') as f:
                _cpp_bytes['data'] = f.read()
        with open(ofile, 'rb') as f:
            return f.read()

    _IN_PROGRESS.add(key)
    ELAB_DEPTH[0] += 1
    try:
        obj, hit = cas.get_or_build(key, '.o', build)
        if not hit and 'data' in _cpp_bytes:
            # First build of this instantiation, and it genuinely needed a
            # coroutine unit: publish it now (build() already ran above).
            cas.publish(key, '.cpp.o', _cpp_bytes['data'])
        # A PATH (cas.lookup's own return convention), not bytes — matches
        # `obj` above exactly, so callers can treat both uniformly (e.g.
        # gimple_codegen.py's `_link_objects`, ultimately passed straight
        # to a linker command line / cas.file_digest(path), never read as
        # in-memory bytes anywhere on that path).
        cpp_obj = cas.lookup(key, '.cpp.o')
    finally:
        ELAB_DEPTH[0] -= 1
        _IN_PROGRESS.discard(key)
    return mangled, obj, hit, cpp_obj
