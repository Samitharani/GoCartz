#!/usr/bin/env python
import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rani_project.settings")
django.setup()

from django.db import connection

# Add missing columns to shop_userprofile
cursor = connection.cursor()

columns_to_add = [
    ("role", "VARCHAR(10) NOT NULL DEFAULT 'buyer'"),
    ("business_category", "VARCHAR(150) NOT NULL DEFAULT ''"),
    ("description", "LONGTEXT NOT NULL DEFAULT ''"),
    ("gst_number", "VARCHAR(20) NOT NULL DEFAULT ''"),
    ("is_vendor", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("is_vendor_approved", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("vendor_city", "VARCHAR(100) NOT NULL DEFAULT ''"),
    ("vendor_name", "VARCHAR(255) NOT NULL DEFAULT ''"),
]

for col_name, col_type in columns_to_add:
    try:
        sql = f"ALTER TABLE shop_userprofile ADD COLUMN {col_name} {col_type};"
        cursor.execute(sql)
        print(f"✓ Added column {col_name}")
    except Exception as e:
        if "Duplicate column" in str(e):
            print(f"ℹ Column {col_name} already exists")
        else:
            print(f"✗ Error adding {col_name}: {e}")

connection.commit()
cursor.close()
print("\n✅ Database schema updated!")
