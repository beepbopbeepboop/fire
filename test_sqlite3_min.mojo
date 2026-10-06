fn main():
    var db = mojo_sqlite3_open(":memory:")
    mojo_sqlite3_close(db)
