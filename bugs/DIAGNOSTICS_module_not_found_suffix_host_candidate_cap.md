# DIAGNOSTICS: the `import os2` suffix differs from CPython at the MNE candidate cap

Found 2026-11-10 by the estate audit: `test_attr_error_messages.py` fails on master.

## Measured
`test_module_not_found_suggestion_suffixes` asserts that `s('os2')` equals `mne_os2_expected()`, the suffix CPython
3.15 appends on this host. The shared engine caps its candidate pool at 750 (C pass) and 751 (fallback), and the
host's discoverable module set is larger than that cap, so the suggestion text does not match.

## Next step
Decide whether the cap is the right behaviour (CPython has no cap) or whether the cap should only affect the search
and not the suffix. Then make the engine match and delete this doc.
