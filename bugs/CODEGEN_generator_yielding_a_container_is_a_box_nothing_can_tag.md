# CODEGEN: a generator that yields a CONTAINER has a boxed `int64_t` value, and nothing at the consumer can tell

**State: OPEN, measured 2026-10-02, not fixed.** Found while fixing
`bugs/CODEGEN_next_generator_value_truncated_in_return_position.md` (deleted by
its fix), whose own scope table lists this row. It is NOT the same bug and the
table did not say so, which is worth stating first because it is why this doc
exists rather than a line in that commit: the return type there was **already
correct** for this shape, and the wrong answer is a level further out.

## What I ran

`.tmp/repro.py <program>` — compile via
`test_gimple_runner.compile_mojo_to_gimple_exe` (single-TU `compile_to_gimple`,
`gcc -fgimple`, `runtime/fire_runtime.c` plus the A3 coroutine objects), run the
binary, diff stdout and exit status against CPython on the same text.

## What I saw

NOT in return position — the plainest spelling, which the return-position fix
does not touch:

```python
def gl():
    yield [1, 2]

def main():
    r = next(gl())
    print(r)
main()
```

```
CPython  : [1, 2]
compiled : 4318025648      exit 0
```

Byte-identical on a pristine `git archive HEAD` checkout of the tree the
return-position fix landed on, so it is pre-existing and untouched by it.

## Why the return-position row was NOT this bug

`__mgco_gl_value` is declared

```c
extern int64_t __mgco_gl_value (MojoGenerator *);
```

— the value slot is the scalar box, because
`_generator_yield_ctype` returns None (== "unsupported") for a container
literal and the coroutine's single promise slot carries one C type. So
`def h(): return next(gl())` inferred `int64_t h(void)`, which is the RIGHT
answer: the value really is a `MojoList *` bit pattern in an `int64_t`. The
function signature is not the defect and must not be "fixed" into
`MojoList *`; that would make the C signature disagree with the slot.

## Where the wrong answer is actually produced

`_gen_print`'s argument ladder. The value arrives with an `int64_t` type and
no entry in `gen._actual_types` (nothing ever saw it unboxed), so it takes the
final `else` and is `sprintf`'d with `%ld` — the pointer's own decimal.

The ladder already has the two arms that would answer this, and neither fires
because both need evidence this path does not carry:

* `gen._boxed_vals` / `mojo_repr_boxed` — for a slot read out of a
  HETEROGENEOUS list, where the runtime stored a `MojoBox` carrying a magic
  number and a kind byte (`MOJO_BOX_MAGIC`). A generator's value slot stores
  the raw word; there is no box.
* `gen._boxed_container_vals` / `_repr_boxed_container` — for "a call to a
  function whose returns disagree on container kind". A generator's returns do
  not disagree; it always yields the same kind, and nothing records which.

So the missing thing is a **runtime tag on the generator's value slot**, or a
codegen-side record that a particular `_value` accessor yields a container. The
second is cheaper and matches what `_gen_print` already consults: the api
registration knows the generator's yield ctype, so it knows `MojoList *` was
boxed — it just does not say so in a form the print ladder reads.

## Next step

`_emit_generator_start_call` already stores the whole api dict against the
handle in `gen._generator_var_api`. Record, alongside it, the CONTAINER kind
the value slot will carry (None when the value ctype is a real `char *` /
`double` / struct pointer), in the same registries `_gen_print` already
consults — `_boxed_container_vals` is the closest fit, and its existing
"dispatches on the registries rather than reading it as whichever kind
`_actual_types` happened to record" comment describes the wanted behaviour
exactly.

Two things to check while there, because they are the same question:

* the 2-argument `next(g, default)` form returns the DEFAULT on exhaustion,
  which may be a container while the yields are not (and vice versa). One
  registry keyed by "this handle's values are containers" is wrong for it;
  either key on the handle AND note the default's kind, or restrict the
  record to the 1-arg form.
* `for x in gl(): print(x)` and `list(gl())` — measured, and ALSO wrong, so
  this is not a `next()` consumer problem at all:

  ```
  CPython  : [1, 2] / [[1, 2]]
  compiled : 4365605040 / [4365605104]
  ```

  (pristine HEAD: `4340242416` / `[4340242480]`). Every consumer of the value
  slot reads a bare `int64_t`, so a container-yielding generator is wrong
  wherever its value is used, and `next()` is just the spelling that exposed
  it.
