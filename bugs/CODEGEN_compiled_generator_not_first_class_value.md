# CODEGEN: compiled generator objects aren't first-class values (can't assign to a variable, can't call next() directly)

## Discovery context

Found via independent verification of Milestone C step 3 (struct-method
generators, commit `654565e`) — confirmed present for the SIMPLEST
Milestone B-level free-function generator too, so this is a pre-existing
gap, not something step 3 introduced. This is severity-wise much less bad
than `bugs/CODEGEN_compiled_generator_unannotated_string_param_mistyped.md`
(that one silently miscompiled; this one fails LOUDLY), but it's still a
real, currently-open limitation worth its own fix.

## Repro

```python
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def main():
    g = counter(3)
    for x in g:
        print(x)

main()
```

- `python3 mojo.py run repro.py` (interpreter): correct, prints `0 1 2`.
- `python3 mojo.py repro.py` (auto/default, no explicit `build`): still
  correct — `mojo.py build`'s internal failure (below) is caught somewhere
  in the fallback chain and the program is fully interpreted instead,
  producing the right output. Not a correctness problem for ordinary use.
- `python3 mojo.py build repro.py -o out`: FAILS with a genuine (non-zero
  exit, no binary produced, no misleading "Built:" message) GCC compile
  error:
  ```
  repro.py:8:5: error: invalid use of void expression
      g = counter(3)
  repro.py:N:8: error: variable or field 'g' declared void
  ```

A second, related shape also fails — calling `next()` directly on a
generator object rather than consuming it via `for`:
```python
g = counter(3)
print(next(g))
```
fails at the LINK stage instead (undefined symbol `_next`), since this
codegen's generic `next()` builtin lowering has no case for a
`MojoGenerator*` value.

## Root cause

Confirmed: `counter(3)`'s result (a `MojoGenerator*`) is correctly typed
ONLY when consumed directly and immediately as a `for`-loop's iterable
expression (Milestone B/C's call-site lowering handles that one specific
shape). The moment the generator call's result is assigned to an
intermediate local variable, this codegen's ordinary local-variable-type
inference has no notion that a bare call to a known-generator function
should type that variable as `MojoGenerator*` — it falls through to
whatever the generic/default inference produces, which resolves to `void`
here (the underlying function doesn't have an ordinary scalar/pointer
return type as far as that inference pass is concerned, since generator
functions don't go through the normal `func_return_types` path the way
ordinary functions do).

## Impact

Any real-world use of a compiled generator beyond the single narrow
"consume immediately as a `for`-loop's expression" shape fails to build at
all (loudly, not silently) — storing a generator in a variable for later
use, passing it to another function, returning it from a function, or
calling `next()`/`.send()` on it directly all currently fail. This is a
significant practical limitation: "cross-function calls" and first-class
handling of generator values were explicitly part of this project's
Milestone C scope (parameters, yield from, struct methods, AND
cross-function calls) — this gap is squarely in that last, not-yet-done
part.

## Suggested fix

Register `MojoGenerator*` (or a per-generator-function specific pointer
typedef, matching however this codegen already distinguishes different
opaque pointer-typed values elsewhere) as a real, known C type in this
codegen's local-variable/parameter/return-type inference machinery, so:
1. A local variable assigned from a call to a known generator function
   gets correctly typed `MojoGenerator*` (or the specific per-function
   variant), not defaulted to `void`.
2. That variable can then be passed as a function argument, returned from
   a function, or consumed later by a `for`-loop/`next()`/`.send()` call,
   with the SAME call-site lowering Milestone B/C already built for the
   inline-consumption case, generalized to also handle "the iterable
   expression is a plain identifier already holding a generator object"
   rather than only "the iterable expression is itself the generator
   call."
3. `next()` as a builtin needs a case for a `MojoGenerator*` argument,
   calling its `_resume`/`_value` pair (and correctly raising/signaling
   `StopIteration` when exhausted, matching whatever this codegen's
   existing `next()`-on-other-iterable-types convention already does, if
   any — reuse rather than invent a new StopIteration-signaling mechanism).

This is likely the single most valuable remaining piece of Milestone C,
more fundamental in everyday usefulness than `yield from` or struct
methods, since "assign a generator to a variable" is an extremely common
pattern.
