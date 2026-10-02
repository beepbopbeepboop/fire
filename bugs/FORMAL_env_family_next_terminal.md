# FORMAL_env_family_next_terminal: `std/os/env.mojo` lowers, and 55 files land on an unbound `unsafe_ptr`

**Filed 2026-09-29, immediately after the `external_call` tuple-subscript fix
(`4ad34f3`).** The 55-file family named in this worker task is closed; the
family has not become 55 passing files, and this is where it lands instead.
Nothing here is a report about a *decision* — the construct now lowers, the
image is correct, and what is left is a different construct this worker did not
claim.

## What changed, measured

`python3 tools/formal_sweep.py --stdlib-subtrees=base64,bit,builtin <stdlib>/std`,
arm64, on a `git worktree add --detach` of the parent commit and on this
branch, both over the same 294 files:

| | parent (`5535925`) | this branch (`4ad34f3`) |
|---|---|---|
| pass | 24 | 24 |
| codegen (in the file) | 88 | 87 |
| codegen/dependency | 181 | 125 |
| not-answerable/unresolved-extern | 1 | 56 |
| codegen coverage | 24/293 = 8.2% | 24/236 = 10.2% |
| `codegen/dependency by family`, top entry | `env.mojo: value with no representation x55` | `info.mojo: MLIR construct x36` |

Diffing the two sweeps file by file: **57 files left the `codegen`/
`codegen/dependency` classes, and 0 entered them, and 0 changed class inside
them.** Two of the 57 are a sweep `-t 30` timeout on
`std/gpu/host/device_context.mojo` (a direct method-call finding, unrelated),
so the honest number is **55** — exactly the family.

## The next terminal, verbatim

```
NOT-ANSWERABLE/UNRESOLVED-EXTERN: std/utils/numerics.mojo
  (build: numerics.mojo imports 'std.sys', which cannot be built either:
   env.mojo: env.mojo: the library would bind 1 symbol(s) that nothing
   provides, so it could not be loaded: unsafe_ptr. …)
```

`std/os/env.mojo` now compiles. The symbol that fails to bind is
`CStringSlice.unsafe_ptr`, reached from its own source:

* `std/os/env.mojo:43,45,61` — `name.as_c_string_slice().unsafe_ptr()`
* `std/collections/string/string.mojo:1442` —
  `def as_c_string_slice(mut self) -> CStringSlice[ImmutOrigin(origin_of(self))]`
* `std/ffi/cstring.mojo:211` — `def unsafe_ptr(self) -> UnsafePointer[Int8, Self.origin]`

So the receiver of `.unsafe_ptr()` is the result of a call whose return type is
a **generic struct instantiation written as a computed type expression**
(`CStringSlice[ImmutOrigin[origin_of(self)]]`). The method-rewriting pass keys
a method on a value receiver on the receiver's static type
(`formal/build.py`'s `_rewrite_method_calls` / `_method_owners`), and a computed
type expression gives it nothing to key on, so the call is not lifted to
`CStringSlice_unsafe_ptr`. The image instead carries a bare reference to the
name `unsafe_ptr`, which no library on the link line provides, and
`formal/build.py`'s `_audit_bound_symbols` refuses it — correctly, and with a
message that is honest about what it knows.

The same refusal already exists in this tree for the receiver that is a plain
local, and says the same thing for the same reason
(`std/utils/static_tuple.mojo`: "a method call on a value receiver is dispatched
by NAME, so `recv.m(x)` carries no type"). What is new here is only the
instantiation in the middle.

## Two things that make the next step awkward, and should be known before starting it

**1. A minimal repro is blocked by an adjacent gap of the same shape.**
Building a two-file version of this — `struct Wrap[t: Int]` with a method, and
a caller — does not reach the bug. It is refused earlier:

```
$ python3 fire.py build --formal --no-prove mm/user4.mojo     # Wrap[Int].mk().get()
build: main: 'Int' has no home: the module-level symbol table is empty for this
unit, and the reading function declares no local or parameter by that spelling.
```

`Wrap[Int]` is a **single**-element subscript, so it is not a multi-index at
all, and the type argument `Int` is a type expression being read as a runtime
name. That is the identical defect the `external_call` fix just closed, in the
generic-construction position instead of the template-application one, and
`formal/build.py`'s `check_module_symbols` still has it: the exclusion added for
`external_call`'s TYPE argument is keyed on
`M.is_external_call_template`, deliberately, so nothing else is exempted by it.
A generic's type argument is compile-time by exactly the same construction, and
the repair is the same shape — but it belongs with the generic/monomorphization
work (`bugs/FORMAL_known_limits.md` §1.2, "Stage 5"), which is a project and
not a patch, and which this worker did not claim.

**2. The family is now filed under a class that says it is not a gap.** The
sweep's `_EXTERN_BUILD_MARK` rule (`tools/formal_sweep.py:393`) files any
`symbol(s) that nothing provides` as `not-answerable/unresolved-extern`,
which is excluded from the coverage denominator and from `DIRTY`. Its comment
is right about the case it was written for — a genuinely unlinkable image — and
wrong about this one: the backend is NOT right to refuse, because `unsafe_ptr`
is a method of a struct that is in the same image and the reason it is unbound
is that a method call was not rewritten. So a real 55-file codegen gap now
sits in the class that says "a fact about the target, not a gap in the
backend", and `codegen coverage` reads 10.2% instead of something lower for
the wrong reason. Worth a second look at whether the marker needs a
narrower form than a substring.

## The exact next step

1. Give the method-rewriting a type for a receiver that is a call result, by
   reading the callee's DECLARED return type when the callee is a function of
   this image (`M.pointer_pointee`'s existing pattern for reading a callee's
   return annotation is the shape to follow) and reducing a type EXPRESSION
   argument to its base name where the base names a struct of this image.
   `CStringSlice[ImmutOrigin[origin_of(self)]]` → `CStringSlice` is the
   reduction, and it is decidable: the base name names a struct whose layout is
   already known to the frame analysis.
2. That needs (1) of the two blockers above first, or at least a refusal
   instead of a bare name: a type argument in ANY bracketed generic position
   must not be read as a value, and a receiver whose type cannot be established
   should be refused with the static-tuple message rather than emitted as a
   dangling symbol.
3. Then re-measure with the same command as the table above. The number to
   watch is `not-answerable/unresolved-extern` (56) and
   `codegen/dependency by family`'s top entry, which should stop being
   `info.mojo`'s MLIR construct and start being whatever the 55 files reach
   next.

## What this worker verified about the construct itself, so the next reader does not re-derive it

`test_formal_external_call.py` (29 cases, all passing) is the test of the closed
half, and it includes the whole of `std/os/env.mojo`'s three functions
transcribed, run and compared against `os.environ` in CPython. Removing the two
imports from `env.mojo` (they pull in `std/sys/info.mojo`, whose module-level
MLIR comptime binding is a separate construct, claimed elsewhere) and writing
`as_c_string_slice().unsafe_ptr()` as the string it evaluates to on this path
builds and runs correctly on **both** arm64 and x86-64 — so the file's own
remaining blocker is a dependency, not its body.
