# ORCH: a gate-ledger doc claims `disabled=` on jobs that have no such marker

## What happens

Every doc `tools/verify_landed.py::write_doc` files carries this paragraph, from
`tools/gate_ledger.py::report_text` (lines 242-243):

    - **Skipped:** the job's registration in `tools/suite.py` carries
      `disabled='bugs/gate-<job>.md'`, so the gate spends no time on it. To fix
      it: remove the `disabled=` argument, make the job pass, and delete this
      doc in the same commit.

For a **fanout item** (a job name like `bootstrap-stage2-dumps:t_arith.mojo`)
that sentence is false. There is no registration with that name — only the
`fanout('bootstrap-stage2-dumps', ...)` call — so
`gate_ledger._registrations(src, job)` finds nothing, `set_disabled(src, job)`
is a no-op, and `apply_findings` records `e["marked"] = False` (verify_landed.py
lines 132-133). The gate does not know the item is off; it RUNS the item and it
fails. The paragraph sent 50 dispatched workers (gate `c0182fd3`) looking for a
`disabled=` switch that was never written.

`report_text` never consults `e["marked"]`, so the paragraph is emitted for
every newly-red job, not only for the ones a marker was actually added to.

## What I saw

    $ python3 tools/suite.py bootstrap-stage2-dumps
    ...
    1 skipped, 2 disabled, 0 failed
      skip  bootstrap-stage2-dumps:t_arith.mojo
            dependency is disabled: bootstrap-stage2-cc
            (bugs/gate-bootstrap-stage2-cc.md is the switch)

and the doc for the same job said "the job's registration carries
`disabled='bugs/gate-bootstrap-stage2-dumps:t_arith.mojo.md'`". The fanout
registration (`tools/suite.py`, `fanout('bootstrap-stage2-dumps', ...)`) has no
`disabled=` argument, and at `c0182fd3` the item ran and died in 1 s on
`FileNotFoundError: ./mojo`.

## Expected

The ledger section states the marker state it actually produced:

- marked: the current paragraph is right;
- not marked (fanout item, or a registration the splice could not find): say so
  — "no `disabled=` marker: this name has no registration of its own (a fanout
  item), so the item still runs and fails; the fix is the producer's, see..."
  — and name the parent registration. A worker reading a gate doc must be able
  to tell "off, costs the gate nothing" from "runs red every gate" without
  checking the registry.

## Exact next step

1. `tools/gate_ledger.py::report_text`: take the marked state (pass
   `e.get("marked")`, or compute `get_disabled(src, job)` at the call site) and
   emit the "Skipped" paragraph only when true; otherwise emit the
   no-registration wording above.
2. `tools/verify_landed.py::write_doc`: pass it through (it already has `e`).
3. Test in `tools/test_gate_ledger.py`: `report_text` for a plain `test(...)`
   with `marked=True` contains "carries", with `marked=False` does not, and for
   a `fanout` item name it says the item has no registration of its own.
4. `python3 tools/test_gate_ledger.py` and `python3 tools/test_gate_doc.py`.

The 49 docs already on master carry the same false paragraph; do not rewrite
them by hand — each is deleted by its own worker as the producer fix lands, and
this bug is about the generator, not the copies.
