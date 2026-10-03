# FORMAL_stlib_core_stringref_is_a_name_this_unit_cannot_resolve: the
# `StringRef` construction in `stdlib_core.mojo` — measured, and the
# `codegen` class it is filed under is defensible

**Status: MEASURED, not fixed, and deliberately not fixed here. Replaces the
version of this doc whose premise was wrong.** Found while measuring row 5 of
the work map ("value with no representation on this path", 15 files) for the
`construct:receiver-position-and-no-representation` claim on 2026-10-01; it is
the **1 file of 15** that group contains. The previous version of this doc said
the question was "what does an UNRESOLVED TYPE ANNOTATION mean on this path".
**That premise is false, and measured below** — an unresolved annotation lowers
in every position. Acting on it would have built the wrong thing, which is what
the original brief for that claim warned about.

## 1. What the previous version of this doc got wrong

It claimed:

> **Why it is not a value-model change.** […] So the file is a
> **name-resolution** question — is a signature annotated with a type the image
> cannot resolve a refusal, a host-import, or a not-answerable? — and not the
> "which value kinds have no representation" question the row's name suggests.

Measured, x86-64 and arm64, every position an annotation can appear in, with
`StringRef` (a name this image has no declaration of) as the annotated type:

```
def f(s: StringRef) -> Int:  return 1                      Built
def f() -> StringRef:        return "x"                    Built
def f() -> Int:  var s: StringRef = 5   return s           Built
struct S:  var f: StringRef;  def g(self) -> Int: return 1  Built
def f() -> List[Span]:  return []                           Built
def f(s: Span, d: DType) -> Int:  return 1                  Built
def f() -> Error:  return 1                                Built
```

Every one builds. So an unresolved annotation is **already inert on this
path**, and there is no name-resolution question to decide. The refusal this
file gets is about a **CONSTRUCTION**, and the construction is a different
thing with a different and already-correct answer.

## 2. What the file actually does, isolated

The whole 24-line file, with the one construction replaced by a literal:

```mojo
struct FileHandle:  pass
def print(s: StringRef):  pass
def open(path: StringRef) -> FileHandle:  return FileHandle()
def read_file(handle: FileHandle) -> StringRef:  return 0        # was StringRef("")
def format_string(prefix: StringRef, value: StringRef) -> StringRef:
    return prefix + value
def main() -> Int:  return 0
```

**Builds.** So `StringRef` as a parameter type, a return type, a local
annotation, and the receiver of `+` (`prefix + value` — two `StringRef`s
concatenated) are all fine; the single construct that refuses is
`StringRef("")`, and:

```
$ python3 fire.py build --formal --no-prove stdlib_core.mojo
build: constructing StringRef has no representation on this path: this image
has no declaration of StringRef to construct — it is not a struct in this
module or in anything it imports, so there is no field list to bring up, and a
formal value is one 64-bit word. […]
```

That message is **accurate and the refusal is right**. A `StringRef` is a
pointer-and-length pair (LLVM's `StringRef`), so it is two words; a formal
value is one, and there is no declaration here that says otherwise. The
backend's own docstring for `type_constructor_prefers_local_struct` states the
correct rule — a struct declared in THIS UNIT beats the name list — and there
is no declaration here to beat it with. The previous version of this doc
agreed with that and then drew the opposite conclusion from it.

## 3. Why fixing it here is worth 0 files, and the ceiling is not reachable

`StringRef` **is not a type in the stdlib this sweep builds against.** Measured
on `../new-modular/Mojo/stdlib/std` (252 files):

| | |
|---|---|
| `struct StringRef` declarations | **0** |
| `StringRef(` construction sites | **0** |
| `StringRef` mentions at all | 2, both inside `#` comments in `string_span.mojo:131` and `sys/arg.mojo:50` |

So `stdlib_core.mojo` is written against an API that does not exist in the
tree: every one of its signatures is annotated with a type nothing declares,
and `read_file`'s body constructs one. It is a 24-line stub ("Stub for now —
would need C interop", `pass`, `pass`) whose own comments say it is
provisional. Nothing imports it — `grep -rn stdlib_core` over the tree finds no
importer outside `bugs/`.

Which means there is nothing to represent: making the file build would mean
inventing a two-word value on a path where a value is one word, for a file
nobody calls. **Ceiling: 0 PASSes**, and it is not reachable by any change to
`formal/`.

## 4. Is the `codegen` class right?

The previous version proposed reclassifying it to `not-answerable`, on the
ground that "the file's types do not exist in the stdlib this sweep builds
against, so there is nothing to represent." **That reasoning supports KEEPING
it in `codegen`, not moving it out**, and the doc said so itself in §3 of its
own "exact next step" while concluding the opposite.

The sweep's class vocabulary (`tools/formal_sweep.py`'s module docstring) puts
`codegen` at "the backend REFUSED a construct in THIS FILE — THE FINDING, the
only class whose count is a gap in the backend". The backend did refuse a
construct in this file, and it refused it for a reason that is true. Moving
the file to a `not-answerable` class would move it out of the coverage
denominator **without making it answerable** — which
`test_formal_frame_len.py` and the sweep's two measurements both name as the drift
direction this sweep's accounting is arranged to resist. Leave it in `codegen`.

## Re-verified 2026-10-01 (`work/formal3-7`): every claim here still holds

Nothing in this doc is fixed and nothing should be — §3's ceiling of 0 PASSes is
a fact about a dead stub, not about the backend. Re-measured rather than assumed,
because a doc that stops being true is worse than no doc:

* **The refusal is still the one this doc quotes**, verbatim and unchanged:
  `constructing StringRef has no representation on this path: this image has no
  declaration of StringRef to construct […]`.
* **`StringRef` still has 0 declarations and 0 construction sites** in the stdlib
  this sweep builds against (252 files under
  `../new-modular/Mojo/stdlib/std`), and its only two mentions are still the two
  inside `#` comments — `sys/arg.mojo:50` and
  `collections/string/string_span.mojo:131`. So the "ceiling: 0 PASSes, not
  reachable by any change to `formal/`" conclusion stands.
* **Nothing imports it.** `stdlib_core.mojo` is 24 lines at the repository root
  with two `pass` bodies and a comment saying it needs C interop, and
  `grep -rn stdlib_core` over the tree finds no importer outside `bugs/`.
* **The sweep-roots question in §5 is still `tools/formal_sweep.py`'s owner's.**
  `default_roots` is `[REPO]` plus the stdlib subtrees and nothing names
  `stdlib_core.mojo` anywhere in the sweep, so the file is swept by
  construction and not by a decision anybody made about it.

So §5's two questions are still the two questions, and neither is a backend
change. This is the honest state: a doc whose subject is a file that should not
exist, recording that the backend is right to refuse it.

## 5. The exact next step

Not a backend change. Two questions, and neither is this file's:

1. **Does `stdlib_core.mojo` belong in the sweep at all?** It is a
   repository-root stub that nothing imports, written against an API the
   current stdlib does not have. `tools/formal_sweep.py`'s `default_roots`
   sweeps `REPO` wholesale, so it is swept as a matter of course; whether a
   hand-written bootstrap stub counts as a compilation target is a question
   about the sweep's ROOTS, which is `tools/formal_sweep.py`'s owner's. **It is
   1 file of 623 and the class is defensible either way**, so this is worth one
   line in a sweep-roots decision and not a backend change.
2. **If the file stays: delete it or rewrite it against the real API.** It is
   dead code with a `pass` body and a comment saying it needs C interop. Either
   is a change to the repository, not to the compiler.

**Nothing here blocks another file.** `StringRef` has 0 construction sites in
the stdlib, so no other file can reach this refusal through it. The only way
any file hits `UNREPRESENTABLE_TYPE_CTORS` is by constructing a name with no
declaration, and for the nine names that table lists the real stdlib has
construction sites (`Span` 69, `Error` 151, `DType` 33, `Optional` 22, `SIMD`
6, `List` 9, `Tuple` 7) — those are the files that matter, and each is
refused on its own account, not through this one.

## 6. Reproducing

```
python3 tools/memslot.py --gb 8 --label sc -- \
    python3 fire.py build --formal --no-prove stdlib_core.mojo -o .tmp/sc.arm64
python3 tools/memslot.py --gb 8 --label sc -- \
    python3 fire.py build --formal --no-prove .tmp/sc_noref.mojo -o .tmp/sc.arm64
cd ../new-modular/Mojo/stdlib/std && \
    grep -rn '\bStringRef\b' --include=*.mojo . ; \
    grep -rn 'StringRef(' --include=*.mojo . | wc -l
```