fn main():
    var db = mojo_sqlite3_open(":memory:")
    var rows = mojo_sqlite3_query(db, "SELECT 1")
    mojo_sqlite3_close(db)
