# CODEGEN: `FloatLiteral.infinity` / `.nan` / negative zero are not constants

## What I ran

    cat > .tmp/flit.mojo <<'EOF'
    def main():
        print(FloatLiteral.infinity)
        print(FloatLiteral.negative_infinity)
        print(FloatLiteral.negative_zero)
        print(FloatLiteral.nan)
    EOF
    python3 tools/memslot.py --gb 8 --label flit-c -- \
        python3 fire.py build -o .tmp/flit .tmp/flit.mojo
    .tmp/flit

and the same file through `python3 fire.py run .tmp/flit.mojo`.

## What I saw

The compiled binary exits 0 and prints `0` four times; the interpreter fails at
line 2 with `NameError: name 'FloatLiteral' is not defined`.  Expected
`inf`, `-inf`, `-0.0`, `nan`, which is what
`mojo/test/mojo-integration/floats.mojo` (lines 54-57 and its whole
infinity-arithmetic section) requires.

## Why this is a separate bug

The `'inf' undeclared` C error from the same file was fixed by
`_float_c_literal` in `fire_compiler.py`: a source literal that OVERFLOWS to
infinity (e.g. `999e9000`) now emits `(double)INFINITY` instead of the Python
spelling `inf`.  This doc is the other half the original report's Notes guessed
at: the `FloatLiteral` CONSTANTS themselves have no lowering at all, so they
never reach `_lower_FloatLiteral`.

## Exact next step

Teach the name `FloatLiteral` (and the four attributes above) in the
mid-end's builtin-constant resolution, the same way other builtin class
constants are resolved (`mojo/middle/module_shared.py`'s
`builtin_module_constant` and its callers), so a `MemberExpr` on it lowers to a
`FloatLiteral` node with `math.inf`, `-math.inf`, `-0.0` and a NaN.  Add the
same names to `myinterpreter.py`'s global scope/`FloatLiteral` stand-in so
`fire.py run` agrees.  The pinning test is the four prints above; the wider
target is `mojo/test/mojo-integration/floats.mojo`, which also needs the
container-repr fix for bug `RUNTIME_repr_of_inf_in_a_container_aborts`.
