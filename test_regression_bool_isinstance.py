# Regression for CODEGEN_bool_annotated_struct_field_prints_as_int option A
# Tests isinstance(type(True)) / type(True) after _TYPE_MAP['bool'] = '_Bool'

def main():
    def show(v: bool):
        print(isinstance(v, bool))
        print(type(v))
    show(True)
    show(False)

main()
