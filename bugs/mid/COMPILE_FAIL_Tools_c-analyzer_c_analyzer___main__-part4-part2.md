# COMPILE_FAIL: `yield from` a captured nested generator — the `c_analyzer/__main__.py` shape (`fmt_summary` / `section` / `build_section`)

Part 2 of `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__-part4.md`
(SPLIT). Depends on part 1 (`bugs/mid/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__-part4-part1.md`),
which makes the minimal shape compile.

## Goal

Make the file's actual shape compile: an enclosing generator on the coroutine
path (`items = list(analysis)`) with two `yield from section(...)` sites, where
`section` is a captured nested generator that itself calls a plain module-level
function `build_section(name, items)` and then `yield from`s a generator value
`render()` obtained by tuple-unpacking that call's return.

    def build_section(name: str, groupitems: list):
        def render():
            yield ''
            yield f'{name}:'
            for item in groupitems:
                yield f'{item}'
        return groupitems, render

    def fmt_summary(analysis: list):
        items = list(analysis)
        def section(name: str):
            _, render = build_section(name, items)
            yield from render()
        yield from section('types')
        yield from section('functions')

    for v in fmt_summary([1, 2]):
        print(v)

## Measurement needed first (not established by the parent doc)

The parent doc measured only the minimal shape. The `render` inside
`build_section` is a different mechanism: a generator value returned through a
plain function's tuple, then delegated to with `yield from render()`. After part 1
lands, the first step is to rebuild the main-shape fixture and record the exact
refusal, if any. Do not assume it is the same unresolved-callee defect. If the
refusal names `build_section`, `render`, or a tuple-unpacked generator, the fix
is in that consumer, and that is the part's scope. If it is a different
refusal, file it as its own bug doc under `bugs/` and say so in Status.

## Acceptance

* `python3 test_nested_generator_yield_from_in_coroutine.py main` exits 0: the
  program builds, runs, and prints exactly what CPython prints for the same
  text (`''`, `types:`, `1`, `2`, `''`, `functions:`, `1`, `2`, in order).
* On the real `c_analyzer/__main__.py`, the build's `Unsupported shape(s)` does
  not name `fmt_summary` or `section`. Measure this with the parent's repro. The
  build may still fail on the imported-module floor (`c_parser/info.py`,
  `.parser`), which is out of scope.

## Done when

`python3 test_nested_generator_yield_from_in_coroutine.py main` exits 0. Run it
under `python3 tools/memslot.py --gb 8 --label part4-part2 -- python3 test_nested_generator_yield_from_in_coroutine.py main`.

## Out of scope

* The minimal shape: part 1.
* Keyword/rebound/`nonlocal` refusals and tagged-kind parity: part 3.
* The imported-module floor: sibling docs named in the parent.
