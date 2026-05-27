#!/usr/bin/env python
import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rani_project.settings")
django.setup()

from django.db import connection

cursor = connection.cursor()
try:
    cursor.execute("ALTER TABLE shop_userprofile ADD COLUMN description LONGTEXT;")
    connection.commit()
    print("✓ Added description column")
except Exception as e:
    if "Duplicate column" in str(e):
        print("ℹ description column already exists")
    else:
        print(f"✗ Error: {e}")
finally:
    cursor.close()
