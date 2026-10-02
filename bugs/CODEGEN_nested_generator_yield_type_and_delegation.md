# A function that returns containers of more than one kind: the call site and the loop target

## What was run

```sh
python3 fire.py build /Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py
```

## What was seen

```
Unsupported shape(s):
  render: every `yield` must carry a value, and all values must agree on one
    scalar type (int64_t/double/_Bool)
  section: `for ... in render(...)` does not consume a generator this compile
    has itself already translated via the C++20-coroutine path
```

The two halves are ONE cause, and the doc's own "fix `render` first and this
message will change" advice is right — `section`'s line is the LAST attempt's
reason, not the blocker.

`render` is a nested generator inside `build_section`:

```python
def render():
    yield ''
    yield f'{name}:'
    yield ''
    for line in _render_table(items, columns, relroot):
        yield line
```

`yield ''` types `char *`. `line` is the loop target over the module-level
generator `_render_table`, and it typed as the `int64_t` default — so the
same-type check saw `char *` against `int64_t` and refused.

## The two fixes, both verified to reach the next blocker

**1. The loop target's type is not looked up.** `_generator_yield_ctype`
(`mojo/middle/exprtypes.py`) types each `yield <expr>` with
`_infer_simple_expr_ctype`, which resolves a bare name through `known` —
the generator's declared params/locals. A name bound by
`for x in <iterable>` is in neither, so it falls to `int64_t`.

`_yield_from_delegate_ctype` ALREADY resolves exactly this question for the
`yield from <iterable>` spelling (`generator_api[name]['value_ctype']`), and
`_cpp_for_stmt`'s generator-delegate branch ALREADY declares the loop target
from that same value. So the answer exists twice and is simply not consulted
on the yield path. Making the yield walk consult it (an overlay on `known`
for `for`-bound names) is a few lines and types `line` as `char *` — verified
to clear `render`'s refusal.

**2. `_cpp_iterable_is_delegatable_generator_call` cannot see a top-level
generator's ORIGINAL name.** This is the part that costs the time. It tests
membership in `gen._all_generator_names`, which `module_gen.py:1356` builds
as `{n.name for n in _generator_fns.values()}` — over the POST-DESUGAR AST.
The A3 stack-switch desugar (`mojo/middle/coro.py`, its own module docstring:
"replaces `g` in the module statement list with `__mgco_<g>_body`, a plain
(non-generator) FunctionDef") has already renamed `rows` to
`__mgco_rows_body`, which is not a generator, so `rows` is NOT in that set.
Meanwhile `gen._generator_api['rows']` — the wrapper name, mapped to the same
`__mgco_rows_start/_resume/_value/_destroy` trampolines the cpp path calls —
IS present. Testing `_generator_api` as well fixes it; the two registries
answer different questions (the name set covers a callee not yet compiled this
pass, which is what drives gen_module's retry loop; the api map covers the
post-desugar spelling) and both are needed.

## The trap, measured

Fixing (2) alone is NOT enough, and it makes things WORSE if stopped there.
Verified on a 26-line distilled repro:

```
g1_gen.cpp:114:20: error: '__mgco_rows_value' was not declared in this scope
```

`_cpp_for_generator_delegate` builds its own `args_text` and never registers
the callee base in `gen._cpp_xmod_generator_refs`, which is the map
`module_gen.py:10501` emits the extern "C" drive-API declarations from.
`_cpp_emit_generator_start_expr` and `_cpp_next_generator_expr` both
register; this one did not. Adding the `setdefault` is one line and gets past
it — into the NEXT failure:

```
g1_gen.cpp:121:72: error: 'columns' was not declared in this scope
 121 |  ... __mgco_rows_start(items, columns), ...
```

which is the real feature gap: a nested generator consuming a
stack-switch-compiled module-level generator needs the enclosing
parameters CAPTURED into the coroutine frame, and the cpp body model has no
capture for them.

## Why this was not landed

Because the last step is a feature, and the two steps before it change which
shapes reach a path that then fails with a g++ error naming an internal
symbol instead of an honest refusal. Shipping (1)+(2)+(the `setdefault`)
converts a named refusal into a confusing compile error for anyone whose
generator consumes a top-level one — a net loss in diagnosis even though the
file gets further. Ship (1)+(2)+(the `setdefault`) together with the capture
work, or not at all.

## Next step

1. Land the capture: `for x in <top-level generator>(...)` inside a nested
   cpp-path generator body must pass the enclosing function's live
   parameters into the callee's coroutine frame. `_cpp_capture_*` (the
   existing closure-capture machinery in `cpp_core.py`) is the place to look.
2. Then (2) and the `setdefault` in `_cpp_for_generator_delegate`.
3. (1) is independent and safe on its own.

Regression shape for (1) once landed: a nested generator that yields a
literal AND re-yields another generator's values, compared against CPython.
`test_silent_noop_iter.py` is the right file for it — it already owns
`multi_kind_local_is_the_box_not_the_first_kind`, the sibling case where a
return value rather than a yield value spans two container kinds.