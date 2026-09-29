# FORMAL_module_state_no_storage: a module cannot hold state, so `sys.argv`, `sys.path` and the stream objects cannot exist on this path

**Status: OPEN, and it is a property of the value model rather than a gap in any
one emitter. Nothing in `sys.mojo` is a workaround; the names it does not define
are listed there with this document as the reason. Closing it means changing what
a formal value IS, which is a change the two backends AND the Lean proof share.**

Found while writing the `sys` module for the formal backend (2026-09-29, the
`module:sys` claim). Every measurement below is from this tree at `ca6e758`.

---

## The rule, and it is one rule

`formal/model.py`, in the comment above `GlobalSymbol`, states it: *"every value a
formal program can name lives in a function's own stack scratch (`_SCRATCH` …),
and that scratch is reclaimed when the function returns. This is the same lifetime
argument that makes a frame address in a field a use-after-free, and it is why
there is no `__DATA` block to put a mutable global in."*

Two consequences, and they are separate, so they are measured separately:

1. **A module-level name that is not a literal-only constant cannot be read, even
   inside the module that declares it.** `fold_literal_expr` substitutes a
   folded `int`/`str`/`bool` at every read site; anything else is refused by name.
2. **A value cannot cross a dylib boundary at all unless it is one 64-bit
   word.** A list or a tuple is a blob carved out of the caller's frame, so
   handing one to another module hands over a frame address that is dead on
   return.

## Measured

**(1) A module-level list, in the module itself.** `.tmp/exp1/g1.mojo`:

```mojo
G = [1, 2, 3]

def get():
  return G
```

```
build: get: 'G' is bound at module level, and this path has no module-global
storage for it: a formal value lives in a function's own stack scratch, and that
scratch is reclaimed when the function returns …
```

The same file with `G = 7` and `H = "hi"` builds and runs, because those are
literal-only and get substituted. So the refusal is about the VALUE, not about
module-level names as such.

**(2) A module-level name, read from ANOTHER module** — the shape `sys.argv` has.
`from mylib import PLAT` where `mylib.mojo` has `PLAT = "darwin"`:

```
build: main: 'PLAT' is imported from `mylib`, so it is a module-level name of
another module. This path compiles an import into a dylib, and a module-level
name is not exported as a word — there is no storage for it here
```

**(3) A tuple cannot cross a dylib boundary — and the failure is a
use-after-frame, not a refusal.** A module returning `(3, 14, 0)`, printed by the
importer:

```
3
print(tupm.vi())   ->   6159887712
```

That is the frame address, printed as a number. The same program does not even
build when the call is in the same unit (`print() cannot tell whether IdentExpr
is a string or a number`).

**(4) `sys.argv` additionally has no SOURCE on this path.** The entry stub
(`ARM64Codegen.compile`, and `X86_64Codegen`'s twin) loads the test input into
X0 and branches to the entry function:

```python
test_val = self.test_input
self.asm.emit(encode_movz_xn_imm(0, test_val))
self.asm.emit(encode_bl(0))
self.asm.emit_label_rel(first_func_name, here_offset=-4)
```

`argc`/`argv` arrive in X0/X1 from the kernel's start and are overwritten before
the first statement runs. So even with storage there would be nothing to read:
the command line is gone, not merely unreachable.

## What this costs, by name

Of the `sys` surface this repository's own files use, measured with
`grep -o "sys\.[a-zA-Z_]*"` over the fourteen files the sweep listed for `sys`:

| `sys` name | uses | blocked by |
|---|---|---|
| `sys.argv` | 73 | (1)+(2)+(4) — a list, in a module, with no source |
| `sys.stderr` | 44 | (2)+(3) — a stream OBJECT, and there is no object |
| `sys.exit` | 33 | a **settled, different** reason: `doc/ABI.md`'s export rule does not advertise a C library symbol (`exit` is one), so no module dylib can be called by that name. Measured and closed in `bugs/FORMAL_known_limits.md` §1.1. The working spelling on this target is a bare `exit(code)`, which lowers today and exits 3 — pinned by `test_formal_sys.py`. |
| `sys.platform` | 7 | no honest value exists: one source file is compiled for Mach-O and for ELF, and nothing in the language asks the target which it is. A module-level `PLATFORM = "darwin"` would be a lie on the ELF build. |
| `sys.setrecursionlimit` + `getrecursionlimit` | 4 | (2) — but the module answers them as functions returning the honest value for a target with no interpreter stack |
| `sys.path` | 3 | (1)+(2) — a mutable list |
| `sys.stdin` | 1 | (2)+(3) |
| `sys.modules` | 1 | (1)+(2)+(3) — a dict of live module objects |

So 117 of the 167 `sys` uses in those files are `argv` and `stderr`, and both are
the same missing capability. `sys.exit` is the next largest and is closed by a
different, already-settled decision.

Over the WHOLE tree (every `.py`/`.mojo` outside `doc/`, `bugs/` and `build/`)
the shape is the same and the two blocked names are bigger still:

| `sys` name | uses, whole tree | blocked by |
|---|---|---|
| `sys.exit` | 194 | the settled export rule, above — not this document |
| `sys.argv` | 167 | (1)+(2)+(4) |
| `sys.stderr` | 137 | (2)+(3) |
| `sys.path` | 103 | (1)+(2) — a mutable list of strings |
| `sys.executable` | 43 | (1) again, one step on: libSystem's `_NSGetExecutablePath` answers it and writes into a CALLER-SUPPLIED buffer, so the missing thing is a place to put a path. Not a capability this target lacks. |
| `sys.platform` | 31 | no honest value; see the table above |
| `sys.modules` | 16 | (1)+(2)+(3) — a dict of live module objects |
| `sys.stdout` / `sys.stdin` | 24 | (2)+(3) |
| `sys.version_info` | 8 | (3) — a tuple |

`sys.executable` is worth its own line because it is the case where reading this
document would otherwise produce the wrong conclusion: the capability IS
reachable (libSystem has the call), and what is missing is storage for its
answer. That distinction is the whole difference between option A and option B
below.

## What `sys.mojo` does instead, and why it is not a dodge

`sys.write_stdout(s)` / `sys.write_stderr(s)` are `write(1|2, s, strlen(s))`
through the module's own exported function. That is a real operation on the real
descriptor, and it is the only spelling available: `sys.stderr` would have to be
an object, and (2)+(3) say an object cannot cross the boundary. The module says
so at each definition, names what it cannot do and why, and cites this document.

## What moved, measured, so nobody has to re-derive it

All fourteen files the sweep listed for `sys` at the start, swept from a CLEARED
CAS (see `bugs/FORMAL_sweep_cache_ignores_imports.md` for why that matters),
`python3 tools/formal_sweep.py --no-stdlib <the fourteen>`:

| file | class before | class after | what stops it now |
|---|---|---|---|
| `t1.mojo` | not-answerable/host-import (`sys`) | **pass** | nothing — but the pass is hollow, see `FORMAL_toplevel_statements_dropped.md`: its body is top-level, so it exits 0 where it says `sys.exit(3)` |
| `t_argv.mojo` | not-answerable/host-import (`sys`) | **codegen** | this document: `sys.argv` |
| `tools/ci_line.py` | not-answerable/host-import (`sys`) | **codegen** | `f.readlines()` — a value method the path does not lower |
| `unescape_c.py` | not-answerable/host-import (`sys`) | **codegen** | `len(s)` where `s` classifies as an int |
| `fire.py`, `build_module.py`, `mojo.mojo`, `scripts/run_mojo_main.py`, `tools/compile_one.py` | not-answerable/host-import (`sys`) | not-answerable/host-import (**`os`**) | `os` — the `module:os` claim |
| `fire_main.py`, `mojo/middle/comptime.py`, `test_async_parsing.py`, `test_yield_parsing.py` | not-answerable/host-import (`sys`) | not-answerable/host-import (**`re`**, through `fire_compiler`) | `re` — **unclaimed** |
| `test_refactor_bugs.py` | not-answerable/host-import (`sys`) | not-answerable/host-import (**`os`**, through `gimple_codegen`) | `os` |

So three of the fourteen moved out of the `sys` refusal, and **eleven were never
blocked by `sys` alone** — they hit `os` or `re` first, which is the sweep
reporting the FIRST thing wrong with a file rather than every thing wrong with
it. `sys` was the whole of the answer for three files, and for the other eleven
it was one line among several.

`re` is worth calling out separately: it blocks four of the fourteen and no
worker holds it.

## The exact next step, for whoever takes it

Two options, and they are different sizes. Both are changes to the VALUE MODEL,
so both are changes the two backends and the Lean proof share, and neither is
this task's to make.

**A. A `__DATA` block for module state (opens `argv`, `path`, `modules`, and
every mutable module global).** `formal/model.py` already has a folded-constant
path that SUBSTITUTES at each read, and the comment above `GlobalSymbol` is
explicit that a stored global is the other half of the same two-way answer. What
is missing is the storage and the accessors: a `__DATA` segment in
`formal/macho_linker.py` (and `formal/elf.py`), a static initializer emitted from
the module's own top-level sequence, and a GOT-free absolute-address load for a
read. Cost: a new segment in both containers, a lifetime story for the proof
(`formal/arm64_proof_gen.py` would have to say what is live across a call), and
the existing frame-address-is-a-use-after-free argument has to be re-examined for
every construct that stores a value in a global.

**B. Keep the model and give the module a protocol (opens nothing on its own).**
A module that needs to publish a computed value exports a FUNCTION that
recomputes it, and the importer calls the function. That is what `sys.mojo` does
for everything it provides, and it is honest as long as the value is a pure
function of the target — which is why `byteorder`, `maxsize` and `hexversion` are
in it and `argv` is not. Cost: nothing in the compiler, and it does not close
`argv`, `path` or the streams.

The third option, and the one NOT recommended: a `sys.argv` that returns a
fabricated one-element list, or a `sys.stderr` that is a struct wrapping the
integer 2. Both build, both run, and both compute something other than what their
name says, which is the failure mode this whole backend's refusals exist to
prevent.
