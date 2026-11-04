# STDLIB_collections_string_iterators_mojo_251_assignment_to_int64_t_from_pointer

**file**: `std/collections/string/iterators.mojo`  
**error**: gcc: .../std/collections/string/iterators.mojo:251:19: error: assignment to 'int64_t' {aka 'long long int'} from ... * makes integer from pointer without a cast  

**notes**: pointer/integer type confusion in codegen.
