# FORMAL_a_dict_subscript_has_no_value_kind: `len(d[k])` is refused even with `d` annotated `dict[K, V]`

**Status: OPEN, measured on `master` (2026-10-02) while sweeping slice `repo-c`,
and NOT fixed here — the change it needs is a value-model capability with a
SIGSEGV failure mode, which is not a light worker's call.** Found as the top
row of `bugs/FORMAL_sweep_work_map_2026-10-02_repo-c.md` §4.1 (3 of 15 answerable
files, one construct).

## What I ran

```
$ python3 tools/memslot.py --gb 8 --label repro -- python3 fire.py build --formal --no-prove .tmp/repro/s2.mojo
build: len(d['text']) — the source does not say what this operand holds, and on
this path the two things len() can answer are told apart by what the operand IS:
a string is a bare char * whose length is a strlen over its bytes to the NUL, and
a list or tuple is a frame-allocated blob whose count is its first 8 bytes.
Reading 8 bytes at offset 0 of an unclassified word is a plausible-looking wrong
number — for a char * it is the first eight CHARACTERS of the string — so it is
refused. Annotate it (`x: String`) or bind it to a list, tuple, range or string
literal this path can see the shape of
```

The program is three lines and the annotation is on the FIRST of them:

```mojo
def main():
    d: dict[str, bytearray] = {"text": bytearray()}
    printf("%d\n", len(d["text"]))     # refused
    return 0
```

## What I see, and the part that sizes the work

**It is not about struct fields.** A plain local with a plain annotation fails
identically, so the `declared_kind` hook (which exists precisely for
`len(self.<field>)`, and which is why `ValueKinds.kind_of` consults it) is not
the missing piece — a **dict subscript has no value kind on this path at all**:

```mojo
def main():
    d: dict[str, bytearray] = {"text": bytearray()}
    d["text"].extend(1)          # this WORKS — the store reaches the slot
    x = d["text"]
    printf("%d\n", len(x))        # build: len(x) is len() of a value classified as 'int'
```

So the codegen can already *read and write through* the subscript; only the
CLASSIFICATION is missing, and only `len` (and anything else that asks a kind)
needs it. `formal/hostmods/struct.mojo`'s `pack_into(fmt, buf, off, …)` writes
through a subscript and `unpack_from` reads one, so the corpus already depends on
this working — what it cannot do is ask what the subscript holds.

## Why the same construct is already in the tree three ways

* `formal/model.py::global_slot_is_dict` exists and says a use site has only the
  name, so "is this a key SCAN or an element address" has to come from the slot's
  own initializer. That is a *dict-ness* answer for a NAME, and there is no
  element-TYPE answer behind it.
* `ValueKinds.kind_of` classifies `F.DictExpr` as `LIST_PREFIX` ("this path's
  dict is a pair blob with a count in its first word, which is all `len` needs") —
  which is right for `len(d)` and says nothing about `len(d[k])`.
* `struct_field_kind`'s docstring records the failure mode to design against:
  claiming a kind from the annotation alone **built and then died with SIGSEGV
  (exit 139) on both architectures**, because the slot held 0 and `len` loaded
  eight bytes from address 0.

## The next step, and the gate to design before writing it

One capability, three cooperating pieces:

1. `declared_type_kind` (or a sibling) answering `dict[K, V]` with `V`'s kind
   rather than `None`;
2. `ValueKinds.kind_of` gaining an `F.Subscript` arm that reads the BASE's
   element kind;
3. `BLOB_TYPE_CTORS` carrying `bytearray`, so `V` is a list of ints.

**The gate is the whole of the design and it is not optional.** A dict element
word is written by the SUBSCRIPT STORE, not by the constructor, so exactly
`struct_field_kind`'s hazard applies: `len(d[k])` before any store into `d` reads
a count from a word nothing wrote. Whatever decides this must be able to answer
"has any element been written", the way `struct_field_kind` answers "is the slot's
value something this path materializes". A refusal that fires on a `dict` whose
elements were never stored is correct; one that fires on every `dict[k]` is the
93.3 % → nothing regression in the other direction.

**Do it with both directions of the oracle in the same file.** `len()` of a
container is answered against a byte count, so a wrong answer here is a plausible
number rather than a crash, and `test_formal_run.py`'s build-and-run shape is the
only thing that notices. `formal/model.py`'s existing `ValueKinds` unit tests (if
any) are the cheaper half; they cannot tell a right count from a wrong one.

## The second, smaller row in the same cause, and it may not be the same fix

`unescape_c.py`'s `len(s)` is `len() of a value classified as 'int'` — an
unannotated parameter, which `ValueKinds.__init__` seeds `INT_KIND`, and
`kind_of` DOES already ask `declared_kind` for a name in `_param_names`. So
either that file's `s` has an annotation the analysis is not reading, or its
value flows from a call the analysis cannot follow. **One probe tells those
apart** and the two have nothing to do with each other; do not assume this is
the same fix.

## What was tried and did not work

Nothing — this is a first filing of the shape, from the sweep rather than from a
build that used to work. The closest existing doc is
`bugs/FORMAL_module_global_string_elements_is_a_storage_decision.md`, which is
about the STORAGE of a module global and not about a subscript's kind; it is
cited there only because both questions end at "this path has no answer for
this container shape".
