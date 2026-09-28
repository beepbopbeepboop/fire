fn main():
    # `print`, not `mojo_print`: the latter is the raw runtime sink declared
    # `void mojo_print(char *str)` (runtime/fire_runtime.h:859) and takes a C
    # string, so handing it the int64 row count dereferenced an integer as a
    # pointer and segfaulted after the link was fixed. `print` is the language
    # builtin, which the codegen formats through to a string first.
    var db = mojo_sqlite3_open(":memory:")
    if db == 0:
        print("FAIL: open")
        return
    var rc = mojo_sqlite3_exec(db, "CREATE TABLE t (id INT, name TEXT)")
    if rc != 0:
        print(mojo_sqlite3_errmsg(db))
        return
    rc = mojo_sqlite3_exec(db, "INSERT INTO t VALUES (1, 'a'), (2, 'b')")
    if rc != 0:
        print(mojo_sqlite3_errmsg(db))
        return
    var rows = mojo_sqlite3_query(db, "SELECT * FROM t ORDER BY id")
    var n = mojo_list_len(rows)
    print(n)
    mojo_sqlite3_close(db)
