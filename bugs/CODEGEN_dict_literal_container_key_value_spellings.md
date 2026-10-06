# A dict literal's container key now renders by value; three gaps remain on the VALUE side

## Status (2026-10-04, `work/bugs6-1`): (2) is FIXED and it was not a mis-typed
## `vt`; (1) and (3) are re-diagnosed below and neither is where this doc's
## "Exact next step" said

The doc's next step guessed "print `vt` and `actual_atype` at
`_emit_dict_int_value_store`; (1) and (2) are almost certainly the same
mis-typed `vt`". **Neither is.** Measured on the tree this branch started from,
with the generated C in hand:

* **(2) was a KEY-DOMAIN mismatch, not a value type.** The store emitted
  `mojo_dict_set_bool(d, _t14, 1)` where `_t14 = mojo_cstr_or_int_str(...)` —
  the *materialised decimal string* — while the matching read emitted
  `mojo_dict_get_int_kw(d, _t20)` with the raw container word. One
  source-level assignment, two key DOMAINS, and the read saw neither entry.
  The cause is `_apply_kw_keys`' membership test: it asks whether the setter
  NAME is in `_KW_DICT_FNS`, so a setter with no `_kw` twin is not refused —
  it silently takes the "build the string now" arm. `_KW_DICT_FNS` listed
  `int`/`double`/`str` and not `bool`/`none`/`struct`/`other_struct`.
  **FIXED**: the four missing twins are in the runtime and the four names are
  in the set. `d[("a",)] = True; print(d[("a",)], len(d))` was `0 1`, is `1 1`;
  `d[("a",)] = None` is now reachable from `in` (`("a",) in n`), which it was
  not. Pinned by `test_gimple_runner.py`'s
  `gimple_container_keyed_store_reaches_its_own_read`.
* **(1) is a MODULE-GLOBAL receiver problem, and the LOCAL spelling is
  already right.** The same program inside a function prints `9.5`:

      def run():
          d = {}
          d[(1, 2)] = 3.5
          print(d[(1, 2)], len(d))       ->  3.5 1     (correct)

  and at module scope prints the double's IEEE-754 bits. The difference is
  `_dict_val_types`, which is keyed by the C TEMP the dict arrives in, and
  every reference to a module-scope `d` loads a FRESH one (`_t5`, `_t14`,
  `_t23`, `_t27` in the measured C). The store records its own temp and the
  read asks about its own, so the value-type record can never connect them
  across two references to the same global — while a local's temp is the same
  one on both sides. The store itself is correct in both cases
  (`mojo_dict_set_double_kw`), which is why the doc's `_emit_dict_int_value_store`
  step found nothing there.
* **(3) is a MISSING per-slot kind on the key tuple, and the fix is NOT a
  pointer-shape test.** The key is built `mojo_list_append_str(pair, ...)`
  with **no** `mojo_list_set_kinds` beside it — `_lower_list_literal` records
  kinds only when they are heterogeneous, and a one-element tuple of strings is
  homogeneous. So `mojo_dict_key_for`'s `_tuple_key_elem` asks
  `mojo_list_slot_kind(pair, 0)`, gets `'i'`, and renders the slot's ADDRESS as
  an integer; two calls to `k("a")` are two addresses, so the read misses.
  `mojo_boxed_is_str` is **not** the answer, and this doc's own next step
  gestures at it: its range test passes for any integer in `[2^31, 2^47)`,
  which is the interval the registered `ptrreg-boxed-str` row is about
  (`RUNTIME_int64_key_above_2gb_dereferenced_as_pointer.md`), so using it
  to DECIDE that a slot is a string turns a wrong key into a `strlen` of an
  integer. The tag has to come from the build, not from the word.

## Exact next step, for what is left

1. **For (3): record the per-slot kinds on a tuple the codegen builds, always,
   not only when they are heterogeneous.** The information is known at every
   `mojo_list_append_*`; what is missing is that it is dropped when the kinds
   are uniform. Two shapes, and the second is the one to check first because
   it costs no memory at all: record them at the point a tuple becomes a dict
   KEY (the subscript STORE and the `_kw` reads both have the key word in hand
   and `mojo_dict_key_for` is their only consumer), or have `mojo_list_append_str`
   assert the kind as it appends. The first needs the codegen to know a tuple
   is a key before it is built, which it does not; the second puts a row in
   `_reg_kinds` per list, and that table is never pruned except on
   `mojo_list_destroy`, so its cost has to be measured against
   `bugs/PERF_selfhost_memory_leak_hunt.md` before it lands.
2. **For (1): key the dict's value-type record on the SOURCE-LEVEL name when the
   receiver is an `IdentExpr`.** Both sides already have it — `_lower_subscript`
   is handed `node.value`, and `_gen_stmt_AssignStmt`'s subscript arm is too —
   and `_dict_val_of_expr` is the existing chokepoint for exactly this
   ("a subscript's receiver is always a source-level name"). The risk is that
   `_dict_val_types` has several consumers and a `double` entry under a global
   name reaches all of them; `_param_dict_val_types`' own note ("a separate
   table because `_inferred_param_types` re-types parameters all over the
   backend and a container entry there has effects far past comparison") is the
   warning to read first.

## What I ran

While merging `work/bugs3-codegen-5-r2` I found its
`gimple_tuple_dict_key_is_content_keyed` case red on arrival and fixed the half
of it that was a real defect (the KEY side: a dict literal rendered a container
key with `_repr_value` while every other key site hands the raw word to
`mojo_dict_key_for`, so a literal's container-keyed entry was unreachable from
every other spelling). Commit `ae9d7605`, and
`test_gimple_runner.py` is back to its pre-merge state with that case passing.

Probing the fixed path turned up three shapes that are still wrong. All three
were measured on the base commit `d0796643` as well, with byte-identical
output, so none of them is a merge regression and none is in the commit above.

Each was compiled with `test_gimple_runner.py`'s own
`compile_mojo_to_gimple_exe` and compared against CPython on the same text.

## What I saw, and what CPython prints

**1. A `double` value under a container key loses its fraction.**

    d = {}
    d[(1, 2)] = 3.5
    d[(1, 2)] = 9.5
    print(d[(1, 2)], len(d))

compiled `9 1`, CPython `9.5 1`. Identical on `d0796643`. The whole part is
dropped, which is the signature of the value going through an `int64_t` slot
and being read back with an integer accessor — `mojo_dict_set_double_kw` exists
and `_emit_dict_int_value_store` would pick it only if `vt` were a float type
here, so the `vt` reaching the store is not.

**2. A bool value under a container key prints `0`, not `True`.**

    d = {}
    d[("a",)] = True
    print(d[("a",)])

compiled `0`, CPython `True`. Identical on `d0796643`. This is the per-slot
bool kind (`mojo_dict_set_bool`, `_DictSlot.kind == 3`) not reaching the
container-keyed store: the container key takes the `_kw` twin route, and there
is no `mojo_dict_set_bool_kw`, so the store that actually runs is the `int` one.
Note the non-container spelling is right — `d["a"] = True` prints `True` — so
this is specific to the container-key path, not to the bool store.

**3. A runtime-BUILT string inside a tuple key is still address-keyed.**

    def k(s): return s + "!"
    d = {}
    d[(k("a"),)] = "R"
    print(d[(k("a"),)], len(d))

compiled `0 1`, CPython `R 1`. Identical on `d0796643`. So `mojo_dict_key_for`
renders this tuple's string slot by ADDRESS while the test's own
`for name in [...]: e[(name, len(name))] = 1` loop — which passes — goes
through a slot whose kind the renderer recognises. The difference between the
two is where the `char *` came from, which is the same evidence
`mojo_dict_key_for`'s element renderer is missing for a call result.

## What I expected

All three to match CPython, and specifically:

* (1) is the float accessor, not the int one — `3.5` and `9.5` both round-trip.
* (2) is a `mojo_dict_set_bool_kw` twin, or the per-slot kind set on the
  container-keyed store, so the repr says `True`.
* (3) is the string slot's kind reaching `mojo_dict_key_for`'s element
  renderer, which is what the docstring on
  `gimple_tuple_dict_key_is_content_keyed` already says is required ("that
  string slot is read by the model's own boxed-string discriminator rather
  than by a pointer-shape test"). A pointer-shape test cannot work here: two
  calls to `k("a")` are two addresses.

## Exact next step

All three live on the same seam, so they are one pass:

1. `_emit_dict_int_value_store` in `mojo/backend_gimple/emit_infra.py` chooses
   the setter from `val_ctype` alone, and the container-key path reaches it
   with a `vt` that is not the value's real type. Start by printing `vt` and
   `actual_atype` at that call site for each of the three fixtures above; (1)
   and (2) are almost certainly the same mis-typed `vt`.
2. For (2), check `runtime/fire_runtime.h` for a `mojo_dict_set_bool_kw`. If
   there is none, adding it is the honest fix, because the container-key route
   is `_kw`-only and the `int` twin is what currently runs. Do NOT special-case
   the literal spelling — the subscript store already goes through the same
   route and would stay wrong.
3. For (3), read `_tuple_key_elem` in `runtime/fire_runtime.c` (called from
   `mojo_dict_key_for`) and find why a `char *` slot built by a call result
   arrives with an unknown kind where a `for`-loop variable's does not.
   `mojo_list_slot_kind` / `mojo_boxed_is_str` are the established answers;
   the pointer-shape test the docstring warns against is not one of them.

Re-verify with `test_gimple_runner.py`'s `gimple_tuple_dict_key_is_content_keyed`
plus the three fixtures above, each against CPython, not against a hardcoded
string.

## Not fixed here, deliberately

`mojo_dict_key_for` raises `unhashable type: 'list'` for an unmarked
`MojoList`, which is CPython's answer for `d[[1, 2]]`. A dict LITERAL nesting a
bare list does not reach that refusal — it address-keys instead, because
`ae9d7605` kept `_repr_value`'s text rendering for keys that are not a
container at all, and a bare list IS a `MojoList *` so it does reach the
container arm. Verified: `lit = {[1, 2]: "L"}` compiles and runs with `len(lit)
== 0` on both trees. Turning that into the refusal is a separate decision: it
would make a currently-running program raise, and the self-host closure has to
be swept for it first (`compile_stdlib.py`, which the integrator runs).
