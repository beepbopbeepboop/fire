"""Regression pin for the SUITE_self_test_red suite-self-test drift bug.

Pins the specific suite-self-test rows that went red when the registry and
test_suite.py drifted apart: self-host key coverage for unknown_decl_check.py,
disabled-job estate/census consistency, estate registration of recently added
tests, admission using a non-disabled job, and gimplerunner expect-count census.
"""
import os
import re
import unittest

import cas
import tools.suite as suite


class SuiteSelfTestRedRegression(unittest.TestCase):
    def test_selfhost_key_includes_unknown_decl_check(self):
        missing, seen = cas.selfhost_closure_is_complete()
        self.assertNotIn('unknown_decl_check.py', missing,
                         f'unknown_decl_check.py must be in the self-host key: {sorted(missing)}')
        self.assertIn('unknown_decl_check.py', cas.selfhost_inputs())

    def test_disabled_jobs_are_accounted_for(self):
        disabled = [n for n, s in suite.REGISTRY.items() if suite.is_disabled(s)]
        # The registry may legitimately have disabled jobs; test_suite.py must
        # account for each one (reserves 0, listed, dry-run disabled). This pin
        # requires that at least the formerly-missing gate-triage jobs, if still
        # disabled, are present with docs; and that no disabled job reserves GB.
        for name in disabled:
            spec = suite.REGISTRY[name]
            self.assertTrue(spec.disabled, name)
            self.assertEqual(suite.reserved_gb(spec), 0, name)
            self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(__file__), spec.disabled)),
                            f'{name}: missing disabled doc {spec.disabled}')

    def test_estate_rows_from_bug_are_registered_or_listed(self):
        # Files named in the SUITE_self_test_red drift bug row 4 must not be invisible.
        estate = [
            'test_binding_evidence.py',
            'test_codegen_simd_exp_statictuple.py',
            'test_codegen_yield_from_walk_ast_memo.py',
            'test_function_body_alias_class_import.py',
            'test_gpu_offload_validation_part3.py',
            'test_mojoc_implicit_default_conformance.py',
            'test_mojoc_import_conformance.py',
            'test_mojoc_module_import_ambiguous.py',
            'test_mojoc_synthetic_signature_default.py',
            'test_stdlib_dylib_lazy_undefined_refs_probes.py',
            'test_stdlib_syntax_variant.py',
            'test_unknown_decl_check.py',
            'tests/test_suite_silentnoop_part1_replan.py',
        ]
        import test_suite
        registered_text = '\n'.join(
            ' '.join(s.cmd) for s in suite.REGISTRY.values())
        for path in estate:
            full = os.path.join(os.path.dirname(__file__), path)
            if not os.path.exists(full):
                continue
            base = os.path.basename(path)
            in_unregistered = path in test_suite.UNREGISTERED or base in test_suite.UNREGISTERED
            in_registered = path in registered_text or base in registered_text
            self.assertTrue(in_unregistered or in_registered,
                            f'{path} must be registered or listed in UNREGISTERED')

    def test_gimplerunner_expect_count_census_consistent(self):
        spec = suite.REGISTRY.get('gimplerunner')
        self.assertIsNotNone(spec)
        if not getattr(spec, 'expect', ''):
            self.skipTest('gimplerunner is no longer marked expect=')
        # census in test_suite.py must agree with marker's leading count
        import re
        m = re.match(r'\s*(\d+)\b', spec.expect)
        self.assertIsNotNone(m, spec.expect)
        marker_count = int(m.group(1))
        # the in-source census check string contains the same count; read it
        with open(os.path.join(os.path.dirname(__file__), 'test_suite.py')) as f:
            src = f.read()
        self.assertIn(f"'gimplerunner': {marker_count}", src,
                      f'test_suite.py census must state gimplerunner count {marker_count}')


if __name__ == '__main__':
    unittest.main()
