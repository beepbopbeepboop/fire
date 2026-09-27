# PARTIALLY FIXED: the constructor-call-site field-typing pass understood only scalars — a list/dict/set/tuple argument yielded an `int64_t` field that segfaults on iteration

**State: item 1 fixed for a container LITERAL argument, still open for a
local/field argument; item 2 fixed.** Found 2026-09-26 by re-testing the
claims in the removed `CODEGEN_unannotated_init_param_field_type_defaults_int64.md`.

## Status 2026-09-27

### Item 2 — FIXED. A field value round-tripped through a local keeps its type

`/tmp/w5/d_a.mojo` (one class, four getters differing only in how the value
reaches the `return`) is now CPython-identical for all four spellings:

```
$ python3 /tmp/w5/d_a.mojo          $ /tmp/w5/bin_d_a
str                                 str
str                                 str
str                                 str
str                                 str
```

Root cause, re-derived: **not** "nothing populates a variable-type map", as
the original analysis guessed. `_infer_local_var_types` *does* infer the
local correctly — `t = self.v` quick-types to `char *` once `self` is seeded
as `Holder *` (which the Pass-2b method loop does before calling it, so the
`struct_field_types` lookup in `_quick_type`'s MemberExpr arm succeeds). The
answer was then **thrown away**: the three sites that seed
`_infer_local_var_types`' result into `var_types` each admitted exactly one
ctype, a literal `== 'MojoBytes *'`:

- `mojo/backend_gimple/module_gen.py:3527` (Pass 2b, unannotated return type)
- `mojo/backend_gimple/module_gen.py:3663` (`_struct_method_signatures`)
- `mojo/backend_gimple/emit_funcs.py:3439` (`_gen_struct_method`)

`MojoBytes *` was the COMPILE_FAIL_zipfile bytes-accumulator case and nothing
else; the same `t = self.<field>; return t` shape with a `char *` or
`MojoList *` field was dropped identically and silently. All three now call
one shared predicate, `gimple_ctypes._seedable_local_ctype`
(`mojo/middle/types.py:262`) — "any `*`-suffixed answer", which is exactly the
class that cannot *be* `_quick_type`'s no-evidence `int64_t` default. SCALARS
are still excluded on purpose: see that function's docstring.

Consolidated from three private whitelists to one, per the project's
"consolidate duplicates" convention. Regression test:
`field_value_through_local_keeps_char_star_return_type` in `test_gimple.py`
(registered: `gimple`, in both `check` and `gate`) — it asserts the emitted
**definition** signature for all three spellings, not the forward
declaration.

### Item 1 — FIXED for a container LITERAL argument; OPEN for a local/field argument

`/tmp/w5/d_list3.py`'s exact repro now works:

```
$ python3 /tmp/w5/d_list3.mojo      $ /tmp/w5/bin_d_list3
1                                   1
2                                   2
3                                   3
                                   exit 0        (was exit 139, SIGSEGV)
```

and the generated C's ONLY difference from the annotated control is gone —
both now declare the same field:

```c
/* d_list3.ci, unannotated `items` */   /* d_list5.ci, `items: list` */
typedef struct Box {                     typedef struct Box {
  int64_t __mojo_type_id;                  int64_t __mojo_type_id;
  MojoList * items;                         MojoList * items;
} Box;                                     } Box;
```

The mechanism is **not** a new `ListExpr` case in `_arg_scalar_type`. That
observer's answers feed `_scalar_obs`/`_ctor_scalar_obs`, whose application
rule is "unanimous `char *` or unanimous `double`" and which is a *different*
rule from the one a struct field needs — and, measured, a *structurally
unsafe* channel for a container type (see the residue below). The fix went
into the channel that provably reaches the field:

- `mojo/middle/module_shared.py:594` — new `_gmi_container_ctype(v)`, the ONE
  answer to "is this expression a list / a dict / a set?", extracted out of
  `_gmi_collect_self_assigns`'s inline `self.<f> = <container>` chain (which
  is replaced by a call to it, behaviour-preserving) and reused by the
  constructor-argument pass. A tuple display answers `MojoList *` (a tuple IS
  a `MojoList` carrying a tuple tag — `mojo_is_tuple` / `_mojo_repr_list`).
- `mojo/backend_gimple/module_gen.py:2432` — the whole-module constructor-call
  scan (`_ctor_calls`, which already walked every call site in `stmts` AND
  `imported_stmts`) classifies a container-literal argument through that
  helper, and `:2459` accepts the three container ctypes in the unanimity
  gate. It flows into `_ctor_lit_param_types`, the channel the field-write
  pass consumes.
- `mojo/backend_gimple/module_gen.py:2467` and `:4701` — the raw
  container-literal evidence is handed to the *other* observer
  (`_ctor_scalar_obs`, the `_arg_scalar_type`-based method/free-body scan) as
  a **veto**. Without it, `Thing([1, 2])` beside `Thing("s")` let the scalar
  channel see only its own half of the evidence, find it unanimous, and type
  the field `char *` — a silent wrong answer where the documented rule is
  "not unanimous → leave unresolved, the `int64_t` default". The veto is
  veto-only by construction: it can refuse a slot, never resolve one.
  Regression test: `ctor_arg_mixed_container_and_scalar_stays_int64`.

Also now fixed, same cause, same channel (the original doc recorded the dict
and bool variants as "same-cause / no-current-symptom" rather than separate
findings; they are the same one-line classifier):

| argument | field type (all were `int64_t`) |
|---|---|
| `Box({...})` | `MojoDict *` |
| `Box({1, 2})` | `MojoSet *` |
| `Box((7, 8))` | `MojoList *` |
| `Box([i for i in ...])` | `MojoList *` |

All four field TYPES verified in the generated C (`typedef struct B1 …
MojoDict * v;` … `B4`) and the list/dict ones additionally verified by build +
execute: `len(b.v)`, `b.v[i]` and `for x in b.v` all agree with CPython.

Two *rendering* gaps are visible on the same run. Neither is this fix, and
both are named only so the next reader does not mistake them for residue:

- `print(b2.v)` for a `MojoSet *` field prints the set's ADDRESS — the
  `print` dispatch has no `MojoSet *` branch at all. `len()` and iteration on
  the very same field are correct. Pre-existing with no constructor in the
  program: `print({1, 2})` → an address.
- `print(B4([i for i in range(3)]).v)` — a field read straight off a
  CONSTRUCTOR TEMPORARY — renders `[None, 1, 2]`, because the field's element
  tracking is not propagated on that read path and `_mojo_repr_list`'s generic
  element reader then treats a `0` slot as `None`. Read through a local
  (`b = B4([...]); print(b.v)`) the same field is exactly right. A distinct
  element-type/`0`-is-`None` bug on the temporary path, not a field-type one:
  `B4([7, 8, 9]).v` prints `[7, 8, 9]` correctly today.

A `Box(x)` where `x` is a *local* bound to a container literal is NOT in this
list — it is the residue below.

Regression tests in `test_gimple.py` (registered):
`ctor_arg_container_literal_field_is_container_typed` (asserts the
unannotated and annotated spellings agree),
`ctor_arg_dict_and_set_literal_fields_are_container_typed`,
`ctor_arg_mixed_container_and_scalar_stays_int64`.

### The residue, precisely — `IdentExpr` / `self.<field>` arguments

`def mk(src): return Ident(src)` called with a list, and
`Reader(self._items)` called from a method, still leave the field `int64_t`
(measured: `/tmp/w5/c5.mojo`, `/tmp/w5/c6.mojo`, `/tmp/w5/c1.mojo` — `len`
prints the right number, the `for` segfaults; **this is the pre-fix state,
byte-identical, not a regression** — the generated struct is
`int64_t v;`).

Those two shapes need the CONTEXT-resolving observer (`self._inferred_var_types`
for a local, `self.struct_field_types` for a field), and that observer's
application channel is **not usable for a container type**. Measured, not
theorised — wiring `_arg_container_type` into it (its IdentExpr + MemberExpr
arms) turns `check` red:

```
FAIL  selfhost  (67s)  exit 1
myinterpreter.py:2283: error: non-trivial conversion in 'var_decl'
  struct MojoList *
  int64_t
  self->funcs = _t1;
myinterpreter.py:2292: error: assignment to 'int64_t' from 'MojoList *' …
myinterpreter.py:2294: error: assignment to 'int64_t' from 'MojoList *' …
```

The mechanism, located by instrumenting
`_gen_stmt_AssignStmt`'s MemberExpr-target branch: that observer's
application writes `self.struct_field_types[Struct][field]` **directly** on
the ROOT gen, which is what the typedef preamble renders from — but an
IMPORTED module's own method bodies are generated by a per-module temp gen
whose `struct_field_types` does NOT have the entry. So the struct typedef
says `MojoList * funcs` while the `self->funcs = funcs` inside that module's
`__init__` still resolves `field_type = int64_t` and emits an uncast store.
Instrumented proof, both structs in one dump:

```
_MojoTestSuiteDiscoverToken funcs field_type= MojoList *   <- resolved by the
                                                               literal channel
_MojoTestSuiteRunner        funcs field_type= int64_t       <- resolved by the
                                                               context channel
```

The scalar ctypes survive this only because `_arg_scalar_type`'s answers are
independently corroborated for them elsewhere; nothing about the channel is
container-safe.

**Exact next step** (not attempted — it is a reordering of two delicate
passes, not a drive-by): make the context-resolving constructor observation
reach the field through the SAME channel the literal one uses. Either
(a) move the whole context observation to run after
`self._inferred_var_types` is populated (`:3808`/`:3813`/`:5394`) and before
the `pm`/`_gmi_collect_self_assigns` field pass (`:2807`-`:2843`), writing
`_ctor_lit_param_types` like the literal observer does; or (b) keep the
position and make the per-module temp gen inherit the conclusion — which
means it has to reach `s.fields`' `VarDecl.type_ann`, i.e. a reverse
ctype→annotation spelling, which is why (a) is the better shape.

### Not touched, and not regressions

- **Printing a list of bools** — `print([True, False])` prints `[1, None]`
  with **no generator anywhere in the program** (measured, `/tmp/w5/bl.mojo`).
  Pre-existing, in the ordinary (non-generator) path: the list's element type
  is `int64_t` and `_mojo_repr_list`'s generic element reader has no bool
  knowledge. Unrelated to this doc.
- **A module-level global list** passed to a constructor
  (`src = [5, 6]; Ident(src)`) — same residue as above; globals live in
  `self._global_var_types`, not `self._inferred_var_types`, so even the
  context observer's IdentExpr arm has nothing to read.
- **Mixed scalar call sites** (`Thing("str")` + `Thing(3.5)`) still print an
  address and `3` — the documented, correct-by-design `int64_t` default
  (verified again 2026-09-27: `4335788288` / `3`).

## Where

- `_gmi_container_ctype` (new, the shared classifier) —
  `mojo/middle/module_shared.py:594`. Its one former inline copy, inside
  `_gmi_collect_self_assigns`, now calls it.
- The whole-module constructor-call scan that consumes it —
  `mojo/backend_gimple/module_gen.py:2377`-`:2474`; the unanimity gate at
  `:2450`; the cross-channel veto published at `:2467` and applied at
  `:4701`.
- `_CTOR_CONTAINER_CTYPES` / `_gmi_is_ctor_container_ctype` —
  `mojo/backend_gimple/module_gen.py:794`/`:797`.
- The three duplicated local-ctype seed whitelists, now one predicate —
  `mojo/middle/types.py:262`, used at `module_gen.py:3527`, `module_gen.py:3663`
  and `emit_funcs.py:3439`.
- The observation pass the residue needs, and whose application channel is the
  blocker — `_arg_scalar_type`, `mojo/backend_gimple/module_gen.py:3851`; its
  application at `:4682`-`:4730`.
- The contrasting free-function pass that *does* special-case containers —
  `mojo/middle/infra_infer.py:213` (`_infer_param_types`).

## Test coverage note (unchanged, still true)

`test_gimple_runner.py` — 124 tests — is still in **no** bucket, in **no**
Make target the gate runs. Its two regression tests for the removed doc
(`gimple_ctor_arg_from_method_self_field`, `gimple_ctor_arg_unanimous_str_and_int`)
and its generator sibling `test_gimple_generator_runner.py` (145 tests) are
still ungated. All eight new tests for this work went into **`test_gimple.py`**
instead (registered as `gimple`, in both `check` and `gate`) for exactly that
reason. Registering the two runners is a `tools/suite.py` change, deliberately
not made here.
