# A dict literal's container key now renders by value; three gaps remain on the VALUE side

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
