"""Compile-time evaluation of `comptime` calls, by running real code.

`comptime f(2)` has to produce a value at compile time. This module's answer
is: compile `f` with the SAME backend that will compile the program, and call
it. That is not a shortcut — it is the property that matters. A comptime
value folded by a *different* evaluator than the one generating code is a
 standing invitation to the compiler disagreeing with itself: the constant it
baked in and the code it emitted for the same expression would come from two
implementations, and nothing would notice until the program misbehaved. Here
there is one implementation, and a value that this path cannot produce is a
value that is NOT folded (the binding stays unresolved and the reference
lowers to a clear "does not fold" error) rather than a value that is folded
approximately.

Mechanism: the function is compiled to a formal dylib and called through
ctypes. A dylib rather than an executable because ctypes gets the full 64-bit
return value, where the executable path can only hand back the process exit
status — 8 bits, which would silently truncate every comptime constant above
255.

Two properties this keeps:

  * CAS-cached on (function source, argument values, compiler fingerprint), so
    a repeated build pays the compile once, ever.
  * Memoized per build, so a comptime function that calls another comptime
    function does not re-run the inner one per call site.

Every failure mode — the function does not compile on this path, the
signature is not marshalable, the call traps — returns None, i.e. "does not
fold". Nothing here ever raises into the compiler.
"""

import ctypes
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cas

# One dylib per (source, args) built during this process, so a comptime
# function called from several sites compiles once.
_BUILT: dict = {}
_MEMO: dict = {}


def _key(source: str, fn_name: str, args: tuple) -> str:
    return cas.formal_build_key(
        source, f"<comptime:{fn_name}>", ("--formal-dylib", "--no-prove"),
        criteria="comptime-runner-v1" + repr(args))


def _build_and_call(source: str, fn_name: str, args: tuple):
    """Compile `fn_name` from `source` as a formal dylib and call it.

    Returns the function's result, or None if this path cannot produce one."""
    from formal.build import compile_formal_dylib
    ckey = _key(source, fn_name, args)
    cached = cas.lookup(ckey, ".comptime")
    if cached is not None:
        try:
            with open(cached, "rb") as f:
                payload = f.read().decode()
            ok, _, val = payload.partition("\n")
            return int(val) if ok == "ok" else None
        except (OSError, ValueError):
            pass
    result = _run(source, fn_name, args)
    cas.publish(ckey, ".comptime",
                (f"ok\n{result}" if result is not None
                 else "nofold\n").encode())
    return result


def _compilable_snippet(source: str, fn_name: str) -> str:
    """The source needed to compile `fn_name`: itself plus whatever it calls.

    Compiling the WHOLE module is not an option: the module is the thing whose
    `comptime` binding is currently unresolved, so compiling all of it
    reproduces the very error the runner was called to resolve, and the runner
    gets None. So this slices out the callee and, transitively, the module
    functions it references — which is the minimum that can actually run.
    """
    import re
    from elaborate import extract_fn_source
    wanted = [fn_name]
    seen = set()
    out = []
    while wanted:
        name = wanted.pop(0)
        if name in seen:
            continue
        seen.add(name)
        try:
            fn_src = extract_fn_source(source, name)
        except Exception:
            fn_src = None
        if not fn_src:
            continue
        out.append(fn_src)
        # Every identifier followed by '(' in this function is a call we may
        # need; add the ones the module defines.
        for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", fn_src):
            callee = m.group(1)
            if callee in seen or callee in _KEYWORDS:
                continue
            if re.search(rf"^\s*(def|fn)\s+{re.escape(callee)}\b", source,
                         re.M):
                wanted.append(callee)
    return "\n\n".join(out)


_KEYWORDS = frozenset((
    "if", "elif", "while", "for", "return", "print", "and", "or", "not", "in",
    "int", "str", "len", "range", "min", "max", "abs", "sum", "bool",
    "float", "list", "dict", "set", "tuple", "isinstance", "printf", "malloc",
    "free", "memcpy", "exit",
))


def _run(source: str, fn_name: str, args: tuple):
    from formal.build import compile_formal_dylib, FormalBuildError
    from formal.arm64_codegen import CodegenError
    memkey = (fn_name, args, hash(source))
    if memkey in _MEMO:
        return _MEMO[memkey]
    _MEMO[memkey] = None          # break cycles: a recursive comptime call
    out = None
    tmpdir = tempfile.mkdtemp(prefix="comptime_")
    try:
        src = os.path.join(tmpdir, "comptime_mod.mojo")
        snippet = _compilable_snippet(source, fn_name)
        if not snippet:
            return None
        with open(src, "w") as f:
            f.write(snippet)
        dylib = os.path.join(tmpdir, "comptime_mod.dylib")
        try:
            res = compile_formal_dylib([src], output=dylib, prove=False,
                                       check=False)
        except (FormalBuildError, CodegenError):
            return None
        sym = None
        for e in res.get("exports") or []:
            if e["name"] == fn_name:
                sym = e["symbol"]
        if sym is None:
            return None
        lib = ctypes.CDLL(dylib)
        # dlsym takes the name WITHOUT the leading underscore.
        fn = getattr(lib, sym.lstrip("_"))
        fn.restype = ctypes.c_int64
        fn.argtypes = [ctypes.c_int64] * len(args)
        out = int(fn(*[int(a) for a in args]))
    except Exception:
        out = None            # a comptime call that traps does not fold
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    _MEMO[memkey] = out
    return out


def make_call_hook(source: str):
    """A `call_hook` for mojo/middle/comptime: (name, args) -> int | None.

    `source` is the module being compiled, so only ITS functions are
    compile-time callable here. A callee from another module is left
    unresolved rather than guessed at — this path resolves no imports, and a
    constant invented for an unknown callee would be a fabrication.

    Recursion and mutual recursion are safe: a cycle returns None for the
    in-progress call rather than looping.
    """
    def hook(fn_name: str, argvals: list):
        if not argvals or any(v is None for v in argvals):
            return None
        key = (fn_name, tuple(argvals))
        if key in _BUILT:
            return _BUILT[key]
        # Only a function defined in this module can be run: the source we
        # hold is the module we were given.
        import re as _re
        if not _re.search(rf"^\s*(def|fn)\s+{_re.escape(fn_name)}\b", source,
                          _re.M):
            _BUILT[key] = None
            return None
        val = _build_and_call(source, fn_name, tuple(argvals))
        _BUILT[key] = val
        return val
    return hook
