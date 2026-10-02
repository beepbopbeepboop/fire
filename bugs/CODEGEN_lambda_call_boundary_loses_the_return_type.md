# CODEGEN: a lambda's own return type is lost — a `double` truncates to an int, a `char *` prints as a decimal

**State: PARTIALLY FIXED 2026-10-02 (`work/bugs4-3`).** The `char *` half and
the control are closed; the `double` half and the nested-`def` row are not, and
the remaining cause is named below rather than left as "the estimator". Nothing
here regressed: the suite verdicts are identical before and after, and the rows
that changed changed from one wrong answer to a less wrong one.

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
(`bugs/CODEGEN_polymorphic_unannotated_param_vacuous_unanimity.md`).

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
`bugs/CODEGEN_lambda_bool_return_prints_as_int.md` (which has the `bool`
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

    def g(): q = 2.5; fn = lambda: q * 2; return fn()   # still 5, want 5.0
    def h(): q = 2.5; fn = lambda: q; return fn()       # still 2, want 2.5

The next step is therefore a scalar overlay beside the pointer one, scoped to
the inference window exactly as `_prebound_local_ctypes` is — a local bound to
a `FloatLiteral` is `double` — and the first thing to measure is how many
signatures it moves, since that function's own docstring predicts "many
existing signatures" for exactly this. A second, narrower alternative worth
weighing first: record the inlined call's REAL (ctype, expr) into
`gen._actual_types` at `_lower_inlined_lambda_call`, which fixes the `print`
dispatch for the `o2`-as-a-statement spelling without touching inference at
all, and cannot help `g`/`h` (a `double` truncated to `5` has lost its type by
the time any table could be read).

**Also still open: the nested-`def` row** (`def a1(): p = 'mm'; def inner():
return p; return inner()` prints the pointer's address). That is
`discover_closures`, not `_lower_LambdaExpr`, and it needs the same overlay to
answer for a local bound to a nested `FunctionDef` — with a recursion guard,
because two mutually recursive nested defs would otherwise infer each other.

**Also open, and a different bug (filed separately as
`bugs/CODEGEN_materialized_lambda_env_double_does_not_survive_the_call.md`):**
`k(p: float)` and `n()` above are the MATERIALIZED shape (a bound method plus
an env struct), and there the env's `double` field does not survive the call
even though the store, the field declaration and the read all agree in the
emitted C. This change makes the declared type right there, so `k(2.5)` prints
`2.0` where it used to print `2` — both wrong (CPython: `5.0`), and the value
was already wrong before it.

## Also measured alongside it, and NOT this bug

- `sorted(x)` where `x` is an unannotated dict PARAMETER returns `[None, None]`:
  the parameter's inferred ctype is `MojoList *`, so `_lower_builtin_sorted`
  dispatches to `mojo_sorted(void *)` and a MojoDict is read as a MojoList.
  Already documented, with its own mechanism, in
  `bugs/CODEGEN_polymorphic_unannotated_param_vacuous_unanimity.md`.
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
