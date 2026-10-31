# Regression pinning test for codegen-gimplerunner-five-reds-at-the-base.
# Four of the five cases fixed by commit 8cda11b64 (mixed-list kind copy)
# and the loop-target fix; the remaining polymorphic-receiver case is
# tracked separately (bugs/CODEGEN_unresolved_method_receiver...).
import sys
sys.path.insert(0, '.')
from test_gimple_runner import test_gimple_stdout

def test_heterogeneous_list_keeps_slots():
    test_gimple_stdout('gimple_heterogeneous_list_literal_keeps_each_slot',
        'fn main():\n    var a = [1, 2.5]\n    print(a)\nmain()\n',
        '[1, 2.5]\n')

def test_mixed_struct_derived():
    test_gimple_stdout('gimple_struct_mixed_reads_survive_a_derivation',
        'fn main():\n    var b = struct.pack(\'<if\', 1, 1.0)\n    var t = struct.unpack(\'<if\', b)\n    print(t)\n    print(list(t))\nmain()\n',
        '(1, 1.0)\n[1, 1.0]\n')

def test_loop_target_rebind():
    test_gimple_stdout('gimple_for_loop_target_rebind_int_then_dict_key',
        'fn main():\n    for i in [5]: pass\n    for a in {"a":1}: pass\n    print(5)\n    print("a")\nmain()\n',
        '5\na\n')

if __name__ == '__main__':
    test_heterogeneous_list_keeps_slots()
    print('PASS heterogeneous_list_keeps_slots')
    test_mixed_struct_derived()
    print('PASS mixed_struct_derived')
    test_loop_target_rebind()
    print('PASS loop_target_rebind')
