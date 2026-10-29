"""Regression pin for CODEGEN_polymorphic_struct_param_degrades_to_a_pointer: polymorphic struct receiver silently degrades to pointer."""
import tempfile, os, sys
sys.path.insert(0, '.')


def test_polymorphic_struct_receiver_raises():
    src = '''
class T:
    def __init__(self, n):
        self.n = n
    def numel(self):
        return self.n

class U:
    def __init__(self, n):
        self.n = n
    def numel(self):
        return self.n + 1

def a(w):
    return w.numel()

def main():
    print(a(T(5)))
    print(a(U(5)))
'''
    import gimple_codegen
    try:
        gimple_codegen.compile_to_gimple(src)
        assert False, 'expected RuntimeError for polymorphic struct receiver'
    except RuntimeError as exc:
        msg = str(exc)
        assert 'polymorphic struct parameter' in msg, msg
        assert 'w' in msg, msg
        assert 'a' in msg, msg
        assert 'T *' in msg, msg
        assert 'U *' in msg, msg
        print('PASS: refusal raised correctly')


if __name__ == '__main__':
    test_polymorphic_struct_receiver_raises()
