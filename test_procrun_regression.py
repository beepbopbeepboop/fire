"""Regression for PERF_formal_job_peaks_at_46gb_against_an_8gb_class: tree_rss sums RSS
(double-counts shared COW pages); tree_usage_unique must report max, not sum."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tools.procrun as p

def test_unique_is_not_sum():
    # Mock: root 1 with child 2, both same RSS 1000 KB -> sum = 2000, max = 1000
    ppid = {1: 0, 2: 1}
    rss = {1: 1000, 2: 1000}
    cpu = {1: 0, 2: 0}
    spent, total, count = p.tree_usage_unique(1, ppid, rss, cpu)
    assert total == 1000 * 1024, "max must be 1000KB not sum 2000KB (got %d)" % total
    assert count == 2
    print("OK: tree_usage_unique reports max (%d bytes), not sum" % total)

if __name__ == "__main__":
    test_unique_is_not_sum()
