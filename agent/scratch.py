"""Scratch file for read-only queries against data/cartwheel.db.

Not part of the homework. Do not commit it.
Run from the repository root: uv run python -m agent.scratch
"""

from agent import db

with db.connection() as conn:
    # An order and its owner scope
    # print(db.get_order(conn, 4127))

    # How many products does store 1 have?
    products = db.list_products(conn, store_id=1)
    print("store 1 products:", len(products))
    for product in products:
        print(product)

    # # Raw SQL, read only (conn.execute works because rows are sqlite3.Row)
    # rows = conn.execute(
    #     "SELECT id, title, price_cents FROM products "
    #     "WHERE store_id = 1 ORDER BY price_cents LIMIT 5"
    # ).fetchall()
    # for row in rows:
    #     print(dict(row))
