# A cursor over a MATERIALISED sequence needs nested-element cursors, and the
# three `MojoList *` files then need four more symbols

## Status

OPEN, 2026-10-03. Not fixed: the first step below was prototyped and measured
and it is a feature, not a one-line widening, and the second half is four
unrelated symbol gaps. Filed from the session that integrated the parallel
stdlib-xfail tree and removed `test/collections/test_span.mojo` from
`EXPECTED_FAILURES`, so the next reader knows the shape is bounded and where
its first obstacle is.

Part of the family in
`bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md`; this doc
is only about the FOUR files whose receiver is a real pointer rather than a
boxed integer, which is the half that does NOT need type-argument inference.

## The four files, and what each receiver is

Re-measured on the merged tree (`emit_calls._lower_call`'s `next(...)` refusal,
which names the receiver's C type as codegen computed it):

| file | receiver | what produced it |
|---|---|---|
| `test/iter/test_enumerate.mojo` | `MojoList *` | `enumerate(x)` in VALUE position eagerly materialises the `(index, element)` pair-lists into a `MojoList *` (`emit_calls._lower_builtin_enumerate_value`) and returns it |
| `test/collections/test_set.mojo` | `MojoList *` | same |
| `test/python/test_python_object.mojo` | `MojoList *` | same |
| `test/iter/test_zip.mojo` | `void *` | `_lower_builtin_zip_n` returns `'void *'` ON PURPOSE — its own comment records that typing it `MojoList *` broke `funcs_shared.py`'s nested-tuple comprehension target over `zip` and took the whole self-host compile down. `mojo/middle/types.py`'s `'zip': 'MojoList *'` is the STALE half of that pair and disagrees with it |

So `next(it)` on these is correct Mojo with no new lowering: the value IS a
materialised sequence, and a caller that stores one in a variable and calls
`next()` on the variable is iterating it. Round 4 (a) of the family doc reaches
the same conclusion for `enumerate`.

## Step 1, prototyped and measured: the cursor admits the value, but the ELEMENT
## is a nested container and the cursor cannot read one

`_try_bind_iter_cursor` gates on `value.func.name == 'iter'`. Widening it to
admit a materialising builtin is correct and compiles:
`test/iter/test_enumerate.mojo`'s `next(it)` refusal disappears and the generated
C reads the outer list's slots. It then prints the WRONG thing, and the reason
is the element type:

    # it = enumerate(["hey", "hi", "hello"]); print(next(it)[0], next(it)[1])
    compiled:  h e        (and h i for the second pair)
    CPython:   0 hey

`_lower_builtin_enumerate_value` records the pair typing — `gen._elem_types[res]
= 'MojoList *'` and `gen._nested_elem_types[res] = ['int64_t', elem]` — so the
information exists and is correct. What the cursor does with it is the gap:

* `itc.slot_ctype('MojoList *')` returns `'int64_t'`, so `next(it)` is typed as
  an integer;
* `itc.read_at`'s 'list' branch calls `list_suffix('MojoList *')` → `'int'`, so
  the read is `mojo_list_get_int(...)`, i.e. a boxed pointer presented as an
  integer — and `elem[0]` then reads whatever the print/subscript path guesses.

The fix is a nested-element cursor: `slot_ctype` must answer `'MojoList *'` for
a container element, and `read_at` must return the boxed pair TYPED as a
`MojoList *`. That last part is where this stops being small: the value has to
come back through a temp, because a cast applied directly to a CALL result in
an assignment RHS is `error: invalid operand in unary operation` under
-gimple (measured — the same constraint the `Span(<list>)` fix in the family
doc works around, and the same one that makes a NESTED cast
`error: expected expression before '(' token`).

## Step 2, independent of step 1: three of the four files then link to nothing

The parallel tree BUILT step 1 for `enumerate` and measured the link, and
parked it for this reason (`tools/linkcheck.py`, against runtime + the dylib):

| file | undefined after runtime + dylib | verdict |
|---|---|---|
| `test/iter/test_empty.mojo` (accepted green) | 11 — the libc + `std.testing` baseline | the bar as applied |
| `test/iter/test_enumerate.mojo` | **8 — exactly that baseline** | would pass |
| `test/collections/test_set.mojo` | 16, incl. `_Set` | would not |
| `test/python/test_python_object.mojo` | 18, incl. `_Python`, `_PythonObject`, `_int64_t_as_unsafe_any_origin` | would not |

Those four names are unrelated pre-existing gaps — `_Set` is the census's
generic-struct family, `_Python`/`_PythonObject` are imported STRUCT TYPES
called as functions, and `int64_t_as_unsafe_any_origin` / `conforms_to` are
names this codegen synthesises that exist nowhere in the stdlib or the runtime.

**This is why step 1 cannot be landed alone, and it is a rule rather than a
preference:** `compile_stdlib.py` exits non-zero on any `EXPECTED_FAILURES`
entry whose file now PASSES. Binding the cursor makes all three
`MojoList *` files pass `gcc -fsyntax-only`, so all three entries must come out
— and two of them would then be green on a syntax check whose artifact links
to nothing. That is the exact trade this project rejects. So the order is: the
four symbols, THEN step 1, THEN remove the three entries, and gate each removal
on `tools/linkcheck.py` rather than on the sweep.

## Step 3: `test_zip` needs a DECISION, not a fix

`zip(a, b)` materialises pair-lists exactly as `enumerate` does, so steps 1–2
would give it a cursor too — except its value types as `void *`, by a decision
recorded in `_lower_builtin_zip_n`'s own comment (a `MojoList *` return broke
the self-host compile). The decision to re-take is whether that self-host shape
has since been fixed by something else; `mojo/middle/types.py:321`'s
`'zip': 'MojoList *'` is the stale half of the disagreement and should be
corrected either way, since two tables in the tree currently disagree about
what `zip` returns.

## Next step, in order

1. Nested-element cursors in `mojo/middle/itcursor.py` (`slot_ctype` +
   `read_at`), with the two GIMPLE cast constraints honoured by materialising
   through temps. Acceptance bar: the four-line program above prints `0 hey` /
   `1 hi` in both pipeline modes.
2. The four symbols, each as its own change with its own artifact evidence.
3. Widen `_try_bind_iter_cursor` to the materialising builtins, and remove
   `test/iter/test_enumerate.mojo`, `test/collections/test_set.mojo` and
   `test/python/test_python_object.mojo` from `EXPECTED_FAILURES` in the SAME
   commit — with `tools/linkcheck.py` run on each first, and its undefined set
   at or under the accepted-green baseline.
4. Decide `zip`'s `void *`, and fix whichever of the two disagreeing tables is
   wrong.