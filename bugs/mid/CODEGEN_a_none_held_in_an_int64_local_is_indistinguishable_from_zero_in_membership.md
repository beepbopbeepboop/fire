# CODEGEN: a `None` held in a variable is the int 0 when it is a `in` needle

**State: PARTIAL, found 2026-10-31; partial fix 2026-10-31** (see Status at the end). While fixing the `1 in ["a", 1]` SIGSEGV (the int needle over a kind-mixed list).
A `None` LITERAL needle is now handled exactly (`None in ["a", None]` is True,
`None in [0, 1]` is False). A `None` held in a VARIABLE is not: the local is
lowered as an int64 word, and that word is the same as the int `0`.

Repro:

    def main():
        n = None
        print(n in ["a", None])
    main()

- CPython: `True`
- compiled: `False`

The generated C is `int64_t n; n = 0LL;` and the membership reads `_t6 = n;`
then `mojo_list_contains_mixed_int (_t1, _t6)`, so the needle is an int 0 by
the time the membership is lowered. Master also answers `False` here, so this
is not a regression from the int-needle fix; it is the same underlying gap.

Cause: the value ABI has no None word. The generator-yield None family ("a None yield value prints 0",
fixed on the default path) records the same representational fact for generator yields ("a None value
cannot be represented in the word at all"). The membership lowering can only
see the static type `int64_t`, so it applies the int meaning, which is the
right answer for `0 in ["a", None]` and wrong for a None variable.

Next step: the fix needs a None-typed local, not a membership change. Either
(a) the lowering records, per local, that it was last assigned `None`
(the same bookkeeping `_int_word_vals` uses) and lowers the membership against
the NULL needle when it is still that value, or (b) the None value gets a
tagged representation (the ABI change the yield doc describes). (a) is a
bounded codegen change; (b) is the owner-level one. Pin with
`test_gimple_matches_cpython` in `test_gimple_runner.py` for `n = None` used as
an `in` needle against a list with and without a None slot.

## Status

**2026-10-31, partial fix (option (a), narrowed).** Landed in
`mojo/backend_gimple/emit_exprs.py`: `none_only_locals(gen)` returns the locals
of the function being lowered whose EVERY binding is the literal `None` (no
other assignment, augmented/tuple/for/with/except/walrus target, parameter,
import, `global`/`nonlocal`, nested def name, or `match` anywhere in the
function). `is_none_needle(gen, node)` treats such a local as a `None` needle,
so `n in [...]` takes the NULL-needle path (`mojo_list_contains_str` with a NULL
needle, or `mojo_list_contains_none`), exactly as a `None` literal already did.
The per-function cache (`_none_only_names`) is reset in `_reset_func` and saved/
restored with the nested-function state in `emit_infra.py`.

Pinned by `test_none_bound_local_is_none_not_zero_in_membership` in
`test_gimple_runner.py` (registered in the late-test list): the repro, the
no-None-slot list, `not in`, and a second function whose `n = 0` must still be
an int.

**Still open.** A local that is `None` on one path and some other value on
another keeps the int path. Probe (CPython `True`, compiled `False`):

    def main():
        n = None
        if len("ab") > 5:
            n = 1
        print(n in ["a", None])
    main()

The flow-insensitive check cannot answer this, because the local has a
non-None binding. The next step is either (1) a flow-sensitive record of which
locals are None at the membership point, which needs the join points of `if`/
`while`/`try` lowered into the bookkeeping, or (2) the tagged None word the
none-yield fix introduced for generator yields, which removes the ambiguity at the value level. Dict and set
membership of a None-held local are also still unaddressed: `x_is_none` only
reaches the list branch, and the `none_only_locals` answer is not consulted by
`_lower_in_dispatch`'s dict/set arms.

### 2026-10-31, planning round: the dict/set side is a stored-None representation gap

This round set out to land the dict/set None-needle arm the section above
names as unaddressed. The probes below show that a needle-only change cannot
be correct, so nothing was landed; the guide here is the output.

**Measured (compiled vs CPython, via `test_gimple_matches_cpython`):**

    s = {None, 1}
    print(0 in s, None in s)        # CPython: False True   compiled: True True
    d = {None: 1, "a": 2}
    print(0 in d, None in d)        # CPython: False True   compiled: True True

    def main():
        n = None
        s = {0, 1}
        print(n in s)               # CPython: False        compiled: True

So the cause is the STORED side, not only the needle. `_lower_set_literal`
lowers a `None` element through `lower_expr`, which yields the int64 word 0,
then calls `mojo_set_add_int` (or `mojo_set_add_word`). The stored None is
the int 0 slot. The needle side is the same word, so a None needle can never
be told apart from an int 0 in a set or dict. `None in {0}` is wrong today
too, and it is a literal, not a local.

**Why not a needle-only arm:** `x_is_none` in the dict/set arms of
`_lower_in_dispatch` would answer "does the set hold the None word", which
requires the stored None to have a word distinct from 0. Without that, the
arm is either `mojo_set_contains_int(0)` (today's wrong answer) or a constant
False (wrong for `{None, 1}`, where `None in s` must be True).

**Decision needed (the owner-level one, option (b) above):** where the None
member is kept in a set/dict.
- (i) A new slot tag, consistent with the existing per-kind domains. Sets
  already tag slots (`_SetSlot.tag`: 0 int, 1 str, 2 bytes; `_set_slot_str_tag`
  takes a tag), so a None member is tag 3. Dicts keys already carry a domain
  (`_DictSlot.keykind`, where bytes is kind 2 and `mojo_dict_contains_bytes`
  uses it), so a None key takes the next keykind.
- (ii) A `has_none` flag on `MojoSet`/`MojoDict`. Smaller, but iteration,
  `len`, repr, `sorted`, copy and union each need to know about it, and the
  flag misses per-slot ordering (`_SetSlot.seq`).

**Recommendation: (i).** It follows the pattern the set and dict already use
for bytes, so the iteration and repr code gains one kind rather than a second
mechanism. Its cost is that every site that switches on `tag` must learn tag 3:
`runtime/fire_runtime.c` has 54 `.tag` references, including the rehash
`tag == 1 || tag == 2` test at line ~7040, and `_set_slot_int`/`_set_slot_str`
at ~6915-6960.

**Implementation plan (for the next round, in order):**

1. `runtime/fire_runtime.c` + `fire_runtime.h`: `mojo_set_add_none(MojoSet *)`,
   `mojo_set_contains_none(MojoSet *)`, `mojo_set_discard_none(MojoSet *)`,
   using tag 3 and a fixed key (no value word). Audit all 54 `.tag` sites:
   iteration (`mojo_set_iter_*`, line ~7391-7438) must yield None for tag 3, the
   repr must print `None`, and the rehash at ~7040 must keep tag 3 slots.
2. `runtime/fire_runtime.c`: `mojo_dict_contains_none` / a None keykind, same
   pattern as `mojo_dict_set_none` (which is a None VALUE, kind 4, not a key).
3. `mojo/backend_gimple/emit_exprs.py` `_lower_set_literal` (~line 7020): a
   `None` element (`is_none_needle`-style check on the AST node, before
   `lower_expr`) emits `mojo_set_add_none`, not `mojo_set_add_int`. The same
   for `set.add(None)`, and for the dict key path in `_lower_dict_literal`.
4. `emit_exprs.py` `_lower_in_dispatch`, dict and set arms: when `x_is_none`,
   call `mojo_set_contains_none` / the None-key contains. The dict-subclass
   branch (`_dsub_in`) takes the same arm unless the subclass defines
   `__contains__`.
5. Local-needle decision (the flow-insensitive `none_only_locals` already
   answers the common case) is unchanged by this step.

**Tests that prove it (add to `test_gimple_runner.py` next to
`test_none_bound_local_is_none_not_zero_in_membership`, all via
`test_gimple_matches_cpython`):** the two stored-None probes above (set and
dict), plus `n = None; s = {0, 1}; n in s` (must be False), `None in {0}`
(False), and `None in {None, 0}` (True). These currently FAIL, so they are the
regression tests for step 1-4. The stdlib-compile gate is the integrator's.

**Not yet attempted:** steps 1-4 are a runtime representation change that
touches every set and dict iteration/repr site, so it is a feature-sized round,
not a quick fix. The flow-sensitive local case (`if` joins) is unchanged and
still listed above.
