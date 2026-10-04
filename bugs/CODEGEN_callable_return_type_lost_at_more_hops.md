# CODEGEN: a callable's return type and calling convention, at the two more hops that were still open

**State: CLOSED 2026-10-02 — all three items measured, all three now agree
with CPython.** The doc is kept (rather than deleted) because its #1 item
names the shape-independent check every one of the three hangs off, and
because the mechanism it introduced — `_return_callable_ret_types` and the
node attribute that carries it — is what the fix below extends. Verified with
CPython alongside; the two new regression cases are
`test_gimple_runner.py`'s
`gimple_function_returning_a_callable_keeps_its_return_type` and
`gimple_bound_method_in_a_module_global_keeps_its_convention`.

## Status at the start of this session

Item 1 (a function calling a module global's callable) and item 3's return-type
half were already fixed on this tree when this session opened — both shapes
print CPython's answer, and item 1 is covered by the existing
`gimple_module_level_callable_keeps_its_return_type`. Item 3's CALLING-CONVENTION
half was still wrong and is the one that needed the most work. Item 2 was
still wrong.

## 1. FIXED before this session — a FUNCTION calling a module global's callable

Unchanged. `gimple_module_level_callable_keeps_its_return_type` is the check,
and the doc's own "why the obvious fix is not the obvious fix" analysis still
stands: `_reset_func` clears the value-keyed tables at every function entry
because `_tN` recycles, and `gen_module_impl` calls `_gen_toplevel` after
every `FunctionDef`, so a function's body is generated before the module
scope's. The answer a function needs is therefore compile-scoped, not
function-scoped — which is what `_global_callable_ret_types` and Phase 1.7's
`_lambda_ret_type` pre-pass are.

## 2. FIXED here — a function RETURNING a callable

```python
def a():
    e = lambda: False
    return e
def c():
    e = a()
    print(e())        # CPython False; compiled 0
```

`int64_t a (void)` boxes the `void *` callable into an `int64_t`, and `c`'s
assignment records nothing.

**Why the existing carry could not do it.** `ginf.carry_callable_ret_types`
copies the three value-keyed tables from the lowered VALUE `v` to the
destination name. A call result is a fresh temp with no entry to copy: the
fact lives on the AST (`node._callable_ret`, set by `GimpleGen.lower_expr`,
which exists for the `mk()(...)` direct-callee spelling) and, before that, in
the compile-scoped `_return_callable_ret_types['a']` that the callee's own
`return` wrote. The new `emit_infra.carry_callable_ret_from_call` reads the
callee name straight off the CallExpr and writes the destination's entry. It
is called from the same four store sites that call the shared carry, because
"a copy that is silently forgotten is a wrong value with exit 0" — the
sentence is the existing helper's own, and it is why this one is four calls
and not one.

Only `_callable_ret_types` is written: that is where a non-capturing closure
or a lifted free function lands. A callee returning a `MojoBoundMethod *` is
the `_bound_method_ret_types` family and is not claimed.

## 3. FIXED here — a BOUND METHOD stored in a module global

```python
m = C()
f = m.truthy
print(f())        # CPython True; compiled 1, exit 0
```

`print(1)` is the wrong answer; the deeper defect is that it is a call with
the WRONG ARITY. The generated C said so:

```c
_root_globals.f = _t7;         /* the MojoBoundMethod * boxed */
_t11 = (void *)_t10;
_t12 = mojo_fnptr_call_0 (_t11);
```

`mojo_fnptr_call_0` calls the RAW method symbol with no `self`. It printed `1`
rather than crashing, which the doc recorded as luck and not a property — and
the `add(a, b)` shape in the new regression is two arguments, which is what
makes the arity visibly wrong rather than merely untidy.

Three facts, each one a place the code asked a question it had never asked:

1. **The kind is known at the store and thrown away.** The value's own type at
   `f = m.truthy` IS `MojoBoundMethod *`; the globals-struct FIELD is
   `int64_t` (`_global_dst_ctype`), and that is the type the call site sees.
   The store now records `gen._actual_types['f'] = 'MojoBoundMethod *'` —
   the same overlay `_lower_MemberExpr` already uses for a boxed container
   pointer, and the same one `_lower_call`'s
   `_get_actual_type(_fname_var_ctype, fname_raw) == 'MojoBoundMethod *'`
   guard already consults. The predicate is the presence of a
   `_bound_method_ret_types` entry for the destination name, which is sound
   because that table holds a `MojoBoundMethod *` and nothing else.
2. **`_lower_bound_method_call` did not resolve a global's name.**
   `_lower_fnptr_call` and `_lower_maybe_bound_call` both have the
   three-branch routing (capture → `_env->name`; module global →
   `_lower_IdentExpr`, because a global is a field of the globals struct and
   not a C identifier; otherwise `_c_names`). `_lower_bound_method_call` went
   straight to `gen._c_names.get(fname_raw, fname_raw)`. With (1) in place
   this became reachable and failed to BUILD — gcc's `'f' undeclared` — so
   (2) was not optional polish: it is the third link in the chain.
3. **The return-type carry was already there and already worked.**
   `_bound_method_ret_types['f']` was `_Bool` (measured) before either of the
   above, which is why `gimple_capturing_lambda_inlined_at_call`'s family of
   "the type is missing" fixes did not reach this: here the TYPE was present
   and the CONVENTION was wrong. The doc's note that "the same carry is now
   applied and the convention is still wrong" was exact.

The `local()` lines in the new regression are the control: the identical
spelling bound to a LOCAL was always right, because a local keeps its
`MojoBoundMethod *` type. That is what made this look like another return-type
carry rather than a calling-convention bug.

## The original write-up follows, with each item's original next step

(kept for the two diagnoses that are still the best description of the code)

---

## 1. A FUNCTION calling a module global's callable — generation order

    g = lambda: False

    def show():
        print(g())

    show()

Measured directly (instrumenting `_lower_call` and `_lower_LambdaExpr`):

    CALL G in show in_toplevel False      <- _callable_ret_types is {}
    LAMBDA-lift, ctx = _toplevel          <- the global's store, far too late

So the answer a function needs is only ever known after the fact.

### Why the obvious fix is not the obvious fix

Emitting `_toplevel` first would fix it, but the pre-pass immediately above
it ("Reconcile toplevel global C types with LATE-resolved callee return
types") exists precisely because the toplevel body *needs* information the
function passes produce. Reordering is a real change to emission order, not
a one-liner, and it is the same class of reordering the two lambda bug docs
describe as hazardous.

Recording the global's type in the existing pre-pass means re-running the
lambda's return-type inference there, i.e. a SECOND implementation of what
`_lower_LambdaExpr` does — which CLAUDE.md's "consolidate duplicates rather
than maintaining parallel implementations" rules out, and which would let
the two disagree.

### Next step

Either make the module-global callable's return type a COMPILE-scoped fact
recorded once, in a pre-pass that reuses `_lower_LambdaExpr`'s own inference
rather than repeating it, or emit the module body before the functions and
re-gate. The first is much smaller. **This is what landed** —
`_global_callable_ret_types`, seeded in `_reset_func` from Phase 1.7's
`_lambda_ret_type`.

## 2. A function RETURNING a callable — the type stops at the return

    def a():
        e = lambda: False
        return e

    def c():
        e = a()
        print(e())

`func_return_types` records `a` as returning `int64_t`, so `c`'s assignment
records nothing. Same family as #1 — nothing carries the type across the
call — but a different hop, and fixing #1 did not fix this one. **The next
step this section named is what landed**: a per-function "the callable this
function returns, and what THAT returns" record, written at the `return`
(`_return_callable_ret_types`, module scope for the flush-ordering reason the
value-keyed tables cannot have) and read at the call site. The value-keyed
half it also needed is `carry_callable_ret_from_call`.

## 3. A BOUND METHOD stored in a module global loses its CALLING CONVENTION

    class C:
        def __init__(self):
            self.k = 9
        def truthy(self):
            return self.k > 4

    m = C()
    f = m.truthy
    print(f())

The identical spelling inside a `def` is right. At module scope the globals
struct field is `int64_t` (`_global_dst_ctype`), so `_lower_IdentExpr`'s
global read returns `int64_t`, and the call site routes to
`mojo_fnptr_call_0` — which calls the RAW method symbol with no receiver.

**Next step, as this document stated it:** the globals struct field's declared
C type has to be the value's real type (`MojoBoundMethod *`) for a global
bound method, the way it is for a local, and the global-read path needs the
same `_actual_types`-style overlay `_lower_MemberExpr` already uses for a
boxed container pointer. **Both landed**, with one correction worth
recording: changing the field's declared type would have been the wrong move.
The field is shared by every value a global can hold, so the field cannot
carry a per-value kind; the per-value kind belongs in `_actual_types`, which
is what the call site already consults for exactly this reason.
