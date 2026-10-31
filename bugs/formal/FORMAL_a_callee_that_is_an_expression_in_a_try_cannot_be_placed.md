# A callee that is an EXPRESSION inside a `try` is the whole of what is left
# of the unplaceable tier

**Area:** FORMAL, exceptions. `formal/model.py`'s `RaiseGraph` — the
`("other", "")` key — and `formal/imports.py`'s `CrossModuleRaises` for the
cases it still cannot answer. Both backends. **Status: OPEN, filed 2026-10-05,
and it is the successor to
the doc whose subject was "a callee this pass cannot RESOLVE is not asked
whether that callee raises" — deleted with its fix in `6db5461a`, `a try around
another image's raiser is refused, on both backends` — and not a duplicate of
it.** That doc's residual was "a callee this pass cannot place"; the
cross-module half of that is closed and measured, and what is left is a list, of
which this is the only entry that is a live hazard.

## What is closed, and what this is

The cross-module half landed with the fix that deleted its doc, and it closed
**four spellings** of "a function of another image", each of which was being read
as something local and therefore decided by whatever the importing file happened
to declare:

| spelling | read as, before | answered by, now |
|---|---|---|
| `mod.f(…)` | a METHOD call named `f`, out of this image's method table | `CrossModuleRaises.function`, exact |
| `from mod import f` then `f(…)` | a bare name of this image, so `False` | the same, through the import's own alias table |
| `f(…)` in an image function that calls `mod.f(…)` | not part of the fixed point at all | seeded into it, so the local `f` raises too |
| `b.f(…)` on a linked struct | a method declared HERE | `CrossModuleRaises.method`, by bare name |

The deleted doc's own census is what decided the order, and it was right about
the decision it recorded: the
certain tier moved 51 files and the **corpus cost is zero files**, because every
one of those 51 is already refused for an unresolvable import, which
`_resolve_imports` reports after and which outranks this check (that ordering is
`formal/build.py`'s parked-prepare-refusal, and it is why the number is zero
rather than merely small).

## The census that is left, and the one entry in it that is a hazard

Re-measured on this tree over all 570 `.py`/`.mojo` files, parse-only, counting
the callees a `try` with arms contains that the graph still cannot place:

| what the callee is | count | can it end the process? |
|---|---:|---|
| a method name no imported module declares (`dict.get`, `Path.is_file`, a hostmod entry point) | 1168 | **No.** It is a method of an object this image does not hold; there is no frame of ours for it to raise into. |
| a bare name declared nowhere in the image (`AssertionError`, `IdentExpr`, a local alias of one) | 530 | **No**, for the same reason — with the exception below. |
| a module-qualified callee whose module does not resolve (`ast.parse`, `asyncio.run`, `cas.gcc_syntax_key`) | 277 | **No.** An unresolvable module is CPython's stdlib, which is not in the image. |
| a bare C symbol in `BARE_C_RETURN_KINDS` | 202 | **No**, and this is the doc's own argument: C has no unwinder of ours to unwind into. |
| an import binding whose module is a host module or unresolvable | 49 | **No**, same reason as the row above. |
| **a callee that is an EXPRESSION** | **34** | **Possibly, and this is the doc.** |

The five no-rows are not a residual to be worked; they are the measured decision
the deleted doc made, and re-deriving it per callee would be the five-fold
over-refusal that doc measured. **The expression row is different in kind**: it
is the only bucket whose callee is not *known* to be outside the image. `f(…)`
where `f` is a local holding a function value is an ordinary program on this
path — `formal/model.py` has a whole refusal about calling one
(`call_result_frame_struct` and the `formal/model.py:43913` note) — and
`RaiseGraph` reads it as `("other", "")`, which is `False` by construction.

So the same wrong-but-exit-0 class the cross-module fix closed is still reachable
through a function value, and it is the last way into it.

## The exact next step

1. **Resolve a callee that is a bare `IdentExpr` against the local it is bound
   to**, and only then: `_call_keys` cannot see a binding, but the image can —
   `formal/build.py` already resolves a name to its home for four other checks,
   and the answer this needs is the same one (`this function's local `f` holds a
   function VALUE; whose?`).
2. **Refuse when the answer is still unknown**, which is what `("other", "")`
   should mean. Today it means `False`, i.e. "cannot raise", which is the one
   direction a refusal must never be wrong in. A `try` whose body calls
   `handlers[i](x)` where `handlers` is a list of this image's functions is a
   program whose arm is unreachable, and it builds.
3. **Measure the corpus cost of (2) before landing it**, and expect it to be the
   first refusal in this class that costs files: an expression callee is common
   in ordinary Python (`self.callbacks[k]()`, a `__getitem__`-dispatched call), so
   the number to watch is files refused, not files fixed. The control is the
   `c`/`e` rows above — a callee that is a NAME with no home is still answered
   `False`, and the two must not be merged.

## What is NOT the fix, so nobody proposes it again

* **Not `raise` a `CodegenError` for every `("other", "")` key.** That is the
  blanket refusal of every indirect call in the corpus, and it is the mistake the
  deleted doc measured at five times the certain answer's cost.
* **Not treating a method name as raising because SOME method of that name
  raises, across every module.** That was tried and measured during this fix: it
  moved 51 files, of which the ones whose callee was a bare name are decided by a
  coincidence between an exported function called `read_file` and a method called
  `read`. `ModuleRaises`'s two sets (`exports`, `methods`) exist because of it,
  and `test_formal_cross_module.py`'s method case carries both halves.

## What was run

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_cross_module.py
formal cross-module: PASS=37 EXPECTED=0 FAIL=0
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_exceptions.py
exceptions: PASS=228 FAIL=0 (228 checks)
```

and the census above, which is parse-only and asks `RaiseGraph` and nothing
else. The 51-file movement was then checked by BUILDING all 51 on both the fixed
tree and its parent: every one is refused for its import on both, which is the
zero-file cost claim above.
