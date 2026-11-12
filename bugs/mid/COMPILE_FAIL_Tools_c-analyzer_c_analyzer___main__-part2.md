# COMPILE_FAIL: c_analyzer/__main__.py part 2 — `yield from` a generator handle held in a local, inside a nested generator

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__.md` (SPLIT)
Class: mid

Filed under `bugs/mid/` (the class this part argues it needs). Independent of
parts 1 and 3.

## Measured current state (2026-11-11, this tree)

**(a) Silent miscompile.** Save as `.tmp/replan/repro_w.py`:

```python
def leaf():
    yield 'a'
    yield 'b'


def outer():
    def inner():
        g = leaf()
        yield from g

    yield from inner()


def main():
    for x in outer():
        print(x)


main()
```

It builds (exit 0) but the compiled binary prints a long stream of pointer
values and zeros instead of `a\nb\n`. CPython prints `a\nb\n`. A module-level
generator with the same `g = leaf(); yield from g` body (no enclosing `def`)
builds and prints `a\nb\n`, so the defect is specific to the nested-generator
body.

**(b) The real `__main__.py` shape.** Save as `.tmp/replan/repro_s.py`:

```python
def build_section(name, groupitems):
    def render():
        yield f'{name}:'
        yield from groupitems

    return render


def fmt_summary(analysis):
    items = list(analysis)

    def section(name):
        render = build_section(name, items)
        yield from render()

    yield from section('types')


def main():
    for line in fmt_summary(['a', 'b']):
        print(line)


main()
```

It is refused. The reported reason is:

```
section: is a nested generator that reads enclosing-scope variable(s) items;
the coroutine path has no capture model for a generator defined inside another
function ...
```

but `MOJO_DEBUG=1` shows the real first refusal:

```
[coro] nested generator 'section' has a capture the box machinery cannot take
(no capture plan):
```

The capture message is a mask, not the cause. The same `section` body with
`yield from items` instead of `yield from render()` compiles and matches
CPython, and `yield from g` in a module-level generator compiles. The failing
shape is the delegation to a generator handle held in a local, inside a nested
generator — which is exactly `section`'s body in the real file
(`_, render = build_section(name, items); yield from render()`).

## Scope

Make `yield from <local holding a generator handle>` inside a nested sync
generator either:

1. lower correctly, delegating through the handle's registered
   `_resume/_value/_destroy` API with the handle's own value type, or
2. refuse honestly with a message naming `yield from` and the handle, never
   the enclosing capture and never a compiled body that produces garbage.

The module-level path already handles this shape (`_cpp_yield_from`'s
handle-local branch; `_cpp_for_generator_delegate` does the same for `for`),
so find why the nested/moved-generator body loses the handle's API and reuse
that lowering rather than adding a second one.

Sites to inspect:

- `mojo/backend_gimple/cpp_async.py::_gen_cpp_generator_unit` and its
  `_cpp_yield_from` lowering — the nested coroutine body's `yield from`
  branch.
- `mojo/backend_gimple/cpp_core.py::_cpp_yield_from` — the module-level
  handle-local branch to share.
- `mojo/middle/coro.py::_lower_escaping_generators` — only if the moved body
  is where the handle's registered API is lost.

## Acceptance

- `repro_w.py` builds and prints exactly `a\nb\n` (CPython-identical), not a
  pointer stream.
- `repro_s.py` builds and prints `types:\na\nb\n` (CPython-identical).
- The real `section` body with the tuple unpack
  (`_, render = build_section(name, items); yield from render()`) builds and
  matches CPython.
- Existing `run_nested_generator_capture_tests` and
  `run_escaping_nested_generator_tests` stay green:
  `python3 tools/memslot.py --gb 8 --label ca-p2-test -- python3 test_gimple_generator_runner.py`.
- If a shape genuinely cannot be lowered, its refusal names `yield from` and
  the handle, not `items`; a compiled body must never emit garbage. Add one
  regression case for the nested handle-local delegation.
- Narrow verification only; no whole-closure compile, self-host build, or
  gate run.

## Not in scope

- `_render_table`'s yield slot (part 1).
- The escaping generator's `yield ''` (part 3).
- The inline consumer shape `for v in make()()` (measured separately: it is
  typed `int64_t` and reports `mojo_unsupported_iter`; `__main__.py` binds
  the handle to a local before consuming it, so this is not on the parent's
  path).
- Imported-module blockers owned by the sibling docs named in part 4.
