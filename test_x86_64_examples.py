#!/usr/bin/env python3
"""Run every formal/examples/*.mojo through BOTH codegens and compare the answer
with each other AND with CPython running the same text.

The arm64 formal path is the reference between the two backends: it is the
mature one (proofs typecheck against lib/ProofLib.lean for it), so agreement
between them is much stronger evidence than either being self-consistent. Both
are built from the same fire_compiler AST and the same formal/types.py integer
lattice, so any disagreement is a codegen bug in one of them.

**CPython is the third column, and it is the one that can say an example is
WRONG rather than merely inconsistent.** Two backends agreeing is evidence
about the pair; it is not evidence about either one alone — a shared
misreading of the source (a floor division where the source means a
truncating one, a signedness that both spellings resolved the same way)
reproduces in both images and compares equal. So the answer is also computed
by executing the example's own text under CPython, and a disagreement with
either image is a FAIL.

That costs nothing: `exec` of a two-line function is microseconds against a
two-second build, and it is the same text the backends were handed, so there
is no second copy of the program to drift.

**The entry is the same function the backends call**, which is not a detail:
`formal/model.py::entry_function` takes the MODULE BODY, else a declared
`main`, else the FIRST `def` in source order — so in a two-function example
whose callee is written first, the callee is what runs, and an oracle that
guessed "the function named after the file" would compare a different program
than the one that was built. The rule is asked of `entry_function` itself, not
restated, for the same reason the two backends ask it.

**Six shims, and nothing else**, because each is a SPELLING the formal dialect
has and CPython does not, and none of them changes what the program computes:

  * `struct X:` becomes `class X:` — the fields stay annotations and get a
    keyword `__init__`, so `Point()` plus `p.x = n` is the same stores.
  * `var x = e` becomes `x = e`, and `fn f(...)` becomes `def f(...)` — `var` is
    a declaration modifier and `fn` a keyword, neither of which CPython has.
  * a body-less `def`/`fn` header gets a `pass`: Mojo's implicit `None` return
    is a statement the language allows to be missing and Python's is not, and
    the missing body is unreachable code either way.
  * `Int`, `Int8` … `UInt64` become `int` — annotation NAMES. (They are read
    from `formal/types.py::TYPE_NAMES`, so a new width cannot leave this
    behind.) A `-> Int` return annotation is a no-op in CPython for the same
    reason.
  * `@spec(...)`, `@require(...)` and `@ensure(...)` lines are DROPPED: they
    are the contracts `formal/admitted.py` turns into Lean theorems, the image
    does not execute them, and their grammar (`;`-separated equations, a bare
    `=` in operator position) is not an expression at all. They are read from
    `formal/admitted.py`'s own contract-decorator set rather than spelled here.

Anything beyond those is reported as `NO-ORACLE` rather than shimmed, because a
seventh rewrite of somebody else's language is a way to make this column agree
by construction. `udivmod` is the standing example: `/` truncates on this path
and CPython's does not (`test_formal_run.py`'s `neg_slash_still_truncates` pins
the divergence deliberately), so its CPython answer is a float and there is
nothing to compare.

The exit status is compared as `value & 0xFF`, which is what the process
itself sees: formal's startup stub returns the entry's value to the kernel and
only its low byte survives, and `sys.exit` agrees modulo 256.

The x86-64 binaries are Mach-O and run under Rosetta 2 on Apple Silicon;
`--arch arm64` is native. Invocation:

    python3 test_x86_64_examples.py [-n INPUT] [-j N] [-v]
"""

import argparse
import concurrent.futures
import inspect
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from exec_budget import child_exit_reason   # noqa: E402

EXAMPLES = os.path.join(HERE, "formal", "examples")
DEFAULT_INPUT = 10


def examples():
    return sorted(f for f in os.listdir(EXAMPLES) if f.endswith(".mojo"))


def build_and_run(path: str, arch: str, test_input: int, keep: str = None):
    """Build one example for `arch` and return (status, detail).

    status is the process exit code, or None when the example could not be
    built or run — with `detail` saying which."""
    import formal.build as B

    outdir = keep or tempfile.mkdtemp(prefix="formal-x86-")
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    out = os.path.join(outdir, f"{stem}.aout")
    try:
        B.compile_formal(path, output=out, test_input=test_input, prove=False,
                         arch=arch)
    except Exception as e:                    # noqa: BLE001 — reported, not raised
        return None, f"build failed: {type(e).__name__}: {e}"

    argv = [out]
    if arch == "x86_64" and sys.platform == "darwin":
        # Rosetta 2, exactly as a clang `-arch x86_64` binary needs.
        argv = ["arch", "-x86_64", out]
    r = subprocess.run(argv, capture_output=True, text=True)
    # The signal's NAME, not its number: `signal 11` does not say SIGSEGV, and a
    # `SIGKILL` is a fact about the machine rather than about the example, which
    # is the distinction this line used to throw away. `exec_budget`'s wording,
    # shared with the three suites that had their own copy.
    if r.returncode < 0:
        return None, child_exit_reason(r.returncode, r.stderr)
    if "Bad CPU type" in (r.stderr or ""):
        return None, "Bad CPU type in executable"
    return r.returncode, ""


def _fill_bodiless_defs(source: str) -> str:
    """A `pass` under every header whose body is missing.

    Mojo lets a function body be absent (the implicit `None` return);
    CPython's grammar does not. The inserted statement is unreachable in a
    program that has one, so this cannot change an answer — and it is why
    `wide_recv`'s `fn set_x(self, v: Int):` is a row here rather than a
    `NO-ORACLE`.
    """
    out, lines = [], source.split("\n")
    for i, line in enumerate(lines):
        out.append(line)
        stripped = line.strip()
        if not stripped.startswith(("def ", "fn ", "class ", "struct ")):
            continue
        if not stripped.endswith(":"):
            continue
        indent = len(line) - len(line.lstrip())
        following = lines[i + 1] if i + 1 < len(lines) else ""
        nxt_indent = len(following) - len(following.lstrip())
        if not following.strip() or nxt_indent <= indent:
            out.append(" " * (indent + 4) + "pass")
    return "\n".join(out)


def _drop_unapplied_decorators(source: str) -> str:
    """Every `@name(...)` line whose `name` is not a `def` of this file.

    That is the rule `formal/model.py::unapplied_decorator_refusal` already
    applies to decide a decorator cannot change the image: a decorator whose
    body is not in this unit is one the emitters do not apply, and on this
    path nothing calls it. `@spec` is the corpus's case — its clauses are kept
    as TEXT precisely because they are not expressions — and `@require` /
    `@ensure` are the same family of annotation. A decorator that IS defined
    here is left alone: `formal/model.py` only tolerates it when its whole body
    is `return f`, and rewriting that here would be deciding a question the
    backends decide.
    """
    defined = set(re.findall(r"^[ \t]*(?:def|fn)\s+(\w+)", source, flags=re.M))

    def keep_or_drop(m):
        return m.group(0) if m.group(1) in defined else ""

    return re.sub(r"^[ \t]*@(\w+)\(.*\)[ \t]*$", keep_or_drop, source,
                  flags=re.M)


def cpython_answer(path: str, test_input: int):
    """`(exit status, detail)` for the same source under CPython, or `(None, …)`.

    `None` rather than a guess when CPython itself refuses the program: a
    shim this file cannot spell is a hole in the ORACLE, and reporting it as a
    FAIL would send whoever reads the failure to look at a backend that did
    nothing wrong. The shims and why each is spelling-only are in the module
    docstring.
    """
    from formal.types import TYPE_NAMES

    with open(path, encoding="utf-8") as f:
        source = f.read()
    source = re.sub(r"^struct (\w+):", r"class \1:", source, flags=re.M)
    source = re.sub(r"^(\s*)var ", r"\1", source, flags=re.M)
    source = re.sub(r"^(\s*)fn ", r"\1def ", source, flags=re.M)
    source = _drop_unapplied_decorators(source)
    source = _fill_bodiless_defs(source)
    namespace = {"__name__": "formal_example", "__builtins__": __builtins__}
    # `printf` crosses into the runtime in the formal path; under CPython it is
    # a no-op sink, and an example's ANSWER is its return value, never what it
    # printed — the same split `test_formal_run.py`'s `print_negative` row makes
    # when it asserts an exit status and a stdout substring separately.
    namespace["printf"] = lambda *a, **k: None
    for name in TYPE_NAMES:
        namespace[name] = bool if name == "Bool" else int
    try:
        exec(compile(source, path, "exec"), namespace)     # noqa: S102
    except Exception as e:                                # noqa: BLE001
        return None, f"CPython refused the source: {type(e).__name__}: {e}"
    for obj in list(namespace.values()):
        # A `class X:` body of annotations has no `__init__`, so a keyword one
        # is attached: `Point()` followed by `p.x = n` is the same pair of
        # stores the image performs, and a struct example's answer is those
        # two fields added together.
        fields = getattr(obj, "__annotations__", None)
        if isinstance(obj, type) and fields and "__init__" not in obj.__dict__:
            def __init__(self, **kw):
                for key, value in kw.items():
                    setattr(self, key, value)
            obj.__init__ = __init__

    entry = formal_entry(namespace)
    if entry is None:
        return None, "CPython found no entry function to call"
    try:
        arity = len(inspect.signature(entry).parameters)
    except (TypeError, ValueError):
        arity = 1
    try:
        value = entry(*([test_input] + [0] * (arity - 1) if arity else []))
    except Exception as e:                                # noqa: BLE001
        return None, f"CPython entry raised: {type(e).__name__}: {e}"
    if isinstance(value, bool) or not isinstance(value, int):
        return None, f"CPython entry returned {value!r}, not a word"
    return value & 0xFF, ""


def formal_entry(namespace: dict):
    """The function the backends' startup stub calls, asked of `entry_function`.

    `formal/model.py::entry_function` is the authority and it is asked rather
    than restated, because the rule has three clauses (module body, declared
    `main`, else first in source order) and a two-function example is exactly
    where guessing "the function named after the file" picks the wrong one.
    The AST it wants is handed to it as a list of stand-ins carrying only a
    `name`, which is all that function reads.
    """
    import formal.model as M

    class _F:
        def __init__(self, name):
            self.name = name

    body = [v for v in namespace.values()
            if inspect.isfunction(v) and not inspect.isbuiltin(v)
            and v.__module__ == namespace["__name__"]
            and "." not in v.__qualname__]
    if not body:
        return None
    ordered = M.entry_function([_F(v.__name__) for v in body])
    return namespace.get(ordered[0].name)


def check_one(path: str, test_input: int, verbose: bool):
    stem = os.path.splitext(os.path.basename(path))[0]
    want, want_detail = build_and_run(path, "arm64", test_input)
    got, got_detail = build_and_run(path, "x86_64", test_input)
    cpy, cpy_detail = cpython_answer(path, test_input)
    if want is None:
        return stem, "SKIP", f"arm64 reference unavailable ({want_detail})"
    if got is None:
        return stem, "FAIL", f"x86_64 {got_detail}"
    if want != got:
        return stem, "FAIL", f"x86_64 returned {got}, arm64 returned {want}"
    if cpy is None:
        # The oracle could not be built, so this example is UNVERIFIED against
        # CPython rather than wrong. Its own status is a `SKIP` of the third
        # column only — the two backends did agree, and saying so is the
        # useful half of the answer.
        return stem, "NO-ORACLE", f"both {want}, but {cpy_detail}"
    if want != cpy:
        return stem, "FAIL", (f"CPython returns {cpy}, arm64 and x86_64 both "
                              f"return {want}")
    return stem, "PASS", f"all three {want}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=DEFAULT_INPUT,
                    help="entry function's argument (default 10)")
    ap.add_argument("-j", type=int, default=0,
                    help="parallel workers (default: min(cpu_count, 8))")
    ap.add_argument("-v", action="store_true", help="print every example")
    args = ap.parse_args()
    verbose = args.v
    files = [os.path.join(EXAMPLES, f) for f in examples()]
    workers = args.j or max(2, min(os.cpu_count() or 4, 8))
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(check_one, p, args.n, verbose): p
                   for p in files}
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())
    results.sort()

    for stem, status, detail in results:
        if status != "PASS" or verbose:
            print(f"{status:10} {stem:20} {detail}")

    counts = {}
    for _stem, status, _detail in results:
        counts[status] = counts.get(status, 0) + 1
    print(" ".join(f"{k}={counts[k]}" for k in sorted(counts))
          + f" of {len(results)} examples (n={args.n})")
    return 1 if counts.get("FAIL") else 0


if __name__ == "__main__":
    sys.exit(main())
