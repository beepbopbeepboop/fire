# CODEGEN: a lambda's own return type is lost — a `double` truncates to an int, a `char *` prints as a decimal

**State: OPEN, found 2026-10-01 while fixing
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
