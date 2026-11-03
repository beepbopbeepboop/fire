import test_gimple_runner as R

# Regression for CODEGEN_untyped_param_receives_container_printed_as_int:
# an untyped free-function parameter that only receives a container
# argument must be typed as the container, not left at int64_t.
def test_untyped_param_receives_container():
    R.test_gimple_stdout(
        'untyped_param_receives_container',
        '''
def show(t):
    print(t)

def main():
    x = [i for i in range(3)]
    show(x)
    y = [i for i in range(3)]
    print(y)
''',
        '[0, 1, 2]\n[0, 1, 2]\n')
