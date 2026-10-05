# CODEGEN: calling a function value held in a subscript returned 0

**State: CLOSED 2026-10-02.** Every shape this document measured is fixed,
including the two its own 2026-10-01 entry left open. The only shapes still
stubbed are the two it recorded as *deliberately* out of reach
(`a[i]['k'](...)`, `self.d['k'](...)`), and the reason it gave for those is
unchanged and is restated at the bottom.

## What is fixed, measured against CPython

| shape | before | now |
|---|---|---|
| `d['k'] = lambda a, b: a + b` → `d['k'](2, 3)` | `0` | `5` |
| `d['k'] = lambda *a: ...` → `d['k'](2, 3)` | `0` | `5` |
| `d['k'] = add3` (a lifted free function) | `0` | `6` |
| `d['k'] = lambda x: x + n` (a CAPTURING lambda) | `0` | `11` |
| `dd['m'] = C().m` → `dd['m'](4)` (a `MojoBoundMethod *`) | `0` | `8` |
| `lst = [add3]` → `lst[0](1, 2, 3)` | `0` | `6` |
| `lst = []; lst.append(add3)` → `lst[0](1, 2, 3)` | `0` | `6` |
| `lst = [add3 for _ in range(1)]` → `lst[0](1, 2, 3)` | `0` | `6` |
| `t = (add3,)` → `t[0](1, 2, 3)` | `0` | `6` |
| `e['c'] = mk(100)` → `e['c'](1)` (a call result) | `0` | `101` |

Regressions in `test_gimple_runner.py`: the pre-existing
`gimple_call_through_subscript_callee` and
`gimple_dict_held_bound_method_through_subscript`, and the new
`gimple_call_through_a_list_subscript_callee` (all three list-building
spellings, the tuple, and the `mk` case with a bare-function-pointer-first
control beside it).

## The three changes, and why they are one change

The gate is a POSITIVE test: `_lower_call`'s runtime-subscript-callee arm
asks "was a callable recorded being stored into THIS container?", and answers
`False` for a container nothing has ever recorded — which silently leaves the
stub. Every shape above was that same `False`.

1. **THE TABLE IS NOT ABOUT DICTS, AND IT now says so.** `_dict_callable_ret`
   is `_container_callable_ret` (and `_global_dict_callable_ret` is
   `_global_container_callable_ret`), and `note_dict_callable_ret` is
   `note_container_callable_ret` with a `container_val` parameter — across
   `gimple_codegen.py`, `emit_infra.py`, `module_gen.py`, `emit_calls.py`,
   `emit_stmts.py` and the two test files. The consumer was always
   container-neutral (it never asks which kind it is); only the name lied.
   `gimple_codegen.py` is compiled by the self-hosting bootstrap, so both
   sides change together, as the doc's own next step required.

2. **ALL THREE LIST-BUILDING PATHS NOW RECORD.** `_lower_list_literal`'s and
   `_lower_tuple_literal`'s single append loop, `_lower_list_method`'s
   `append`, and `_gen_compr_append`'s list arm. Three chokepoints, one
   helper, one call each. Recording the literal alone was the doc's proposed
   alternative and it was not enough: the shape a real dispatch table is
   assembled in is a loop with an `append`, and it would still have been
   stubbed — which is what the doc's "a list built by `append` would still be
   stubbed" predicted.

   The value handed to the helper is the PRE-cast `ev`, not `ev_cast`: the
   callable tables are keyed by the name `lower_expr` produced, and the cast
   into the list's slot mints a fresh temp with no entry. Getting that
   backwards is why the first attempt at this recorded nothing and looked
   like a no-op.

3. **A CALL RESULT.** `e['c'] = mk(100)` stores a value no materialization
   site recorded. Its fact is under the callee's NAME in
   `_return_callable_ret_types`, which the callee's own `return` wrote — the
   same compile-scoped record `emit_infra.carry_callable_ret_from_call` reads
   for the named-local hop, and it has to be read again here because this is
   a different destination. `note_container_callable_ret` takes the value's
   AST node and consults it after its two value-keyed sources and before its
   `MojoBoundMethod *` fallback.

There is also a fourth change this doc's 2026-10-01 table called "already
closed" that was NOT: `d['k'] = add3`, a bare lifted free function. Its
`_lower_IdentExpr` function-value branch minted `_funcptr_<csym>` and returned
it without recording what the function RETURNS — so
`note_container_callable_ret`'s first source had nothing to find and the whole
table stayed empty. Measured on this tree before the fix (and not caused by
it: the same `0` at `bc17a62b`). That branch now records
`_callable_ret_types[t] = func_return_types[name]`, which is what its two
siblings already did — a capturing closure records
`_bound_method_ret_types`, a lambda records `_callable_ret_types` in
`_lower_LambdaExpr`. Without it the doc's own "closed" row was a claim about
a tree this one is not.

## Still open, deliberately

`a[i]['k'](...)` and `self.d['k'](...)` keep the stub, for the reason this
document originally gave and the fix has not changed: the discriminator reads
the container's name out of the type TABLES, and a base that is not a plain
`Name` has no name to read them by. `a[i]` is a subscript and `self.d` is a
field; both would need the base's C expression, and `lower_expr` has side
effects (it emits statements and allocates temps), so probing with it and
discarding the result emits the same code twice. A negative test ("the base
looks like a container") is what this bug's own history rules out: finding
that out cost a real regression, where `re`'s `_RE.finditer(src)` reached this
branch with a tuple index and a plain-`int64_t` base and the value-lowered
finditer result landed in the wrong place in the generator's C++.

The next bounded step for those two is a *name-based* discriminator that does
not need the base lowered: record the container under the names an `append` /
`setitem` store used (`self.d` is a field, so `_struct_field_elem_types`-shaped
side data would be needed) — i.e. the same fact keyed by a second route, which
is a real piece of work and not a one-liner.

## The original report (2026-09-30) follows, unchanged, because its mechanism
## analysis is still the reason the fix looks the way it does

CPython prints `5`; the compiled path prints `0`, exit 0, for BOTH a plain
lambda and a variadic one. The INTERPRETER agrees with CPython here
(`python3 fire.py run` prints `5`), so this is the compiled path alone.

`CallExpr.func` here is a `SubscriptExpr`. `_lower_call` value-lowers its
callee for exactly two shapes — a chained `CallExpr` and a `LambdaExpr` (see
its own comment, "ONLY a CallExpr callee (a genuine chained call) and a
LambdaExpr callee (an immediately-invoked lambda — a real runtime callable
value) are value-lowered here"). A `SubscriptExpr` callee deliberately does
NOT take that route: the comment records that a subscript callee is "a GENERIC
TYPE/constructor expression (`Scalar[x.dtype](...)` — a comptime bracket
argument, not a runtime value), whose eager value-lowering would miscompile
(found via math.mojo's `Scalar[x.dtype](...)`)".

That exemption is right for the *generic bracket* spelling and wrong for a
plain runtime subscript on a dict or list holding a callable — the two are not
distinguishable at the point the check is made, so the safe-looking rule
silently stubs the second. That is why the discriminator is
`_static_generic_return_ctype` FIRST (it answers only for a base NAME this
compile recorded as an IMPORTED GENERIC) and the positive container test
SECOND.
