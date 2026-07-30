fn main():
    var db = mojo_sqlite3_open(":memory:")
    if db == 0:
        mojo_print("FAIL: open")
        return
    var rc = mojo_sqlite3_exec(db, "CREATE TABLE t (id INT, name TEXT)")
    if rc != 0:
        mojo_print(mojo_sqlite3_errmsg(db))
        return
    rc = mojo_sqlite3_exec(db, "INSERT INTO t VALUES (1, 'a'), (2, 'b')")
    if rc != 0:
        mojo_print(mojo_sqlite3_errmsg(db))
        return
    var rows = mojo_sqlite3_query(db, "SELECT * FROM t ORDER BY id")
    var n = mojo_list_len(rows)
    mojo_print(n)
    mojo_sqlite3_close(db)
