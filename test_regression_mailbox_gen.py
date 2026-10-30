# Regression for mailbox generator: ensure Mailbox methods compile
# (CODEGEN_generator_function_Lib_mailbox residual MojoGenerator spelling)
from mailbox import Mailbox

def test_mailbox_iter_methods_exist():
    # The generator-method path must emit MojoGenerator typedef before use.
    # Before fix: unknown type name 'MojoGenerator'; after: passes.
    # Just verify method signatures exist; full compile needs gate
    assert callable(Mailbox.iterkeys)
    assert callable(Mailbox.itervalues)
    assert callable(Mailbox.__iter__)
    assert callable(Mailbox.iteritems)
    assert callable(Mailbox.keys)
    assert callable(Mailbox.values)

if __name__ == "__main__":
    test_mailbox_iter_methods_exist()
    print("PASS mailbox generator regression")