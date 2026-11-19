"""Regression: the end-to-end tables must cover every `_FORMS` form.

Bug: FORMAL_x86_64_the_successor_table_is_compared_against_the_model_on_six_forms
and the `group3:not`/false-`hmem` bug of 2026-11-19.

The first bug is the SUCCESSOR table: every form the prover will walk must have
a row whose successor the coverage job compares against the model.  The second
is the WALK itself: `_abs_step`, the constant propagation the end-to-end emitter
builds its path tree from, had no `group3:not`/`group3:neg` branch, so the first
`~n` in `formal/examples/unary_ops.mojo` wiped every register (RSP included) and
every later store was address-less.  An address-less store then looked like a
register-only step to the emitter, which is how a false `hmem` fact got emitted.
"""
import formal.x86_64_model_coverage_test as M
import formal.x86_64_endtoend_test as E


def test_successor_forms_covers_all_forms():
    covered = {row[0] for row in M.SUCCESSOR_FORMS}
    forms = set(E._FORMS)
    missing = forms - covered
    assert not missing, "SUCCESSOR_FORMS missing %d form(s): %s" % (len(missing), sorted(missing))
    stale = covered - forms
    assert not stale, "SUCCESSOR_FORMS names %d form(s) no `_FORMS` row can reach: %s" % (len(stale), sorted(stale))
    # NOT a row-per-form count: `SUCCESSOR_FORMS` deliberately carries more than
    # one row for a form whose WRITE SIDE differs by destination — the three
    # `mov_rm64_imm32` rows at rax, rdi and r15 are what make a regression to the
    # rax-pinned successor visible (see that table's own comment).  The property
    # this test states is COVERAGE, in both directions, not a tally.


def test_abs_step_models_every_form():
    """A form `_FORMS` proves must not wipe the walk's abstract state.

    `_Abs.wipe` is `_abs_step`'s fall-through: it is what the function does for a
    form it does not model, and it sets all sixteen registers unknown.  So this
    is the walk-side coverage check the `group3:not` bug needed and did not have
    — it names the form instead of leaving an `unsolved goals` in a generated
    file three hundred lines later.
    """
    bad = M.walk_failures()
    assert not bad, (
        "_abs_step does not model %d form(s) `_FORMS` will walk: %s — an "
        "unmodelled form wipes the abstract state, and a wipe makes every later "
        "store address-less" % (len(bad), bad))


def test_group3_not_is_the_complement_and_leaves_the_flags_alone():
    st = E._Abs()
    st.put(0, 0xDEADBEEFCAFEBABE)
    st.set_flags(True, False, True, False)            # sentinels
    after = E._abs_step(st, "group3:not", b"\x48\xf7\xd0", M.BASE, 3)
    assert after.get(0) == 0x2152411035014541, (
        "`not rax` is `a ^^^ 0xffffffffffffffff`; got %r" % (after.get(0),))
    assert after.flags == {"zf": True, "sf": False, "cf": True, "of_": False}, (
        "`not` writes no flags at all; got %r" % (after.flags,))


def test_group3_neg_is_zero_minus_and_sets_the_four_flags():
    st = E._Abs()
    st.put(0, 0xDEADBEEFCAFEBABE)
    after = E._abs_step(st, "group3:neg", b"\x48\xf7\xd8", M.BASE, 3)
    # 0 - 0xDEADBEEFCAFEBABE, mod 2^64; CF means `0 < a`, OF is
    # `msb 0 != msb a && msb res != msb 0` = msb(a) && msb(res).
    assert after.get(0) == 0x2152411035014542, (
        "`neg rax` is `0 - a`; got %r" % (after.get(0),))
    assert after.flags == {"zf": False, "sf": False, "cf": True, "of_": False}, (
        "`x86_flags_sub s 0 a res` on a negative operand: got %r"
        % (after.flags,))
    # The REX.B half: `neg r11` is `49 f7 db`, and the operand is rm + REX.B.
    top = E._Abs()
    top.put(11, 1)
    after = E._abs_step(top, "group3:neg", b"\x49\xf7\xdb", M.BASE, 3)
    assert after.get(11) == 0xFFFFFFFFFFFFFFFF, (
        "`neg r11` with REX.B must write r11, not r3; got %r"
        % (after.get(11),))
    assert after.flags == {"zf": False, "sf": True, "cf": True, "of_": False}, (
        "0 - 1 has ZF clear, SF set, CF set (0 < 1) and no signed overflow; "
        "got %r" % (after.flags,))


def test_store_forms_are_exactly_the_successor_rows_that_write_memory():
    """`_STORE_FORMS` is derived from `_SUCCS`, so it cannot fall behind it."""
    want = {form for form, succ in E._SUCCS.items() if "mem_write_bytes" in succ}
    assert set(E._STORE_FORMS) == want, (
        "_STORE_FORMS is not the set of `_SUCCS` rows that write memory: %r"
        % (set(E._STORE_FORMS) ^ want,))
    assert "push_r64" in E._STORE_FORMS
    assert "mov_rm64_r64_disp8" in E._STORE_FORMS
    assert "group3:not" not in E._STORE_FORMS


def test_a_store_at_an_unknown_address_is_still_a_store():
    """The false-`hmem` regression, without building a proof.

    A store through a base the walk does not know makes `_Abs.store` CLEAR the
    write list, so the old "did the list grow?" detector answered "this step
    wrote only registers" — and `emit_terminates` then emitted a memory-
    invariance fact about a `mem_write_bytes` successor.  `_store_of` takes the
    first answer from the FORM, so it says `stored` with no address.
    """
    st = E._Abs()
    assert st.get(7) is None                       # RDI is the input `n`
    raw = b"\x48\x89\x47\x08"                      # mov [rdi+8], rax
    after = E._abs_step(st, "mov_rm64_r64_disp8", raw, M.BASE, 4)
    assert after.writes == [] and not after.mem_ok, (
        "the walk must drop the memory model for an address-less store")
    assert E._store_of("mov_rm64_r64_disp8", st, after) == (True, None), (
        "a store at an unknown address is a STORE; the old list-length test "
        "called it register-only")
    # And a known-address store still carries the address the peel needs.
    # RDI is unknown in `_Abs`, so use a known base: `mov [rbx+8], rax`.
    known = E._Abs()
    after = E._abs_step(known, "mov_rm64_r64_disp8", b"\x48\x89\x43\x08",
                        M.BASE, 4)
    stores, write = E._store_of("mov_rm64_r64_disp8", known, after)
    assert stores and write is not None and write[0] == 0 + 8


if __name__ == "__main__":
    test_successor_forms_covers_all_forms()
    test_abs_step_models_every_form()
    test_group3_not_is_the_complement_and_leaves_the_flags_alone()
    test_group3_neg_is_zero_minus_and_sets_the_four_flags()
    test_store_forms_are_exactly_the_successor_rows_that_write_memory()
    test_a_store_at_an_unknown_address_is_still_a_store()
    print("PASS: all forms covered")
