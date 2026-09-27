# HARD BUG: the constructor-call-site field-typing pass only understands scalars — a list argument still yields an `int64_t` field that segfaults on iteration

**State: OPEN.** Found 2026-09-26 by re-testing the claims in the now-removed
`CODEGEN_unannotated_init_param_field_type_defaults_int64.md`. That doc is
correct that everything it set out to fix is fixed — literal arguments,
`IdentExpr` arguments, method-body `MemberExpr` arguments, and a
`char *`-concatenating `BinaryOp` on one, all verified below. Two things survive
it, and the doc's own text already named the mechanism behind the first.

## 1. A list-typed constructor argument: `int64_t` field, then SIGSEGV

The removed doc's title says the field is mistyped "even for real
**string/list/etc.** call-site arguments". String is genuinely fixed. **List is
not** — the observation pass has no `ListExpr` case, so the `int64_t` default
stands, and the field is then used as a scalar.

`/tmp/vd2/d_list3.py` and `/tmp/vd2/d_list5.py` are the same program with one
character of difference — the field's annotation:

```python
# d_list3.py — unannotated (this doc's bug)
class Box:
    def __init__(self, items):
        self.items = items

# d_list5.py — annotated `items: list` (the control)
```

```python
def main():
    b = Box([1, 2, 3])
    for x in b.items:
        print(x)
```

| | CPython | compiled | exit |
|---|---|---|---|
| `d_list3.py` (unannotated) | `1` `2` `3` | **no output** | **139 (SIGSEGV)** |
| `d_list5.py` (annotated) | `1` `2` `3` | `1` `2` `3` | 0 |

The generated C is the whole story — the *only* difference is the field's
declared type:

```c
/* d_list3.ci */            /* d_list5.ci */
typedef struct Box {         typedef struct Box {
  int64_t __mojo_type_id;      int64_t __mojo_type_id;
  int64_t items;               MojoList * items;
} Box;                       } Box;
```

Same program, same call site, same literal argument. An annotation is the only
thing standing between a working build and a segfault.

The failure is narrower than "the field is wrong": `len(b.items)` and
`b.items[0]` still print the right answers (`3` and `1 2 3`), because those two
sites re-derive the real type from the literal at the call site. Iteration does
not, and dereferences the raw `int64_t` as a `MojoList` header. So the shape
that hurts is the most common one — *you built the list and then iterate it*.

The dict variant (`Box({'a': 1})`) and the bool variant (`Box(True)`) also leave
the field `int64_t`, but every operation I tried on them happens to produce the
right answer, so they are recorded here as same-cause/no-current-symptom rather
than as separate findings.

## 2. A field value round-tripped through a local loses its type

The removed doc's last recorded status names this as an open defect: "a method
whose body is exactly `return self.<field>` (or `return <local>.<field>`) does
not get its return type inferred from the field's type". **The two forms it
names are now fixed** — verified below. The form immediately adjacent to them
is not.

`/tmp/vd2/d_a.py`, one class, four getters that differ only in how the value
reaches the `return`:

| getter body | CPython | compiled |
|---|---|---|
| `return self.v` | `str` | `str` ✓ |
| `t = self.v; return t` | `str` | **`4366489192`** |
| `t = self; return t.v` | `str` | `str` ✓ |
| `t = self; u = t.v; return u` | `str` | **`4366489192`** |

The dividing line is not "local vs no local" — it is **what the local holds**. A
local holding the *pointer* (`t = self`) keeps its type and the field read
through it is correct. A local holding the *field's value* loses it, and the
function's inferred return type falls back to `int64_t`, so `print` renders the
`char *` as a decimal. That is a two-line change from a working getter and it is
silent, exit 0.

## 3. The removed doc's *other* named open defect is fixed

Its status section listed, as a still-open separate defect: "Two classes in one
file that each have an `__init__` parameter of the SAME NAME and a same-named
field (`__init__(self, v): self.v = v`) interact so that neither resolves."
`/tmp/vd2/two_same.py` is that exact program; it now prints `str` / `str2`
(CPython's answer), and both `A.v` and `B.v` are `char *` in the generated C.
Recorded as **fixed**, so nobody re-derives it.

## What the removed doc got right (all re-verified 2026-09-26)

Every one of these was re-run through `fire.py build` + executing the binary:

| claim | CPython | compiled | verdict |
|---|---|---|---|
| `Widget("hello")` (direct literal) | `hello` `5` | `hello` `5` | fixed |
| `s = "hello"; Widget(s)` (`IdentExpr`) | `hello` `5` | `hello` `5` | fixed |
| `Reader(self._p)` / `Reader(self._p + "!")` from inside a method | `hello` `hello!` | `hello` `hello!` | fixed |
| conflicting call sites (`Thing("str")` + `Thing(3.5)`) | `str` `3.5` | `4367619368` `3` | correct-by-design: "not unanimous → leave unresolved", the `int64_t` default |
| comprehension RHS (`self.indents = [i*4 for i in range(indent+1)]`) | `[0, 4, 8]` | `[0, 4, 8]` | fixed |
| `return self.<field>` return-type inference | `str` | `str` | fixed (the removed doc said it was not) |

The conflict row is worth stating explicitly because it looks like a failure and
is not: `4367619368` is the documented fallback (an ASLR-dependent address, so
the digits change per run), and the doc's "not unanimous → leave alone" rule is
intact.

## Root cause

`_arg_scalar_type` (`mojo/backend_gimple/module_gen.py:3781`) resolves one call
argument to a scalar C type or to `None`. Its whole dispatch is:

```python
if isinstance(a, FloatLiteral):   return 'double'
if isinstance(a, StringLiteral):  return 'char *'
if deep_str and _gmi_expr_provably_str(a): return 'char *'   # module_gen.py:746
if isinstance(a, IdentExpr):      ...    # _inferred_var_types / _inferred_param_types
if isinstance(a, MemberExpr):     ...    # self.<f> or a <Struct> * local's <f>
```

There is no `ListExpr` / `DictExpr` / `SetExpr` / `Comprehension` case, and no
`else` that widens. `None` is no-evidence, so the parameter never lands in
`_ctor_lit_param_types` and `_collect_self_assigns`'s caller falls to the
unconditional default at `module_gen.py:2763-2764`:

```python
elif (_as_str(method.name) == '__init__'
      and (_as_str(s.name) + '::' + pname) in self._ctor_lit_param_types):
    pm[pname] = self._ctor_lit_param_types[_as_str(s.name) + '::' + pname]
else:
    pm[pname] = 'int64_t'
```

`mojo/middle/infra_infer.py:213` (`_infer_param_types`) is the analogous pass
for free functions and has a useful contrast: its `analyze_param_usage` **does**
special-case `ListExpr`/`DictExpr`/`SetExpr` and the comprehension forms,
because a free function's parameter is not pinned to one C type per field. A
struct field is: `struct_field_types[struct][field]` holds exactly one ctype
(`module_gen.py:2773`), which is why the ctor pass has to be conservative in a
way the free-function pass is not. That is a real design constraint, not an
oversight — but it means "the observation exists and the field cannot hold it"
has to become an honest refusal or a widened field representation, not silence.

Item 2 has no located site. It is a distinct gap: nothing in
`_infer_param_types` / `_inferred_var_types` records `t = self.<field>` as
"local `t` holds a `char *`", so a function whose only return path is such a
local has no return-type evidence at all. The `return self.<field>` form works
because the method-call return-type inference reads
`struct_field_types` directly at the call site; the local form has to go
through a variable-type map that nothing populates for this shape. Not
investigated further.

## Test coverage — and an orphaned file

Both regression tests the removed doc cites for its own fix live in
**`test_gimple_runner.py`**:

- `gimple_ctor_arg_from_method_self_field` — **PASSES** (re-run directly)
- `gimple_ctor_arg_unanimous_str_and_int` — **PASSES** (re-run directly)

**But that file is not in any gate.** `tools/suite.py` registers
`test_gimple.py` (as `gimple`), `test_runner.py`, `test_module_cache.py`,
`test_selfhost.py`, `test_runtime_diff.py`, `test_link_mode.py`,
`test_no_new_container_casts.py` — and `test_gimple_runner.py` appears in
**none** of them, in **no** bucket. The `Makefile` says so itself:

```make
# `check-gimple-runner` was a stray alias for test_gimple_runner.py, which no
# other target referenced and no gate ran; it stays, running what it always ran.
check-gimple-runner:
	python3 test_gimple_runner.py
```

119 tests, none of them gated. Two further consequences, both found by running
the file:

1. ~~**`gimple_escaping_capturing_lambda_still_lifted` is RED, and it is red
   because it asserts the CPython-wrong answer.**~~ **RESOLVED 2026-09-26.**
   `test_gimple_runner.py:359` pinned `"1\n"` for
   ```python
   fn apply(f, v):
       return f(v)
   fn main():
       var n = 7
       var e = lambda x: n + x
       print(apply(e, 1))
   ```
   whose own comment said "The result is WRONG (1, not 8); this is pinned
   deliberately, so the env-struct work that should fix it flips this test
   instead of changing it silently." The fix **had** landed and the expected
   output has now been updated to `"8\n"`, CPython's answer; the file is
   120/120 green. (`CODEGEN_generator_lambda_expr_unsupported.md` is the
   tracking doc for the surrounding area.)
2. Nothing in the gate would have noticed **either** regression test above
   rotting, reverting, or being deleted — and it did not notice the
   one-character expectation above sitting red for however long it did. The
   orphaning is unchanged and still live.

A fix for item 2 must add its regression tests somewhere that runs —
`test_gimple.py` (registered, `check` + `gate`) is the right home, or
`test_gimple_runner.py` must be registered as its own `tools/suite.py` test.

## Where

- `_arg_scalar_type` — `mojo/backend_gimple/module_gen.py:3781`. The whole bug
  for item 1: no container case, no widening `else`.
- The `int64_t` default it falls through to — `module_gen.py:2763-2764`, inside
  the per-method `pm` build that feeds `_gmi_collect_self_assigns`
  (`module_gen.py:2766`).
- The struct-field store that makes a second ctype impossible —
  `module_gen.py:2770-2773`.
- The observation passes that feed `_ctor_lit_param_types`:
  `module_gen.py:3930-3939` (`_method_caller_bodies`), `:4379-4449` (the
  method-body ctor scan, the one the removed doc's 2026-09-25 entry added), and
  `:2407` / `:2310` (the early literal pass and its dict).
- The contrasting free-function pass that *does* handle containers:
  `mojo/middle/infra_infer.py:213` (`_infer_param_types`).
- Regression tests: `test_gimple_runner.py:1494` and `:1524` — **orphaned**,
  see above. The expectation update that was also orphaned:
  `test_gimple_runner.py:359`, now green.
