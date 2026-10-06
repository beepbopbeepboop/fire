# A function that returns containers of more than one kind: the call site and the loop target

## Status 2026-10-02 — item (1) is WRITTEN AND MEASURED and NOT landed, because
## landing it alone turns this doc's own refusal into a C++ error two levels out

### The typing defect is real and the fix for it is a dozen lines

Item (1) below ("the loop target's type is not looked up") is confirmed, and
the overlay this doc describes resolves it. `_generator_yield_ctype`
(`mojo/middle/exprtypes.py`) types each `yield <expr>` through
`_infer_simple_expr_ctype`, which resolves a bare name via `known`; a name a
`for` binds is in neither, so `yield line` got the `int64_t` default and the
same-type check saw `char *` against it. `generator_api[name]['value_ctype']`
is the answer, and it is already registered at that point — `_rows`'s api
entry reads `{'base': '__mgco__rows', 'value_ctype': 'char *', ...}` while
`render` is being compiled.

The shape this doc's "Next step 3" calls "independent and safe on its own" is
this one:

```python
def _rows(items):
    for line in items:
        yield line

def build_section(name):
    def render():
        yield ''
        yield f'{name}:'
        for line in _rows(['a', 'b']):
            yield line
    return render
```

The landed-shaped implementation was `_generator_for_bound_ctypes(fn,
generator_api, generator_method_api, self_struct_name)` in
`mojo/middle/exprtypes.py` — a `_walk_own_body` pre-pass that maps each
`for <name> in <generator>(...)`'s single-name target to the delegate's
registered `value_ctype`, overlaid onto a COPY of `known` at the top of
`_generator_yield_ctype`. Two details are load-bearing and both were measured:

* `ForStmt.target` is the PARSER's convention, not a node: a bare name is a
  `str`, a parenthesised target is a one-element list of `str`. Handling only
  `IdentExpr` finds nothing.
* The overlay must WIN over an existing `known` entry, not defer to it:
  `declared` already reaches `_generator_yield_ctype` carrying the loop
  target as the `int64_t` box default (`{'line': 'int64_t'}`), so a
  `setdefault`-shaped overlay changes nothing at all.

With it, all three of `render`'s yields type `char *` and the generator
compiles.

### Why it is still not landed

Because what it exposes is worse than the refusal it removes, and that is the
doc's own "Why this was not landed" argument, confirmed rather than refuted.
The refusal this doc was filed for was NAMED
(`render: every 'yield' must carry a value …`). Past it, on a 12-line
distilled repro whose yields all AGREE from the start — so nothing about the
yield-type overlay is involved, and this is reachable on a pristine tree
today:

```python
def _nums(items):
    for v in items:
        yield v

def outer():
    def render():
        yield 0
        for v in _nums([1, 2]):
            yield v
    return render

def main():
    for x in outer()():
        print(x)
main()
```

`render` is a cpp-path generator; `_nums` is A3 stack-switch-compiled
(`__mgco__nums_start`). `_cpp_iterable_is_delegatable_generator_call` tests
membership in `gen._all_generator_names`, which this doc's own item (2)
already identified as the POST-DESUGAR name set — and it is
`['render']`, with `_nums` absent. So the loop falls out of the delegate arm
into the GENERIC iterable lowering, which emits, into the companion `.cpp`:

```cpp
extern "C" MojoGenerator *__mgco__nums_start (int64_t);
...
for (auto v : __mgco__nums_start([&]() -> MojoList * { ... }())) {
```

a C++ range-based `for` over a `MojoGenerator *`, and g++ answers with
`'begin' was not declared in this scope` plus two dozen
`std::ranges::__access::begin` notes — a C++ error in the standard library's
own headers, for a program whose refusal used to name the generator.

`_supported_generators` DOES contain `_nums`, so the arm that would have
driven it correctly is reachable; item (2) below (consult `_generator_api` as
well) is what routes it there. And `_cpp_for_generator_delegate` still has to
survive an A3 delegate across the C/C++ boundary, which is the same feature
gap as the capture work. So the honest order is unchanged and now has a
measurement behind it: fix the generic fall-through first, THEN (1)+(2).

### The one-line thing that would make (1) landable today

With (1) landed and (2) not, the same range-for is reached through the
delegate arm's absence in a different way; what both need is a refusal
instead. The cheapest correct version is for
`_cpp_iterable_is_delegatable_generator_call` to also answer True for a name
in `gen._generator_api` (this doc's item (2)), so `_cpp_for_generator_delegate`
either drives it or raises its own named
`_UnsupportedGeneratorShape` — never the generic range-for. That is a
two-line change; whether it lands green depends on the A3/C++ ABI question
above, which is why it is not done here.

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