# CODEGEN: the accumulated branch broke the self-host compile, and the biggest error class has a name

**Found 2026-10-02 (`work/bugs4-9-c`)** while running the one suite job a
compiler-source change owes. Filed rather than fixed: the largest class's repair
is a two-phase design decision in an area another claim owns the doc for, and
the second class cannot be reproduced without the whole-closure configuration
that is explicitly a worker's no-go. **The integrator will hit this in the
gate** — `selfhost` is green on `master` and red here — so it is filed with the
attribution rather than left to be discovered.

## The measurement, which is the whole point

    $ python3 tools/suite.py selfhost          # in .tmp/master (git archive master)
      suite: 1 passed, 0 failed  (715.2 s wall, peak 4.0 GB)

    $ python3 tools/suite.py selfhost          # this branch's parent, 90cf4968
      FAIL  selfhost  (206 s)  exit 1

    $ python3 tools/suite.py selfhost          # this branch's HEAD
      FAIL  selfhost  (210 s)  exit 1

164 GCC error lines, and they are **identical** before and after this session's
own commits — the normalized multiset of `file + message + count` diffs empty
(only a quoted comment's line number moves, because the fix added comment lines):

    $ grep -E "error:" build/suite.log | sed -E 's|.*/\.tmp/pre/||; s|:[0-9]+:[0-9]+: error:| error:|' | sort | uniq -c
    # identical on both trees

So the break is in the **133 commits this branch adds over master**, not in the
work that landed here today.

## The error classes, largest first

| count | class | attributed? |
|---|---|---|
| 21 + 8 + 4 + 3 + 2 + … | `'_mojo_elem_repr_<ASTNode>' undeclared (first use in this function)` — `TryStmt`, `WithStmt`, `IdentExpr`, `CallExpr`, `IntLiteral`, … across `coro.py`, `ast_rewriter.py`, `offload.py`, `module_gen.py`, `cpp_core.py`, `emit_calls.py`, `emit_loops.py`, `funcs_shared.py`, `lambdareduce.py`, `infra_infer.py`, `regex_compile.py` | **YES — `aab36167`** |
| ~33 | `'struct _mojo_<module>_toplev has no member named '_module_loader'` / `'_TYPE_MAP'` / `'_BIN_OPS'` / `'_C_RESERVED_FUNCS'` / `'_FIXED_ARRAY_ANN_RE'` / `'_SELFHOST_EXTRA_FIELD_CACHE'` / `'STDLIB_PATH'` / `'_BUILTIN_RET_CTYPES'` / … | no — see below |
| 16 + 4 | `passing argument 1 of 'mojo_repr_list_ints' / '_mojo_repr_list' makes pointer from integer without a cast` (`emit_methods.py`, `device_glue.py`, `methods_shared.py`) | no |
| 1 | `module_loader.py:544: implicit declaration of function 'mojo_mark_dict_bool_values'` | already filed: `bugs/COMPILE_FAIL_dict_literal_with_a_bool_value_emits_a_deleted_runtime_entry_point.md` (the runtime entry point was deleted; five emitter sites still call it) |
| 1 | `mojo/middle/solvers.py:708: invalid use of undefined type 'struct _mojo_middle_solvers_toplev'` | no |

## The attributed class: `aab36167`, reproduced in four seconds

`aab36167` — *"repr: a container renders its struct elements through the struct's
own `__repr__`"* — is the commit that introduced the `_mojo_elem_repr_*` shim
machinery, and **every one of the 17 commits from it to the branch tip is bad
for this criterion and none before it is**. Linear scan of all 126 commits
between `master` and `90cf4968`, four seconds per commit:

```python
# .tmp/bisect_probe.py — ONE module, one criterion, ~4 s per commit
from gimple_codegen import compile_to_gimple
c = compile_to_gimple(open('mojo/middle/coro.py').read(), do_imports=False,
                      filename='mojo/middle/coro.py')
defs  = set(re.findall(r'static char \* (_mojo_elem_repr_\w+) \(', c))
decls = set(re.findall(r'static char \* (_mojo_elem_repr_\w+) \(int64_t v\);', c))
uses  = set(re.findall(r'_mojo_elem_repr_(\w+)', c))
print(sorted({'_mojo_elem_repr_' + u for u in uses} - defs - decls))
# aab36167 and later: ['_mojo_elem_repr_TryStmt', '_mojo_elem_repr_WithStmt']
# before:            []
```

Four seconds against 206 s for the failing suite job and 715 s for the passing
one, because the criterion is a property of the GENERATED C rather than of the
gcc invocation — which is also why it is the right thing to bisect on: it names
the commit that introduced the gap rather than the one that surfaced it first.

### The mechanism, exactly

Two places disagree about what "a shim exists" means, and the disagreeing one is
in the caller:

* `module_gen.py`'s `reflect_structs` emits `_mojo_elem_repr_{sn}` only for
  `reflect_emitted`, which is `struct_field_types` keys filtered by a THREE-way
  intersection: in `struct_field_types` **AND** `_emitted_structs` **AND**
  `_struct_allocs_needed` (with a pointer slot). Its comment says why the
  three-way test exists — self-hosted, a `sorted(setA & setB & setC)` loop var
  typed `int64_t` and every `f"_mojo_repr_{sn}"` then concatenated a boxed
  pointer.
* `emit_exprs.py`'s `_struct_elem_repr_shim` — the site that emits
  `mojo_list_set_elem_repr(t, _mojo_elem_repr_X)` for a list literal whose
  element type is a struct — asks ONE of those three: `struct_field_types[sn]`
  non-empty. Its docstring says this is deliberate ("the same condition
  `reflect_structs` itself filters on, restated rather than queried so this
  needs no new cross-module table").

**It is not the same condition**, and that is the whole bug: `TryStmt` and
`WithStmt` have fields (so they pass the caller's test) and are never allocated
or emitted as structs in the self-hosted closure (so `reflect_structs` skips
them and no shim is declared anywhere). The caller then names a function that
does not exist, in ~21 places.

**Why the repair is not a one-line tightening of the caller's test**, which is
the obvious fix and does not work: neither `_emitted_structs` nor
`_struct_allocs_needed` is populated at the time the call site runs. Both are
filled DURING body emission (`_lower_struct_constructor`,
`emit_stmts.py`'s annotated-struct VarDecl) and again while the struct typedefs
are RENDERED — which happens after every function body in the same
`parts`-building function. So at the call site the answer is not yet available,
and `mojo_list_set_elem_repr`'s argument is written into the body inline, where
it cannot be retracted later either.

That leaves a genuine design decision, which is why this is filed and not
fixed: the choice is between (a) record the request in a side table during body
emission and, in `reflect_structs`, emit a shim for every REQUESTED struct that
`reflect_emitted` skipped — which needs a definition for a struct whose typedef
and `_mojo_repr_{sn}` do not exist in this unit, so the shim would have to
degrade to something like `mojo_repr_obj(v)`, i.e. re-introduce the pointer
decimal `aab36167` was written to remove, for exactly the structs that cannot be
reflected; and (b) something in the pre-pass that makes the three-way test
answerable before bodies are emitted, which is a cross-module data-flow change.
(a) is a behaviour decision about what `repr([<unreflectable struct>])` should
print; (b) is a bigger change. Neither is a drive-by, and
`bugs/CODEGEN_user_defined_dunder_repr_not_consulted_by_str_and_container_
spellings.md` (another claim's) is the doc for the behaviour (a) would trade
against, so the decision belongs with that owner.

## The second class, and why it is not attributed

`'struct _mojo_backend_gimple_emit_infra_toplev has no member named
'_module_loader'` and ~32 siblings: a module-level constant of the compiler's own
`mojo/backend_gimple/*` modules is read from a function body but is not a member
of that module's toplevel struct. **The same cheap probe does not judge this
one**: compiling `mojo/backend_gimple/emit_infra.py` alone emits no toplevel
struct at all (the name appears nowhere in its output), because the struct is
only produced in the module-boundary / whole-closure configuration. So the
criterion has to be the closure build, i.e. `suite.py selfhost` at 206 s per
failing commit — feasible, but it is ~10 steps and this is where the gate's time
belongs. `git log -S` does not isolate it either, because the reads are
ordinary attribute accesses that were always in the source.

The structural question for whoever takes it: `_module_loader`,
`_TYPE_MAP`, `_BIN_OPS`, `_C_RESERVED_FUNCS`, `_SELFHOST_EXTRA_FIELD_CACHE`,
`_BUILTIN_RET_CTYPES`, `_LIBM_FN_RETVALS`, `STDLIB_PATH`, `TEST_PATH` — a
module-level NAME that is read at toplevel must be in the toplevel struct's
field list, and the field-freeze pass that builds that list is not covering the
`mojo/backend_gimple/*` modules' own constants.

## What the integrator should do with this

1. Do not read a red `selfhost` in the gate as caused by the branch merged today;
   it is red at `90cf4968`, i.e. before this session's first commit.
2. The `aab36167` class is the largest (21+ of 164) and has a four-second
   reproduction, so it is the cheapest thing to move and the one to move first.
3. `bugs/CODEGEN_print_of_a_container_never_frees_the_repr_it_asked_for.md` (the
   other doc filed in this session) is a real leak and unrelated to any of this.

## Commands, for reproduction

```sh
git archive master | tar -x -C .tmp/master      # then, in .tmp/master:
python3 tools/suite.py selfhost                 # 1 passed, 715 s, 4.0 GB

git archive 90cf4968 | tar -x -C .tmp/pre       # then, in .tmp/pre:
python3 tools/suite.py selfhost                 # FAIL, 206 s, 2.1 GB
grep -E "error:" build/suite.log | sed -E 's|.*/\.tmp/pre/||; s|:[0-9]+:[0-9]+: error:| error:|' \
  | sort | uniq -c                                # the class census above
```

The `_mojo_elem_repr_*` probe itself is the `bisect_probe.py` in this session's
`.tmp/`; it is thirteen lines and needs no suite job.