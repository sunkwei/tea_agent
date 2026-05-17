# -*- coding: utf-8 -*-
import sqlite3, os
from datetime import datetime

db_path = os.path.expanduser("~/.tea_agent/chat_history.db")
c = sqlite3.connect(db_path)

target = "1aa4ceb6-ac8d-4981-a727-2a6ce8878e5a"
r = c.execute("SELECT id, stamp, topic_id FROM conversations WHERE id=?", (target,))
row = r.fetchone()
if row:
    print("ID:", row[0])
    print("stamp:", row[1])
    print("topic_id:", row[2])
else:
    print("NOT FOUND")

print("---")
now_utc = c.execute("SELECT datetime('now')").fetchone()[0]
now_lc = c.execute("SELECT datetime('now','localtime')").fetchone()[0]
print("UTC:      ", now_utc)
print("localtime:", now_lc)
print("Python:   ", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
c.close()
