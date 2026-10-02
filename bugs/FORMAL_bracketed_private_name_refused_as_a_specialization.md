# FORMAL_bracketed_private_name_refused_as_a_specialization: `priv._helper[1](x)` is refused for the wrong reason, and the doc that names it is stale

## Status

OPEN — found 2026-10-01 while landing `construct:module-name-as-a-value`
(commit `663f174d`). **Not caused by that work and not fixed by it**, which is
measured rather than assumed: the case was re-run with `formal/build.py` and
`formal/model.py` reverted to HEAD and it fails identically.

This is the ONE red case of 18 in `test_formal_module_attr.py`, and the 18th
is the one this doc is not about. The existing doc for this case is
`bugs/FORMAL_bracketed_call_to_a_private_name_is_refused_as_a_dangling_symbol.md`
— **read that first**, because it is the same construct and its §"the exact next
step" is still the right work. It is filed here for a different reason: **its
recorded measurement is stale, and following it would send a reader to the wrong
place.**

## What the stale doc says, and what this tree actually does

`FORMAL_bracketed_call_to_a_private_name_is_refused_as_a_dangling_symbol.md`
records two backends disagreeing:

    ===== arm64 =====
    build: prog.mojo: the image would bind 1 symbol(s) that nothing provides,
    so it could not be loaded: _helper. …

    ===== x86_64 =====
    build: unsupported call target on the formal x86-64 path (got SubscriptExpr)

**Neither of those is what this tree produces now.** Both architectures produce
one message, from `formal/model.py:specialization_call_refusal`:

    $ python3 fire.py build --formal --no-prove --backend arm64 -o /tmp/x.aout \
        priv.mojo prog.mojo
    build: _helper[…](…) calls a name this unit does not compile, so the brackets
    cannot be bound. A comptime specialization's brackets are the generic's
    comptime parameters, and on this path those are ordinary leading arguments
    the call site evaluates and passes first — a decision about a signature,
    which needs a declaration and there is none in hand. If `_helper` is a
    generic of another module then its instantiation is the boundary symbol,
    one per set of type arguments (doc/ABI.md §Generics), and this path does not
    monomorphize, so there is no callee here to pass them to; …

    $ python3 fire.py build --formal --no-prove --backend x86_64 -o /tmp/x.aout \
        priv.mojo prog.mojo
    build: _helper[…](…) calls a name this unit does not compile, …      <- same

(the `.mojo` pair is the case's own tree: `priv.mojo` defines `_helper` and
`pub`, `prog.mojo` is `from priv import _helper` + `return _helper[1](2)`).

So the tree has MOVED, in two ways that matter to whoever picks this up:

1. **The arm64 dangling-symbol half is FIXED.** It no longer reaches the linker.
   The refusal is now a construct refusal asked during the name walk.
2. **The x86-64 "unsupported call target" half is no longer a backend gap for
   this shape.** `formal/x86_64_codegen.py`'s missing `SubscriptExpr` arm is not
   reached, because the check refuses before codegen. The 56-file x86-64 gap the
   old doc cites is a DIFFERENT set of files (ones whose brackets are well-formed
   and whose callee this unit compiles) and is not contradicted by this.

**The architectures no longer disagree**, which is what the old doc called the
real problem. That is an improvement, not a regression, and it happened on
someone else's branch — the doc's measurements date from 2026-09-30 and name no
commit.

## Why it still fails

The test asserts the refusal names the EXPORT rule:

    check("does not export it" in text and "_helper" in text, …)

which is `formal/model.py:imported_callee_refusal`'s wording, and asserts the
message is not the storage one (`"no storage for it"`), which now passes. The
message that fires is `specialization_call_refusal`'s, which is a third thing:
it is about the BRACKETS, not about the export rule and not about storage. All
three are true statements; the test wants the second.

That is the tension the old doc's step 1 named, and it is still open:
`bracketed_call` is asked BEFORE the imported-callee refusal in
`formal/build.py`'s `check_module_symbols` (`bracketed` is asked before
`callees`, and the specialization refusal is computed into `bracketed`), so for
a bracketed callee this unit does not compile, the brackets win. The old doc's
step 1 — resolve the shape through `model.subscript_callee_name(call)` and give
the EXPORT rule the answer — is still exactly right, and it is still the same
precedence question.

## The next step, exactly

Ask the export rule before the brackets for a bracketed callee that is a name
another module does not export, using the two recognisers that already exist —
`model.subscript_callee_name(call)` for the base name and
`model.subscript_callee_names(call)` for what the bracket consumes — so
`priv._helper[1](2)` is refused as "a leading `_` is private, so there is
nothing to bind", which is the fact and is what the test asserts. Keep
`specialization_call_refusal` for a bracketed callee this unit DOES compile and
has no signature for; that is its case and it is worded for it.

One thing NOT to do here: do not reach for `imported_module_names` /
`module_reads` from `construct:module-name-as-a-value` to fix it. That change
exempted the root of a dotted chain from the name-placement walk and added a
refusal for the MEMBER; `_helper[1](2)` has no member read (`_helper` is a bare
`IdentExpr` under a `SubscriptExpr`), so it is not in that change's scope and
touching it would widen an unrelated construct.

## Verified on this tree

    $ python3 test_formal_module_attr.py
      FAIL  `priv._helper[1](x)` is refused as an export gap, not a storage one
      …
      formal module attributes: PASS=17 FAIL=1

    # and with formal/build.py + formal/model.py reverted to HEAD:
      formal module attributes: PASS=10 FAIL=1        <- same case, same message

## Related

- `test_formal_module_attr.py` builds every case for BOTH architectures, so this
  cannot be made to pass by matching one of them — and per the measurement above
  it no longer needs to.
- `tools/suite.py` registers this file's job with an `expect=` marker that used
  to name the OLD doc and describe its (now-fixed) two-backend split. **That
  marker's reason was corrected in this commit** to name this doc and the
  message the tree actually produces — a marker whose reason is stale is a
  marker a reader cannot act on, and the file it names is the one this bug
  supersedes. The marker itself stays: the case is still red.
