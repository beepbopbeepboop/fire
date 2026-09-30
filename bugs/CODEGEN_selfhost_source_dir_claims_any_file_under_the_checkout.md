# `_is_selfhost_source_dir` still says "self-host" for any file under the checkout, and injects the compiler's own AST struct layouts into a user program's C

**State: OPEN, not fixed. One instance of a defect that WAS fixed elsewhere
in the same series** — see "Relationship to the fix that landed" below.

## What I ran

`.tmp/issd_probe.py` (scratch; not committed) compiles ONE byte-identical
program twice through `gimple_codegen.compile_linked`, once with the source
file under this checkout and once under `/tmp`, in the same process, then
diffs the two generated C texts. The program is ordinary: an `import`, a
top-level `def helper(a, b)`, a `class Box` with `__init__`/`get`, a `def
run(path)` using `len`, `int`, `os.path.basename` and a dict, and a
`print`.

```
_is_selfhost_source_dir(<repo>/.tmp/x)            = True
_is_selfhost_source_file(<repo>/.tmp/x/prog.py)   = False
_is_selfhost_source_dir(/tmp/x)                   = False
_is_selfhost_source_file(/tmp/x/prog.py)          = False

in-repo  C bytes : 38473
out-repo C bytes : 32057
DIFF lines: 355
```

## What I saw

355 diff lines for a program with no AST nodes in it. All but one are
struct typedefs the compiler injected for ITSELF and the out-of-repo build
does not emit at all:

```
+typedef struct BinaryOp   { int64_t __mojo_type_id; char * op; int64_t left; int64_t right; } BinaryOp;
+typedef struct CallExpr   { int64_t __mojo_type_id; int64_t func; MojoList * args; MojoList * kwargs; } CallExpr;
+typedef struct MemberExpr { int64_t __mojo_type_id; int64_t obj; char * member; } MemberExpr;
+typedef struct Parser     { int64_t __mojo_type_id; MojoList * _tok; int64_t _pos; char * _filename; ... } Parser;
+typedef struct Scope      { int64_t __mojo_type_id; struct Scope * parent; MojoDict * vars; } Scope;
+typedef struct ReturnValue      { int64_t __mojo_type_id; int64_t value; } ReturnValue;
+typedef struct BreakException   { int64_t __mojo_type_id; int _dummy; } BreakException;
+typedef struct ContinueException { ... } ContinueException;
+typedef struct MojoOverloadSet  { ... } MojoOverloadSet;
+... (Token, UnaryOp, SubscriptExpr, SliceExpr, WalrusExpr, ...)
```

The single remaining diff hunk is the `#line` directive, which correctly
carries each file's own path.

## What I expected

Byte-identical generated C. A program's location is not something the
language gives a compiler any reason to treat specially, so the same source
must compile the same way whether it is written in `/tmp`, in `build/`, or
in a downstream project's own checkout — and certainly must not acquire the
*compiler's* AST-node struct layouts on the strength of where it sits.

## Where

`mojo/backend_gimple/module_gen.py::_is_selfhost_source_dir` (line 63). It
answers "is this a directory holding a genuine checkout of this compiler's
own source", which is a question about the DIRECTORY — and it answers it by
walking UP from the file's directory looking for a `fire_compiler.py`
ancestor, so it is True for every descendant of this checkout, including
`.tmp/`, `build/`, `tools/`, `formal/` and anything else below them.

Two call sites, both unconditional once it says True:

- `module_gen.py:1761` — `_is_selfhost_file`, which registers
  `struct_field_types` entries for `Scope`, `Token`, `ReturnValue`,
  `BreakException`, `ContinueException`, `MojoFunction`, `_MojoSortFn` and
  the rest of the AST node set into `self.struct_field_types`. That table is
  what member-access typing reads, so a user program that declares its own
  `Scope`/`Token`/`Parser` and happens to live inside the checkout is typed
  against the COMPILER's layout for that name. I did not construct that
  collision; the 355-line diff above is what I did measure, and it is enough
  to show the predicate is over-broad.
- `module_gen.py:1347` — `_seed_selfhost_module_globals` /
  `_seed_selfhost_struct_dict_field_types` / `_seed_selfhost_return_elem_types`,
  which re-tokenize this compiler's own sources and push their globals and
  field types into the gen being used for someone else's program.

## Relationship to the fix that landed

This is the same defect as `bugs/CODEGEN_link_mode_bare_submodule_marker_
call_silent_wrong_value.md` (deleted by that fix) — "is this file the
compiler's own source?" answered by "is it under the compiler's install
directory?" — and it is the THIRD copy of that answer, after the two the
fix consolidated into `mojo/middle/methods_shared.py::_is_selfhost_source_file`:

| site | predicate | status |
|---|---|---|
| `emit_methods.py` `_lower_method_call`'s generic module-qualified-call branch | bare `_SELFHOST_DIR` prefix | fixed |
| `emit_calls.py` `_lower_call`'s A5 `getattr(obj, 'attr', default)` field-type hint | bare `_SELFHOST_DIR` prefix | fixed |
| `module_gen.py::_is_selfhost_source_dir` | `fire_compiler.py`-at-any-ancestor walk | **this doc** |

`_is_selfhost_source_file` is the correct direction — a root-level `*.py`
beside `fire_compiler.py`, or a file inside this compiler's own `mojo/` or
`jit/` package — but it cannot be dropped in here unchanged:
`_is_selfhost_source_dir` is called with a DIRECTORY, not a file, and it
also has to keep recognizing a subdirectory of a genuine checkout reached
through a symlink, plus the compiled binary's `_SELFHOST_DIR`-is-its-CWD
case (its own docstring's `_rdir.split(os.sep)[:1]` note).

## Next step

1. Split the two questions `_is_selfhost_source_dir` currently conflates.
   "Is this a compiler-SOURCE directory?" is answerable with
   `_is_selfhost_source_file` (it needs no ancestor walk at all: the caller
   has the file). "Is this directory somewhere inside a compiler checkout?"
   is a different question and is only needed by the symlinked-subdirectory
   case, which both call sites can answer by asking
   `_is_selfhost_source_file` about the file they already hold.
2. Replace `module_gen.py:1761` and `:1347` with the file-level predicate,
   then re-run `.tmp/issd_probe.py`'s comparison and require **byte-identical
   C** between the two locations. That is the same before/after `cmp` the
   rest of this repo asks for of a behaviour-preserving codegen change.
3. Take `_run_pipeline`'s `_selfhost_register_gimplegen` gate
   (`gimple_codegen.py:4790-4793`) as the shape to mirror rather than
   inventing one: it is already narrow — a basename allowlist
   (`fire.py`/`mojo_main.py`/`fire_compiler.py`) AND a `fire_compiler.py`
   sitting next to the entry file — which is what "genuinely one of the
   compiler's own named entry files" looks like in practice. Not a defect;
   the reason it is in this list is that it is the one gate in the file that
   already got it right, so it is where the answer is.
