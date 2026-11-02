"""Regression for MERGE_bulk_resolved_to_master_dropped_branch_definitions.
The bulk merge kept the master-side signature but dropped the branch's
SET_ALGEBRA_OPS definition (or duplicated it). Pinned: exactly one
definition exists and it carries the correct three operators.
"""

def test_set_algebra_ops_defined_once():
    src = open("formal/model.py").read()
    lines = [ln for ln in src.splitlines() if "SET_ALGEBRA_OPS =" in ln]
    assert len(lines) == 1, f"expected 1 SET_ALGEBRA_OPS definition, got {len(lines)}: {lines}"
    # Verify the three set-algebra operators are present
    assert '"-"' in lines[0] and '"&"' in lines[0] and '"^"' in lines[0], \
        f"SET_ALGEBRA_OPS missing operators: {lines[0]}"

if __name__ == "__main__":
    test_set_algebra_ops_defined_once()
    print("PASS merge bulk resolved regression")
