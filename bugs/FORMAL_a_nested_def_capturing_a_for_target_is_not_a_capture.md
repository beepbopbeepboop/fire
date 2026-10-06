# FORMAL: a nested `def` capturing a `for` loop variable is refused, because the closure scope never learns the loop target

**Area:** FORMAL (both backends), and the root cause is one line of SHARED code
in `mojo/middle/closures.py::discover_closures` — which is why this round filed
it instead of fixing it.

**Found while measuring closures against CPython** in a round whose claim is
`project33:closures-lambdas`. The refusal is not wrong, only silent about itself:
it answers `'i' has no home`, a sentence about the register allocator, for what
is a fact about the closure pass.

## What was run

    $ cat lv.mojo
    def main():
        s = 0
        for i in range(3):
            def get():
                return i
            s = s + get()
        return s
    $ python3 lv.mojo   # with `print(s)` and `main()` appended
    3
    $ python3 fire.py build --formal --no-prove -o lv lv.mojo
    build: main_get: 'i' has no home: the module-level symbol table is empty for
    this unit, and the reading function declares no local or parameter by that
    spelling. …

Identical on `--backend=x86_64`.

CPython answers `3`: `get()` is called inside the same iteration that defined it,
so it reads the current `i` — 0, then 1, then 2.

## What was expected

`3`. The by-value capture ABI already answers this shape for an ordinary local:

    def outer(a):
        def add(x): return x + a
        return add(5)          # 15, and `capture_read_directly_in_the_enclosing_scope`
                                # in test_formal_closures.py pins it

and a loop variable is a local of the enclosing function like any other.

## The root cause, and why this round did not fix it

`discover_closures` builds `enriched_scope` — the map of what the enclosing
function holds, and the filter every inferred capture is tested against
(`if v in enriched_scope`):

    for bstmt in _gmi_all_stmts_nonfunc(body):
        if isinstance(bstmt, AssignStmt) and isinstance(bstmt.target, IdentExpr):
            … enriched_scope[name] = t
        elif isinstance(bstmt, VarDecl):
            … enriched_scope[bstmt.name] = t

**A `ForStmt` target is in neither arm.** So `i` is not in `enriched_scope`, `i`
is a free name of `get`'s body (it is used and not declared there), and the
capture filter drops it. Measured directly, by asking the pass itself:

    closures: {'main': {'get': []}}       # `i` missing
    after flatten: [('main', []), ('main_get', [])]   # no leading param

The lift then produces `main_get()` whose body reads `i`, which is a name with no
home anywhere — hence the refusal.

**Why not fixed here.** `mojo/middle/closures.py` is the copy shared with the
compiled backend (`formal/build.py` and `mojo/backend_gimple/module_gen.py` both
call `discover_closures`, and its header says future architecture backends must
too). Adding a `ForStmt` arm to `enriched_scope` changes the compiled path's
capture set as well, and CLAUDE.md is explicit that a change under
`mojo/middle/*` owes a full `make gate` — which this round's brief forbids
("no gate for formal", "do not run the quality gate"). Changing a shared closure
decision with no way to prove the compiled path is unaffected is exactly the
trade CLAUDE.md's gate section warns about, so the honest outcome is a filed doc
and a refusal row, not a one-line edit whose blast radius nobody measured.

## The fix, for whoever can gate it

One arm on the same loop, mirroring the two above and using the same
`ctx._quick_type`-free default of `'int64_t'` the `VarDecl` arm uses when there
is no initializer:

    elif isinstance(bstmt, ForStmt):
        for _tgt in _loop_target_names(bstmt):
            if _tgt not in enriched_scope:
                enriched_scope[_tgt] = 'int64_t'

`ForStmt.target` is a `str`, an `IdentExpr`, or a `TupleExpr`/`ListExpr` of those,
so the unpack needs its own reader — and it must NOT be spelled twice: this file
already walks loop targets three lines above it for `inner_assign_targets`
(`isinstance(bstmt, ForStmt): tgt = bstmt.target; … hasattr(tgt, 'name')`), so
that walk is the one to extract and share. A `Comprehension` is a separate scope
and its targets are NOT enclosing-scope locals — `formal/build.py`'s
`_apply_module_constant_sites` docstring says so at length, and getting it wrong
in the other direction would capture a comprehension's loop variable into a
closure and shadow it.

## What to check the fix against, and the hazard in it

By-value capture of a loop target is right for THIS program and wrong for the
program it looks like. `get()` called inside the defining iteration reads the
current value, so 3 is right. But

    fs = []
    for i in range(3):
        def g(): return i
        fs.append(g)
    print(fs[0](), fs[1](), fs[2]())     # CPython: 2 2 2

is LATE binding \u2014 one cell, three closures \u2014 and a by-value capture would
answer `0 1 2`. So the fix must be checked against both, and it is worth being
explicit that the by-value ABI cannot express the second shape at all: it is
correct to keep refusing it, and to refuse it by NAME (the late-binding row in
`test_formal_closures.py`'s refusal group is the same construct written with a
lambda, and gets `model.capturing_lambda_refusal`).

Today the second shape is not reachable with a nested `def` anyway: it needs the
closure stored in a container, and a container element read back and called is
refused by `model.value_bracket_reading_refusal`. **Check that it still is after
the fix** \u2014 it is the only thing standing between the fix and a silent
wrong-answer class, and it is a refusal about a different construct, so nothing
about the capture change obviously protects it.

## Test coverage

`test_formal_closures.py`'s `a_nested_def_capturing_a_loop_variable` row, a
refusal row: both backends must refuse, identically, naming the name the capture
missed. It pins the FACT that the shape does not build; the comment above it
records that the right sentence is a closure-capture one rather than a
register-allocator one, so whoever fixes the pass moves the row to the answered
group instead of re-deriving what it should say.