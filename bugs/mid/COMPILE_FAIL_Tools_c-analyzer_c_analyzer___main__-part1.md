# COMPILE_FAIL: c_analyzer/__main__.py part 1 — `_render_table`'s `yield '\t'.join(columns)` value slot

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__.md` (SPLIT)
Class: mid

Filed under `bugs/mid/` (the class this part argues it needs).

## Measured current state (2026-11-11, this tree)

Save this as `.tmp/replan/repro_z.py`:

```python
def _render_table(columns):
    yield '\t'.join(columns)
    yield 'done'


def build_section(name):
    columns = ('a', 'b')

    def render():
        yield f'{name}:'
        for line in _render_table(columns):
            yield line

    return render


def main():
    render = build_section('types')
    for line in render():
        print(line)


main()
```

Build:

```
python3 tools/memslot.py --gb 8 --label ca-p1 -- python3 fire.py build -o .tmp/replan/out_z .tmp/replan/repro_z.py
```

refuses with:

```
_render_table: yields ['columns'], whose call sites do not all pass the same
statically-known type (they disagree, or one of them the static scan could not
type at all) — a compiled generator has ONE fixed C value-slot ...
build_section__render__esc: `for ... in _render_table(...)` does not consume a
generator this compile has itself already translated via the C++20-coroutine
path ...
```

The second line is downstream of the first. `_render_table` alone, called from
two ordinary functions (a tuple literal and a tuple parameter), compiles and
prints the right rows. So the conflict is the call from the moved/escaping
`render` body, where the captured tuple local's static type differs from the
direct call sites.

This is the same "yield sites agree internally but the SITES disagree" shape
the parent doc's 2026-10-04 entry names; it is the live refusal for
`_render_table` in the real file today.

## Scope

Fix the shared call-site-kind scan / yield-slot inference so a parameter that
reaches a `yield` only as the argument of a result-kind-independent string
method does not set the yield slot's kind. `'\t'.join(x)` is always `char *`,
whatever `x`'s element kind is; the same holds for the `str` formatting
methods whose result is a string. The mechanism already exists for module
functions: `_ambiguous_yielded_params`' `passed_through` walk in
`mojo/middle/coro.py` (~:2996-3002) excludes arguments of calls whose result
kind, not the argument kind, sets the slot. Extend that to the `str`-method
call whose result is a string.

Do not widen the slot for a genuinely mixed `yield columns` or
`for x in columns: yield x` — that must keep the honest refusal.

Sites to inspect (one implementation, no copy):

- `mojo/middle/coro.py::_ambiguous_yielded_params` — the `passed_through`
  walk is the narrow place to teach `'\t'.join(...)`/`str.format(...)`.
- `mojo/middle/coro.py::_scan_callsite_param_kinds` /
  `_CALLSITE_PARAM_CONFLICTS` — only if the call-site type itself is the real
  cause rather than the yield expression.
- `mojo/backend_gimple/cpp_async.py::_gen_cpp_generator_unit` (~:579-593) —
  it already consumes `_ambiguous_yielded_params`; do not add a second gate.

## Acceptance

- `repro_z.py` builds and its stdout is `types:\na\tb\ndone\n`,
  byte-identical to `python3 .tmp/replan/repro_z.py`.
- A direct-call variant with a tuple literal and a tuple parameter still
  builds and matches CPython (the shape that already works today).
- A generator that genuinely yields a conflicted parameter — e.g.
  `def g(xs): for x in xs: yield x` called once with `["p"]` and once with
  `[1]` — still refuses with the same message. This pins that the change is a
  `join`-result fix, not a blanket hole in the conflict rule.
- Add one case next to the yield-kind tests in
  `test_gimple_generator_runner.py` and run it narrowly:
  `python3 tools/memslot.py --gb 8 --label ca-p1-test -- python3 test_gimple_generator_runner.py`.
  No whole-closure compile, self-host build, or gate run.

## Not in scope

- `yield from <generator handle local>` inside a nested generator (part 2).
- The escaping generator's `yield ''` value slot (part 3).
- Imported-module blockers (`c_parser/*`, `c_common/*`, `ggc` shadow), which
  belong to the sibling docs named in part 4.
