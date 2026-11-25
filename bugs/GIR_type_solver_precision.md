# GIR type solver: precision for the self-host closure's early decisions

Author: design owner, 2026-11-24 (session 3). Replaces the Haiku draft (`design_haiku_v1`,
scratch only, never checked in). This doc is self-contained: an implementer needs nothing
else, but the background is in `bugs/GIR_type_solver.md` (the solver, S1-S6) and
`bugs/GIR_selfhost_extern_return_types.md` (its first consumer, the early decision).

Supersedes, and the implementer should edit those docs when the step that replaces them
lands (see section 9 for the exact paragraphs):
- `bugs/GIR_selfhost_extern_return_types.md`: the Status "Remaining" list of 2026-11-24
  (items 1-4) and Acceptance item 2's definition of `conflict` and "expect about 32 early".
- `bugs/GIR_type_solver.md`: the bare-container rows of 2.1, the `with`/external-import
  rows and the isinstance paragraph of 2.3, the builtin table of 2.3, and the
  "None for an annotated function" rule of 2.5.

## 1. Goal

The self-host closure translation unit (`fire.py`, `do_imports=True`) must compile with gcc
with ZERO `conflicting types`, ZERO `makes integer from pointer`, ZERO
`cannot convert to a pointer type`, and no error inside `mojo/tsolve/*` (the solver joined
the closure, so its own code must compile too). The ledger (`FIRE_TSOLVE_LEDGER`) must have
zero `conflict`, zero `weak` and zero `undecided` lines. `weak` and the split of the old
`conflict` line are new; section 4.5 says why. The only gcc errors allowed to remain are the
three `invalid operands to binary + (have 'MojoList *' and 'double')`, which belong to
`bugs/GIR_selfhost_unexplained_error_kinds.md`.

## 2. Measured state (HEAD `0753a4f1f`, 2026-11-24)

### 2.1 The acceptance run

In a clean copy of the tree (`git archive HEAD | tar -x -C $R`; see `tools/selfhost_ci.py`'s
docstring):

    cd $R
    FIRE_TSOLVE_LEDGER=$R/ledger.txt /opt/homebrew/bin/python3 tools/memcap.py --limit-gb 24 -- \
        /opt/homebrew/bin/python3 tools/selfhost_ci.py selfhost.ci          # ~5 min, peak ~11 GB
    gcc-mp-15 -O0 -g0 -fgimple -I runtime $(/opt/homebrew/bin/python3-config --cflags) \
        -c -o /dev/null -x c selfhost.ci 2> gcc.log
    grep -E "^[^ ]+:[0-9]+:[0-9]+: error:" gcc.log | sed -E 's/.*error: //' | sort | uniq -c
    awk '{print $1}' ledger.txt | sort | uniq -c
    grep '^undecided' ledger.txt | sort | uniq -c | sort -rn

Numbers (measured by the previous session; this session re-read that run's `ledger.txt`,
`gcc.log` and `selfhost.ci` and did not repeat it):

- gcc: 12 errors.
- ledger: 39 `early`, 35 `conflict`, 2848 `undecided` lines.

### 2.2 What the 12 gcc errors are

| n | error | cause (section) |
|---|---|---|
| 3 | `invalid operands to binary + (have 'MojoList *' and 'double')` (coro.py:7714, elab_intu.py:4166/4169) | other doc, out of scope |
| 2 | `conflicting types for 'mojo_middle_funcs_shared_register_module_member_value_4bdd1c'` (module_parse.py:625, funcs_shared.py:1425) | the function is UNDECIDABLE in the solver (nested tuple for-target), so the early read is `undecided` and the importer falls back to `int64_t` (3.2) |
| 2 | `assignment to 'STy *' from incompatible pointer type 'Type *'` (tsolve/sty.py:75 `BOOL`, :76 `INT`) | backend: a module global's C type is looked up by BARE name, and `mojo/ir/types.py` also defines `BOOL: Type`, `INT: Type` (3.5) |
| 2 | `expected pointer as argument of unary '*'` (tsolve/summarize.py:381 `apath = res[0]`, :385 `queue.append((apath, res[1]))`) | the summarizer calls a callable stored in a field (`self.load(ref, path)`) and indexes its tuple result (3.5) |
| 3 | `invalid types in nop conversion`, 2x `invalid conversion in gimple call` (tsolve/summarize.py:369) | same function, same cause: `_t61 = (int64_t) res` where `res` was typed as the `_Summarizer` struct |

So no error is caused by a `conflict` line today: the definer obeys the frozen answer, and the
backend converts the return value (`mojo_box_word` then a cast, e.g. `selfhost.ci` around line
2528972 for `_home_def_return_type`). The conflicts are a precision and agreement problem, the
`undecided` reads are where the remaining `conflicting types` come from, and seven errors are the
solver's own code.

### 2.3 What the 2848 `undecided` lines are

`undecided` is appended on EVERY read that misses (`emit_funcs._early_return_decision`,
emit_funcs.py:2660), so 2848 lines are 100 distinct names. Classified against the solver's own
program (real `ClosureLoader`, solved):

| class | names | lines | examples |
|---|---|---|---|
| the definer has an ANNOTATED return (`Solution.ret_sty` refuses by design, `__init__.py:35`) | 93 | 2809 | `elaborate.type_param_names -> list` (866), `module_loader.module_name_for_path -> str` (350), `build_config.find_gcc -> str` (224), `module_loader.load_module -> dict` (142), `build_config.find_gxx` (121), `calls_shared._resolve_overload -> dict` (113), `fire.build_executable -> bool` (4, qualifier `''`) |
| UNDECIDABLE: nested tuple for-target `for ct, (pn, pt) in ...` (summarize.py:822) | 4 | 32 | `register_module_member_value` (23), `_signature_ctypes`, `_home_signature_ctypes`, `_local_sibling_module_exports` |
| UNDECIDABLE: subscript store whose container is not a name (summarize.py:809) | 3 | 7 | `emit_calls._lower_call` (`a.b[i][j] = v`), `funcs_shared._param_ctype`, `register_imported_symbol` (`f(...)[k] = v`) |
| `bot` answer (nothing reaches a return) | 0 | 0 | |

**No `undecided` name is a `bot` answer.** The previous Status (item 3, "these are decidable;
their answer is `bot`") and the Haiku draft's H2 ("unfed chains") were wrong: the big names are
all annotated. An annotated return is the easiest fact in the program, and the early decision
simply never asks for it.

### 2.4 What the 35 `conflict` lines are

9 names; each is recorded once per definer pass (three or four passes), hence 35 lines.

| name | frozen (solver) | measured (backend) | direction |
|---|---|---|---|
| `funcs_shared._sanitize_cname_qualifier` | `int64_t` (dyn) | `char *` | solver weaker |
| `funcs_shared._parsed_import` | `int64_t` (dyn) | `MojoList *` | solver weaker |
| `funcs_shared._resolved_export_entry` | `int64_t` (dyn) | `MojoDict *` | solver weaker |
| `funcs_shared._find_imported_struct` | `int64_t` (dyn) | `StructDef *` | solver weaker |
| `funcs_shared.param_aug_rebinding_ctype` | `int64_t` (dyn) | `char *` | solver weaker |
| `calls_shared._as_cstr` | `int64_t` (dyn) | `char *` | solver weaker |
| `calls_shared._isinstance_type_name` | `int64_t` (dyn) | `char *` | solver weaker |
| `elaborate.infer_struct_type_args` | `MojoList *` | `int64_t` | solver stronger (and right) |
| `emit_funcs._home_def_return_type` | `char *` | `int64_t` | solver stronger (and right) |

### 2.5 Closure-wide numbers (the solver run alone, no compile, ~65 s)

Program: 7911 functions, 70697 vars, 153702 flows after solving.
- 351 functions are UNDECIDABLE: 124 declared so (decorator, generator, async, overload,
  nested def), 100 nested tuple targets, 65 subscript stores into a non-name container (27
  `a.b[k]=`, 21 `a[i][j]=`, 17 `f()[k]=`), 25 slice stores `x[a:b] = v`, 22 `yield` found by
  expression, 6 a class inside a function, 6 a dict splat `{**d}` (a `None` key reaches the
  catch-all at summarize.py:989), 2 f-string fields, 1 starred target.
- Of 2566 decidable unannotated functions, 760 (30%) solve to `dyn`.
- Offline shadow report (the solver's lowered return vs the definition the backend emitted in
  the run's `selfhost.ci`, unannotated decidable free functions whose symbol was found): 768
  agree, 153 disagree, 5 `bot`. Of the disagreements 108 are solver `dyn` vs a precise backend
  type, 44 a precise solver type vs backend `int64_t`, 1 other.
- 25 decidable unannotated functions have a `return` whose term solves to `bot` while another
  return gives a value; 4 of them answer `none` (lowered `void`), 3 `str`, 2 a struct. These
  answers ignore a return site the solver did not understand. None is in today's early set, but
  any of them would be frozen wrong if it became a back-edge (4.3).

### 2.6 How these numbers were produced (reproduce without a compile)

Scratch scripts (session scratchpad, not checked in; step 1 lands the durable tool):
1. Build the solver program exactly as the compile does: `gen = gimple_codegen.GimpleGen()`,
   `gen._current_filename = 'fire.py'`, `stmts = mojo.middle.module_parse.parse_module_source(src,
   abspath('fire.py'))`, `prog = summarize_closure(abspath('fire.py'), stmts,
   ClosureLoader(gen).load)`, then `solve(prog)`. Always solve: an unsolved program is all `bot`.
2. Classify ledger names: map a solver function to `(qualifier, name)` with
   `relpath(fs.path)[:-3].replace('/', '_')`, and look at `decidable`, `annotated_ret` and
   `prog.vars[fs.ret]`.
3. Undecidable cause: wrap `_Summarizer._undecidable` and read the caller frame's code name,
   line and the `st`/`e`/`target` local.
4. Provenance of a `dyn`: wrap `Program.add_flow` to record the current statement (wrap
   `_Summarizer._stmt`), then walk from `fs.ret` backwards over flows whose evaluated source
   contains `dyn` (re-evaluate with a fresh `_Solver(prog)` whose `queued` is all False).
5. Order dependence: reset non-pinned vars to `bot` and re-run the worklist, printing every
   change of one variable (this is how 4.2.d was found).
6. Shadow: parse definitions (`^<ret> <sym> (<params>)$`, no `;`) out of `selfhost.ci`, strip the
   `_<6 hex>` overload suffix, compare with the lowered solver answer.

## 3. Diagnosis

### 3.1 Why the seven `weaker` answers are `dyn` (provenance, file:line)

Each chain was traced flow by flow (2.6 step 4). None of them is "mixed call-site evidence" in
the sense of two real, different types reaching a parameter; every `dyn` enters through a
construct the solver does not model, and then `join` carries it.

- `_sanitize_cname_qualifier(q)` (funcs_shared.py:2623). `q` gets `_shome`
  (module_gen.py:8802 `self._struct_home_by_id.get(_sid, '')`). The field's value type is
  `dict[int, dyn]` because of the store at module_gen.py:15300 of `_hms_home`, which is
  `os.path.splitext(os.path.basename(path))[0]` (module_gen.py:15297). `os` is an EXTERNAL
  module: `import os` binds `dyn` (summarize.py:447), `os.path` becomes `field('path', dyn)`,
  the dyn-receiver rule (solve.py:150) joins every closure class's field named `path`, which is
  `Resolver.path: list[dyn]`, and `.splitext` on a list is `dyn`. So an external module is
  mistaken for an unknown object, and the "unanimous field" rule then answers with an unrelated
  class's field. **Cause class: external modules.**
- `_parsed_import` (funcs_shared.py:2237 `return cache[module]`). `cache = _as_dict(...)`
  (2164) and `_as_dict(e: object) -> dict` (fire_compiler.py:4898) is pinned to
  `dict[dyn, dyn]`; the setitem growth `cache[module] = (path, src, _pst)` (2233) joins into
  that and stays `dict[dyn, dyn]`. **Cause class: a bare container annotation pins its contents
  to `dyn`; an identity cast helper hides its argument.**
- `_find_imported_struct` (funcs_shared.py:857 `return s`). `s` iterates
  `_parsed_import(...)[2]` (above), and the return is under
  `isinstance(s, gimple_ctypes.StructDef) and s.name == name`, which the narrowing rule does not
  see: the class is a `module.Class` MemberExpr and the test is inside an `and`
  (summarize.py:778-792 accepts only `isinstance(Name, Name)` as the whole condition). **Cause
  classes: narrowing; bare containers.**
- `_isinstance_type_name(ta)` (calls_shared.py:55-61). Returns `ta.name` / `ta.member` under
  `isinstance(ta, gimple_ctypes.IdentExpr)` and `isinstance(ta, gimple_ctypes.MemberExpr) and
  ...`. Without the narrowing, `ta` is `dyn`: its callers pass `node.args[1]`, and
  `_lower_builtin_isinstance(gen, node: gimple_ctypes.CallExpr)` (emit_calls.py:6841) has its
  `node` pinned `dyn` because `from_annotation` cannot resolve a dotted class name. **Cause classes: narrowing; dotted annotations.**
- `_as_cstr(param_ctype)` (calls_shared.py:368): `param_ctype if isinstance(param_ctype, str)
  else str(param_ctype)`. A ternary's condition never narrows. **Cause class: narrowing.**
- `param_aug_rebinding_ctype` (funcs_shared.py:395-491). `cache = getattr(gen,
  '_param_aug_rebind_cache', None)` reads a field no class declares (it is only ever stored
  through `gen.`, never `self.`), so the read is `dyn`; and `widened` comes from
  `gimple_ctypes.TypeLattice.join(...)`, a classmethod reached through a module alias, which is
  `const dyn` (summarize.py:1051). **Cause classes: undeclared (loose) fields; static/class
  methods.**
- `_resolved_export_entry(gen, module, name, info)` (funcs_shared.py:886/896/929). `info` gets
  `_fi_hinfo` (emit_funcs.py:514 `_fi_hexp.get(name) if _fi_hexp else None`). `_fi_hexp` has
  two flows, `None` (512) and the exports dict (510). The FIFO happens to evaluate the `None`
  flow first, `.get` on a `none` receiver returns `DYN` (solve.py:178 to `builtin_method`, which
  has no `none` row), and `join` never shrinks, so `_fi_hinfo` is `dyn` forever even though its
  final source value is a dict. **Cause class: a `None` receiver makes the evaluation
  non-monotone.** (Also the bare `-> dict` of `load_module`.)

### 3.2 The `undecided` names

93 annotated (2.3): not a precision problem at all; the early decision does not ask. The other 7
are summarizer coverage gaps (nested tuple targets, subscript stores). One of them,
`register_module_member_value`, is the 2 remaining `conflicting types` errors.

### 3.3 The two `stronger` conflicts

- `infer_struct_type_args` (elaborate.py:3855 `return resolved[0]`, `resolved.append([binding[p]
  for p in params])`): a list of lists, so `MojoList *` is right; the backend measures `int64_t`
  because its local element tracking does not type `resolved[0]`.
- `_home_def_return_type` (emit_funcs.py:2594-2608): `store = getattr(gen,
  '_home_def_return_types', None)` and `got = store.get(key)`; the solver resolves a literal
  `getattr` to the declared field `dict[str, str]`, so `char *` is right; the backend does not
  type `getattr` and measures `int64_t`.

Both are representation-compatible (the definer already returns `(char *) mojo_box_word(got)`),
and both are cases where the BACKEND is the weaker engine. Making the solver agree would mean
making it worse. As the solver improves, this class GROWS: the prototype (4.7) turns three more
early-set answers from an accidental `int64_t`/`int64_t` agreement into a correct `str` vs a
backend `int64_t` (`_ref_scalar_param_ctype`, `extract_fn_source`, `unbound_type_parameter`).
An acceptance that counts these as failures punishes every precision gain.

### 3.4 Answers that are wrong, not just weak

The two latent wrong-answer classes found while measuring:
- **`bot` at a return site** (2.5, 25 functions): `join` treats `bot` as "no value", so a return
  the solver did not understand silently disappears from the answer. A function returning
  `first.value` (unknown) or `None` answers `none`, i.e. `void`.
- **Bare-container contents as `bot`** (prototype variant, 4.7): reading a bare `list`/`dict`
  annotation as "no elements" instead of "unknown elements" made `.get()` on it `none`, and the
  number of `none`-vs-`int64_t` shadow disagreements went from 4 to 21. Unknown is not empty.

### 3.5 The seven errors in `mojo/tsolve`

- `sty.py:75-76`: the generated code stores `_mojo_tsolve_sty_globals.BOOL = (Type *) ...`. The
  field is right (module-qualified struct), but the CAST comes from the bare-name table
  `gen._global_var_types` (first writer wins across the whole closure,
  emit_funcs.py:415-436 says so), and `mojo/ir/types.py:141/144` defines `BOOL: Type`,
  `INT: Type`. This is a backend bug that any two modules with a same-named, differently-typed
  global hit; `mojo/tsolve` is just the first. Renaming `sty.BOOL` would hide it.
- `summarize.py:369-385` (`collect`): `res = self.load(ref, path)` calls a callable held in a
  field (the backend types the call result as the enclosing struct, hence `(int64_t) res` and
  the `nop conversion` errors), and `queue` is a list of 2-tuples indexed `[0]`/`[1]`. Both
  break `doc/GIR.md` rule 2 in spirit (no first-class callables crossing the API, no tuple
  plumbing).

## 4. The design

### 4.1 What stays

- The lattice (`sty.py`) and its reading of `dyn` as "unknown or conflicting", lowered to the
  boxed word. The solver stays SOUND in this sense: it never claims a precise type for a value
  it has not seen. This matters more than it did, because after 4.5 a precise answer that the
  backend measures as `int64_t` is accepted without a cross-check.
- Flow-insensitive flows with a FIFO worklist, `join` as the only combinator.
- `bot` as "nothing reached here".

### 4.2 Fix the sources of `dyn`, one class each (summarizer and solver)

a. **External modules.** A module the loader does not resolve is not `dyn`; it is
   `_Binding('extern', <dotted module name>)`. `import os` binds `os` to `extern 'os'`;
   `import os.path` binds `os` too; `import a.b as x` binds `x` to `extern 'a.b'`;
   `from os.path import join` binds `join` to `extern 'os.path.join'` (module level and local).
   A MemberExpr chain rooted at an extern binding is a DOTTED NAME (`os.path.join`), never a
   `field` term (so the dyn-receiver field rule can no longer see it). A call of a dotted name
   looks it up in `mojo/tsolve/externs.py` `FUNCS` (dotted name -> annotation text, parsed by
   `from_annotation`); an attribute read looks it up in `ATTRS`; a name in neither is `dyn`.
   `os.environ.get(k, d)` is `join(str, d)`. Builtins added to `_builtin`: `open(...)` is
   `struct_of('<file>')` (a pseudo-class that is never in `prog.classes`); `enumerate(x)` is
   `list[tuple[int, elem(x)]]`, `zip(a, b, ...)` is `list[tuple[elem(a), elem(b), ...]]`,
   `reversed(x)` is `list[elem(x)]`. `with open(...) as f` flows the `<file>` struct to `f`
   (only when `open` is the builtin). `solve.method` on `<file>`: `read`/`readline` -> str,
   `readlines` -> `list[str]`, `write` -> int, `close` -> none, else `dyn`. The str-method table
   gains `rsplit` (`list[str]`), `partition`/`rpartition` (`tuple[str, str, str]`), `zfill center
   ljust rjust title capitalize swapcase casefold expandtabs removeprefix removesuffix
   translate` (str), `isidentifier isnumeric isdecimal isprintable isascii istitle` (bool),
   `rfind rindex` (int).
   The table is facts about CPython, so a unit test checks every `FUNCS` row whose function is
   safe to call (all of `os.path`, `json.dumps`, `textwrap.*`, `shlex.*`, `math.*`, `str`
   methods) by calling it on sample arguments and comparing `type(result)` with the row.
b. **Dotted annotations.** `node: gimple_ctypes.CallExpr` is `struct:CallExpr` when
   `gimple_ctypes` is a module binding in that module and `CallExpr` resolves (through aliases and
   wildcards, `resolve_name`) to a UNIQUE closure class. Interface: `from_annotation(text,
   names)` where `names` is a new plain class `sty.ClassNames` with two dict fields: `classes`
   (unique class name -> True, today's argument) and `qualified` (dotted spelling -> class
   name). `_bare` looks a dotted name up in `qualified`. The summarizer builds one
   `ClassNames` per module (`_Summarizer._names_for(mod)`, cached in `_Mod.ann_names`): for each
   module binding `alias -> path` in `mod.names` (and each `from pkg import sub` submodule), every
   name of the target module that `resolve_name` resolves to a unique class gets
   `qualified[alias + '.' + name]`. Every pin site (`_declare_module_var`, `_declare_struct`,
   `_new_fn` params and return, `_predeclare`) passes its module's `ClassNames`.
c. **Narrowing** becomes a small fact system. `_facts(scope, cond, positive) -> list` returns
   `[name, STy]` pairs that hold when `cond` is `positive`:
   `isinstance(Name, K)` with `K` an IdentExpr class, a `module.Class` MemberExpr (resolved as in
   b), a builtin type name not shadowed in scope (`str int float bool list dict set tuple`,
   giving `STR`, `list_of(DYN)`, ...), or a tuple of those (joined); `not c` flips `positive`;
   `a and b` with positive, and `a or b` with negative, concatenate both sides; anything else
   gives `[]`. Where facts apply:
   - `if c:` then-body under `_facts(c, True)`; elif conditions, elif bodies and the else body
     under `_facts(c, False)`;
   - `x if c else y`: `x` under `_facts(c, True)`, `y` under `_facts(c, False)`;
   - `a and b` / `a or b` (summarize.py `_binop`): `b` under `_facts(a, True)` / `_facts(a, False)`;
   - the REST OF THE BLOCK after an `if c:` with no elif/else whose then-body exits
     (`_terminates`, or ends in `continue`/`break`): `_facts(c, False)` until the block ends.
     This is the `if not isinstance(x, C): return ...` idiom. `_block` implements it (it
     pushes facts after such an `if` and pops them at the end of the block), and
     `_summarize_fn` runs the body through `_block`.
   - SOUNDNESS GUARD (new, not in the prototype): a fact is NOT applied to a name that is
     assigned anywhere inside the region it would cover (`_assigned_names` over the region's
     statements; for rest-of-block, over the remaining statements). Flows are
     flow-insensitive, so a narrowed name rebound in the region would otherwise narrow the
     new value too.
   The `narrow` term carries an `STy` in `Term.ty` (today it carries a class name in `name`):
   evaluation returns the struct when the class is unique (else `dyn`), the var's own value when
   the fact is a container kind and the var's value has that kind, else the fact's type.
d. **A `None` receiver is `bot`, not `dyn`.** `field`, `method`, `elem_of` and `slot_of` on a
   `none` receiver return `BOT`. In Python an attribute, method, item or iteration of `None`
   raises, so no value comes out; and since `join(none, P)` is `P` for every pointer kind, the
   receiver's value grows `none -> dict` and the result then grows `bot -> precise`. Today the
   transient `none` produces a `DYN` that `join` can never take back, so the answer depends on
   the FIFO order of the flows (3.1, `_resolved_export_entry`). Invariant to state in solve.py's
   docstring and test: every term evaluation is monotone in the values it reads.
e. **Static and class methods.** A method whose only decorator is `staticmethod` or
   `classmethod` is decidable (`FnSummary.deco: str`, '' / 'staticmethod' / 'classmethod';
   a classmethod's first parameter is pinned `DYN`; no `self` pin for either). A call
   `C.m(...)` or `mod.C.m(...)` (C a unique class) of such a method is a static call of that
   `FnSummary` with offset 0 (static) or 1 (classmethod). A decorated FREE function stays
   undecidable (`test_a_decorated_function_is_undecidable` keeps passing).
f. **Loose fields.** A store `x.f = v` where no closure class declares `f` (today it "flows
   nowhere", summarize.py:800-804) creates one loose var per field name
   (`Program.loose: dict`, name -> TVar) and registers it in `field_index`; `solve.field` on a
   struct receiver whose class lacks `f` reads the loose var if there is one. This is the
   `gen._param_aug_rebind_cache = cache` idiom (helpers in the middle tier store on the
   generator object they are handed).
g. **Bare container annotations are KIND pins.** `x: list`, `-> dict`, `s: set | None`
   (`sty.is_bare_container(text)`) pin the KIND, not the contents: the var starts at `bot`,
   `Program.kind_pinned[var] = shape`, and the solver joins with `sty.kind_join(shape, old,
   val)`: a value of the same kind (or a tuple into a list) joins its contents; `none`/`bot` add
   nothing; any other value (including `dyn`) makes the contents `dyn` while the kind stays.
   So the contents are exactly what flows in, and `dyn` when something unknown flows in. This
   is NOT the rejected "contents are `bot`" reading (3.4): an unknown source still makes them
   `dyn`. Parameterised annotations (`list[str]`) keep today's full pin.
h. **Identity cast helpers.** A function with one parameter, an annotated return, and a body
   that is (after its docstring) exactly `return <that parameter>` is a CAST HELPER
   (`FnSummary.cast_ty: STy`, None otherwise). A static call of it is a new term
   `cast(ty, arg)`: the argument's value when it has `ty`'s container kind, `ty` with `dyn`
   contents when it has another kind, `bot` when the argument is `bot`, `ty` for a scalar, the
   struct for a unique class. `_as_dict`, `_as_list`, `_as_str`, `_as_structdef_node`,
   `_as_funcdef_node`, ... (fire_compiler.py:4740-4902) are all of this shape; they exist to
   tell the backend a type, and they must not make the solver forget one.
i. **Summarizer coverage** (each removes an undecidable cause, 2.5):
   - nested tuple targets, in `for` and assignment: `_bind_target` parses a string target with
     `sty.split_top` recursively and binds `slot(i)` of `slot(j)` terms;
   - slice store `x[a:b] = v`: a `grow` of `extend` kind with `v` on the container var;
   - a subscript store whose container is not a name/field (`a[i][j] = v`, `f()[k] = v`):
     flows nowhere, by the same argument as the existing field-store rule (no modelled variable
     holds that container), and documented as part of the alias limitation (section 7, R2);
   - a dict splat `{**d, k: v}` (pair key `None`): the join of `d` and the literal;
   - a class defined inside a function: the name is a `dyn` local (like a nested def), not
     undecidable;
   - a starred target `*a, b = ...`: `a` gets `list_of(elem(value))`, `b` its slot.
   Generators, async, and other decorators stay undecidable by design.

### 4.3 A return the solver did not understand makes the answer undecided

`FnSummary.ret_terms: list` holds every term that flows into `ret` (returns and the fall-off
`None`). After solving, `Solution.ret_sty` evaluates them (new `solve.eval_term(prog, term)`,
a fresh `_Solver` read-only evaluation) and answers None if any of them is `bot`
(`Solution.why_none` reports `bot-return`). Rationale: `bot` at a return means a value we know
nothing about leaves the function; dropping it from the join is the one way this solver
produces a wrong precise answer today (3.4).

### 4.4 Annotated definers are decided early, by the backend's own annotation routine

An annotated return is a fact. The importer must see the same ctype the definer will publish,
so the early decision computes it with the ONE routine the definer uses:
`funcs_shared.annotated_return_ctype(gen, fn_node) -> str` (new; middle tier), which is
`gen._resolve_type(fn_node.return_type)` plus the existing body-sensitive rule (a
`MojoTuple_*` answer whose body does not build a struct tuple is `MojoList *`; when it does,
`gen._ensure_tuple_struct(fn_node.return_type)` as the definer does). It replaces the inline
copies at emit_funcs.py:4241-4257 (`gen_func`), module_gen.py:13180-13192 (the all-functions
pass) and funcs_shared.py:899-910 (`_resolved_export_entry`). The other
`_body_builds_struct_tuple` sites (funcs_shared.py:2297, resolve_shared.py:2801,
emit_loops.py:3748, emit_calls.py:12188, emit_funcs.py:5796, module_gen.py:7482) are to be
read; consolidate each one that computes this same fact, leave the ones that do not.

The solver hands the backend the definition: `FnSummary.node` (the `FunctionDef`, set in
`_new_fn`), exposed as `Solution.definition(path, name)` (None unless the closure defines
exactly one such function). `_early_return_decision`: when `Solution.is_annotated(path, name)`,
`ctype = annotated_return_ctype(gen, sol.definition(path, name))`, stored and frozen as today,
ledger `early <q>.<n> <ctype> annotated`. The definer records the same value through the same
routine, so a `conflict` here can only mean the routine read different state at the two times
(for example a class of the in-progress module not registered yet when the importer read it);
that is reported, never silenced (R1).

### 4.5 The ledger says what kind of disagreement it is

Today every `frozen != measured` is a `conflict`. Three different things hide in it:

| line | condition | meaning | acceptance |
|---|---|---|---|
| `conflict <q>.<n> early=<f> measured=<m>` | the two are not representation-compatible: two different pointer types, a pointer or word vs `double`, `void` vs a value, `_Bool` vs a pointer | a miscompile risk | 0 |
| `weak <q>.<n> early=int64_t measured=<m>` | frozen is the boxed word, measured is a pointer type or `_Bool` | the solver lost a type the backend knew: importers box a value they could have typed | 0 |
| `refined <q>.<n> early=<f> measured=int64_t` | frozen is a pointer type or `_Bool`, measured is the boxed word | the backend is the weaker engine; the definer converts (`mojo_box_word` + cast) | allowed, listed |

Representation-compatible means: one side is `int64_t` and the other is `_Bool`, `char *`,
`MojoList *`, `MojoDict *`, `MojoSet *`, or a struct pointer; the runtime boxes and unboxes
between them (`mojo_box_word`, fire_runtime.c:2432). `double` is excluded (a boxed double is a
`'d'` box that `mojo_box_word` returns unchanged).

Why `refined` is allowed, and how it is kept honest: the solver is sound by construction
(4.1), the S3 stage deletes the backend's return measurement anyway, and the alternative is to
make the backend agree by teaching it the solver's rules (literal `getattr`, nested list
elements), which is work S3 throws away. The price is that a `refined` answer has no second
opinion, so every `refined` name is listed in this doc's Status with the line of source that
makes the solver's type right, and a new `refined` name is a review item, not noise.

Also: one line per key (today a key is repeated per pass and per read), `undecided` carries
`reason=annotated|undecidable|bot|bot-return|not-defined` (from `Solution.why_none`), and the
ledger ends with one `summary early=E conflict=C weak=W refined=R undecided=U shadow=S` line.

`shadow <q>.<n> solver=<s> measured=<m>`: for every unannotated definer the solver knows that
was NOT frozen, `gen_func` compares the solver's lowered answer with the measured one after
`_record_home_def_return_type` and appends a line when they differ (ledger only; no C change).
This is the S2 shadow report of `bugs/GIR_type_solver.md` §3, at no extra cost: one
acceptance run measures agreement over the whole closure, not only over the ~140 names that
happen to be back-edges today, so the next back-edge does not start a new round of diagnosis.

### 4.6 The solver compiles in the closure

- **Loader protocol without a callable.** `summarize_closure(root_path, root_stmts, load)`
  becomes a driver the caller runs: `b = summarize.ClosureBuilder(root_path, root_stmts)`;
  `while b.has_request(): r = b.next_request()` (`r` is a `ModuleRequest` with `ref: str`,
  `importer: str`); the caller resolves and calls `b.provide(r, path, stmts)` or
  `b.provide_external(r)`; then `prog = b.finish()` (declare + summarize). The BFS queue holds
  `_Pending(path, stmts)` objects, not tuples. `ClosureLoader` (funcs_shared.py:3093) becomes
  `ClosureLoader.summarize(root_path, root_stmts) -> Program` running that loop, and
  `solve_closure(root_path, root_stmts, loader)` calls it through a plain method on a known
  class. `test_tsolve._Files` gets the same method. No stored callables, no tuple results.
- **Global C types by owner.** The backend's store of a module-level assignment must cast to
  the assigning module's OWN declared type: look the name up in `_own_global_var_types` before
  the bare-name `_global_var_types`, the same precedence `_lie_global_window`
  (emit_exprs.py:715-735) already states for reads ("THIS module's own struct, whenever it
  declares the name"). Find the emission by searching the generated `(Type *)` cast for
  `_mojo_tsolve_sty_globals.BOOL` back to the code that writes `_<mod>_globals.<field> = (<T>) v`
  for a top-level `AssignStmt`/annotated assignment. Do NOT rename `sty.BOOL`: the bug is any
  two modules with one global name and two types.

### 4.7 Evidence: the prototype

A scratch copy of `mojo/tsolve` with 4.2 a-i (without the 4.2c soundness guard and without
4.3), each behind an environment flag, run on the real closure (same loader, no compile).
It lived in the session scratchpad (`.../scratchpad/proto/ptsolve`, with `measure.py` and the
analysis scripts in `.../scratchpad/prec`); it is throwaway code that breaks rule 2 and is not
a starting point, only the source of the numbers below.
"Early set" = the 139 distinct names of today's ledger; "measured" = today's ledger (`early`
value or `conflict measured=`), and for the two undecidable ones the definition in
`selfhost.ci`.

| | HEAD | prototype |
|---|---|---|
| undecidable functions | 351 | 109 (by design: 40 declared, 22 `yield`; not prototyped: 29 slice stores, 8 dict splats, 6 classes in a function, 1 starred target; 3 f-string fields) |
| unannotated decidable solving to `dyn` | 760 / 2566 (30%) | 658 / 2634 (25%) |
| shadow agree / disagree / bot | 768 / 153 / 5 | 788 / 168 / 6 |
| early set: `weak` (solver dyn, backend precise) | 7 | 0 |
| early set: `refined` | 2 | 5 (`infer_struct_type_args`, `_home_def_return_type`, `_ref_scalar_param_ctype`, `extract_fn_source`, `unbound_type_parameter`, each checked by reading the source) |
| early set: undecidable unannotated | 2 | 0 (`register_module_member_value` and `_local_sibling_module_exports` solve to a tuple = `MojoList *`, which is what `selfhost.ci` defines) |
| early set: `bot-return` | - | 0 (no early-set function has a `bot` return site) |

Ablation (all rules on, then each one turned off alone; "regresses" = what reappears in the
early set):

| rule off | early-set regression | closure effect |
|---|---|---|
| 4.2a externs | `_sanitize_cname_qualifier` weak | |
| 4.2b dotted annotations | none (the isinstance argument is resolved by 4.2c itself) | shadow agree -2 |
| 4.2c narrowing | `_isinstance_type_name`, `_as_cstr`, `_find_imported_struct` weak | shadow agree -6 |
| 4.2d `None` receiver | `_resolved_export_entry` weak | |
| 4.2e static/class methods | `param_aug_rebinding_ctype` weak | undecidable 109 -> 193 |
| 4.2f loose fields | `param_aug_rebinding_ctype` weak | |
| 4.2g kind pins | `_resolved_export_entry` weak | shadow agree -9 |
| 4.2h cast helpers | `_parsed_import` weak | |
| 4.2i nested targets | `register_module_member_value`, `_local_sibling_module_exports` undecidable | undecidable 109 -> 208 |
| 4.2i subscript stores | `register_module_member_value` undecidable | undecidable 109 -> 152 |

Every rule but 4.2b is needed by at least one early-set name, and several names need two
(`_resolved_export_entry` needs both d and g). 4.2b stays because it is the same resolution 4.2c
needs and it is what makes `node: gimple_ctypes.CallExpr` parameters precise everywhere else.

The shadow `disagree` count rises because the solver now answers precisely where the backend
says `int64_t` (solver precise vs backend `int64_t`: 44 -> 83; `str` vs `int64_t` alone
16 -> 36): exactly the `refined` class of 4.5. Solver `dyn` vs a precise backend type fell
108 -> 84; the rest is genuinely polymorphic code (an AST `node` parameter that receives several
node classes, `struct ⊔ struct = dyn`; `*args`; most of `myinterpreter.py`), which no
back-edge reads today and which S2/S3 will work down with the `shadow` lines.

What the prototype also showed, and the design therefore excludes:
- bare annotations read as `bot` contents (3.4): 21 `none`-vs-`int64_t` disagreements;
- without 4.2d, `_resolved_export_entry` stays `dyn` whatever else is fixed.

### 4.8 Alternatives considered and rejected

- **Use-based evidence as a flow** (Haiku H1a: a parameter used as a `str` receiver gets a
  `str` flow). Unsound exactly where it was meant to help: `_sanitize_cname_qualifier` returns
  `q` itself in the falsy arm, so a `None` or `0` argument is returned as is, and a use in one
  branch says nothing about paths that do not reach it. Measured, it is also unnecessary: the
  `dyn` in `q` came from `os.path` (4.2a), not from a missing flow.
- **Weak/strong flows, or an "opaque" lattice element that is the identity of `join`.** The
  same as above in lattice form: an opaque value joined with `str` becomes `str`, so
  `json.loads(...) if c else ''` would be `char *`. With 4.5 allowing unchecked `refined`
  answers, the solver must not guess.
- **Per-call-site (context-sensitive) parameters.** Would fix polymorphic helpers, but the
  measured causes are not polymorphism; it multiplies the program size and is a different
  project (S4 territory).
- **A ledger line naming the poisoning call site, then fixing call sites.** Kept as a TOOL
  (`tools/tsolve_why.py`, step 1), rejected as the method: every chain measured ended in a
  modelling gap, not in a wrong caller, and patching callers is per function.
- **Making the backend agree on the `stronger` cases** (typed `getattr`, nested list elements
  in `resolve_shared` local inference). In scope of S3/S6, not here (4.5).
- **Leaving annotated early reads undecided and silencing the line.** The importer then
  depends on the bare-name `func_return_types` fallback (emit_funcs.py:3891-3892), the exact
  bare-name sharing `_home_def_return_types` exists to avoid. One fact, one decision.
- **Bidirectional container contents along every copy (unification).** Sound for aliasing,
  but through context-insensitive helpers (`_as_dict(e)` is called with every dict in the
  compiler) it collapses every container passed to one helper to `dyn`. Rejected for now; the
  restricted form is a follow-up (R2).

## 5. Implementation plan

Order and grouping. Each step is one commit; verify once per step (CLAUDE.md batching).
Every `mojo/tsolve` change obeys `doc/GIR.md` rule 2: plain classes, every field annotated in
`__init__`, no closures, lambdas, `re`, tuple unpacking, `getattr`, generators.

### Step 1: instruments (behaviour-preserving)

- `mojo/tsolve/summary.py`: `Flow.origin: str` (`'<abspath>:<line>'`); `Program.add_flow(src,
  dst, origin='')`. `summarize.py`: `_Summarizer.cur_origin: str`, set in `_stmt` from
  `st.line` (save and restore around nested blocks), passed by every `add_flow`.
  `solve._Solver.add_flow` copies the creating flow's origin.
- `mojo/tsolve/__init__.py`: `Solution.why_none(path, name) -> str` ('' when there is an
  answer, else `annotated`, `undecidable`, `bot`, `not-defined`; `bot-return` arrives in step 2).
- `mojo/backend_gimple/emit_funcs.py`: the ledger as in 4.5 (dedupe, `reason=`, summary line),
  KEEPING the single `conflict` class for now; the `shadow` lines in `gen_func` after the
  `_record_home_def_return_type` call at emit_funcs.py:4281. Keep the per-key dedupe in a dict
  on `gen` shared like `_tsolve_ledger` (`emit_resolve._compile_imported_module` share block).
- `tools/tsolve_why.py` (not in the closure, may use anything): `--fn NAME [--path PART]
  [--depth N]` prints the `dyn`/`bot` provenance chain of a function's return (2.6 step 4, with
  `Flow.origin`); `--classify LEDGER` prints 2.3's table; `--shadow SELFHOST_CI` prints 2.5's
  shadow report; `--undecidable` prints 2.5's cause counts. It builds the program the way
  `_solve_import_closure` does (2.6 step 1).
- Verify: `python3 test_tsolve.py`, `python3 test_import_cycle_sigs.py`,
  `python3 tools/c_oracle.py check --base fb2a9269b` (identical), `python3 compile_stdlib.py`.
  New unit test: origins are recorded (a two-line function's return flow carries line 2).

### Step 2: the solver's precision (behaviour change only for programs with an import cycle)

In this order inside the step (each with its unit tests, section 6):
1. 4.2d (`None` receivers) and the monotonicity statement in solve.py's docstring.
2. 4.3 (`ret_terms`, `eval_term`, `bot-return`).
3. 4.2a externs (`mojo/tsolve/externs.py`, `_Binding('extern')`, `_extern_dotted`,
   `_builtin` rows, `<file>`, str methods).
4. 4.2b dotted annotations (`sty.ClassNames`, `_names_for`).
5. 4.2c narrowing (`_facts`, `_push`/`_pop`, `_block`, ternary, `and`/`or`, the soundness
   guard; `Term.ty` for `narrow`; delete `_isinstance_narrow`).
6. 4.2e static/class methods, 4.2f loose fields.
7. 4.2g kind pins (`Program.kind_pinned`, `sty.is_bare_container`, `sty.kind_join`,
   `Program.pin_ann(var, text, names)` used by every annotation pin site), 4.2h cast helpers.
8. 4.2i coverage.

Measure before committing, without a compile: `tools/tsolve_why.py --classify <last ledger>`
and `--shadow <last selfhost.ci>`; expect the prototype's numbers (4.7) or better, and zero
early-set `weak`. Verify: test_tsolve, test_import_cycle_sigs, c_oracle against `fb2a9269b`
(any changed program must contain an import cycle; name it), compile_stdlib.

### Step 3: annotated early decisions and the ledger classes

- `funcs_shared.annotated_return_ctype(gen, fn_node)` and the consolidation in 4.4.
- `FnSummary.node`, `Solution.definition`, `Solution.is_annotated`.
- `emit_funcs._early_return_decision`: the annotated branch; `_record_home_def_return_type`:
  the `conflict`/`weak`/`refined` classification (a helper
  `_return_disagreement(frozen, measured) -> str` in emit_funcs.py, with its table in the
  docstring).
- `test_import_cycle_sigs.py`: add an annotated cross-cycle function (`def pair(n) ->
  tuple[str, str]` returning a runtime tuple, and `def label(x) -> str`), and assert the ledger
  has their `early ... annotated` lines and no `conflict`, `weak` or `undecided`.
- Verify as step 2.

### Step 4: `mojo/tsolve` compiles in the closure

- 4.6 loader protocol (`summarize.py`, `__init__.py`, `funcs_shared.ClosureLoader`,
  `gimple_codegen._solve_import_closure`, `test_tsolve._Files`).
- 4.6 owner-first global C type (backend). Regression test in `test_gimple.py` (or the file
  that holds the module-global cases, e.g. the `own_module_global_beats_the_imported_homonym`
  case of `test_gimple_runner.py`): two modules, each with a module-level `X: <its own class> =
  <its constructor>()`, one importing the other; build and run, compare with CPython.
- Verify: c_oracle identical against `fb2a9269b` (the loader change is behaviour-preserving;
  the global-type change may change C only for programs with such a homonym: name them),
  test_tsolve, compile_stdlib.

### Step 5: acceptance and the docs

Run 2.1 once. Record every number of section 8 in this doc's Status. Then: delete
`bugs/GIR_selfhost_extern_return_types.md` if its own acceptance is met (it is, when section 8
is), update `doc/GIR.md` "Selfhost closure: remaining errors", edit `bugs/GIR_type_solver.md`
per section 9, rewrite this doc's own citations of the deleted doc (name the bug or the
commit instead), run `python3 tools/dangling_doc_refs.py --ratchet`. If anything in section 8
fails, do not mark it; write the failing number and the provenance (`tools/tsolve_why.py`)
into Status and fix the rule with a unit test.

## 6. Tests (`test_tsolve.py`; today 41 cases)

Step 1: an origin test.
Step 2, one or more cases per rule, each a small program solved with `_ret`:
- None receiver: `def f(d):\n    x = None\n    x = d\n    return x.get("k")` with `f({"k": "v"})`
  is `str`, whatever the flow order (also solve twice with the flows reversed and compare).
- bot-return: `def f(o):\n    if o:\n        return o.unknown_field\n    return None` with no
  caller is None (`why_none == 'bot-return'`).
- externs: `import os\ndef f(p):\n    return os.path.basename(p)` is `str`;
  `os.path.splitext(p)[0]` is `str`; `from os.path import join` then `join(a, b)` is `str`;
  `open(p).read()` and `with open(p) as fh: return fh.read()` are `str`; an unknown extern
  call is `dyn`; `os.path` is never a field read (a class with a `path: list` field in the
  closure does not change `os.path.basename(p)`). One test walks `externs.FUNCS` and checks each
  callable row against CPython (`type(os.path.join('a', 'b')).__name__ == 'str'`, ...).
- dotted annotations: module `m` defines `class C`, main does `import m` and
  `def f(x: m.C):\n    return x.name` with `C.name: str` gives `str`.
- narrowing: `isinstance(x, m.C)`; `isinstance(x, C) and x.name`; ternary
  `x if isinstance(x, str) else str(x)` is `str`; `if not isinstance(x, dict): return None` then
  `return x` is `dict`; `isinstance(x, (A, B))`; the guard: `if isinstance(x, C):\n    x = 1\n
  return x` is NOT narrowed.
- static/class methods: `class K:\n    @staticmethod\n    def m(a):\n        return a + "!"`,
  `K.m("x")` is `str`; a classmethod through `mod.K.m(...)`.
- loose field: `def put(g):\n    g.cache = {"a": 1}` and `def get(g):\n    return g.cache` with
  both called on a `G()` whose class does not declare `cache`: `dict[str, int]`.
- kind pins: `def f() -> dict:\n    return {"a": [1]}` read through `f()["a"]` is `list[int]`;
  `def g(x: list):\n    return x[0]` called with `["s"]` is `str`; called also with an unknown
  value, `dyn`.
- cast helpers: `def _as_dict(e: object) -> dict:\n    return e`, then `c = _as_dict(g.f)`,
  `c["k"] = (1, "s")`, `return c["k"]` is `tuple[int, str]`; `_as_str(x)` is `str`.
- coverage: `for a, (b, c) in xs` decidable with the right slots; `x[1:2] = ys`;
  `a[i][j] = v` decidable; `{**d, "k": 1}`; a class inside a function; `*a, b = xs`.
- the existing `test_isinstance_narrows_inside_its_branch` and
  `test_a_decorated_function_is_undecidable` keep passing unchanged.
Step 3: `test_import_cycle_sigs.py` additions (above), and a unit test of
`_return_disagreement` over its table.
Step 4: `test_tsolve` drives `ClosureBuilder` directly (the request/provide loop), and the
backend global-homonym runtime test.
Closure acceptance: section 8.

## 7. Risks

- R1 (step 3) An annotated early decision reads backend state too early: `_resolve_type` of a
  class that the in-progress module has not registered, or a `MojoTuple_*` typedef emitted after
  its first use. Shows up as `conflict ... annotated` or a gcc `unknown type name`. Mitigation:
  `annotated_return_ctype` calls `_ensure_tuple_struct` exactly as the definer does (check where
  the typedef lands in the TU with the step 3 test); if a class is not yet registered, register
  the in-progress module's classes before `_gmp_compile_imports` rather than special-casing the
  decision.
- R2 Aliasing (pre-existing, made more visible). Container contents are VALUES: a write
  through an alias (`c = self.f; c[k] = v`, or a callee appending to a list argument) reaches
  the alias's var, not the original. Precise contents can therefore miss a write and a
  `refined` answer can be wrong with no second opinion. Mitigation now: section 8 requires each
  `refined` name to be justified from the source. Follow-up (not required for acceptance):
  "field-alias locals", a local whose only assignments are a field read (possibly through a
  cast helper) also flows its `grow` terms into that field's var.
- R3 Narrowing is flow-insensitive within its region; the 4.2c guard covers rebinding, not
  mutation through an alias (same as R2).
- R4 The externs table states facts about CPython; a wrong row is a wrong precise answer. The
  CPython-checking unit test is the mitigation; keep the table to functions the closure calls.
- R5 Cost: the prototype summarizes and solves the closure in 65 s, the same as HEAD (flows
  +2.5%). If step 2 is slower by more than 10%, profile before landing.
- R6 Self-hostability: everything added to `mojo/tsolve` is compiled by the closure. The
  prototype used `getattr` and tuples for brevity; the real code must not.
- R7 Step 2 changes generated C for programs with an import cycle (that is its purpose).
  c_oracle against `fb2a9269b` must list only such programs.

## 8. Acceptance (all required; record each number in Status)

1. `python3 test_tsolve.py` (41 + the new cases) and `python3 test_import_cycle_sigs.py` pass.
2. The closure run (2.1): gcc has 0 `conflicting types`, 0 `makes integer from pointer`,
   0 `cannot convert to a pointer type`, 0 errors in `mojo/tsolve/*`, and otherwise only the
   three `MojoList * + double` errors. Ledger summary: `conflict=0 weak=0 undecided=0`; every
   `refined` name listed in Status with the source line that makes the solver's type right
   (expected: the five of 4.7); `early` about 140 (one per distinct back-edge name).
   Report the `shadow` count too (no threshold; it is the S2 metric).
3. `python3 tools/c_oracle.py check --base fb2a9269b`: identical, except programs with an
   import cycle (named) or, for step 4's backend change, a global homonym (named).
4. `python3 compile_stdlib.py`: `FAILED: N (E expected, U unexpected)` with U not increased and
   no new `skip` lines.
5. `python3 test_gimple_lint.py`, `python3 test_type_string_ratchet.py`,
   `python3 test_gir_builder.py` pass.

## 9. What this replaces in the other docs

- `bugs/GIR_selfhost_extern_return_types.md`: Status "Remaining, in order of what the census
  shows" items 1-4 (2026-11-24, later) are replaced by sections 3-5 here; item 1's "narrow a
  parameter by what its uses prove" is rejected (4.8); item 3's "their answer is `bot`" is
  wrong (2.3). Acceptance item 2: "0 `conflict`" now means the 4.5 table; "expect about 32
  `early` lines" becomes about 140.
- `bugs/GIR_type_solver.md`: 2.1 `from_annotation` bare `list`/`dict`/`set` rows (now kind
  pins, 4.2g) and dotted names (4.2b); 2.3 rows "`with e as x` -> DYN" (now `<file>` for `open`),
  external imports (4.2a), "the only flow-sensitive rule" paragraph (4.2c), "anything else ->
  const DYN" for calls (externs, static methods), the builtin table (4.2a), the field rule on
  a `BOT`/`DYN` receiver (a `none` receiver is `BOT`, 4.2d); 2.5 "None unless ...
  UNANNOTATED" (the annotated decision moves to the backend routine, 4.4, and `bot-return`
  joins the None cases, 4.3). §3 S2: the `shadow` ledger lines and `tools/tsolve_why.py
  --shadow` deliver the shadow report.

## Status

### HANDOFF (read first; kept current by whoever works on this)

- Branch: master. Commits so far (newest last): c7878b789 (step 1 instruments), db2a1cdba
  (2a None receivers, bot-return), 8bc44e1ed (2b externs), b5a1cccdf (2c narrowing),
  336eff194 (2d dotted annotations), c8bb6578a (2e static/class methods, 2f loose fields).
- 4.2e (static/class methods) and 4.2f (loose fields) LANDED and verified: test_tsolve 64/0,
  c_oracle identical vs 336eff194 (286 + 35), compile_stdlib 610/0, cycle test PASS.
- 4.2g (kind pins), 4.2h (cast helpers), 4.2i (coverage) IMPLEMENTED (session 3, on master, not
  VERIFIED: test_tsolve 74/0, c_oracle identical vs 08849a810 (286 + 35), compile_stdlib 610/0,
  cycle test PASS. Deviations, decided while
  implementing:
  * 4.2h: the design's own test expects `_as_dict(g.f)` (an unknown argument) to give
    `tuple[int, str]`, but its rule says an argument of another kind gives the named kind with
    `dyn` contents. The sound rule is kept (3.4: unknown is not empty; `dyn` is the join's top);
    the test now passes a real dict, and a second test pins the unknown-contents case as `dyn`.
  * 4.2i: a store into a container no modelled name holds (`a[i][j] = v`) flows nowhere (R2), so
    it is decidable; a class inside a function is a `dyn` local, its methods are not summarized
    (the same reach as a nested def's flows, noted as a coverage limit).
  * 4.2g: `kind_join` keeps `none`/`bot` out of the contents; a kind-pinned variable that only
    ever receives `None` stays `bot` (no information), which is undecided, not a wrong answer.
- STEP 2 DONE (2d1a9131c: 2g-2i; earlier commits as listed above).
- STEP 3 LANDED (verified: c_oracle identical vs 2d1a9131c, 286 + 35; compile_stdlib 610/0;
  test_import_cycle_sigs PASS including the annotated `label`/`pair` cases). Contents:
  * `funcs_shared.annotated_return_ctype(gen, fn_node)`: the one annotated-return routine. Used by
    gen_func (emit_funcs) and `_resolved_export_entry` (funcs_shared). NOT yet used by
    module_gen's all-functions loop (~line 13180, its ordering differs; to consolidate next).
  * `FnSummary.node`, `Solution.definition`, `Solution.is_annotated`.
  * `_early_return_decision` decides an annotated definer by `annotated_return_ctype` (ledger suffix
    ` annotated`).
  * `_return_disagreement(frozen, measured)` (same | refined | weak | conflict) in emit_funcs, with its
    table in the docstring; the record path logs refined/weak/conflict lines.
  * test_import_cycle_sigs.py: annotated `label -> str` and `pair -> tuple[str, str]` in the cycle.
  * STILL OPEN in step 3: a unit test of `_return_disagreement` over its table (design 6); and
    module_gen's all-functions loop (~line 13180) still computes its own annotated return.
- STEP 4 IN PROGRESS.
  * DONE (verified: c_oracle identical vs bacc2f396, 286 + 35; compile_stdlib 610/0; cycle PASS;
    test_tsolve 74/0): the loader is an OBJECT with `resolve(ref, importer) -> ModuleFile | None`
    (summarize.ModuleFile, `_Pending`); `solve_closure(root, stmts, loader)`; no stored callable,
    no tuple results. DEVIATION from 4.6: no request/provide loop; a method call on the loader object
    meets the same rule (no closures, no stored callables) with less code.
  * NOT DONE: owner-first global C types (4.6, backend). Measured reason to do it: `sty.py`'s
    `BOOL`/`INT` globals get a cast to `mojo/ir/types.py`'s `Type` (2 of the 12 gcc errors). The
    emission path is `gen._global_var_types` (bare name, first writer wins) read by the store of an
    annotated top-level assignment; the fix must look up `_own_global_var_types` first (see
    emit_exprs `_lie_global_window`). Regression test: two modules each with a module-level
    `X: <own class> = <ctor>()`, one importing the other; build, run, compare with CPython.
    Find the store emitter first (grep the generated `(Type *)` cast in a closure TU).
- STEP 5 (not started): acceptance (section 8): closure run (2.1) and the doc updates of section 9.
- Tools: `tools/tsolve_why.py --classify|--shadow|--undecided LEDGER`. `--fn` and `--undecidable`
  (section 2.6, need the solved program) are not written yet.
- How to verify each step: `python3 test_tsolve.py`; `python3 tools/c_oracle.py check --base <last
  commit>` (identical unless a program has an import cycle); `python3 compile_stdlib.py` (PASSED 610,
  FAILED 0); `python3 test_import_cycle_sigs.py`. Acceptance (section 8) is the closure run (2.1),
  about 5 minutes, ~11 GB under memcap.
- Known pitfalls found this session: an analysis that does not call `solve()` sees every variable
  as `bot`; the AST rewriter lowers `os.environ.get` to `mojo_c_getenv` (externs.INTERNAL); the
  stub emitter's keys are mangled symbols (`_definer_name`); the store is keyed by the SANITIZED
  qualifier (`module_qualifier`).


- 2026-11-24 (session 3): designed. Measured as in sections 2 and 4.7 (the HEAD numbers from
  the previous session's acceptance run, re-read; the prototype numbers from a scratch copy of
  `mojo/tsolve`, no compile). Nothing in the tree changed. Next: step 1.
- 2026-11-24 (session 3, implementation): step 1 LANDED (instruments, byte-identical). Flow origins
  (`Flow.origin`, `_Summarizer._flow`/`_stmt`, solver-made flows inherit), `Solution.why_none`,
  the ledger's `undecided reason=` / one-line-per-key dedupe / `shadow` lines (gen_func) / `summary`
  line, `tools/tsolve_why.py --classify|--shadow|--undecided`. Verified: test_tsolve 43/0,
  c_oracle identical vs 0753a4f1f (286 + 35), compile_stdlib PASSED 610 FAILED 0,
  test_import_cycle_sigs PASS. Not yet: `--fn` and `--undecidable` (need the solved program).
  Next: step 2 (solver precision), in the order of section 5.
- 2026-11-24 (session 3, implementation): step 2, first two rules LANDED: 4.2d (`none` receivers
  and containers evaluate to `bot`; the monotonicity invariant is stated in solve.py) and 4.3
  (`ret_terms`, `eval_term`, `Solution.has_bot_return`, `why_none` -> `bot-return`). Verified:
  test_tsolve 45/0, c_oracle identical vs c7878b789 (286 + 35), compile_stdlib 610/0,
  test_import_cycle_sigs PASS. Still open in step 2: 4.2a externs, 4.2b dotted annotations,
  4.2c narrowing, 4.2e static/class methods, 4.2f loose fields, 4.2g kind pins, 4.2h cast helpers,
  4.2i coverage.
- 2026-11-24 (session 3, implementation): step 2, rule 4.2a (externs) LANDED. `mojo/tsolve/externs.py`
  (FUNCS, ATTRS, INTERNAL), `_Binding('extern')` for external imports, `_dotted` names (never a
  field read), `open` as `<file>` (and the `with` form), enumerate/zip/reversed, the wider str table.
  The rewriter's `os.environ.get` lowering (`mojo_c_getenv`) is in INTERNAL, found by testing.
  Verified: test_tsolve 53/0 (incl. CPython check of every FUNCS row), c_oracle identical vs
  db2a1cdba (286 + 35), compile_stdlib 610/0, test_import_cycle_sigs PASS.
  Still open in step 2: 4.2b, 4.2c, 4.2e, 4.2f, 4.2g, 4.2h, 4.2i.
- 2026-11-24 (session 3, implementation): step 2, rule 4.2c (narrowing) LANDED: `_facts`
  (isinstance with a class, a `module.Class`, a builtin type or a tuple; `not`, positive `and`,
  negative `or`), `_push`/`_pop` with the soundness guard (no fact about a name the region rebinds),
  `if`/`elif`/`else` under facts, the rest-of-block facts after `if c: <exit>` (`_block`), ternary
  arms, and the right operand of `and`/`or`; the `narrow` term carries an STy. Verified: test_tsolve
  59/0 (dotted class, and, ternary, early-return idiom, tuple, the guard), c_oracle identical vs
  8bc44e1ed (286 + 35), compile_stdlib 610/0, test_import_cycle_sigs PASS.
  Still open in step 2: 4.2b, 4.2e, 4.2f, 4.2g, 4.2h, 4.2i.
- 2026-11-24 (session 3, implementation): step 2, rule 4.2b (dotted annotations) LANDED:
  `class_names` maps a spelling to its class name; `_names_for(mod)` adds `alias.Class` for each
  closure class an `import m as alias` reaches (built from the target's statements, so declaration
  order does not matter); every annotation pin site uses its module's names. Verified: test_tsolve
  60/0, c_oracle identical vs b5a1cccdf (286 + 35), compile_stdlib 610/0, cycle test PASS.
  Still open in step 2: 4.2e, 4.2f, 4.2g, 4.2h, 4.2i.
