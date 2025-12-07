import sqlite3
import os

basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
db_path = os.path.join(basedir, 'instance', 'shop.db')

if not os.path.exists(db_path):
    print('Database not found:', db_path)
    raise SystemExit(1)

con = sqlite3.connect(db_path)
cur = con.cursor()

# Read all products
cur.execute("SELECT id, title, description, tags, brand, color, sku, sizes FROM product")
rows = cur.fetchall()
for r in rows:
    pid = r[0]
    parts = [str(x) for x in r[1:] if x]
    search_text = ' '.join(parts)
    cur.execute("UPDATE product SET search_text = ? WHERE id = ?", (search_text, pid))

con.commit()
con.close()
print(f'Updated {len(rows)} products search_text.')
