# HARD BUG: two different real classes sharing a bare name across modules corrupt each other

**State: OPEN, and NOW REACHABLE (2026-09-27).** NOT fixed. The 4-step plan
below (module-qualified field-table keys / value-identity propagation /
per-owner tables in Phase 2a / typedef-name qualification) is still the
right fix and is still unattempted — it remains foundational, shared
struct-identity machinery rated moderate-to-high risk by this doc's own
Risk section.

**The blocker this doc's own §4 named ("module.Class(...) construction is
unresolved on every path") is FIXED 2026-09-27** — see
`bugs/PARTIAL_WORK_HANDOFF.md` §2.4 and `mojo/backend_gimple/
emit_methods.py`'s new qualified-constructor check in `_lower_method_call`.
Re-tested with the doc's own §3 collision repro (`mod_a.Dialog(n)` +
`mod_b.Dialog()`, both constructed from `main.py` via `import mod_a` /
`import mod_b`) now that construction actually works: it no longer reaches
§3's silent field-coercion residue at all — it hits a NEW, LOUDER symptom
first. `mod_b.Dialog()` (0 args) resolves to `mod_a`'s winning
`__init__` (1 arg), a hard `gcc -fgimple` **compile** error ("too few
arguments to function 'mod_a_Dialog___init__'; expected 2, have 1") rather
than a runtime miscompile — `_lower_struct_constructor` resolves the bare
name "Dialog" to whichever struct won `_struct_name_owner`'s race,
independent of which MODULE the call was qualified through. This is a
new, sharper reachability finding, not yet the underlying fix: the 4-step
plan below is unaffected by it and remains the right shape, but the FIRST
observable symptom for a real two-arg-mismatched collision is now this
compile error, not §3's silent value.

**A same-ARITY collision reaches §3's silent coercion as a LIVE, running
program** — confirmed this session, first real end-to-end reproduction:

    # mod_a.py                      # mod_b.py
    class Dialog:                   class Dialog:
        def __init__(self, n):          def __init__(self, unused):
            self.n = n                      self.n = "hello"
    # main.py
    import mod_a, mod_b
    def main():
        a = mod_a.Dialog(5)
        b = mod_b.Dialog(0)
        print(a.n); print(b.n)

CPython: `5` / `hello`. Compiled (`do_imports=True`, builds and runs clean,
exit 0): `5` / `0` — `b.n` silently reads through `mod_a`'s winning field
table (an `int64_t` slot `mod_b_Dialog___init__` never actually writes a
string into), exactly the "loser's access resolves against the winner's
field table" mechanism §3 predicted, now genuinely live rather than
theoretical. This is the shape the 4-step plan below should be fixed
against and verified with.

**Re-derived 2026-09-26.** The mechanism is unchanged and the plan below still
stands, but **three of this doc's load-bearing claims are now false** and are
corrected in place below: the documented C error no longer occurs; the
`mod_a.Dialog(...)` / `ADialog(...)` call sites no longer reach the collision
at all (a *different, larger* bug intercepts them first — see "Why it is
unreachable end-to-end"); and the one genuinely **silent** residue is now
identified and reproduced at the artifact level, which is a sharper target than
anything the earlier entries describe.


## Re-derived 2026-09-26: mechanism intact, documented symptom STALE, silent residue isolated, and a bigger bug found in front of it

Method: re-derived the root cause from the current source rather than trusting
any entry below, then reproduced each shape on the current tree (HEAD `b463d61`).
Everything here is a fresh measurement; the entries further down are kept as
history and are explicitly superseded where they disagree.

### 1. The mechanism is unchanged, and still where this doc says it is

`mojo/backend_gimple/module_gen.py:2422-2425` is the first-wins bare-name
registration, verbatim as documented:

```python
for s in all_struct_defs:
    s = _as_structdef_node(s)
    if isinstance(s, StructDef) and s.name not in self._struct_name_owner:
        self._struct_name_owner[s.name] = s
```

and `:2434` is the loser's skip: `if self._struct_name_owner.get(s.name) is not
s: continue`. `_struct_by_name` at `:2817` filters to the owner too, so the
loser's own field scan is dropped as well. Phase 2a still compiles **every**
StructDef's methods. All of that is as documented.

### 2. The documented C error is GONE. Field access in a loser's methods now degrades dynamically

Every entry below (2026-08-08, 2026-08-20, 2026-08-23, 2026-08-26) claims
`mod_b_Dialog___init__` emits `self->result = ...` against mod_a's `Dialog`,
producing `mod_b.py:3:7: error: 'Dialog' has no member named 'result'`. **That
no longer happens.** `/tmp/b2d` (the doc's own repro: `mod_a.Dialog{widgetName}`,
`mod_b.Dialog{result}`, both constructed from `main.py`), `--dump-full` on the
current tree:

```c
typedef struct Dialog {          /* ONE winner, mod_a's field set */
  int64_t __mojo_type_id;
  int64_t widgetName;
} Dialog;

void __GIMPLE mod_b_Dialog___init__ (Dialog * self, int64_t result)
{
  ...
  _mojo_dispatch_setattr (_t6, _t1, _t2);   /* NOT self->result = ... */
}
int64_t __GIMPLE mod_b_Dialog_show (Dialog * self)
{
  ...
  _t2 = _mojo_dispatch_getattr (_t1, _t3);  /* NOT self->result */
}
```

The loser's field names are simply **not in the winner's table**, so the
read/write lowering takes the dynamic getattr/setattr branch it already had for
unknown members. Net effect: the C-level corruption became a **runtime
`AttributeError: widgetName`, exit 1** — loud and catchable, not silent and not
a compile refusal. That is a real improvement over what this doc recorded, and
it means "fix the C error" is no longer a describable goal.

### 3. The one genuinely SILENT residue: a field name both structs share

The dynamic fallback only covers names the two structs do *not* share. When they
do share a name, the loser's access resolves against the **winner's** field
table — including the winner's ctype — and the value is coerced into it. That is
the doc's own "or, worse, silently reads/writes the wrong offset" prediction,
and it is real. `/tmp/b2j`:

```python
# mod_a.py                          # mod_b.py
class Dialog:                      class Dialog:
    def __init__(self, n):             def __init__(self):
        self.n = n                        self.n = "hello"
```

`--dump-full main.py` (`import mod_a` + `import mod_b` + one construction from
`mod_a`), generated C:

```c
typedef struct Dialog { int64_t __mojo_type_id; int64_t n; } Dialog;  /* mod_a won */
void __GIMPLE mod_b_Dialog___init__ (Dialog * self)
{
  char * _t1;  int64_t _t2;  void * _t3;  int64_t _t4;
  _t1 = _slit_10000;                          /* "hello" */
  _t3 = (void *)_t1;
  _t4 = (int64_t)_t3;                         /* the STRING's pointer bits */
  _t2 = _t4;
  self->n = _t2;                              /* into mod_a's int64_t field */
}
```

`mod_b.Dialog.n` is a `str`; the compiled artifact stores a raw pointer in an
`int64_t` slot. Any consumer that reads it as an integer gets a **heap address
— a different value on every run (ASLR), exit 0, no diagnostic**. Nothing in
the generated C is wrong enough for gcc to notice. This is the shape to fix,
and it is strictly narrower than the general plan below: it needs the loser's
own field to have its own slot, nothing more.

### 4. Why it is unreachable end-to-end — and the bigger bug in front of it

No runnable repro of this bug exists on ANY path today, and the reason is not
the one this doc gives. It is **not** that link mode keeps each module in its
own translation unit (true, and still the reason the stdlib corpus never sees
it). It is that a class reached through its module never gets constructed at
all, collision or not. `/tmp/b2e` — a SINGLE module, no second `Dialog`
anywhere:

```python
# mod_a.py
class Dialog:
    def __init__(self, widgetName):
        self.widgetName = widgetName
# main.py
import mod_a
def main():
    var x = mod_a.Dialog("a")
    print(x.widgetName)
```

emits `_t7 = _t2;  /* int64_t.Dialog() stubbed */`. The `from mod_a import
Dialog as ADialog` spelling is worse — `/tmp/b2f` compiles
`ADialog("a")` to the *string literal* `"a"`, and `x.widgetName` then reads a
string's bytes as an object. Confirmed on the **link-mode** path too:
`driver.compile_linked` on the same `main.py` returns `dylibs: []` and the same
`int64_t.Dialog() stubbed`.

So `module.Class(...)` construction through a module object is unresolved
independent of this bug, on both paths. That is a strictly larger and more
valuable bug, it is what currently makes this one unobservable at runtime, and
**fixing it is what would force this one to be fixed** — the moment a real
program can build a `mod_b.Dialog`, section 3's silent miscompile becomes a
live silent miscompile. Sequence them in that order.

### 5. Reachability of the inline path, re-checked

- The compiler's own `--dump-full` closure — the one whole-program inline
  compile the bootstrap actually performs — was walked for duplicate bare class
  names: 49 files, exactly one duplicate, `StringLiteral`, and **both
  definitions are in `fire_compiler.py` itself** (`class StringLiteral` at
  lines 233 and 252, byte-identical bodies). No cross-module duplicate, so the
  bootstrap is not a live instance. Note the consequence for any fix: the
  in-tree duplicate means `_struct_name_owner` really does drop a definition
  that the gate exercises, so a blanket "refuse when a struct loses the name
  race" would fire inside the bootstrap. It happens to be harmless there only
  because a `@dataclass` with no method bodies has no `self.<field>` access to
  refuse — that is luck, not a property, and any fix must key on the *field
  access*, not on the name loss.
- The two real-world triggers this doc names are both dead for unrelated
  reasons now: `Lib/typing.py` no longer builds at all (it fails in
  `_collections_abc` / `re._compiler` / `enum` / `dis` / `dataclasses` /
  `argparse` on `cannot coerce MojoList * to MojoSet *`-shaped errors, and then
  in typing.py itself on `cannot coerce MojoDict * to MojoList *` at
  `globalns`), so its `_CallableGenericAlias` collision cannot be observed
  either way.

### Verdict

NOT FIXED, no code change, and the reason is sharper than "moderate-to-high
risk": **there is no program that can exhibit it**, so any fix would be landed
unvalidated. The two candidate narrow fixes and why neither is landable today:

- *Refuse the loser's `self.<field>` outright* (turning the silent
  type-punned write into a compile error). Provably scoped — it can only fire
  inside a genuine bare-name loser's own method bodies — but it converts a
  miscompile into a **refusal**, and this repo classes "a compile refusal on a
  shape real stdlib code actually uses" as a hard bug in its own right. With
  section 5's `fire_compiler.py` duplicate showing the loser's path is
  genuinely exercised, "no real file hits it" is not demonstrable here.
- *Route the loser's shared-name field access to the dynamic getattr/setattr
  path its own body already uses for its non-shared names.* This is strictly
  better than refusing (it makes the loser self-consistent instead of merely
  loud) and cannot introduce a new failure mode, since it only reuses a path
  the same function already emits. But it is still **unvalidatable**: with
  section 4 in force there is no program whose behaviour could be shown to
  change, so "did I break anything" has no experiment attached to it.

Once section 4's bug is fixed and a runnable repro exists, the second of those
is the first thing to try, and the general 4-step plan below is the fallback for
the case where the loser's fields turn out to need genuinely separate slots
rather than a side dict.

## Re-verified 2026-08-26 (branch fix/rest-remainder15): minimal repro still corrupts identically; general plan remains DOCUMENTED-NOT-FIXED, deliberately not attempted

> **SUPERSEDED by the 2026-09-26 entry above.** Its central claim — that
> `mod_b_Dialog___init__` emits `self->result = ...` and gcc rejects it with
> `'Dialog' has no member named 'result'` — no longer reproduces. Kept as
> history; do not re-derive from it.

Re-ran the exact minimal 2-file repro (`mod_a.Dialog{widgetName}` /
`mod_b.Dialog{result}`, both constructed from a `main.py`) fresh against
current tree (`a913ab8`) via
`gimple_codegen.compile_to_gimple_cached(do_imports=True)` + a real
`gcc-mp-15 -fgimple -x c` compile: byte-for-byte the same failure as the
2026-08-23 entry below — one `typedef struct Dialog { int64_t
widgetName; } Dialog;` wins the bare-name race, and `mod_b_Dialog___init__`
still emits `self->result = ...` against it: `mod_b.py:3:7: error:
'Dialog' has no member named 'result'`. Per this task's explicit
guidance (rated moderate-to-high risk historically; only proceed if
something genuinely narrow turns up), read the doc's own 4-step "what a
real fix needs" plan again end-to-end: step 2 (propagating a value's
resolved qualified-type identity through every later field-access site
derived from it) remains a genuinely broad dataflow problem across
`_actual_types`/construction-site tracking/`_imported_struct_home`, not
a local, contained change — nothing about this session's shared fixes
(map()/getattr gaps, dict-subscript, generator-consumption ordering,
etc.) touches struct field-table/type-identity registration at all.
Confirmed nothing narrow presented itself. DOCUMENTED-NOT-FIXED, not
attempted, per instructions. No code change.

## Re-verified 2026-08-23 (triage pass): minimal repro still corrupts at the TYPE-IDENTITY layer; general plan remains DOCUMENTED-NOT-FIXED

Re-ran the minimal 3-file repro (mod_a.py and mod_b.py each defining
an unrelated `class Dialog` — fields `widgetName` vs `result` — with a
root main.py importing both under aliases and constructing both)
directly against the vulnerable entry point
(`gimple_codegen.compile_to_gimple_cached(src, do_imports=True)`),
then compiled the generated .ci with the project's real `-fgimple`
GCC:

- The 2026-08-20 method-symbol fix is holding: the two classes'
  methods now emit/declare as `mod_a_Dialog___init__`/`mod_a_Dialog_show`
  vs `mod_b_Dialog___init__`/`mod_b_Dialog_show` (no C symbol collision).
- But the STRUCT TYPEDEF itself is still one bare-name winner: a single
  `typedef struct Dialog { int64_t widgetName; } Dialog;`, and mod_b's
  `___init__` body still emits `self->result = ...` against it —
  confirmed live via `gcc-mp-15 -fgimple -x c -c`: exactly
  `mod_b.py:3:7: error: 'Dialog' has no member named 'result'`.

So the corruption this doc describes has moved fully into the
field-table/type-identity layer, precisely as the general 4-step plan
below anticipates. That plan (module-qualified field-table keys,
value-identity propagation to field-access sites, per-owner tables in
Phase 2a's method compile loop, typedef-name qualification) remains
unattempted — still foundational machinery touched by every compiled
struct, still rated moderate-to-high risk by this doc's own Risk
section. DOCUMENTED-NOT-FIXED; the fresh repro commands above are the
fastest known way to re-derive the failure.

## Partial fix (2026-08-20 — the STRUCT-METHOD-SYMBOL-QUALIFIER piece of this mechanism is fixed; the general struct FIELD-TABLE/TYPE-IDENTITY plan below remains open/unattempted)

Investigating the live `Lib/mailbox.py` instance from the 2026-08-11
entry just below (`class Message(email.message.Message):`, bare-name-
identical to its real imported base) found and fixed the specific
sub-mechanism responsible for the `redefinition of 'email_message_
Message___str__'`-shaped symptom: `_struct_method_qualifier`
(gimple_codegen.py ~line 25808) checked the shared, whole-program
`_imported_struct_home` registry (keyed purely by bare struct name)
BEFORE checking whether the struct currently being emitted is
genuinely locally declared in the file currently being compiled
(`_local_struct_names`) — so a struct that IS locally defined but
happens to share a bare name with an unrelated (or, as in mailbox.py's
case, a genuine base-class) struct registered elsewhere in the closure
got ALL its methods wrongly qualified with the OTHER module's prefix,
producing duplicate/colliding C symbols with that other module's own
real emissions. Fixed by reordering: local declaration now always wins
this instance's own qualifier over the shared import registry. This
only changes behavior for the narrow case where a bare name is present
in BOTH `_local_struct_names` and `_imported_struct_home`
simultaneously — every other struct's qualification (the overwhelming
majority) is unaffected, since a struct's own compiling temp_gen
registers into `_imported_struct_home` under the same value the local
branch would already produce, so the two branches always agreed absent
a genuine collision.

**This is a narrower, much lower-risk fix than the general plan this
doc lays out below** (which additionally covers struct FIELD-TABLE/
TYPE-IDENTITY qualification, `_struct_name_owner`'s field-registration
collision handling, and the free-function `func_return_types` bare-key
analog called out in the 2026-08-11 entry) — none of that broader,
"moderate-to-high risk" work was attempted here. Concretely: two real,
UNRELATED classes sharing a bare name (the tkinter `Dialog` repro this
doc originally documents) still corrupt each other exactly as before if
BOTH are locally-defined structs with no import relationship at all (this
fix only helps the "one side is genuinely imported, the other is local"
shape) — the minimal 2-file `Dialog`/`Dialog` repro described below was
NOT re-tested against this fix and is not expected to be affected by it.

Verified via real rebuilds: `Lib/mailbox.py`'s `email_message_Message_*`
redefinitions (0, was 48), `Lib/typing.py`'s `_collections_abc__
CallableGenericAlias___repr__`/`___reduce__` redefinitions (0, was 2,
same mechanism — `typing.py`'s own `_CallableGenericAlias` bare-name-
collides with `_collections_abc.py`'s unrelated class of the same name),
`Lib/socket.py`'s dominant "'X' undeclared here" collision-pattern error
count (13, was 370) all confirmed fixed/improved. The two originally-
confirmed real-world triggers (`Lib/tkinter/filedialog.py`, `Lib/
tkinter/simpledialog.py`) still build clean (unaffected either way,
since they go through link mode, not this inline-path mechanism). Full
quality gate (`test_gimple.py` 248/248, `test_module_cache.py` 76/76,
`make check-selfhost`, from-scratch stdlib dylib rebuild 0 skipped
before/after via a separate `git worktree add` baseline, `compile_
stdlib.py -j8` 664/664) all pass, no regression.

The general fix this doc's own plan calls for (struct field-table
qualification, propagating a value's resolved identity through later
field accesses, Phase 2a using each struct's own qualified field table)
remains genuinely unattempted — still assessed as moderate-to-high risk,
still a real, broader gap. Not deprioritized-as-unreachable anymore
though: this session's fix demonstrates the narrower method-symbol slice
of the mechanism WAS reachable and fixable at acceptable risk; whoever
picks up the remaining field-identity work should re-assess reachability
given `fire.py build`'s inline fallback is evidently exercised more often
in practice than the "structurally unreachable" framing below assumed.

## Cross-reference (2026-08-11 — live counter-example found to the "unreachable via primary path" claim, PLUS the same mechanism confirmed for free functions, not just structs)

Investigating `bugs/CODEGEN_generator_function_Lib_mailbox.md` (a
different, generator-focused doc) found a live, concrete instance of
this exact bare-name-collision mechanism reachable through `fire.py
build`'s documented inline fallback: `driver.compile_program` (link
mode) returns `None` for `Lib/mailbox.py`, so `fire.py build` falls
back to the whole-program `do_imports=True` inline path — precisely
the path this doc's 2026-08-08 entry calls "only reached as `fire.py
build`'s degraded fallback" with "no known live, reachable instance."
mailbox.py IS such an instance. So the claim that the two named
real-world triggers (`tkinter/filedialog.py`/`tkinter/simpledialog.py`)
building clean via link-mode implies the bug is unreachable in
practice does not generalize — any file whose link-mode compile fails
for unrelated reasons falls into the vulnerable inline path.

Also confirmed the **same bare-name-collision mechanism applies to
free functions, not just structs**: `gimple_codegen.py`'s free-function
return-type registration (`self.func_return_types[node.name] =
ret_type`, ~line 22802) keys purely on bare name with no module
qualifier, exactly like the struct case this doc documents. Concrete
repro: `Lib/tokenize.py` (and codecs.py/gzip.py/bz2.py/lzma.py/wave.py/
shelve.py/webbrowser.py) each define a module-level `def open(...)`
that shadows the builtin; once any of these is transitively compiled
into the same whole-program unit as mailbox.py, `_lower_named_call`'s
builtin-`open`-vs-user-`open` guard (`gimple_codegen.py:14449`, `'open'
not in self.func_return_types`) flips globally, misrouting mailbox.py's
own genuine `open(path, mode)` calls to the 1-arg `mojo_open_file`
builtin-C-symbol path (arity mismatch, `too many arguments to function
'mojo_open_file'; expected 1, have 2`). See that doc's 2026-08-11 entry
for full detail, including why a naive "just always treat bare `open`
as the builtin" fix is rejected: it would silently regress
`Lib/webbrowser.py`, which is already in the 664-file gate corpus and
genuinely relies on its own shadowing `open(url, new, autoraise)` being
bare-callable from `open_new()`/`open_new_tab()` in the same file.

Not fixed here (out of scope for the generator-focused task that found
it) — left as a precise pointer for whoever next picks up this doc:
a real fix needs per-module free-function/struct-name scoping in the
whole-program inline compile path (`self.module_name`/
`self._current_module_ctx` are NOT actually module-scoped per
originating `FunctionDef`/`StructDef` in that path today — confirmed by
reading every assignment site, all unconditionally set to the single
entry-module value for the whole `GimpleGen` instance's lifetime).

## Status (re-verified 2026-08-09 — unchanged, still deprioritized/not fixed)

Re-ran both named repros again against current master via plain
`python3 fire.py build <file>.py`:

- `Lib/tkinter/filedialog.py` — still builds clean (exit 0, no
  struct-collision errors in the compile log).
- `Lib/tkinter/simpledialog.py` — still builds clean (exit 0, same).

No change from the 2026-08-08 assessment below — both real-world
triggers still go through `driver.py`'s link-mode path (each imported
module its own translation unit), so the collision this doc describes
remains structurally unreachable on the primary `fire.py build` entry
point for these two files. The underlying `do_imports=True` inline-path
gap itself was not re-derived or re-attempted here (lightweight
re-check only, per this session's assignment) — the 2026-08-08 analysis
below still stands.

## Status (reassessed 2026-08-08 — deprioritized, not fixed)

Re-verified both originally-confirmed real-world triggers against current
master using the actual, default, user-facing command
(`python3 fire.py build <file>.py`):

- `Lib/tkinter/filedialog.py` — **builds clean**, no struct-collision
  errors (runs, hits an unrelated separate bug at runtime —
  `AttributeError: curdir` from an unresolved-import stub, out of scope).
- `Lib/tkinter/simpledialog.py` — **builds clean** as well.

Neither reproduces via `fire.py build` anymore. Root cause: `fire.py
build` now goes through `driver.py`'s module-cache "link mode" FIRST
(`driver.compile_program`, see its own docstring: "compiles the client
in link mode (extern decls)... content-addresses the whole program...
If the link path can't produce a binary we return None so the caller
can fall back to the inline builder"), only falling back to the
`do_imports=True` whole-program inline builder
(`gimple_codegen.compile_to_gimple_cached`, `fire.py build_executable`)
on failure. Link mode compiles EACH imported module as its OWN separate
translation unit/dylib — `tkinter/dialog.py`'s `Dialog` and
`tkinter/commondialog.py`'s unrelated `Dialog` are never in the same
`struct_field_types`/`_struct_name_owner` dict at once, so the
collision this doc describes is structurally impossible on that path.
`compile_stdlib.py` (the quality-gate corpus tool) uses the same
per-module compile primitive (`build_stdlib_dylib.compile_module_to_c_
cached`), which is why its 664/664 clean-compile corpus has never
caught this bug either — same reason, independently confirmed.

**The underlying gap is still real and confirmed live** — a fresh
minimal 2-file repro
(`class Dialog: def __init__(self, widgetName): self.widgetName = ...`
in one file, an unrelated `class Dialog: def __init__(self, result):
self.result = ...` in a sibling file, both constructed from a third
file) invoked directly against the vulnerable entry point
(`gimple_codegen.compile_to_gimple_cached(src, do_imports=True, ...)`,
bypassing `driver.py` entirely) reproduces the exact documented
mechanism: the generated C has ONE `struct Dialog { int64_t
widgetName; }` typedef, and BOTH classes' `__init__` methods get
emitted under the SAME qualified C symbol name
(`mod_a_Dialog___init__`, even for the class that's really from
`mod_b` — confirming `_struct_method_qualifier`/`_imported_struct_home`
resolve to the WRONG home module for the "loser" struct, not just a
missing-qualification gap), with the second one writing to `self->
result` — a field that doesn't exist on the struct that won the
bare-name race. This would fail with both a C redefinition error
(same symbol name emitted twice) AND a "no member named 'result'"
error, exactly matching this doc's originally-documented symptoms.

Today, in practice, this inline `do_imports=True` entry point is only
reached as `fire.py build`'s degraded fallback (triggered when link
mode itself fails for unrelated reasons — driver.py's own docstring:
"we accept things break, but a program that can build still does") and
by `--dump-full`. Since link mode is tried first and both originally-
confirmed real-world instances succeed on it, this bug currently has
**no known live, reachable instance** through any of this project's
primary, supported entry points (`fire.py build`, `compile_stdlib.py`,
the stdlib dylib build). Given the fix this doc's own plan calls for
touches genuinely foundational, shared struct-identity machinery
(referenced by field access, method dispatch, reflection, construction,
and forward-declaration emission — the doc's own "Risk" section already
rates this moderate-to-high, and it has been deliberately deferred
twice before under the same reasoning), attempting the general fix now
— for a bug with zero live reachable instances on any primary path —
is not the right risk/reward trade. Deprioritized, not attempted.
Revisit if: (a) a real-world file is found where link mode itself
falls back to the inline builder AND that file also hits a genuine
same-bare-name collision, or (b) `do_imports=True` becomes a primary
(not fallback-only) path again for some other reason.

## Original status (2026-08-06/07, historical)

Unfixed. Concrete diagnosis + phased plan below (2026-08-06). Found while
fixing bugs/COMPILE_FAIL_tkinter_filedialog.md's original symptom (now
fixed, see commit `a907260`) — the ORIGINAL bug was masking this deeper
one: `tkinter/filedialog.py`'s own `_Dialog(commondialog.Dialog)`
inheritance couldn't even be resolved before, so this never got compiled
far enough to reach the current failure.

**2026-08-07**: repro re-confirmed reproducing byte-for-byte identically
on current master (`python3 fire.py build
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py` — same
`conflicting types for 'tkinter_commondialog_Dialog___init__'`/`'Dialog'
has no member named 'widgetName'/'parent'/'result'/'initial_focus'`
errors as originally documented). Implementation deliberately NOT
attempted this session: assessed the 4-step plan below against the
current code (`_struct_name_owner` at gimple_codegen.py:3649, the
registration loop at ~26765-26771, Phase 2a's per-StructDef method
compile loop) and confirmed steps 1 and 3 are more tractable than the
original write-up suggested (Phase 2a already iterates real `StructDef`
objects with real `id()` identity, not just names, so "is this the
`_struct_name_owner`-registered winner for its own bare name" is a
cheap, local check at each struct's own method-compile site) — but step
2 (propagating which-qualified-class a given VALUE resolves to, through
to every later field-access site derived from it, for the general case
where the disambiguating construction-site signal isn't locally
available) is a genuinely broad dataflow problem, and the doc's own
"Risk" section's warning — partial qualification "will just move the
corruption to a different consumer instead of fixing it" — was judged a
real, not theoretical, risk given this project's documented history of
exactly this class of regression from narrower changes to adjacent
shared machinery (see `bugs/COMPILE_FAIL_collections___init__.md`).
Given the "moderate-to-high" risk this doc's own Risk section already
assigns, and this being core struct-identity machinery "referenced by
field access, method dispatch, reflection..., constructor lowering, and
forward-declaration emission" (far broader blast radius than a
preamble-only change), deferred to a dedicated pass with a larger time
budget rather than attempting a partial version under time pressure.

**2026-08-07 (Track B session)**: a second, independent real-world
instance found (not investigated/fixed, purely logged per this
project's "elaborate the bugs database" convention) — `python3 fire.py
build /Users/mrs/net/Python-3.14.6/Lib/typing.py`: `Lib/_collections_
abc.py` defines `class _CallableGenericAlias(GenericAlias):` and `Lib/
typing.py` INDEPENDENTLY defines its OWN, unrelated `class
_CallableGenericAlias(_NotIterable, _GenericAlias, _root=True):` (line
1615) — same bare name, same shape of bug: `redefinition of
'_collections_abc__CallableGenericAlias___repr__'`/`___reduce__`,
`conflicting types for '..___getitem__'`, `'_CallableGenericAlias' has
no member named '__parameters__'/'__module__'`. Same root cause, same
"deferred to a dedicated pass" status — not attempted here either,
explicitly out of scope per this session's own assignment (task #141).

## Symptom

```
error: conflicting types for 'tkinter_commondialog_Dialog___init__'; ...
error: 'Dialog' has no member named 'widgetName'
```
or, depending on which file's `Dialog` "wins" the name first:
```
error: redefinition of 'tkinter_commondialog_Dialog___init__'
error: 'Dialog' has no member named 'parent'
error: 'Dialog' has no member named 'result'
```

## Repro

Real: `Lib/tkinter/dialog.py` defines `class Dialog(Widget):` (fields
`widgetName`, `num`, ...). `Lib/tkinter/commondialog.py` defines a
COMPLETELY UNRELATED `class Dialog:` (fields none of the same). `Lib/
tkinter/simpledialog.py` defines YET ANOTHER unrelated `class
Dialog(Toplevel):` (fields `parent`, `result`, `initial_focus`, ...).
Real Python has zero ambiguity — each file imports whichever `Dialog` it
needs under its own binding (`from tkinter.dialog import Dialog`, or
stays qualified as `commondialog.Dialog`) — but any TWO of these reaching
the same whole-program compile (e.g. `tkinter/filedialog.py` transitively
pulls in `tkinter/dialog.py`'s `Dialog` AND `tkinter/commondialog.py`'s
`Dialog`; `tkinter/simpledialog.py` pulls in its OWN `Dialog` AND
`commondialog.py`'s) corrupts one of them.

Not yet minimally reproduced with a small hand-written 2-file repro (a
first attempt using `from a import Dialog as ADialog` + a same-named
local `Dialog` compiled clean — the real files' actual trigger involves
`from tkinter import *` wildcard imports pulling in `Dialog` transitively
through `tkinter/__init__.py`'s own re-exports, a shape not yet isolated
down to a minimal case). The two REAL, directly-confirmed repros
(`Lib/tkinter/filedialog.py`, `Lib/tkinter/simpledialog.py`, both via
plain `python3 fire.py build <file>.py`) are solid, reproducing evidence
on their own — see their exact errors above, captured directly from the
real compiler.

## Root cause (confirmed)

`gen_module`'s struct pre-registration pass (gimple_codegen.py:~26440-26463)
uses `self._struct_name_owner: dict[str, int]` (name -> `id()` of the
StructDef that "owns" that bare name) as a cross-module-shared collision
guard: the FIRST StructDef seen anywhere in the transitive closure under
a given bare name claims `struct_field_types[name]`/`_class_attrs[name]`;
every OTHER StructDef with the same bare name is skipped entirely at this
registration step (`if self._struct_name_owner.get(s.name) != id(s):
continue`) — this guard exists specifically to prevent the WORSE bug it
replaced (silently MERGING two unrelated classes' fields into one
Frankenstein struct — see its own docstring, "two unrelated classes
sharing a bare name... must NOT have their fields merged").

But this guard only protects the FIELD-TABLE REGISTRATION step. Phase 2a
(gimple_codegen.py's per-statement body-compilation loop) is NOT gated by
`_struct_name_owner` at all — it iterates `stmts`/`imported_stmts`
directly and compiles EVERY StructDef's methods it finds, including the
"loser" class's. Those method bodies (e.g. `Dialog.__init__` from
whichever file lost) get compiled against `struct_field_types['Dialog']`,
which by then belongs entirely to the WINNING class — any field access
the loser's own methods make that isn't ALSO a field of the winner either
hard-fails ("has no member named") or, worse, silently reads/writes the
wrong offset if the two structs happen to share a same-named-but-
different-meaning field.

## Why this wasn't caught before

Two real classes sharing a bare name AND both being reachable in the SAME
whole-program transitive-closure compile is uncommon in the curated
test_gimple.py/compile_stdlib.py corpus (which mostly compiles one
stdlib module's dependency tree at a time, rarely hitting two unrelated
same-named classes at once) but is a completely ordinary shape in a large
real-world package like `tkinter` with many small, independently-named-
after-their-purpose dialog files.

## What a real fix needs

This codegen's struct-identity model currently assumes one bare class
name maps to exactly one real class within a whole-program compile — true
almost everywhere except this shape. A real fix needs genuine cross-
module-qualified struct identity, mirroring the pattern this codegen
ALREADY uses for the analogous free-function and struct-METHOD-symbol
collision cases (SB-1 project: `_func_qualifier`/`_imported_func_home`
for free functions, `_imported_struct_home`/`_struct_method_qualifier`
for method SYMBOLS) — just not yet applied to the struct's own FIELD
TABLE / TYPE IDENTITY itself:

1. When `_struct_name_owner` detects a genuine collision (a second
   StructDef, different identity, same bare name), instead of silently
   skipping its registration, register it under a MODULE-QUALIFIED key
   (e.g. `f"{home_module}::{name}"`, mirroring `_struct_method_qualifier`'s
   existing qualification scheme) in `struct_field_types`/`_class_attrs`
   — do NOT drop it.
2. Every consumer that currently looks up `struct_field_types[bare_name]`
   for an instance whose STATIC type is ambiguous between two same-named
   classes needs to resolve to the right qualified entry instead. Since
   this codegen already tracks a value's real originating type in several
   places (`_actual_types`, construction-site tracking, `_imported_struct_
   home`), the disambiguation signal usually already exists at the point
   a value is CONSTRUCTED (`Dialog(...)` called from within a specific
   module's own compile context resolves unambiguously to THAT module's
   Dialog) — the gap is propagating that resolved identity through to
   every later field-access site on values derived from it, not
   re-deriving "which Dialog" from the bare type name alone.
3. Phase 2a's struct-method compilation loop needs to use each struct's
   OWN qualified field table (from step 1) when compiling its methods,
   not the bare-name lookup that currently always wins for whichever
   struct claimed the name first.
4. C symbol emission (the `struct Dialog { ... }` typedef, `Dialog_init`-
   style method symbols) already has SOME qualification machinery
   (`_struct_method_qualifier`) for methods — extend it to also qualify
   the STRUCT TYPEDEF NAME ITSELF when a genuine bare-name collision is
   detected (two real, structurally-different structs), so the two C
   struct definitions don't collide either. A struct with NO collision
   keeps its current unqualified name unchanged (no behavior change for
   the overwhelmingly common non-colliding case).

### Verification

1. The minimal 2-file repro above compiles, links, and runs correctly —
   `x.widgetName` prints `"a"`, `y.result` prints `"b"`, no cross-
   contamination.
2. `Lib/tkinter/filedialog.py` and `Lib/tkinter/simpledialog.py` (both
   real, confirmed-live triggers) compile clean.
3. Full quality gate (test_gimple.py, test_module_cache.py, make
   check-selfhost, from-scratch dylib rebuild, compile_stdlib.py -j8) —
   this touches core struct-identity machinery used by every single
   compiled struct, so a regression here would be broad; all four (plus
   compile_stdlib.py) must stay green, not just the two new repros.

### Risk

Moderate-to-high. Struct identity is foundational — referenced by field
access, method dispatch, reflection (`_mojo_dispatch_getattr`/`dataclasses.
fields()`), constructor lowering, and forward-declaration emission. The
qualification must be applied CONSISTENTLY everywhere a bare struct name
is currently used as a dict key, or partial qualification will just move
the corruption to a different consumer instead of fixing it. Recommend
implementing behind the EXISTING `_struct_name_owner` collision-detection
signal (only qualify when a real collision is detected, never for the
common single-owner case) to keep the change's blast radius scoped to
genuinely-colliding names.
