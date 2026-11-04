# STDLIB_builtin_error_mojo_246_assignment_to_int64_t_from_char_pointer

**file**: `std/builtin/error.mojo`  
**error**: gcc: .../std/builtin/error.mojo:246:15: error: assignment to 'int64_t' {aka 'long long int'} from 'char *' makes integer from pointer without a cast  

**notes**: likely related to if-case binding or String/char* type inference issues.
