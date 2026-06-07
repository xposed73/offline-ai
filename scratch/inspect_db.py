import sqlite3
import json
conn = sqlite3.connect('data/open-webui/webui.db')
cursor = conn.cursor()
cursor.execute("SELECT id, name, email, settings, info FROM user WHERE email='admin@gmail.com';")
row = cursor.fetchone()
if row:
    print("User ID:", row[0])
    print("Name:", row[1])
    print("Email:", row[2])
    print("Settings:", row[3])
    print("Info:", row[4])
conn.close()
