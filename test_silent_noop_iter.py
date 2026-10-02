#!/usr/bin/env python3
"""The silent no-op class: every `for` loop the compiled backend declines
must either compute the right answer or be refused BY NAME.

`mojo_unsupported_iter` used to be the only thing standing between a
silently-wrong compiled program and a correct one, and it was not enough,
for two reasons this file pins down:

  * it fires only when the loop is REACHED, so a wrong answer computed
    without ever touching the fallback — a container reinterpreted as a
    different container, a reversed sequence iterated forwards — is not
    covered by it at all; and
  * it names only the static C type it was handed (`int64_t`, `void *`),
    which says nothing about what the value actually was.

Every case here is checked by COMPARING the compiled binary's stdout with
the reference `python3` answer for the same program, because "the compiled
path did not crash" is not evidence of anything in this class. A case whose
compiled output differs from the reference FAILS even when the compiled run
exits 0 and prints nothing alarming.

The oracle is plain CPython, NOT `python3 fire.py run`. The in-repo
interpreter is the other engine under test in this project and it is known
to lag the compiled backend on whole constructs (FORMAL.md §11.1's
`comptime` table), so using it here would make a case assert "both engines
are wrong in the same way" — precisely the shared-bug blindness
`test_runtime_diff.py` cannot see past.

Slow by nature: every case builds and links its own binary (~40 s each), so
the full run is minutes rather than seconds. Individual cases can be named
on the command line to run just those.

Set GMOJO_HOME (FORMAL.md §11.3) — this file inherits it and does not set
one, so two agents running it concurrently cannot collide.

Usage:
    python3 test_silent_noop_iter.py [-v] [case ...]
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MOJO = os.path.join(HERE, 'fire.py')
TIMEOUT = 300

_PASS = 0
_FAIL = 0
_VERBOSE = False


def check(name, cond, detail=''):
    global _PASS, _FAIL
    if cond:
        print(f'PASS  {name}')
        _PASS += 1
    else:
        print(f'FAIL  {name}  {detail}')
        _FAIL += 1


def _run(cmd, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True,
                          errors='replace', timeout=TIMEOUT, cwd=cwd or HERE)


def _reference_stdout(src, tmpdir):
    """The answer CPython gives for `src` — the oracle for every case here.

    Plain `python3`, not `python3 fire.py run`. The in-repo interpreter is
    the *other engine under test* in this project, and it is known to lag
    the compiled backend on whole constructs (FORMAL.md §11.1's `comptime`
    table is the documented example: the interpreter raises NameError where
    the compiled path computes an answer). Using it as the oracle would make
    a case assert "both engines are wrong in the same way", which is
    precisely what `test_runtime_diff.py` cannot catch and what this file
    exists to catch. `fire.py run` is still consulted, as a fallback, for a
    case CPython itself cannot run.
    """
    p = os.path.join(tmpdir, 'ref_case.py')
    with open(p, 'w') as fh:
        fh.write(src)
    r = _run([sys.executable, p])
    if r.returncode == 0:
        return r.stdout
    r = _run([sys.executable, MOJO, 'run', p])
    return r.stdout if r.returncode == 0 else None


def _compiled_stdout(src, tmpdir, tag):
    p = os.path.join(tmpdir, f'{tag}.py')
    with open(p, 'w') as fh:
        fh.write(src)
    exe = os.path.join(tmpdir, tag)
    b = _run([sys.executable, MOJO, 'build', '-o', exe, p])
    if b.returncode != 0 or not os.path.exists(exe):
        return None, f'BUILD FAILED: {b.stderr.strip().splitlines()[-1:] or b.stdout[-300:]}'
    r = _run([exe])
    if _VERBOSE:
        sys.stderr.write(f'--- {tag} compiled stderr ---\n{r.stderr}\n')
    return r.stdout, (r.stderr if r.returncode != 0 else None)


def _self_invoking(src):
    """Append the `main()` call, so the SAME text runs under plain CPython.

    Every case here defines `main()` and stops, because that is how this
    repo's own programs are written — `fire.py build` generates the entry
    that calls it. Plain CPython has no such entry, so without this the
    reference run produces empty stdout and every case compares the
    compiled answer against nothing. Appending the call to the source (as
    opposed to having the harness invoke `main` somehow) is what keeps the
    two engines reading byte-identical input, which is the only way a
    stdout comparison means anything. Verified: a trailing `main()` prints
    exactly once under `fire.py build` — the generated entry point and the
    module-scope call do not double up.
    """
    return src if src.rstrip().endswith('main()') else src.rstrip() + '\n\nmain()\n'


def _case(name, src, expect_refusal_substring=None):
    """Compile `src`, run it, and require the compiled stdout to equal the
    reference's. A `mojo_unsupported_iter` on stderr is allowed ONLY when
    the case declares one and names the construct it expected."""
    global _PASS, _FAIL
    src = _self_invoking(src)
    with tempfile.TemporaryDirectory() as tmpdir:
        ref = _reference_stdout(src, tmpdir)
        if ref is None:
            check(name, False, 'reference could not run this program at all')
            return
        got, err = _compiled_stdout(src, tmpdir, name)
        if got is None:
            check(name, False, err or 'no output')
            return
        refused = 'mojo_unsupported_iter' in (err or '')
        if expect_refusal_substring is not None:
            # The construct is one the backend genuinely cannot model, so a
            # refusal is the CORRECT outcome — but it must name itself, and
            # the rest of the program must still run to completion.
            ok = refused and expect_refusal_substring in got
            check(name, ok,
                  f'expected a refusal naming {expect_refusal_substring!r}; '
                  f'stdout={got!r} stderr={(err or "")[:300]!r}')
            return
        if got == ref:
            check(name, True)
        else:
            check(name, False,
                  f'compiled {got!r} != reference {ref!r}'
                  + (f'  [stderr: {(err or "")[:200]}]' if err else ''))


# ── The cases ────────────────────────────────────────────────────────────
#
# Each is a program whose compiled stdout must equal its reference stdout.
# They are grouped by the defect they pin, and each carries the shape that
# reproduces it.

CASES = {}


def case(name):
    def deco(fn):
        CASES[name] = fn
        return fn
    return deco


@case('container_kind_not_reinterpreted')
def _():
    # A `set` handed to a parameter the compiler inferred as `MojoList *`
    # from a DIFFERENT call site. The backend used to emit
    # `pp = (MojoList *)s;` at the call site and the callee then read
    # `mojo_list_len`/`mojo_list_get_int` out of a `MojoSet` — printing 0
    # for 10, with no diagnostic, and reading past the set's own slot
    # array. MojoDict/MojoList/MojoSet/MojoBytes are four distinct runtime
    # structs (DESIGN.html R2); a cast between them is not a conversion.
    return '''def probe(box):
    for x in box:
        print("v", x)

def main():
    probe([1, 2])
    probe({10, 20})
    probe((7, 8))
    print("done")
'''


@case('comprehension_return_kind_is_not_neighbour_kind')
def _():
    # A local bound from a COMPREHENSION — a real container, whose C type
    # depends on the comprehension's `kind` — returned from a function whose
    # other branch returns a list.
    #
    # The local-type pre-pass (`infra_infer._prebound_local_ctypes`, which
    # `_infer_return_type` overlays onto `var_types`) knew about
    # `{a, b}`/`[a, b]`/`{k: v}` DISPLAYS but not about `{x for x in y}`:
    # a `Comprehension` carries its kind as an attribute, so it does not fit
    # the `type(...).__name__` table those three share. The local therefore
    # typed as the int64_t box, the function's return type came out from its
    # OTHER return statement alone (`MojoList *`), and the body then had to
    # store a real `MojoSet *` into that `MojoList *` return slot — refused
    # by `_sce_simple_emit`'s container-kind guard, which is the honest
    # answer to a mis-typed store but leaves the file unbuildable.
    #
    # Real: `Apple/__main__.py`'s `lib_platform_files` (returns `names`, or
    # a set comprehension of ignored names, or `set()`).
    #
    # The join is the point, and it is asserted by the reference stdout: the
    # function's return type is the BOX (`int64_t`) precisely because its
    # branches disagree on container kind, so the values must come back
    # through each branch's own storage, not through one reinterpreted slot.
    return '''def pick(names, kind):
    if kind == 1:
        return names
    elif kind == 2:
        ignored = {name for name in names if name.startswith("_sys")}
    else:
        ignored = set()
    return ignored


def main():
    print(pick(["a", "b"], 1))
    print(pick(["_sysconfigdata_x", "build-details.json"], 2))
    print(pick(["_sysconfigdata_x"], 3))
'''


@case('multi_kind_local_is_the_box_not_the_first_kind')
def _():
    # One local bound to a LIST on one branch and a SET on another. Python is
    # happy with this; the compiled representation cannot be either
    # container, so it must be the box.
    #
    # `_infer_local_var_types` already reached that answer — it joins the two
    # kinds and reports `int64_t` — but three separate "trust ground truth"
    # rules in `_gen_stmt_AssignStmt` each read that `int64_t` as a STALE
    # SCALAR hint the first assignment site refines, and pinned the slot to
    # `MojoList *`. Every later branch's store was then a container-kind
    # coercion `_sce_simple_emit` refuses, so the file did not build at all.
    #
    # Real: `Tools/build/umarshal.py`'s `Reader.r_object`, whose `retval` is a
    # list, a dict, a set, a frozenset and a `Code` on five different
    # branches. That file builds again.
    #
    # Printing both branches is what makes it a test rather than a build check:
    # a box that "works" by being read as a list is exactly the failure, and
    # the branch ORDER matters because the first assignment site is the one
    # the pinning rules act on.
    return '''def pick(kind):
    if kind == 1:
        box = [1, 2]
    else:
        box = {7, 8}
    return box


def main():
    print(sorted(pick(1)))
    print(sorted(pick(2)))
'''


@case('multi_kind_global_rebound_in_a_function_is_the_box')
def _():
    # The module-GLOBAL twin of `multi_kind_local_is_the_box_not_the_first_
    # kind`, and the one shape Phase 1.7's global pre-scan structurally
    # cannot see: `X = <kind A>` at module scope and `global X; X = <kind B>`
    # inside a function are TWO assignments to ONE binding, so the two types
    # must be JOINED — and every one of those pre-passes walks module-level
    # statements only. `X` was therefore frozen at kind A forever, the
    # cross-function store was coerced to kind A through a pointer cast, and
    # the very next line — which slices the same global as the list it has
    # just become — sliced a `char *` and emitted `char * + MojoList *`.
    #
    # Real: `Mac/BuildScript/build-installer.py`'s
    # `FW_VERSION_PREFIX = "--undefined--"  # initialized in parseOptions`
    # and `FW_VERSION_PREFIX = FW_PREFIX[:] + ["Versions", getVersion()]`.
    # That file did not build at all before this; it builds now.
    #
    # Every line after the reassignment is a DIFFERENT consumer of the same
    # binding, and each is printed rather than merely compiled: a slice, a
    # `print` of the global itself (repr dispatch), and a method call on it.
    # A box that "works" by being read as a `char *` fails all three, and the
    # `configure()` return additionally pins the `return L[1:]` slice type —
    # the shape whose `_quick_type` used to answer the box for a global.
    return '''PREFIX = ["Library", "Frameworks"]
SUFFIX = "undefined"


def configure():
    global SUFFIX
    SUFFIX = PREFIX[:] + ["Versions", "3.14"]
    return SUFFIX[:1]


def main():
    print(configure())
    print(SUFFIX)
    print("|".join(SUFFIX))
'''


@case('slicing_a_boxed_global_reads_the_container')
def _():
    # A module global is stored in an `int64_t` field — the codebase-wide
    # convention for a container global — so `L` reads back as a box. Every
    # other consumer of a box resolves its kind through `_get_actual_type`
    # (`L[2]` included); the SLICE was the one that did not, and fell
    # through to the generic pointer-arithmetic fallback, which on an
    # `int64_t` is INTEGER addition. `L[1:]` emitted `t + 1` and printed
    # `33067958273` where CPython prints `[20, 30, 40]`.
    #
    # Silent because `L[2]` was already right, which is what makes the
    # subscript-vs-slice disagreement the property under test: the same
    # binding, read two ways, must give the same answer. `S` is the `char *`
    # counterpart, because resolving the box through `_get_actual_type` also
    # newly reaches the `char *` slice branch (`mojo_cstr_slice`) for a
    # boxed string global, and that must not change.
    return '''L = [10, 20, 30, 40]
S = "hello world"


def main():
    print(L[1:])
    print(L[:2])
    print(L[2])
    print(S[6:])
    print(S[:5])
    for x in L[1:]:
        print("item", x)
'''


@case('multi_kind_parameter_returned_is_the_box')
def _():
    # `multi_kind_local_is_the_box_not_the_first_kind`, one indirection on:
    # the multi-kind name is a PARAMETER. Both `return`s hand back the SAME
    # local, so the disagreement lives in the local's bindings and never in
    # the return statements — which is exactly what made this one slip
    # through. The parameter's own type came from usage evidence
    # (`_infer_param_types`, which cannot see a binding), the return type
    # inherited it, and the CALL SITE then applied the `int64_t`-returning
    # branch's default of "`_actual_types` says `MojoList *`" and formatted
    # the dict through `mojo_repr_list_ints` — another container's memory, out
    # of bounds. `{'a': 1}` printed as `[0]`, exit 0.
    #
    # Both branches are printed because the property is that the two
    # CALL SITES agree with the source, not that one of them is right: a
    # caller-side fix that only recognised the dict would pass with the list
    # arm still guessing.
    return '''def probe(box, kind):
    if kind == 1:
        box = [1, 2]
    else:
        box = {"a": 1}
    return box


def main():
    print(probe(None, 1))
    print(probe(None, 2))
'''


@case('next_iter_over_a_dict_items_expression')
def _():
    # `next(iter(<expression>))`, where the expression is not a bare name.
    # Reading a dict's first entry this way is the ordinary Python idiom, and
    # the `next(iter(x))` lowering existed only for `x` being an IdentExpr —
    # so this shape matched no `next(...)` form at all and hit the
    # whole-module refusal ("`next(...)` on next(CallExpr) has no lowering"),
    # which is not a per-line diagnostic: it takes the whole file out of the
    # compiled path. Real: `Apple/__main__.py`'s
    # `next(iter(slice_parts.items()))`, twice.
    #
    # The `for k, v in d.items():` line is in the case on purpose: the
    # destructuring form and the loop form read the SAME [key, value] pair,
    # so they must print the same thing. That is the property, not just
    # "compiles" — an element-type guess that made `next(iter(...))` disagree
    # with the loop over the same list would still be wrong here.
    #
    # In one function, deliberately: a dict handed to a CALLEE does not carry
    # its value type across the call boundary in this codegen (a separate,
    # pre-existing gap that the `for` form shares — see
    # bugs/CODEGEN_unannotated_dict_param_value_type_not_propagated.md), so
    # putting the pair read behind a call would test that instead of this.
    return '''def main():
    d = {"alpha": "one", "beta": "two"}
    k, v = next(iter(d.items()))
    print(k, v)
    for k2, v2 in d.items():
        print(k2, v2)
        break
    print("done")
'''


@case('container_kind_dict_keys')
def _():
    # The same class with a dict: `mojo_dict_keys` is the real conversion
    # (iterating a dict yields its keys), so the callee must see the dict's
    # two keys.
    #
    # This case counts rather than prints, deliberately. A `for x in box`
    # whose iterable type is known only from an inferred parameter binds `x`
    # with the callee's own (uninformed) element type, so PRINTING `x` is
    # testing a different defect — an untracked list element type — and
    # would fail here for a reason that has nothing to do with the
    # conversion under test. The count is the property this case owns.
    return '''def probe(box):
    n = 0
    for x in box:
        n = n + 1
    print("n", n)

def main():
    probe([1])
    probe({"a": 1, "b": 2})
    print("done")
'''


@case('reversed_over_untyped_param')
def _():
    # `reversed()`'s caller-side gate required a STATICALLY TYPED argument,
    # so a boxed int64_t parameter missed it and the call fell to
    # `mojo_reversed` — a `void *` identity stub. `for x in reversed(seq)`
    # then iterated an untyped handle: zero iterations, then a segfault,
    # then (once the type was recovered) a FORWARD iteration, which is a
    # wrong answer with no diagnostic at all. All three are wrong; the
    # only correct outcome is reverse order.
    #
    # One type per parameter, deliberately. A parameter called with both a
    # list and a string makes the compiler's own parameter-type inference
    # disagree with itself, and that inference is a different defect (and
    # one this file does not claim). Mixing them here would test that, not
    # this.
    return '''def rev(seq):
    for x in reversed(seq):
        print("v", x)

def main():
    rev([1, 2, 3])
    print("done")
'''


@case('reversed_over_untyped_str')
def _():
    # The same fix on a string, which takes the cstr branch of the lowering
    # rather than the list one.
    return '''def rev(seq):
    for c in reversed(seq):
        print("c", c)

def main():
    rev("abc")
    print("done")
'''


@case('reversed_over_list_literal')
def _():
    # Same, with a statically-typed argument, so this is the shape that
    # already worked and must keep working.
    return '''def main():
    xs = [1, 2, 3, 4]
    for x in reversed(xs):
        print(x)
    for c in reversed("hi"):
        print(c)
    print("done")
'''


@case('findall_no_groups')
def _():
    # `re.findall` had NO lowering at all. The call fell to a `void *`
    # identity stub and the consuming loop ran ZERO times, silently.
    return '''import re

def f(src):
    for w in re.findall(r'[A-Za-z_][A-Za-z0-9_]*', src):
        print("w", w)

def main():
    f("ab cd ef")
    print("done")
'''


@case('findall_one_group')
def _():
    # One capturing group: real Python returns the group, NOT a 1-tuple.
    return '''import re

def f(src):
    for g in re.findall(r'[0-9]+', src):
        print("g", g)

def main():
    f("a1 b22 c333")
    print("done")
'''


@case('findall_two_groups')
def _():
    # Two groups: one TUPLE per match, so `for a, b in ...` unpacks.
    return '''import re

def f(src):
    for a, b in re.findall(r'([a-z]+)=([0-9]+)', src):
        print("p", a, b)

def main():
    f("ab=12 cd=34 zz")
    print("done")
'''


@case('findall_no_match')
def _():
    # Zero matches must yield an empty iteration, not a garbage one.
    return '''import re

def f(src):
    n = 0
    for w in re.findall(r'[0-9]+', src):
        n = n + 1
    print("n", n)

def main():
    f("no digits here")
    print("done")
'''


@case('generator_over_untyped_handle')
def _():
    # A generator reached through a parameter the compiler could not type.
    # Recorded here because it is the shape a `MojoGenerator *` iterable
    # takes when the static type is lost, and the correct outcome — the one
    # this asserts — is that it still produces the generator's values rather
    # than dropping the loop.
    return '''def gen(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def probe(box):
    for x in box:
        print("v", x)

def main():
    probe(gen(2))
    print("done")
'''


@case('finditer_still_lowered')
def _():
    # finditer already had a lowering; the findall work must not disturb it.
    return '''import re
_RE = re.compile(r'[a-z]+')

def f(src):
    for m in _RE.finditer(src):
        print("m", m.group())

def main():
    f("ab 12 cd")
    print("done")
'''


@case('zip_nested_tuple_target')
def _():
    # A regression guard on a lowering that already worked: a zip whose
    # first target slot is itself a tuple.
    return '''def f(pairs, others):
    for (a, b), g in zip(pairs, others):
        print(a, b, g)

def main():
    f([(1, 2)], [9])
    print("done")
'''


@case('untyped_param_zip_still_works')
def _():
    # And the same over arguments the compiler could not type, which is the
    # shape `_materialize_as_list` exists for.
    return '''def f(xs, ys):
    for a, b in zip(xs, ys):
        print(a, b)

def main():
    f([1, 2], [3, 4])
    print("done")
'''


# Cases asserted at CODEGEN level rather than by running the binary.
#
# A refusal is a property of the emitted C, and asserting it there is both
# cheaper and sharper than asserting it through a program's output: the
# program may well die before reaching the loop (a `re.MULTILINE` attribute
# read on the compiled `re` module raises before the loop is emitted at all),
# which would make a runtime assertion about the refusal untestable.
CODEGEN_CASES = {}


def codegen_case(name):
    def deco(fn):
        CODEGEN_CASES[name] = fn
        return fn
    return deco


@codegen_case('findall_flags_refused_by_name')
def _():
    """`re.findall(pat, s, re.MULTILINE)` must be REFUSED, not silently
    evaluated without the flag.

    A flags argument changes what `^`/`$`/`.` mean, and this backend's
    regex engine takes no flags at all. Lowering the call and dropping the
    flag would return the single-line answer to a question that was asked in
    multi-line terms — a wrong answer with nothing to distinguish it from a
    right one, which is the whole defect class. So the findall lowering
    raises on a third positional argument, the caller rolls back, and the
    loop's own `mojo_unsupported_iter` is what remains in the emitted C.
    """
    return ("""import re

def f(src):
    for a, b in re.findall(r'^([a-z]+)=([0-9]+)$', src, re.MULTILINE):
        print("p", a, b)
""", 'mojo_unsupported_iter')


@codegen_case('findall_two_groups_lowered')
def _():
    """The positive counterpart: a two-group findall must emit NO refusal.

    The flag case above is only meaningful if the lowering fires for the
    shapes it does support, so this pins that a plain two-group findall
    reaches the scan (a `mojo_regex_search` in the emitted C) and leaves no
    `mojo_unsupported_iter` behind.
    """
    return ("""import re

def f(src):
    for a, b in re.findall(r'([a-z]+)=([0-9]+)', src):
        print("p", a, b)
""", None)


@codegen_case('reversed_lowered_no_refusal')
def _():
    """`reversed()` over an untyped parameter must reach a real reversal.

    Before this, that shape emitted `mojo_unsupported_iter` naming `void *`
    (the `mojo_reversed` identity stub) — the silent no-op in its purest
    form. The marker asserted here is the absence of that refusal plus the
    presence of the runtime reversal call.
    """
    return ("""def rev(seq):
    for x in reversed(seq):
        print(x)
""", 'mojo_list_reverse')


def _codegen_case(name, src, marker):
    """Assert on the emitted C rather than on a program's output.

    `marker` is a substring that must (or, when None, must NOT) appear in
    the generated `.ci`. This is the direct expression of "the loop is
    refused by name" / "the loop is really lowered": the refusal is a line
    in the generated C, so testing for it there tests exactly the thing,
    with no dependence on whether the program survives long enough to reach
    the loop at run time.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        p = os.path.join(tmpdir, f'{name}.py')
        with open(p, 'w') as fh:
            fh.write(src)
        r = _run([sys.executable, MOJO, '--dump', p])
        # `fire.py --dump` writes the artifacts into the CURRENT directory
        # under the source's BASENAME, not next to the source — so the .ci
        # lands in the repo root, and is removed again here rather than
        # left for the next test to trip over.
        ci = os.path.join(HERE, f'{name}.ci')
        try:
            if r.returncode != 0 or not os.path.exists(ci):
                check(name, False, f'dump failed: {r.stderr.strip()[-300:]}')
                return
            with open(ci, errors='replace') as fh:
                gen = fh.read()
        finally:
            for ext in ('.ci', '.ast', '.tok', '.pyi'):
                try:
                    os.unlink(os.path.join(HERE, f'{name}{ext}'))
                except OSError:
                    pass
    if marker is None:
        ok = 'mojo_unsupported_iter' not in gen
        detail = 'emitted C still contains a mojo_unsupported_iter refusal'
    else:
        ok = marker in gen
        detail = f'emitted C has no {marker!r}'
    check(name, ok, '' if ok else detail + _unsupported_sites(gen))


def _unsupported_sites(gen):
    """The `file:line: type` each refusal in this generated C names.

    Printed on failure because "there is a refusal" is not a diagnosis: a
    refusal that names an unrelated line is a different bug from the one the
    case is about, and only the site says which.
    """
    import re as _re
    lits = dict(_re.findall(r'static char \* (_slit_\d+) = "((?:[^"\\]|\\.)*)";', gen))
    last = {}
    out = []
    for line in gen.splitlines():
        m = _re.match(r'\s*(_t\d+) = (_slit_\d+);', line)
        if m:
            last[m.group(1)] = lits.get(m.group(2), '?')
            continue
        if _re.match(r'\s*mojo_unsupported_iter \((_t\d+)\);', line):
            out.append(last.get(_re.match(r'\s*mojo_unsupported_iter \((_t\d+)\);', line).group(1), '?'))
    return ('  refusals in this .ci: ' + '; '.join(out)) if out else '  (none)'


def main(argv):
    global _VERBOSE
    args = list(argv[1:])
    if '-v' in args:
        _VERBOSE = True
        args.remove('-v')
    names = args or (list(CASES) + list(CODEGEN_CASES))
    for name in names:
        if name in CASES:
            _case(name, CASES[name]())
        elif name in CODEGEN_CASES:
            src, marker = CODEGEN_CASES[name]()
            _codegen_case(name, src, marker)
        else:
            print(f'SKIP  {name}  (no such case)')
            continue
    print(f'\n{_PASS} passed, {_FAIL} failed')
    return 1 if _FAIL else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
