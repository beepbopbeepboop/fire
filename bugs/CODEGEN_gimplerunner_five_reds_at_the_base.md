# test_gimple_runner.py: five rows fail at the base commit f34254962

## Status

OPEN. Found 2026-10-29 while running `test_gimple_runner.py` for the
enum-case change (86f908c22). The same five rows fail with that change
reverted (`git show f34254962:<file>` for the three changed files), so they are
not caused by it: 467 passed, 5 failed at the base; 469 passed, 5 failed with
the change (the two new rows pass).

## The five rows

    gimple_struct_mixed_reads_survive_a_derivation
        expected '(1, 1.0)\n[1, 1.0]\n...', got '[1, 4607182418800017408]\n...'
    gimple_heterogeneous_list_literal_keeps_each_slot
        expected '...[1, 2.5]\n[1, 2.5]\n', got '...[5e-324, 2.5]\n[1, 2.5]\n'
    gimple_struct_mixed_reads_survive_a_function_boundary
        expected '...[7, 0.5]\n...', got '...[7, 4602678819172646912]\n...'
    gimple_ctor_param_polymorphic_slot_reads_receiver
        expected '2\n2\n', got '4320137984\n4320137648\n'
    gimple_for_loop_target_rebind_int_then_dict_key
        expected '5\na\n', got '5\n4377268976\n'

Each one prints a float or a string slot's bits as an int: a list or a
polymorphic slot is read at the wrong element kind, which is the family of
the polymorphic non-str print bug (its doc was deleted when fixed) and
the loop-target rebind bug (its doc was deleted when fixed).
That is a guess from the symptoms; no row has been traced yet.

## Next step

Run one row alone (`python3 test_gimple_runner.py` prints each, or call its
`test_gimple_stdout` from a small script), dump its generated C, and find the
first slot read whose C type differs from the value's Mojo type. Start with
`gimple_ctor_param_polymorphic_slot_reads_receiver`, the smallest.
