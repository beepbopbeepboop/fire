fn main():
    var db = mojo_sqlite3_open(":memory:")
    var rows = mojo_sqlite3_query(db, "SELECT 1 AS x")
    var n = mojo_list_len(rows)
    print(n)
    mojo_sqlite3_close(db)
