# CODEGEN: nine test_gimple_runner.py cases fail after upstream commit 3530da89e

`python3 test_gimple_runner.py` (about 30 minutes) was 628 passed / 0 failed at `cb1a264a0`
(2026-11-17). On 2026-11-20 it reports `635 passed, 9 failed`. `git bisect` on one of the nine
(`gimple_and_chain_bool_call_empty_list_caller`) names the first bad commit:

    3530da89e  codegen: a system-struct collision's helpers do not read our fields
               (mojo/backend_gimple/module_gen.py, +31/-12)

It is not caused by the 2026-11-20 int-or-None return rule or the tagged-copy change (those landed
later and the case already failed with them absent). The other eight were not bisected; they fail
with the same kind of symptom (a `getattr` / attribute read that used to resolve now raises
`AttributeError`, or answers an empty string), so check them against the same commit first.

## The nine cases

    gimple_nested_class_method_reads_field_of_rebound_capture   AttributeError: directory
    gimple_struct_local_retained_by_a_method_is_not_freed       AttributeError: x
    gimple_ctor_param_polymorphic_slot_reads_receiver           AttributeError: numel
    gimple_ctor_param_three_candidate_poly_dispatch             AttributeError: numel
    gimple_dynamic_attribute_string_keeps_its_type              prints '' where 'hello' is expected
    gimple_printed_struct_repr_does_not_grow                    output differs
    gimple_struct_field_dump_is_not_an_address                  output differs
    gimple_or_chain_bool_getattr_dict                           exits 1 after the third line
    gimple_and_chain_bool_call_empty_list_caller                prints 'plain' where 'star' is expected

## Reproduce one in about 20 s

    python3 - <<'PY'
    import sys
    sys.path.insert(0, '.')
    import test_gimple_runner as R
    R.test_and_chain_with_a_bool_call_and_an_empty_list_caller()
    PY

## Next step

Read the diff of `3530da89e` (`git show 3530da89e`): it changes which struct a name in a system-struct
collision resolves to. The failing programs read an attribute off an object whose class shares a name
with a system struct (`numel`, `directory`, `x`). Make the lookup fall back to the program's own
struct when the collision helper does not own the field, rerun the nine cases, and delete this doc.
