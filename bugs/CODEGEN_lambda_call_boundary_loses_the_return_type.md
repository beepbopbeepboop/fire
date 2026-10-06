# CODEGEN: a lambda's own return type is lost — a `double` truncates to an int, a `char *` prints as a decimal

**State: the `double` half FIXED 2026-10-02 (`work/bugs4-3-c`).** Both halves
this doc reported are now closed and pinned against CPython; what remains is
the nested-`def` row and two measurements recorded below because they are the
part that is easy to get wrong. The doc is kept rather than deleted because
the nested-`def` row is genuinely still open and is a different emission path
(`discover_closures`, not `_lower_LambdaExpr`).

**State before that: PARTIALLY FIXED 2026-10-02 (`work/bugs4-3`).** The
`char *` half and the control were closed; the `double` half and the nested-`def`
row were not, and the remaining cause was named below rather than left as "the
estimator". Nothing here regressed: the suite verdicts were identical before and
after, and the rows that changed changed from one wrong answer to a less wrong
one.

**State before that: OPEN, found 2026-10-01 while fixing
`CODEGEN_captured_string_local_reads_falsey.md` (since deleted — its bug was
the capture LIST missing a name, which is fixed).** Independent of that: this
one is about the value on the way BACK, and it reproduces with a capture list
that is perfectly correct. Silent wrong values, exit 0, every case.

## What I ran and what I saw

Every program here captures correctly (`p`/`q`/`s` all reach the env); what
differs is the `double`/pointer the lambda hands back.

| program | CPython | compiled |
|---|---|---|
| `def g(): q = 2.5; fn = lambda: q * 2; return fn()` | `5.0` | `5` |
| `def h(): q = 2.5; fn = lambda: q; return fn()` | `2.5` | `2` |
| `def k(p: float): fn = lambda: p * 2; return fn()` — called `k(2.5)` | `5.0` | `2` |
| `def n2(): s = 'ab'; fn = lambda: s * 2; return fn()` | `'abab'` | `'abab'` — RIGHT |
| `def o2(): s = 'ab'; fn = lambda: s; return fn()` | `'ab'` | `4330302752` |
| `def a1(): p = 'mm'` / `def inner(): return p` / `return inner()` | `'mm'` | `4332793352` |

Note the third row: an ANNOTATED `float` parameter is wrong too, so this is not
the unannotated-parameter ABI gap
(`CODEGEN_polymorphic_unannotated_param_vacuous_unanimity`).

## Mechanism

A lambda that is created and called in the same statement list
(`fn = lambda: ...` then `return fn()`) is never materialized: it is INLINED,
its body emitted straight into the enclosing function. The surrounding
`return` has the enclosing function's own inferred return ctype, `int64_t`
here, so the inlined body's value is boxed on the way out:

```c
int64_t g (void)
{
  double q;
  int64_t fn;
  double _t2; double _t3; int64_t _t4;
  q = 2.5;
  fn = (int64_t)0;              /* the lambda value itself is a NULL stub */
  _t2 = (double)2;
  _t3 = q * _t2;               /* the body, inlined: the arithmetic is right */
  _t4 = (int64_t)_t3;          /* <-- 5.0 truncated to 5 */
  return _t4;
}
```

`fn = (int64_t)0` is the tell that the INLINED path was taken at all: a
lambda that is really materialized leaves a `mojo_bound_method_new` /
`_funcptr_<lifted>` in that slot instead.

Why `s * 2` survives and `q * 2` does not: a boxed `char *` is recoverable
afterwards. `_to_int64`'s boxed-pointer convention is `(int64_t)(void *)ptr`,
and `gen._actual_types` records the real type of the temp, so the `print`
dispatch's `_get_actual_type` re-derives `char *` and prints the string. A
`double` has no `int64_t` spelling — `(int64_t)5.0` is `5`, and nothing left
in the tables can tell that from a genuine 5. So this is the same
"a value crossing a call boundary is homogenized to `int64_t`" family as
`“CODEGEN: a lambda whose body is a bool returns int64 0/1”` (which has the `bool`
flavour and is owned elsewhere) — this doc has the `double` and pointer
flavours, including the nested-`def` row, and notes the one recovery that
already works so the next reader does not re-derive it.

## Exact next step

1. Find where the inlined lambda's result type is discarded. The
   `fn = (int64_t)0` stub is emitted by `_lower_LambdaExpr`'s reference-site
   path in `mojo/backend_gimple/emit_calls.py`, and the inlining itself is
   decided nearby; the value that must survive is the lowered (type, expr)
   pair of the lambda's body, not the enclosing `return`'s inferred ctype.
2. `gen._actual_types` is the mechanism the pointer case already uses to
   cross the `int64_t` boundary intact. Either record the inlined value's real
   type there (so `print`'s `_get_actual_type` finds it, exactly as it does for
   a boxed `char *`), or give the enclosing function the lambda body's own
   inferred return ctype when the only `return` is that call.
3. Cover in the test: `double`, `float`, `char *`, `int`, and a nested `def`
   (not a lambda) — the nested-`def` row is a different emission path
   (`discover_closures`, not `_lower_LambdaExpr`) and happens to be RIGHT for
   the `MultiAssignStmt` body, so it pins that it stays right.

## Suite-bucket note

None. `test_gimple_runner.py` (`gimplerunner`, in `check` and `gate`), with
CPython's exact text as the expectation.

## Status (2026-10-02) — what landed, and what is left

**Landed.** The value the inlined lambda produces is now what the enclosing
function's SIGNATURE says it is, for every kind the return-type inference can
already see. `infra_infer._lambda_call_ret_locals` walks the body under
inference for `name = lambda: ...` bindings and records what calling `name`
produces; `resolve_shared._quick_type`'s call case consults it (through the
same save/overlay/restore window `_prebound_local_ctypes` and
`_dict_value_locals` already use), so `_infer_return_type` — which every
consumer of a function's return type goes through — sees the lambda's body
type instead of the `int64_t` an unknown callee gets. Deliberately NOT
`_callable_ret_types`: that table is keyed by lowered value as well as by name
and is populated during emission, which is too late for a signature whose
forward declaration has already been written.

Closed, pinned by `gimple_inlined_lambda_string_return_keeps_its_type`
against CPython (before: `4295248216` / `4303968256`; after: `ab` / `ab!`,
with an `int` row as the control that must not move):

| program | CPython | before | after |
|---|---|---|---|
| `def o2(): s = 'ab'; fn = lambda: s; return fn()` | `ab` | address | **`ab`** |
| `def o3(): s = 'ab'; fn = lambda: s + '!'; return fn()` | `ab!` | address | **`ab!`** |
| `def i1(): n = 7; fn = lambda: n + 1; return fn()` | `8` | `8` | `8` |

**Still open: the `double` half**, and the cause is now specific. The overlay
asks `_quick_type` about the lambda's BODY, and the body reads a LOCAL scalar
(`q * 2`), which the inference-time `var_types` does not have:
`_prebound_local_ctypes` deliberately records only pointer-valued bindings
("Scalars are NOT included — they are what the int64_t default is for, and
adding them would change many existing signatures"), so `q` reads as
`int64_t`, `q * 2` joins to `int64_t`, and nothing is recorded. So:

    def g(): q = 2.5; fn = lambda: q * 2; return fn()   # was 5, now 5.0
    def h(): q = 2.5; fn = lambda: q; return fn()       # was 2, now 2.5

(CLOSED 2026-10-02 -- see "the `double` half, landed" below. The scalar
overlay this next step names is what landed; the narrower `_actual_types`
alternative was taken FIRST, by `work/bugs4-3`, and closed the `o2` row on its
own.)

**Also still open: the nested-`def` row** (`def a1(): p = 'mm'; def inner():
return p; return inner()` prints the pointer's address). That is
`discover_closures`, not `_lower_LambdaExpr`, and it needs the same overlay to
answer for a local bound to a nested `FunctionDef` — with a recursion guard,
because two mutually recursive nested defs would otherwise infer each other.

**The MATERIALIZED shape (a bound method plus an env struct) was a separate
bug, and it is now FIXED.** `k(p: float)` and `n()` above are that shape, and
there the env's `double` field did not survive the call even though the store,
the field declaration and the read all agreed in the emitted C: it read as
`1.0`, i.e. from a block nothing wrote. Measured on this tree's base
(`ccb157ed`) that whole repro now prints CPython's `3.5 / 3.5 / 5.0`, so the
defect is gone rather than reduced — pinned by
`gimple_materialized_lambda_keeps_a_double_capture` in test_gimple_runner.py,
which is the case this section describes and did not exist.

## Status (2026-10-02, `work/bugs4-3-c`) - the `double` half, landed

`infra_infer._prebound_local_ctypes`'s `note` gained the one RHS that is
unambiguous evidence of `double` with no inference in between:
`FloatLiteral`. Its docstring above calls scalars "not included - they are
what the int64_t default is for", and that is true of every scalar EXCEPT
this one, because for a `double` the int64_t default is a TRUNCATION rather
than a box: `(int64_t)5.0` is `5` and no table can tell it from a genuine 5.
Every pointer-shaped value this map records is recoverable downstream
(`_to_int64`'s boxed-pointer convention plus `_actual_types`); a `double` is
not, so it has to be right BEFORE the boundary.

Deliberately NOT added, each for the reason that docstring gives for every
other exclusion - each would be a second, independently-drifting inference: a
`double` from a call, from an annotated `VarDecl`, or from an arithmetic
expression. The conflict rule there already covers the awkward case: a name
first bound to a `FloatLiteral` and later to a list records the box
(`int64_t`), which is this function's existing conservative verdict for a slot
holding more than one kind.

**The measurement the doc's own next step asked for, and it is the
interesting part.** That step said to measure "how many signatures it moves,
since that function's own docstring predicts 'many existing signatures'". It
moves NONE that can be observed: the self-host closure's `.ci` is 13 distinct
gcc errors before and 13 after, the same set. The reason is worth recording,
because it is the answer to "is this safe": in that closure every enclosing
function returning such a value has a HAND-WRITTEN SIGNATURE, in one of the
three tables `gimple_codegen._SELFHOST_FUNC_RETURN_TYPES` /
`_SELFHOST_SIGS` / module_gen's `_sh_ret`, and those override the estimate
outright. The estimator only decides signatures nothing else has an opinion
about.

**And the defect was never about the lambda.** `def j(): q = 2.5; return q`
printed `2` before this change and prints `2.5` after - no lambda, no
`_lower_inlined_lambda_call`, no call boundary. The `g`/`h` rows were two
instances of one missing fact (`q` is `double`) that the lambda rows merely
made visible. Pinned by `gimple_double_local_keeps_its_type_across_inference`
in `test_gimple_runner.py` (CPython-diffed, with the `int` and `char *`
controls the two previous commits established), beside the unchanged
`gimple_inlined_lambda_string_return_keeps_its_type`.

### One row that is NOT fixed and is not this fix's business

`def k(): q = 2.5; if q > 1: q = [1, 2]; return q` - a local rebound from a
`double` to a list - fails to compile (`cannot convert to a pointer type`).
Measured identical with and without this change, so it is pre-existing and
untouched: the codegen's own local declaration for that slot is not the box
`_prebound_local_ctypes` records, and teaching the EMITTER about the box is a
different fix from teaching inference about the `double`.

## Also measured alongside it, and NOT this bug

- `sorted(x)` where `x` is an unannotated dict PARAMETER returns `[None, None]`:
  the parameter's inferred ctype is `MojoList *`, so `_lower_builtin_sorted`
  dispatches to `mojo_sorted(void *)` and a MojoDict is read as a MojoList.
  Already documented, with its own mechanism, in
  `CODEGEN_polymorphic_unannotated_param_vacuous_unanimity`.
- A closure that mutates an enclosing local without `nonlocal` — which
  CPython rejects with `UnboundLocalError` — instead compiles and mutates
  something, silently:

      def f():
          n = 0

          def inner():
              n += 1
              return n
          inner()
          return n

      print(f())      # CPython: UnboundLocalError.  compiled: 1, exit 0.

  `discover_closures` emits an EMPTY env struct for this closure (its
  `captures` list is empty because the body only AUGMENTS a free name, which
  is the exact reason `mutated_free_names` exists), and the write still lands
  on the outer `n`. NOT reduced to a mechanism and NOT the same bug as
  anything above — recorded only so the next person does not have to
  rediscover that a closure carrying an empty env can still mutate an outer
  local. Note this is arguably a *refusal* the compiled path owes (Python has
  no answer here), so the fix may be to say so rather than to capture.
- Two `test_gimple_runner.py` cases are RED on master, measured by
  reverse-applying a finished branch and re-running them, so they are not
  collateral from any of the work in this area and the integrator should not
  read them as such:

      FAIL gimple_char_scan_allocates_nothing_per_character: stdout '4800000\n'
        (want '4800000\n'), peak RSS 246.7 MB (limit 60)
      FAIL gimple_kinds_survive_a_sibling_list_being_freed: expected
        "[9.5, 1, 'zz']\n9.5\n1\nTrue\n[2.5, 1, 'yy']\n[3.5, 1, 'xx']\n[2.5, 1, 'yy'] [3.5, 1, 'xx']\n",
        got "[9.5, 1, 'zz']\n"

  Identical output at master (246.6 MB for the first). Neither has a doc.
