import sqlite3
import json

conn = sqlite3.connect('data/open-webui/webui.db')
cursor = conn.cursor()

# Get existing config data
cursor.execute("SELECT id, data FROM config WHERE id=1;")
row = cursor.fetchone()
if row:
    config_id, data_str = row
    data = json.loads(data_str)
    print("Old config data:", data)
    
    # Enable signup
    if 'ui' not in data:
        data['ui'] = {}
    data['ui']['enable_signup'] = True
    
    updated_data_str = json.dumps(data)
    print("New config data:", data)
    
    cursor.execute("UPDATE config SET data=? WHERE id=1;", (updated_data_str,))
    conn.commit()
    print("Update successful!")
else:
    # No row with id=1? Let's check if there are other rows
    cursor.execute("SELECT id, data FROM config;")
    rows = cursor.fetchall()
    print("Found rows:", rows)

conn.close()
