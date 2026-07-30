fn main():
    var db = mojo_sqlite3_open(":memory:")
    if db == 0:
        print("FAIL: could not open database")
        return
    var rc = mojo_sqlite3_exec(db, "CREATE TABLE IF NOT EXISTS t (id INT, name TEXT)")
    if rc != 0:
        print(mojo_sqlite3_errmsg(db))
        mojo_sqlite3_close(db)
        return
    rc = mojo_sqlite3_exec(db, "INSERT INTO t VALUES (1, 'hello'), (2, 'world')")
    if rc != 0:
        print(mojo_sqlite3_errmsg(db))
        mojo_sqlite3_close(db)
        return
    var rows = mojo_sqlite3_query(db, "SELECT * FROM t")
    var n = mojo_list_len(rows)
    print("rows:")
    var i = 1
    while i < n:
        var row = mojo_list_get_str(rows, i)
        var id = mojo_list_get_int(row, 0)
        var name = mojo_list_get_str(row, 1)
        print(id)
        print(name)
        i = i + 1
    mojo_sqlite3_close(db)
