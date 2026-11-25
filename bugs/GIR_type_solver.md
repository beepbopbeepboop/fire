# GIR: a whole-closure type solver (`mojo/tsolve/`)

Design and staged plan, written 2026-11-24. The first consumer is
the import-cycle back-edge fix (S1; now landed, see `bugs/GIR_type_solver_precision.md`). The later stages
are the road to one type solver that answers every signature, field and local type in
the program. Unboxed code depends on that: a value can only be emitted unboxed when
something has proved its type.

Read `doc/GIR.md` §2 first. Rule 2 there (self-hostable code) applies to every file
named here.

## 1. Why a solver, and why not the existing inference

Today types come out of about a dozen passes inside `gen_module_impl`
(`_gmp_infer_return_types`, `_gmp_infer_return_types_fixpoint`,
`_gmp_infer_unannotated_function_returns`, `_gmp_infer_return_types_late`,
`_gmi_apply_call_site_param_evidence`, `_gmp_collect_param_value_obs`, ...). They
run **per module, depth-first, during code generation**, and they write C spellings
into name-keyed dictionaries on `gen`. That has three consequences:

1. **An answer exists only after its module has been compiled.** When modules import
   each other in a cycle, the importer runs first and cannot see the answer.
   The self-host closure has one import cycle of 76 of its 107 modules (measured
   2026-11-24 with a Tarjan pass over `fire.py`'s imports), so this is the normal case.
2. **Running the existing inference "early" is not pure.** Measured 2026-11-24 (probe
   described in the extern-return-types doc): calling `gen._infer_return_type` on a
   definer's `FunctionDef` from the importer gave the right answer for 29 of 32
   functions, but it changed the generated C of the whole closure. `_tN` temps,
   `bb_N` labels and `_slit_N` pool entries shifted, adding 1,369 lines. The engine
   allocates while it infers, so it cannot be used as an oracle.
3. **There is no single answer to audit.** The same fact (the return type of `f`) is
   recomputed by three passes plus `gen_func`, with "last writer wins".

A solver fixes all three. It runs once, before any code generation, over the
whole closure. It is pure: it reads ASTs and produces a table. It has one answer
per symbol, built from a lattice with a stated join.

## 2. The three IR forms

All in a new package `mojo/tsolve/`. Every file follows `doc/GIR.md` rule 2: plain
classes, every field annotated in `__init__`, no closures, no lambdas, no `re`, no
tuple unpacking, no `getattr`, no generators. `mojo/tsolve` must not import
`gimple_codegen` or anything in `mojo/backend_gimple/`. It may import `fire_compiler`
for the AST node classes. The one exception is `lower.py` (§2.4), which takes `gen` as
a parameter and calls only `gen._resolve_type`.

### 2.1 `sty.py`: source-level types (the lattice)

```
class STy:
    def __init__(self, kind: str, name: str, args: list):
        self.kind: str = kind     # see KINDS
        self.name: str = name     # class name when kind == 'struct', else ''
        self.args: list = args    # list/set: [elem]; dict: [key, val]; tuple: slots
        self.key: str = ...       # canonical spelling, e.g. 'list[str]', 'struct:Token'
```

`KINDS = bot none bool int float str list tuple dict set struct func dyn`.

- `bot` means no information yet. It is the solver's starting value and the identity
  of `join`.
- `dyn` means conflicting or unknowable. It is the top of the lattice and lowers to the
  boxed word.
- Constructors: module constants `BOT NONE BOOL INT FLOAT STR FUNC DYN`, plus
  `list_of(e)`, `set_of(e)`, `dict_of(k, v)`, `tuple_of(slots)` and `struct_of(name)`.
  Each one returns an interned instance (a module dict keyed by `key`), so equality is
  `a.key == b.key`.
- `join(a, b)` is the only place two types are combined. The rules, in order:
  1. If `a` is `bot`, the result is `b`. If `b` is `bot`, it is `a`. Equal keys give `a`.
  2. `none` joined with `str`, `list`, `tuple`, `dict`, `set` or `struct` gives the
     other side, because every pointer is nullable in the C representation. `none`
     joined with anything else gives `dyn`.
  3. Two values of the same container kind join elementwise. Tuples of different
     arity give `list_of(join of all slots)`. A `tuple` joined with a `list` gives
     `list_of(join of elements)`.
  4. Everything else gives `dyn`. That includes `bool` with `int` and `int` with
     `float`. If shadow measurement (S2) shows the backend picks something more
     specific, the rule changes here, in one place, with a test.
- `cap(t)` limits nesting to depth 3 (deeper `args` become `dyn`). `join` applies it,
  so the lattice has finite height and the solver terminates.
- `from_annotation(text, class_names)`: parses an annotation string into an STy.
  `int Int Int64 → INT`, `float Float64 → FLOAT`, `bool Bool → BOOL`,
  `str String StringLiteral → STR`, `None → NONE`, `list/List[X]`, `dict/Dict[K, V]`,
  `set/Set[X]`, `tuple/Tuple[...]`, `Optional[X]` and `X | None` (that is `join(X, NONE)`).
  A name in `class_names` gives `struct_of(name)`. Anything else gives `DYN`. It splits
  on top-level commas with a small hand-written scanner, not `re`.

### 2.2 `summary.py`: the constraint IR

A function body is summarized as **flows**, written `term → var`, meaning the value
of the term may reach the variable. The flows are flow-insensitive: statement order
and control flow are ignored. That is deliberate. It is what keeps the summarizer
small and the solver monotone.

```
class Term:                      # an expression whose type the solver evaluates
    op: str        # const | var | call | method | field | elem | slot | dval | join | narrow
    ty: STy        # const
    var: int       # var
    name: str      # call: callee FuncKey; method/field: member name; slot: index; narrow: class
    args: list     # sub-terms (receiver first for method/field/elem/slot/dval)

class Flow:
    src: Term
    dst: int       # TVar id

class FnSummary:
    key: str              # FuncKey: abspath + '\x1f' + 'f' or 'Cls.m'
    params: list[int]     # TVar per parameter (self included for methods)
    param_names: list[str]
    ret: int              # TVar
    annotated_ret: bool   # True: ret is pinned to the annotation (no inference)
    decidable: bool       # False for overload sets, generators, async defs, nested defs

class ClassSummary:
    name: str; path: str
    bases: list[str]
    fields: dict[str, int]          # field name -> TVar
    methods: dict[str, FnSummary]

class Program:
    vars: list[STy]                 # the solution, indexed by TVar id
    pinned: list[bool]              # annotated: flows into it are ignored
    flows: list[Flow]
    fns: dict[str, FnSummary]       # FuncKey -> summary
    classes: dict[str, ClassSummary]  # class name -> summary (first definition wins;
                                      # a second same-named class marks both 'dyn')
    field_index: dict[str, list[int]] # field name -> every class's TVar for it
```

`FuncKey` is a path plus a name. It is not a module qualifier, because the
qualifier spelling drifts between importer and definer, and `_PUBLISHED_DEF_PTS`
uses the path for the same reason (see its comment in `mojo/middle/funcs_shared.py`).

### 2.3 `summarize.py` (AST to Program) and `solve.py` (Program to solution)

`summarize_closure(root_path, root_stmts, load) -> Program`.

`load(module_ref, importer_path)` returns `(abspath, stmts)` or None. The compiler's
`load` must resolve and parse exactly as `_compile_imported_module` does
(`imports.resolve_source`, then `Parser(py_tokenize(src)).parse_module()`, then
`ast_rewriter.rewrite`). Factor that parse into one helper,
`funcs_shared.parse_module_file(path)`, and call it from both places. Do not keep two
copies.

The summarizer walks the closure breadth-first from the root, following
`ImportStmt`/`FromImportStmt` at any depth, including imports inside functions. That
is the same closure `do_imports` compiles. Per module it records a name environment,
`name → FuncKey | class name | module path | global TVar`, from top-level `def`,
`class`, `X = ...` and the import statements. Module globals are TVars too.

Rules for statements, all producing flows:

| statement | flows |
|---|---|
| parameter `p: T` | `const(from_annotation(T))` → p, and p pinned |
| parameter default `p=e` | `term(e)` → p |
| `self` in a method of class C | `const(struct_of(C))` → self, pinned |
| `x = e`, `x: T = e`, walrus | `term(e)` → x (with an annotation: const and pinned) |
| `a, b = e` | `slot(e, i)` → i-th name |
| `for x in e` | `elem(e)` → x |
| `with e as x`, `except E as x` | `const(DYN)` → x |
| `return e` / bare `return` | `term(e)` / `const(NONE)` → ret |
| body can fall off the end | `const(NONE)` → ret (fall-off = last statement is not `return`/`raise`) |
| `self.f = e` in a method | `term(e)` → class field f |
| class-level `f: T` | `const(T)` → field f, pinned |
| call `f(a0, a1, k=a2)` to a resolved FuncKey | `term(ai)` → param i (by position, keywords by name; `*args`/`**kw` ignored) |

Inside the then-branch of `if isinstance(n, C):`, an `IdentExpr` `n` summarizes as
`narrow(C)`. That evaluates to `struct_of(C)` when C is a closure class, else `dyn`.
This is the only flow-sensitive rule.

Expressions map to terms:

| expression | term |
|---|---|
| `IntLiteral`, `FloatLiteral`, `BoolLiteral`, `NoneLiteral` | const INT / FLOAT / BOOL / NONE |
| `StringLiteral`, f-strings, `%` with a string left operand | const STR |
| `ListExpr`, `SetExpr`, `DictExpr`, `TupleExpr` | const containers; element terms joined via `join` terms; empty gives `list_of(BOT)` etc. |
| `BinaryOp` `+ - * // %` | `join(left, right)` |
| `BinaryOp` `/` | FLOAT |
| `and` / `or` | `join(left, right)` |
| `CompareChain`, `not`, `in`, `is` | BOOL |
| `UnaryOp -`/`+` | the operand |
| `TernaryExpr` | `join(then, else)` |
| `IdentExpr` | `var` (local, param, global), or `const(FUNC)` for a function name |
| `MemberExpr` on a module alias | that module's global or function |
| `MemberExpr` otherwise | `field(receiver, name)` |
| `SubscriptExpr` with a `SliceExpr` index | the container term |
| `SubscriptExpr` with an int literal | `slot(container, i)` |
| `SubscriptExpr` otherwise | `elem(container)` (`elem` of a dict is its value; of a str is STR) |
| `LambdaExpr` | const FUNC |
| call of a closure function | `call(FuncKey, args)` |
| call of a closure class | `const(struct_of(C))`, with args flowing to `C.__init__` params |
| `obj.m(args)` | `method(obj, m, args)` |
| builtins | the table below |
| anything else | const DYN |

Builtin calls: `str repr format chr ''.join → STR`; `int len ord hash id → INT`;
`float → FLOAT`; `bool isinstance hasattr callable any all → BOOL`;
`list(x) sorted(x) → list_of(elem(x))` (no argument: `list_of(BOT)`);
`tuple(x) → list_of(elem(x))`; `set(x) → set_of(elem(x))`;
`dict(x) → x` (no argument: `dict_of(BOT, BOT)`); `min/max/abs → join(args)`;
`range → list_of(INT)`; `getattr(o, 'lit', d) → join(field(o, 'lit'), d)`.

`solve.py`: `solve(program) -> None`, which fills `program.vars`. It is a worklist:

1. Seed: every non-pinned var is BOT, and every pinned var holds its constant.
2. For each flow, evaluate `src` and set `vars[dst] = join(vars[dst], value)`. When the
   value changes, queue every flow whose `src` reads `dst`. Each flow records the
   vars it read during evaluation in `depends: dict[int, list[int]]` (var → flow ids).
3. Term evaluation:
   - `method`: on `struct_of(C)`, look up `C.m`, walking `bases`. The result is its
     `ret` var. The first time a given (flow, C) pair resolves, add arg → param
     flows; this is the only place flows are created during solving. On a `str`
     receiver use the str-method table (`strip lstrip rstrip replace lower upper
     join format → STR`, `startswith endswith isdigit ... → BOOL`,
     `split splitlines → list_of(STR)`, `find index count → INT`). On `list`:
     `pop → elem`, `copy → same`. On `dict`: `get → join(val, default)`,
     `pop setdefault → val`, `keys → list_of(key)`, `values → list_of(val)`,
     `items → list_of(tuple_of([key, val]))`, `copy → same`. Anything else gives DYN.
   - `field`: on `struct_of(C)`, the field var (walking `bases`). When the receiver
     is BOT or DYN, join every class's var for that field name (`field_index`).
     That is the "field name is unanimous" rule the backend already applies.
   - `elem`, `slot`, `dval`: read the container's `args`.
4. Stop at the fixpoint. Assert iterations ≤ 64 × number of flows, so a lattice bug
   cannot hang the compiler.

Determinism: modules in BFS order, flows in creation order, a FIFO worklist with a
`queued` bitmap. Two runs must produce identical `vars`; a unit test checks it.

### 2.4 `lower.py`: STy to C (the lowering pass)

`ret_ctype(gen, sty) -> str` is the only STy-to-C mapping:

| STy | C |
|---|---|
| `bot`, `none` | `void` |
| `bool` | `_Bool` |
| `int`, `func`, `dyn` | `int64_t` |
| `float` | `double` |
| `str` | `char *` |
| `list`, `tuple` | `MojoList *` (an unannotated tuple is a runtime tuple, see `_body_builds_struct_tuple`) |
| `dict` / `set` | `MojoDict *` / `MojoSet *` |
| `struct` C | `gen._resolve_type(C)` (it knows the struct's emitted C name) |

When GIR stage 4 (one type vocabulary) lands, this returns a `mojo.ir.types.Type`
instead of a string. That changes this file only.

### 2.5 The query API (`mojo/tsolve/__init__.py`)

```
class Solution:
    def ret_ctype(self, gen, path: str, name: str) -> str | None
        # None unless the function is in the closure, decidable, and UNANNOTATED
    def ret_sty(self, path: str, name: str) -> STy | None     # tools and tests
def solve_closure(root_path: str, root_stmts: list, load) -> Solution
```

## 3. Stages

Each stage is shippable on its own and has its own acceptance test.

- **S1: the solver and its first consumer.** §2 in full, plus the integration in
  the import-cycle back-edge fix (landed). The solver's answer is used only for a
  return type an importer needs before its definer has analyzed. Everything else
  still comes from the existing passes, so C output is unchanged for any program
  without an import cycle.
- **S2: shadow report.** `tools/tsolve_report.py <root.py> <dump.ci>` compares the
  solver's lowered return type with the definition the backend emitted, for every
  unannotated free function and method. It prints agreement and the disagreeing
  rows. Disagreements are worked down by adjusting `join`, the builtin tables, or
  the summarizer, each with a unit test. Track the number in this doc's Status.
- **S3: returns come from the solver.** Once S2 agreement is 100% on the pydiff
  corpus and the self-host closure, delete `_gmp_infer_return_types`,
  `_gmp_infer_return_types_fixpoint`, `_gmp_infer_unannotated_function_returns` and
  `_gmp_infer_return_types_late`. `_home_def_return_types` is then seeded from the
  solution at module start. Oracle: `tools/c_oracle.py check` identical.
- **S4: parameters and the overload hash.** The solver already computes parameter
  types (call-site flows). Make `overload_suffix_for` read the solved parameter
  ctypes, so both halves of a mangled symbol come from one computation. That deletes
  `_PUBLISHED_DEF_PTS`, `_home_def_param_types` and the call-site evidence passes
  (`_gmi_apply_call_site_param_evidence`, `_gmp_collect_param_value_obs`, the
  struct/scalar observation passes).
- **S5: class layouts.** Field types come from `ClassSummary.fields`. That deletes
  the field inference in `_gmp_register_struct_fields` and the hand-written
  self-host tables in `_gmp_selfhost_ast_layouts` (see
  `bugs/GIR_selfhost_unexplained_error_kinds.md`).
- **S6: locals and unboxing.** Expose `local_sty(fn, name)`. A local whose solved
  type is a scalar or a concrete container is declared with that C type; only `dyn`
  stays a boxed word. This is the performance stage. It replaces the name-keyed
  side tables (`_elem_types`, `_boxed_vals`, `_dyn_word_vals`, ...) that
  `doc/GIR.md` §1 counts.

## 4. Tests (`test_tsolve.py`, registered in the `check` bucket, `tiny`)

Pure unit tests, with no compile:
- the `join` table, row by row, including the `none`-pointer rule and `cap`;
- `from_annotation` over every row of §2.1;
- the summarizer on small source strings (parse with `fire_compiler`), checking the flows;
- the solver on mutual recursion across two modules (`a.f` returns `b.g()`, `b.g`
  returns `[a.f()]`, with a fixpoint at depth 3), a method through `self`, field-name
  unanimity, isinstance narrowing, tuple returns, `None`-or-`str`, an annotation
  beating a flow, and a call into a class constructor;
- determinism: solving twice gives identical `vars`;
- `ret_ctype` over every row of §2.4.

## Status

- 2026-11-24: designed. Nothing implemented. S1 is specified together with its
  consumer: the import-cycle back-edge fix (landed; its record is `bugs/GIR_type_solver_precision.md`).
