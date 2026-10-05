# FORMAL_an_explicit_parameter_list_naming_a_comptime_value: a generic applied as `T[Type, comptime]` is refused, and two of the messages are wrong about the source

**Area:** FORMAL (`formal/monomorph.py`'s demand walk, and the two refusal
messages a caller reaches when it does not fire). **Status:** OPEN, filed
2026-10-05 on `work/formal27-5` at `7ac78995`, with every claim below measured
on that tree. **Not a light worker's to close** and not this branch's claim: the
monomorphisation area belongs to `bugs/FORMAL_generic_monomorph_scope.md` and
`FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`, and
closing the wall needs the demand walk to bind a NON-TYPE parameter.

**Why it is filed rather than mentioned:** two of the sweep-scope docs asked for
exactly this and could not do it themselves, because the shape is in neither of
their scopes. `bugs/FORMAL_std_os_io_round2_scope_is_one_refusal_shape.md` §3
link 2: *"Link 2 has NO bug doc and no claim … It is filed nowhere of its own,
and 4 files of this scope sit behind it, so it is worth a doc rather than a
mention."* `bugs/FORMAL_std_builtin_sys_time_slice_2026-10-04.md` §3 row 12
records it as `sys/arg.mojo`'s terminal cause and calls it *"the same
monomorphisation wall as 11, from the other side"* without saying which side.

## 1. The construct, and the standing instance

`../new-modular/Mojo/stdlib/std/sys/arg.mojo:51`:

```mojo
var result = Span[StaticString, ImmStaticOrigin]()
```

`Span` takes a **type** parameter and a **comptime value** parameter, and the
call spells both. The refusal, measured on both architectures and
**byte-identical** (one `fire.py build --formal --no-prove` per arm):

```
build: Span[StaticString, ImmStaticOrigin] is a compile-time explicit-parameter
list on a generic, not a subscript: the brackets name types and comptime values,
none of which is a runtime word. This path has no type or comptime parameter to
bind, so what the call means depends entirely on which parameters were passed.
Refused rather than read as an index — a binding for `size_of[type, target]`
would have to come from a target description this backend does not have, and a
plausible constant is a fabricated answer.
```

**Every clause of that is TRUE, and it is worth saying so plainly: this is an
honest refusal, not a wrong answer.** The "fabricated answer" it refuses to
invent is the real hazard — a comptime value parameter is substituted at compile
time by the language, so binding `origin` to a plausible constant would produce
a program that computes something and means nothing.

## 2. What is actually missing, measured rather than restated

The refusal says "no type or comptime parameter to bind", and the useful
question is **which half** of the two the path is missing. Five synthetic cases
on this tree, each two files in one directory (`mylib` declares `struct Box[T]`
and `def unbox(t: Box[T]) -> T`; `tagged` declares
`struct Tagged[T, origin: Int]` and `def untag(t: Tagged[T, origin]) -> T`),
built with `fire.py build --formal --no-prove` and RUN where they build:

| # | the call | verdict on this tree |
|---|---|---|
| 1 | `Box[Int]()` — one **type** argument, explicit, on a constructor | **builds and runs** (exit 10 = the startup stub's integer) |
| 2 | `unbox(b)` — the same instantiation, **inferred** | **builds and runs** |
| 3 | `unbox[Int](b)` — an explicit type argument on a plain generic **function** | **refused**, and see §3: the repair it names is the spelling the source already uses |
| 4 | `Tagged[Int, 0]()` — a **type and a comptime value**, on a constructor | **refused**: the explicit-parameter-list message above |
| 5 | `mylib.Box[Int]()` — case 1 spelled **dotted** | **refused as a call to `mylib`**, and see §3: the source never calls `mylib` |

**So the TYPE half is not missing and the comptime half is the whole of it.**
Row 1 is `formal/monomorph.py`'s demand walk working: an explicit type argument
on a constructor produces the instantiation and the mangled boundary symbol.
Row 4 differs from row 1 by exactly one thing — the second element of the
bracket is `0`, a **value**, and there is no parameter of a kind this path can
substitute. `formal/monomorph.py::type_arg_text` answers `""` for an argument
that is not a type, by design, and the mangler then has nothing to mangle from.

**That is why the two docs' "the same monomorphisation wall" was the right
instinct and the wrong shape**: it is not the bare-call inference row
(`FORMAL_a_bare_call_to_a_template_…`, where the brackets are ABSENT) and it is
not `FORMAL_generic_monomorph_scope.md` §1 (a type argument in a **non-call**
position — an annotation, a field, a return type). It is a bracket that IS
written, whose second element is not a type. Neither existing doc lists it;
§8 of the monomorph doc's "what is not here, deliberately" does not mention it,
which is where `FORMAL_std_os_io_round2_…` §3 looked for it.

## 3. Two messages in this neighbourhood are wrong about the source

Both are in the family `formal/model.py::imported_callee_refusal` writes, both
are reachable from a program whose source is correct Mojo, and both are the
defect this repository calls `refuse_without:` — a next step that is wrong about
the code being compiled. **They are recorded here rather than fixed, because the
monomorphisation area is another claim's.**

**Row 3's message recommends the spelling the program already uses.** For
`unbox[Int](b)`:

> `unbox[…](…)` calls a name this unit does not compile, so the brackets cannot
> be bound. … so a call arriving here asked for none: its brackets named no type
> argument, named a value rather than a type, or spelled the template as
> `module.unbox`. **Write it as `unbox[<a type>](…)`** and the library will carry
> the instantiation

The program is written `unbox[Int](b)`. So the three alternatives are all
exhausted and the advice is the source, which means the sentence is a dead end
twice over: it cannot be true that "its brackets named no type argument" of a
call whose bracket is `[Int]`. The real answer is measurable from rows 1 and 2 —
**a type argument is a demand when the callee is a CONSTRUCTOR and is inferred
rather than read when the callee is a plain function** — and it is one clause,
not three alternatives.

**Row 5's message blames the module's export table for a call the program does
not contain.** For `import mylib; mylib.Box[Int]()`:

> `mylib` is called, and it is imported from `mylib`, so the call has to bind a
> symbol `mylib` exports. That module does not export it …

`mylib` is a MODULE, it is not called, and the program never mentions it as a
callee. The same shape spelled with a from-import (row 1) builds, so the dotted
application is a **parser/lowering** difference rather than a demand difference,
and the message should say the brackets could not be attached to the member
rather than that the module was called. This is also the shape
`FORMAL_generic_monomorph_scope.md` §2 is titled after ("A DOTTED application —
`mod.Pair[Int]()`"), which is worth re-checking against row 5 before §2 is
relied on for a dotted call.

## 4. The next step, and what it costs

1. **The comptime-value parameter**, which is the wall: `formal/monomorph.py`'s
   demand walk has to read a bracket whose second element is a comptime
   ARGUMENT, and `instantiate` has to substitute it into the body's
   `origin`-typed positions. That is a value substitution, not a text
   substitution, and the mangler needs the argument's **text** — which is why
   `type_arg_text` returning `""` for a non-type is right and insufficient
   rather than a bug to widen.
2. **The two messages**, which are independent of (1) and can be landed first:
   row 3's advice is a clause that can be written from the measurement in §2,
   and row 5 needs the dotted application to say what it is. Both are the
   `refuse_without:` class and neither needs the value model.
3. **What NOT to do:** bind the comptime value to a plausible constant, or read
   a two-element bracket as a flat index. The first is a wrong answer, the
   second is the refusal the existing message already declines to make, and
   §1's `size_of[type, target]` sentence is the measured reason why.

## 5. Reproducing

Five one-file-per-case builds, no Lean, no sweep, under `tools/memslot.py`:

```sh
export PATH=/opt/homebrew/bin:$PATH
S=../new-modular/Mojo/stdlib/std
for a in arm64 x86_64; do
  python3 tools/memslot.py --gb 8 --label ep -- \
    python3 fire.py build --formal --no-prove --backend=$a -o .tmp/arg.$a \
    $S/sys/arg.mojo                       # the standing instance, §1
done

mkdir -p .tmp/ep
# the library halves, then one program per row of §2
printf 'struct Box[T]:\n    var v: T\n\n\ndef unbox(t: Box[T]) -> T:\n    return t.v\n' > .tmp/ep/mylib.mojo
printf 'struct Tagged[T, origin: Int]:\n    var v: T\n\n\ndef untag(t: Tagged[T, origin]) -> T:\n    return t.v\n' > .tmp/ep/tagged.mojo
# …and the five programs are in .tmp/ep/p_{ok,from,from_ct,ctonly,ct}.mojo
```

`tools/formal_sweep_causes.py` files this construct under `other refusal` or
under the export row depending on which message fires, which is a fourth fact
about it: **one construct, two rows in the ranking instrument, and neither row
is about the construct.** The `sys/arg.mojo` instance is 1 of the 60 dependency
refusals in `FORMAL_std_builtin_sys_time_slice_2026-10-03.md` §4 and 4 files
behind it in `FORMAL_std_os_io_round2_…` §3, so the sweep's own numbers put it
at 5 files and the round-2 doc's probe put it at 4; both are lower bounds,
because a file whose own construct refuses first is not in either count.
