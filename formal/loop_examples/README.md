# The loop corpus this layer's obligations are measured over

Twelve programs, one per family `formal/loop_invariants.py::family_of` names,
and every one of them BUILDS and RUNS on both architectures with CPython's answer
(measured; `test_formal_loop_invariants.py` keeps it that way).  They live HERE
and not in `formal/examples/` for a reason that is a measurement and not a
preference: `test_formal.py` scores a stem whose proof fails and which is not in
its `EXPECTED_FAILURES` as `FAIL`, so eleven of these twelve would turn two
registered jobs red for a claim about a different thing.  `formal/examples/` is
the census of what the PROOF GENERATOR emits; this directory is the census of
what the INVARIANT LAYER derives, and the two have different units.

Each program is also a row in `tools/formal_loop_invariants_baseline.json`, so a
change that makes an obligation stop closing is reported by name.
