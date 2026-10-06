# A local rebound to a container from a SCALAR keeps the container's C type, and the scalar store becomes a pointer cast

Found 2026-10-04 while closing
`CODEGEN_lambda_call_boundary_loses_the_return_type.md`'s nested-`def` row.
That doc named this shape as "a row that is NOT fixed and is not this fix's
business"; it has no doc of its own anywhere in `bugs/`, and the
`_multi_kind_locals` machinery that would carry it is documented in terms that
make the omission visible.

## What I ran

`gimple_codegen.compile_to_gimple` + `gcc -fgimple` + `runtime/fire_runtime.c`,
against CPython on the same text, via `.tmp/repro.py`'s harness (rebuild it from
this doc: compile the source, gcc `-fgimple -Iruntime` with
`fire_runtime.c`, run, diff stdout and exit code).

```python
def k():
    q = 5
    q = [1, 2]
    return q

print(len(k()))
```

CPython prints `2`. **So does the compiled program** — and that is the problem.
The generated C is not what a reader would write:

```c
MojoList * k (void)
{
  MojoList * q;
  int64_t _t1;
  MojoList * _t2;
  ...
  _t1 = (int64_t)5;
  q = (MojoList *)_t1;          /* <-- a length header read off address 5 */
  _t2 = mojo_list_new ();
  mojo_list_append_int (_t2, (int64_t)1);
  mojo_list_append_int (_t2, (int64_t)2);
  q = _t2;                      /* overwritten before anything reads it */
  return q;
}
```

`q` is declared `MojoList *` because
`resolve_shared._infer_local_var_types`'s `TypeLattice.join_all` joined
`['int64_t', 'MojoList *']`, and `TypeLattice.join` answers a
pointer-vs-anything pair with **the pointer**:

```python
if cls.is_pointer(t1) or cls.is_pointer(t2):
    ...
    return t1 if cls.is_pointer(t1) else t2
```

So the scalar store becomes a pointer cast and the value is a wild address. The
right answer happens to hold only because the second store overwrites the slot
before the `return` reads it — move the container store into a branch that
CPython does not take and the same program reads a header off `5`.

## The four shapes, measured

| program | CPython | compiled |
|---|---|---|
| `q = 5; q = [1, 2]; return q` | `2` | `2` — by luck (see above) |
| `q = None; q = [1, 2]; return q` | `2` | `2` |
| `if c: q = None else: q = [1, 2]; return q` | `2` | `2` |
| `q = 'ab'; if q: q = [1, 2]; return q` | `2` | `2` |
| `q = 5; if q > 1: q = [1, 2]; return q` | `2` | **exit 1** (TypeError at run time) |
| `q = 2.5; if q > 1: q = [1, 2]; return q` | `2` | **does not compile** |
| `q = 2.5; if c: q = [1, 2]; return q` | `2` | **does not compile** |

The last two are the loud ones, and they are loud for a reason worth reading
rather than skipping: the local is a `MojoList *`, so the comparison `q > 1`
lowers to a `list > int` comparison, which the codegen correctly refuses — it
emits `mojo_raise_type_error("'not supported between instances of 'list' and
'int'")` — and then still declares the slot `MojoList *` and stores `2.5`
into it:

```c
int64_t k (void)
{
  MojoList * q;                 /* the join's verdict */
  ...
  q = (MojoList *)2.5;          /* <-- gcc: cannot convert to a pointer type */
  _t1 = _slit_10000;
  mojo_raise_type_error (_t1);
```

That is the only shape in the table that **refuses to build**, and it is the
one in `CODEGEN_lambda_call_boundary_loses_the_return_type.md`'s closing
paragraph. `double` reaches it and `int` does not, because `join('int64_t',
x)` and `join('double', x)` differ once the store is emitted: `(int64_t)5` is a
legal conversion to a pointer in C and `(MojoList *)2.5` is not.

## Root cause: `_multi_kind_locals` counts two CONTAINERS, never a container
and something else

`resolve_shared._infer_local_var_types` keeps a second table for exactly this
question, and its own comment says so:

```python
_known_structs = set(gen.struct_field_types)
conflicting: set = set()
for vname in inferred:
    _kinds = {t for t in inferred[vname]
              if t in ('MojoDict *', 'MojoList *', 'MojoSet *')
              or gimple_exprtypes._is_known_struct_ptr_ctype(t, _known_structs)}
    if len(_kinds) > 1:
        conflicting.add(_as_str(vname))
```

`len(_kinds) > 1` means "bound to containers/structs of **more than one
kind**". A name bound to one container kind and one scalar has `len == 1`, so
it is not in `conflicting`, so `_gen_stmt_AssignStmt`'s "trust ground truth"
rule pins it to the container and every scalar store into it becomes a pointer
cast. The `None`-then-container rows in the table above are the same defect
and are equally unsound — they merely have nothing to read through the bad
cast, because `None` is `int64_t` 0 and every consumer of the slot either
tests it for null or overwrites it.

That is why the `char *` row works: `join('char *', 'MojoList *')` returns
`'char *'`, so the slot is declared `char *` and the list store launders the
pointer through it — the same boxing convention every other mixed pointer slot
in this compiler uses, which is why it happens to be right.

## Exact next step

1. Widen the `conflicting` test from "two container kinds" to "a container or
   struct pointer kind AND anything else", i.e.
   `if _kinds and len(inferred[vname]) > len(_kinds)`. Every name already in
   `conflicting` stays in it (the widening is strictly additive), and a name
   whose kinds are all containers is unaffected.
2. Measure the blast radius before believing it: this changes the DECLARED C
   type of locals across the whole corpus, so the two gate verdicts that need
   judgement are the ones CLAUDE.md names for a compiled-path change —
   `stdlib-dylib`'s `skip <module>:` count must not increase and
   `stdlib-syntax`'s unexpected-failure count must not increase. Also
   byte-compare the generated C for a large succeeding case before and after,
   which is the standard for a change meant to be behaviour-preserving.
3. The consumer side has to be ready for the box. With `q` an `int64_t`, the
   program needs three things that already exist and one that may not:
   - `len(q)` — `mojo_len_of_word` now asks the runtime's own registries, so a
     boxed container is answered correctly. **This row is why the fix above is
     cheap rather than a rewrite.**
   - `q > 1` — an `int64_t` compared with an integer, which is right for the
     `5` case and is exactly what CPython raises `TypeError` for after the
     rebinding, so the pre-existing `raise_type_error` path stops firing and
     the program's own control flow is right.
   - `print(q)` — already routed through `mojo_cstr_or_int_str` /
     `mojo_cstr_or_int_len`, so a boxed container prints as itself.
   - **`return q` out of a function whose inferred return type is
     `MojoList *`** — `_lambda_call_ret_locals` and the
     `_prebound_local_ctypes` overlay both refuse to record an `int64_t`
     answer, so the function's signature has to come out as the box too. If
     that arm turns out to need work, this doc's programs are the
     reproductions and step 1's measurement will say how much of the corpus
     depends on it.
4. If step 1's measurement says the blast radius is too wide to take in one
   commit, the honest split is by KIND rather than by module: `double` →
   container is the only shape that refuses to build today, so it can land
   first as its own narrowing (`is_float` on the non-container side) with
   `int` → container filed as the follow-up it is. Do not ship the narrowing
   alone as if it were the fix — the `int` rows are wrong C that happens to
   print the right number, which is the shape this project has been bitten by
   repeatedly.

## Not this doc's business, and worth knowing while fixing it

Two neighbouring facts, so the next reader does not re-derive them:

- The `if q > 1` comparison already has an honest refusal
  (`mojo_raise_type_error`) that fires because the slot was typed as a list.
  Widening `conflicting` makes that refusal stop firing, which is CORRECT for
  CPython (`5 > 1` is `True`) but means the refusal's own coverage loses a row
  it never should have had.
- `CODEGEN_lambda_call_boundary_loses_the_return_type.md` recorded this row as
  pre-existing and measured identical with and without its own change. That
  measurement still holds: this doc's programs behave the same before and
  after anything in that doc's history.