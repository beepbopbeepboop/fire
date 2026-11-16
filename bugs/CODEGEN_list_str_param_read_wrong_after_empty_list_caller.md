# A `list[str]` parameter reads its elements wrongly when one caller passes an empty list VARIABLE

Class: medium. Silent wrong answer, exit 0. Three defects stacked; fix them
in the order below, one per round.

## Symptom

    def ends(lines: list[str]) -> str:
        if lines and lines[-1].endswith(':'):
            return "open"
        return "closed"

    def main():
        e: list[str] = []
        print(ends(e))
        print(ends(["a", "b:"]))

    main()

CPython prints `closed` then `open`. Measured 2026-11-16: the compiled
program prints `closed` `closed`.

(The same program with `ends([])`, the empty list written in place, was
fixed on 2026-11-16: an empty LITERAL is no longer recorded as a call site
that passes a list of ints.)

## Defect 1 (the cause): an annotated empty local counts as "a list of ints"

`gen_module_impl` in `mojo/backend_gimple/module_gen.py` records what each
call site passes for a parameter. In its nested `_static_arg_elems`, the
`IdentExpr` arm looks the argument up in `elem`, the caller's local element
types from `self._scan_container_elems(body)`. For `e: list[str] = []` that
answer is `int64_t` (the "cannot tell" default: the annotation is not
read), the arm sets `_static_arg_int[0] = True`, and the call site is
recorded in `self._param_int_elem_obs`. A second call site passes strings,
so the parameter is put in `self._param_elem_mixed` and its element type
becomes unknown.

Fix: a local declared with a container annotation (`e: list[str]`) has the
annotation's element type in that scan. Make `_scan_container_elems`
answer `char *` for it, so the arm records a `char *` observation and the
two call sites agree.

## Defect 2: a kind-mixed element is cast to `char *` instead of unboxed

With the parameter mixed, `lines[-1]` is read with
`mojo_list_get_boxed (lines, -1)` and the method call then does

    _t9 = (char *)_t8;
    _t11 = mojo_str_endswith (_t9, _t10);

`mojo_list_get_boxed` (`runtime/fire_runtime.c`) returns a BOX for a string
slot, not the string pointer, so the cast reads the box header. The
receiver of a string method that is a boxed word must go through the
runtime (`mojo_word_cstr_value`) before it is used as `char *`. Search
`mojo/backend_gimple/emit_methods.py` for the "Opaque int → coerce"
comment; that block casts an `int64_t` receiver to the container type.

## Defect 3: `mojo_list_get_boxed` does not accept a negative index

    int64_t mojo_list_get_boxed(MojoList *l, int64_t i)
    {
        if (!l || i < 0 || i >= l->len) return 0;

Every other list accessor (`mojo_list_get_int`, `mojo_list_get_str`) goes
through `_norm_idx(l, i)`, so `xs[-1]` works for them and returns 0 here.
Use `_norm_idx` the same way.

## How to verify

1. Add the program above to `test_gimple_runner.py` (compare with CPython).
   It passes after Defect 1 alone.
2. For Defects 2 and 3 add a program whose parameter is genuinely mixed:
   `show([1, 2])` and `show(["a", "b:"])` calling
   `def show(xs): print(xs[-1])`, compared with CPython.
3. `python3 test_gimple.py` keeps its pass count with 0 failed;
   `python3 tools/suite.py stdlib-syntax stdlib-dylib gimple-lint` passes.

## Done when

Both programs pass and this file is deleted in the same commit (then
`python3 tools/dangling_doc_refs.py --ratchet`). A partial round removes
the fixed defect's section.
