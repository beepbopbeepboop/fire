# plan/step-14c: `set.add(x)` on both backends
Class: mid      Size: M      Depends: 14b      Blocks: none
Source: `bugs/FORMAL_set_value_model.md` table row `s.add(x)` ("REFUSED; `add` is not in `model.BUILTIN_VALUE_METHODS`").

## Current state (measured; verified 2026-11-05)
- `BUILTIN_VALUE_METHODS` (`formal/model/cfg.py:3818`) maps `"append": "list_append"` etc.; dispatch `how = M.builtin_value_method(method) or ...` at `arm64_codegen.py:7915` / `x86_64_codegen.py:6169`, arms `if how == "list_append": self._emit_list_append(e)` (arm64 `:7922`; implementation `:8506`, x86 `:6883`).
- The append capacity is computed by `_scan_list_caps` (arm64 `:5303`; loop `for node, recv, method, _args in _walk_value_methods(fn): if method != "append" or not isinstance(recv, F.IdentExpr): continue`), so a set that gets `add` calls has no room beyond its literal's elements.
- Receiver kinds: `builtins.py:4061-4063` maps `SetExpr` -> kind name `"set"`.

## Decisions already made
- `add(x)` = `if not contains(blob, x): append(blob, x)` — the SAME element-eligibility rule as 14b (int kind; otherwise `set_runtime_element_refusal`), the same `_emit_set_contains` scan, then the existing `_emit_list_append` store path including its run-time capacity guard (`model.list_append_overflow_message`).
- Capacity: `_scan_list_caps` (both backends) counts `add` call sites exactly like `append` (same loop multiplier via `walk_stmt_trips`). Implementation: change the condition to `method not in ("append", "add")`. Because `add` is also a user-method name, the cap scan only matters for receivers that are bound to a set literal; the existing code already keys on the receiver NAME bound to a literal, so a name bound to a struct is not in the map. Do not special-case further.
- `add` is lowered only when the receiver's kind is the set kind. Add `"add": "set_add"` to `BUILTIN_VALUE_METHODS` ONLY IF `value_method_refusal`'s receiver-kind guard stops a user `struct.add(...)` from being captured; verify with a row (below). If the guard cannot tell, instead dispatch inside the `how` chain on `self._is_set_expr(obj)` (write it using the same helper the set operators use: `_maybe_emit_set_binop`, arm64 `:14897`).
- Return value: `add` returns None; used as a statement only. A use in value position is refused by the existing statement-vs-value machinery for `append`; mirror it.
- Order after `add`: appended at the end (insertion order), unchanged model.

## Work order
1. `formal/model/cfg.py` `BUILTIN_VALUE_METHODS["add"]` (comment: set insert, dedup by scan).
2. `_emit_set_add(self, e)` on both backends: evaluate element -> reg; load base, count; `_emit_set_contains`; skip store when found; otherwise fall into the body of `_emit_list_append` after its element evaluation (factor the shared tail out of `_emit_list_append` into `_emit_list_append_tail` rather than copying it).
3. `_scan_list_caps` condition (both).
4. Tests `test_formal_container_methods.py` SET_CASES: `s_add_new` (`["s = {1, 2}", "s.add(3)"]`, `len(s)` -> 3), `s_add_dup` (`s.add(2)` -> 2), `s_add_loop` (`for i in range(5): s.add(i % 2)` from `s = {9}`: len 3), `s_add_in` (`3 in s`), `s_add_walk_sum`; and a REFUSAL/guard row: a user struct with a method named `add` called on a struct instance still behaves (build it with a struct `Acc` having `def add(mut self, x): self.v = self.v + x`, `a.add(2)`, result 2).
5. Doc status lines (`bugs/FORMAL_set_value_model.md` table row `s.add(x)` updated).

## Do NOT
- Do not skip the capacity guard; do not grow a blob.
- Do not make `add` work on a `dict`/`list` receiver.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_container_methods.py
```

## Done when
- [ ] the five `s_add_*` rows pass on both backends vs CPython
- [ ] the user-struct `add` guard row passes
- [ ] a 6th `add` of a new value into a set with capacity exhausted stops with the append-overflow message (add one NO_ANSWER-shaped row modelled on `d_insert_during_walk`'s shape) or, if the loop bound makes the cap exact, state that in the doc

## If stuck
If `add` collides with a user method name irrecoverably, refuse `add` with a sentence naming the collision and stop; leave `BUILTIN_VALUE_METHODS` untouched.
