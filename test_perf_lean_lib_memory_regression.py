"""Regression: cold lean library build 9 GB measurement is captured."""
import tools.suite as S

def test_prooflib_peak_9gb_class_covered():
    peak, note = S.MEASURED_PEAK_GB['prooflib']
    assert peak == 9.0, f"expected 9.0 GB, got {peak}"

def test_sweep_truth_class_above_peak_explains_9gb():
    assert 'formal-sweep-truth' in S.CLASS_ABOVE_PEAK
    text = S.CLASS_ABOVE_PEAK['formal-sweep-truth']
    assert '9.0' in text or 'cold-store' in text

def test_prooflib_memclass_module_covers_9gb():
    # module = 24 GB; 1.5 * 9.0 = 13.5 < 24
    assert S.MEMCLASS['module'] >= 24
