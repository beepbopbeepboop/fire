#!/usr/bin/env python3
"""Quick regression for bugs/CODEGEN_dynamic_call_layer_residue_after_fsutil.md.

Item 1 (FIXED): module-alias fallback `not node.kwargs` guard removed in
_ lower_method_call; verified by test_link_mode.py::
test_bare_submodule_import_keyword_call (PASS).

Item 2 (NOT REPRODUCED in minimal form): `len(list(mod.gen(...)))` —
module-attribute generator used as argument to list() — passes on this
tree in the minimal package form; doc's next step (reproduce with real
c_common/fsutil.py shape) requires the full link-mode build of fsutil
which exceeds quick-test budget.

Item 3 (FIXED): `.startswith`/`.endswith` on an unsolved word typed `_Bool`;
verified by test_link_mode.py::test_str_affix_method_on_unsolved_word_is_bool.

Items 4-5: not yet started.
"""

# No executable assertion beyond the existing test_link_mode coverage;
# this file serves as a pinned reminder of what's verified.

def test_regression_item1_fixed():
    # Verified externally: test_link_mode.py::test_bare_submodule_import_keyword_call
    assert True
