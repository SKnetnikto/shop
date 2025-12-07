import sqlite3
import os

basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
db_path = os.path.join(basedir, 'instance', 'shop.db')

if not os.path.exists(db_path):
    print('Database not found:', db_path)
    raise SystemExit(1)

con = sqlite3.connect(db_path)
cur = con.cursor()

cur.execute("PRAGMA table_info('product')")
cols = [r[1] for r in cur.fetchall()]

to_add = []
if 'tags' not in cols:
    to_add.append("ALTER TABLE product ADD COLUMN tags VARCHAR(200) DEFAULT ''")
if 'brand' not in cols:
    to_add.append("ALTER TABLE product ADD COLUMN brand VARCHAR(80)")
if 'color' not in cols:
    to_add.append("ALTER TABLE product ADD COLUMN color VARCHAR(50)")
if 'sku' not in cols:
    to_add.append("ALTER TABLE product ADD COLUMN sku VARCHAR(64)")
if 'search_text' not in cols:
    to_add.append("ALTER TABLE product ADD COLUMN search_text TEXT")
if 'sizes' not in cols:
    to_add.append("ALTER TABLE product ADD COLUMN sizes VARCHAR(200)")

if not to_add:
    print('All columns already exist.')
else:
    for stmt in to_add:
        print('Executing:', stmt)
        cur.execute(stmt)
    con.commit()
    print('Columns added.')

con.close()
