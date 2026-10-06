"""`nonlocal` end to end: a real `NonlocalStmt` on BOTH execution paths.

`nonlocal` used not to exist in this compiler at all. `nonlocal` was not in
the keyword set, so `nonlocal working_dir` degraded into a stray EXPRESSION
statement — visible in the generated `.ci` as a constant-0 read commented
`/* ct param or undeclared: nonlocal */` — and the closure-capture pass then
classified the name as a plain assigned-local of the inner function. The
compiled program therefore exited 0 with the WRONG closure value: the write
went to a local that vanished when the inner function returned, and the
enclosing frame read back its own untouched initial value. See
“COMPILE_FAIL: Tools/wasm/wasi/__main__.py”.

The fix is one rule expressed twice, because the two paths represent a cell
differently:

  * the INTERPRETER's function scopes are shared objects, so `nonlocal` is a
    declaration recorded on the running scope (`Scope.nonlocals`) and a plain
    `x = ...` to a declared name goes through `Scope.set` — the nearest
    ENCLOSING binding — instead of `Scope.define`, which is the always-local
    default every other plain assignment keeps;
  * the COMPILED path's closure env is a struct passed by pointer, so the name
    has to be captured BY REFERENCE for the write to be visible outside. The
    by-reference capture machinery already existed (it is what makes Mojo's
    `{mut}` capture spec work); what was missing is that a `nonlocal`-declared
    name must be treated as FREE in the declaring function, so
    `mojo/middle/closures.py` now takes the declared names out of
    `inner_declared`.

Every case below compiles, links and RUNS on both paths and asserts on real
output. `print` is used rather than `printf` because `printf` has no
interpreter builtin, so a `printf` repro could not compare the two paths.

Two shapes are deliberately NOT asserted here, because they are blocked by
SEPARATE pre-existing gaps that `nonlocal` does not own and that reproduce
without it (both verified with Mojo's own `{mut}` spelling in place of
`nonlocal`):

  * a `nonlocal` capture of a `char *`: an unannotated `str` PARAMETER types
    as `int64_t`, so the closure receives an integer where the source passes a
    string (`bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_
    int64.md`'s family). The capture itself is correctly by-reference — the
    generated C is `char * * _mutptr_buf` — the value arriving is the wrong
    type. The three-closure cases below are therefore int-valued for the same
    reason: they are about the CELL, not about the value's representation.
  * `nonlocal` reached through a module-level `@decorator`: a plain
    `@deco` on a `def` is not applied on either path (see the new bug doc
    `bugs/COMPILE_FAIL_decorator_application_dropped.md`), so the decorated
    name is still the undecorated function. `Tools/wasm/wasi/__main__.py`
    reaches `nonlocal working_dir` exactly that way, which is why its
    `subdir`-shaped case is exercised here through a direct call instead.
"""
import os
import subprocess
import sys
import tempfile

import driver

HERE = os.path.dirname(os.path.abspath(__file__))

_PASS = 0
_FAIL = 0


def check(name, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}  {detail}")
        _FAIL += 1


def _build_and_run_compiled(mojo_src: str) -> str:
    """Real compile + link + run through `driver.compile_program`, the same
    path `fire.py build` uses (mirrors test_general_mutable_closure_capture's
    harness, which is the other real by-reference-capture suite)."""
    wd = tempfile.mkdtemp(prefix='mojo_nonlocal_')
    src_path = os.path.join(wd, 'prog.mojo')
    with open(src_path, 'w') as f:
        f.write(mojo_src)
    exe = os.path.join(wd, 'prog.exe')
    rc = driver.compile_program(src_path, mojo_src, output=exe, run=False)
    if rc is None:
        raise RuntimeError("driver.compile_program failed to build")
    r = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"program exited {r.returncode}, stderr={r.stderr}")
    return r.stdout


def _run_interpreted(mojo_src: str) -> str:
    """Real interpretation through `fire.py run`, in a subprocess, so this
    exercises the path a user's `fire.py <file> run` would."""
    wd = tempfile.mkdtemp(prefix='mojo_nonlocal_interp_')
    src_path = os.path.join(wd, 'prog.mojo')
    with open(src_path, 'w') as f:
        f.write(mojo_src)
    r = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'), 'run', src_path],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"interpreter run exited {r.returncode}, stderr={r.stderr}")
    return r.stdout


# ── 1. the accumulator: the exact shape `Tools/wasm/wasi/__main__.py` uses ──
#
# `subdir`'s `wrapper` declares `nonlocal working_dir` and rebinds it from a
# callable; here the rebinding value is an argument, which is the smallest
# form that shows the same miscompile (the write is lost, the outer frame
# keeps its initial value). Two calls, so a first-write-only accident would
# also be caught.
_ACCUM_SRC = """\
def acc(n):
    total = 0
    def add(k):
        nonlocal total
        total = total + k
    add(3)
    add(4)
    return total


def main(n):
    print(acc(0))
"""

# ── 2. augmented assignment: `nonlocal` is the explicit spelling of `{mut}` ──
_AUG_SRC = """\
def acc2(n):
    total = 0
    def add(k):
        nonlocal total
        total += k
    add(5)
    add(6)
    return total


def main(n):
    print(acc2(0))
"""

# ── 3. a container, so the by-reference cell is not just an int64_t box ──
_CONTAINER_SRC = """\
def grow(n):
    items = [0]
    def push(v):
        nonlocal items
        items = items + [v]
    push(1)
    push(2)
    return len(items)


def main(n):
    print(grow(0))
"""

# ── 4. read-only: `nonlocal` with no rebinding is just a capture ──
_READONLY_SRC = """\
def peek(n):
    x = 5
    def get():
        nonlocal x
        return x
    return get()


def main(n):
    print(peek(0))
"""

# ── 5. THE CONTROL, and the most important row in the file ──
#
# The same program WITHOUT the declaration must still create a local, because
# that is Python's rule and it is this compiler's long-standing behaviour. A
# fix that made every plain assignment inside a nested `def` write outwards
# would pass rows 1-4 and break this one, silently turning every nested
# function into a mutator of its parent.
_CONTROL_SRC = """\
def shadow(n):
    v = 1
    def setv():
        v = 99
    setv()
    return v


def main(n):
    print(shadow(0))
"""

_CASES = [
    ("accumulator (the __main__.py shape)", _ACCUM_SRC, "7\n"),
    ("augmented assignment", _AUG_SRC, "11\n"),
    ("container capture", _CONTAINER_SRC, "3\n"),
    ("read-only capture", _READONLY_SRC, "5\n"),
    ("no declaration -> still a local (Python's rule)", _CONTROL_SRC, "1\n"),
]

# ── 6. TWO closure levels deep, over a LOCAL ──
#
# `inner`'s `nonlocal total` binds `outer`'s local, so the by-reference box
# has to be threaded through the INTERMEDIATE closure `mid`: `mid` captures
# it by reference too, and hands `inner` the same pointer. Before this the
# transitive capture fixup in `discover_closures` propagated the NAME but not
# the by-reference-ness, so `mid`'s env field was a plain `int64_t` and
# `inner`'s seeding became `_env_inner->total = _env->total;` — an `int64_t`
# stored into an `int64_t *` field, a hard `-Wint-conversion` error (the same
# shape `Tools/wasm/wasi/__main__.py`'s `subdir` -> `decorator` -> `wrapper`
# chain hit). `mid` RETURNS `inner`, so the box must also outlive `mid`'s
# frame — which it does, because the box is heap-allocated in `outer`'s
# prologue rather than being `&outer`'s stack slot.
_TRANSITIVE_LOCAL_SRC = """\
def outer():
    total = 0

    def mid():
        def inner(k):
            nonlocal total
            total = total + k
        return inner

    f = mid()
    f(3)
    f(4)
    return total


def main(n):
    print(outer())
"""

# ── 7. TWO closure levels deep, where the OWNER is a PARAMETER ──
#
# The same chain with `seed` as a parameter rather than a local. This is the
# `Tools/wasm/wasi/__main__.py` shape exactly (`def subdir(working_dir, *,
# clean_ok=False)` with a doubly-nested closure rebinding it). It needs a
# second mechanism on top of case 6: a by-reference capture of a PARAMETER,
# because a parameter is already declared under the source-level name and
# `_seed_mut_captured_local_types` skips every name `var_types` already holds.
# The incoming parameter is therefore declared under a second C identifier
# (`_mutbox_seed`) and the box local carries the source-level one, seeded
# from it in the prologue.
_TRANSITIVE_PARAM_SRC = """\
def outer(seed):
    def mid(f):
        def inner(k):
            nonlocal seed
            seed = seed + k
        return inner

    g = mid(1)
    g(3)
    g(4)
    return seed


def main(n):
    print(outer(0))
"""

# ── 8. the intermediate's OWN read of the cell ──
#
# `mid` reads the same box `inner` writes, so this fails if the chain copies
# the value at any level instead of sharing one cell. Two calls, so a
# first-write-only accident is caught too: the seed accumulates across them
# (0 -> 5 -> 11) and the result is their sum, 16 — a per-level copy would
# give 5 + 6 = 11.
_TRANSITIVE_MID_READ_SRC = """\
def outer(seed):
    def mid(step):
        def inner(k):
            nonlocal seed
            seed = seed + k
        inner(step)
        return seed

    return mid(5) + mid(6)


def main(n):
    print(outer(0))
"""

_CASES += [
    ("two closure levels deep (local owner)", _TRANSITIVE_LOCAL_SRC, "7\n"),
    ("two closure levels deep (parameter owner)", _TRANSITIVE_PARAM_SRC, "7\n"),
    ("intermediate closure reads the same cell", _TRANSITIVE_MID_READ_SRC, "16\n"),
]


def main():
    for name, src, want in _CASES:
        try:
            got = _run_interpreted(src)
        except Exception as e:  # noqa: BLE001 - report, do not mask
            got = f"<error: {e}>"
        check(f"interpreter: {name}", got == want,
              detail=f"got {got!r}, want {want!r}")
        try:
            got = _build_and_run_compiled(src)
        except Exception as e:  # noqa: BLE001
            got = f"<error: {e}>"
        check(f"compiled:    {name}", got == want,
              detail=f"got {got!r}, want {want!r}")
    print(f"\nnonlocal: PASS={_PASS} FAIL={_FAIL}")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
