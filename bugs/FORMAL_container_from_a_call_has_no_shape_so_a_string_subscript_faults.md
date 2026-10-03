# FORMAL_container_from_a_call_has_no_shape_so_a_string_subscript_faults

**Found 2026-10-02 (the `sweep6:module-state` round), while re-measuring
`FORMAL_module_state_no_storage.md`'s §(1) row. Not fixed here: it is not a
module-state defect and it is not fixable in one spelling.** A dict that arrives
from a CALL has no shape on this path, so `d["a"]` is emitted as a SEQUENCE
subscript — a load from a nonsense address — and the image exits 1 from a build
that was green. It is the same fault the module-global spelling had until
`formal/model.py`'s `_body_store_shape` taught a slot to read its callee's
annotation; every OTHER spelling of the same expression still has it.

## Measured, both architectures, on this tree

`exit 1`, no output, `fire.py build --formal --no-prove` green on both:

    # r1.mojo — a LOCAL bound from a call
    def mk():
        var d: Dict[String, Int] = {"a": 1}
        return d

    def show() -> Int:
        d = mk()
        printf("%d|", d["a"])
        return 0

    show()

    # r2.mojo — an UNANNOTATED PARAMETER, same program
    def show(d) -> Int:
        printf("%d|", d["a"])
        return 0

CPython answers `1` for both (with `print`, or with `printf` under a `mojo`
interpreter that resolves it — the formal `printf` is not in the Mojo
interpreter's namespace, which is why every case here uses `printf` and states
the expected value rather than asking the interpreter).

The three spellings that are now RIGHT, and why the contrast is the argument:

| spelling | status | mechanism |
|---|---|---|
| `D = {"a": 1}` at module level, read by a function | works | the initializer's shape is in the slot (`init[0] == "blob"`, `init[1] == "dict"`) |
| `D = mk()` at module level, `def mk() -> Dict[String, Int]` | **fixed 2026-10-02** | `GlobalSlot.is_dict`, from the callee's declared return type |
| `d = mk()` local / `def show(d)` parameter | **exits 1** | nothing states the shape |

So the round's fix removed one of four spellings of one expression, and the
three that remain are not module state: a local and a parameter have no slot at
all.

## Why the fault and not a refusal, and what a refusal would have to be careful
about

`_emit_subscript_addr` (`formal/arm64_codegen.py:3725`, with
`x86_64_codegen.py`'s twin) is the single choke point and it asks, in order: is
this a dict lookup, is the base a `char *`, is the base a pointer, else the blob
walk. "Is this a dict lookup" is `_is_dict_subscript`, which for a name answers
from `_dict_vars` — a per-function, flow-sensitive map that
`_note_binding` fills from the binding's RIGHT-HAND SIDE
(`M.is_dict_expr`) and `_note_global_kinds` fills from a module slot. A call
result is neither, so the answer is False, and the blob walk takes the key's
interned ADDRESS as an element offset:

    arm64   exit=1 out=''     x86_64  exit=1 out=''
    # the identical program with `d` bound to the dict LITERAL prints 1.

The failure is loud in the one sense that matters (a non-zero exit, so a
`expect=` marker or a sweep's `ok` cannot read it as a pass) and silent in the
sense that costs the most: no diagnostic names the shape, and a program that
prints before the subscript exits 0 with the wrong output on stdout.

**The refusal cannot simply be "a string index needs a dict base".** A string
index against a `char *` is a byte subscript and that is legal (`s[0]`), and
`M.string_index_refusal` already owns that distinction. The case to refuse is
narrower: the base's shape is UNSTATED and the index is a string. That is
exactly the pair (dict key scan, string byte subscript) that the source does not
choose between, and neither member of it is a plausible default — one is a scan
and the other is `base + i`.

## The exact next step

**One hook, asked once, in `model.py`, from both backends** — the same shape as
every other shared refusal there. The evidence already exists in each backend and
is already collected:

* `arm64_codegen._callee_kind` / its x86-64 twin resolve a call to a function of
  this unit from the callee's DECLARED return type and, failing that, from
  `ValueKinds(fn).return_kind` — which is built from the callee's RETURN
  STATEMENTS. `def mk(): … return d` therefore has an answer the model does not
  consult: `return_kind` says a blob.
* What is missing is the DICT-vs-SEQUENCE half of that answer, and the same
  reason `GlobalSlot.is_dict` had to be a field rather than a kind: on this path
  `List[Int]`, `Tuple[Int, Int]`, `Set[Int]` and `Dict[String, Int]` are one word
  and `declared_type_kind` answers all four with the bare list prefix. `ValueKinds`
  has the same blindness — `kind_of(DictExpr)` returns the bare prefix — so
  `return_kind` cannot say "dict" either, and a new evidence source is needed
  rather than a new reading of an existing one.

The shape of the fix, in the order it should be written:

1. **`ValueKinds` learns the dict-ness it already has evidence for.** The scan
   already visits every `return` statement to collect `_returns`; the returned
   NODE is right there and `M.is_dict_expr` already answers "is this a dict
   literal or a dict comprehension". Unanimity, like everywhere else in that
   class: two definitions of one name whose returns disagree claim nothing.
2. **`_dict_vars` gains a branch in `_note_binding` for a call result**, using
   (1) — so `d = mk()` marks `d`, and the subscript takes the dict path.
3. **A refusal for the residue**, so the unanswerable case stops being a fault: a
   base of unstated shape with a STRING index. Wording belongs in `model.py`
   beside `string_index_refusal`, because it is the same question asked of the
   other end of the subscript and two copies of a diagnostic is how a reader ends
   up learning three spellings of one message.

Steps 1 and 2 make a correct program correct and change no existing answer —
`_note_binding`'s branches are mutually exclusive and a call result currently
falls through to the clearing `else`, so the only programs that move are the ones
that fault today. Step 3 is the one that needs care, because a string index
against a base that IS classified still has to keep working.

Tests to write with it, all three engines (`fire.py run`, arm64, x86-64), in
`test_formal_value_model.py` next to the existing kind rows:

* `d = mk()` with an annotated callee, `print(d["a"])` → `1` (today: exit 1);
* the same with an UNANNOTATED callee whose returns state a dict literal — the
  step-1 evidence, and the row that says the fix is not annotation-only;
* a REFUSAL row for the residue: a base of unstated shape with a string index,
  asserting the build fails on BOTH backends with the message, because the whole
  point of step 3 is that a fault cannot be reported as a pass.

**Not a `frozenset` bug and not a module-state bug**, and worth saying because
the sweep files both under the same row: `TYPES = frozenset({...})` at module
level stores fine now and is refused at the LINK audit ("the image would bind 1
symbol(s) that nothing provides: frozenset") because `frozenset` is not lowered
at all — a missing builtin, and a strictly better diagnostic than the storage
refusal it replaced. `REPO = os.path.dirname(HERE)` and a module-level
`ELF_MAGIC = b"\x7fELF"` both lower and print correctly on both architectures as
of this round; see `FORMAL_module_state_no_storage.md` §(1).