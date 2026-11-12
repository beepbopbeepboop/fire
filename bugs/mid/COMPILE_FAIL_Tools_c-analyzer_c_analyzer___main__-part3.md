# COMPILE_FAIL: c_analyzer/__main__.py part 3 — an escaping generator whose first yield is the empty string

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__.md` (SPLIT)
Class: mid

Filed under `bugs/mid/` (the class this part argues it needs). Independent of
parts 1 and 2.

## Measured current state (2026-11-11, this tree)

Save as `.tmp/replan/repro_ac.py`:

```python
def make():
    def gen():
        yield ''
        yield 'x'

    return gen


def main():
    g = make()
    for v in g():
        print(v)


main()
```

It builds (exit 0) but the compiled binary prints two decimal addresses
(measured `4369635600` and `4369635608` on this run) instead of a blank line
and `x`. CPython prints `\nx\n`.

Controls that pin the cause:

- The same escaping shape with `yield 'x'` first prints correctly.
- A module-level generator `def g(): yield ''; yield 'x'` prints correctly.
- A non-escaping nested generator with the same two yields prints correctly.

So the defect is specific to the escaping/moved-generator path: the first
`yield ''` makes the generator's single value slot (or the trampoline's
dynamic-word kind) `int64_t`, and every string yield is then printed as its
address. This is the silent-wrong-answer class the parent doc's `render`
(`yield ''` twice) hits once parts 1 and 2 let it compile.

## Scope

Fix the value-kind inference for the empty string literal in the
escaping/moved-generator path so `''` is `char *` like any other string
literal, and the generator's value slot is `char *` (or a tagged word that
renders an empty string). Do not special-case only the first yield: the slot
must be consistent for every yield in the body, and a body that genuinely
mixes kinds must keep the honest refusal.

Sites to inspect (one implementation, no copy):

- `mojo/middle/coro.py::_lower_escaping_generators` — the moved generator's
  value typing and the trampoline's `mojo_gen_call_with` word classification.
- `gimple_gen_coro._generator_value_kind` / `_KIND_TO_SLOT_CTYPE` — if `''`
  is classified as a non-string kind.
- `mojo/backend_gimple/cpp_async.py::_generator_yield_ctype` — if the slot is
  chosen there for the moved body.

## Acceptance

- `repro_ac.py` builds and prints `\nx\n`, byte-identical to
  `python3 .tmp/replan/repro_ac.py`.
- A `build_section`-style escaping `render` with
  `yield ''; yield f'{name}:'; yield ''` prints blank line, `types:`, blank
  line (the real `render` shape).
- The `yield 'x'`-first escaping shape, the module-level `yield ''` shape, and
  the non-escaping nested `yield ''` shape are unchanged.
- Add one regression case in `run_escaping_nested_generator_tests` in
  `test_gimple_generator_runner.py` and run it narrowly:
  `python3 tools/memslot.py --gb 8 --label ca-p3-test -- python3 test_gimple_generator_runner.py`.
  No whole-closure compile, self-host build, or gate run.

## Not in scope

- `_render_table`'s yield slot (part 1).
- `yield from <generator handle local>` inside a nested generator (part 2).
- The inline consumer shape `for v in make()()` (measured separately; it
  reports `mojo_unsupported_iter` and is not on the parent's path).
- Imported-module blockers owned by the sibling docs named in part 4.
