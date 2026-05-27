#!/usr/bin/env python
import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rani_project.settings")
django.setup()

from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

# Tables already exist, just mark migrations as applied
recorder = MigrationRecorder(connection)

migrations_to_mark = [
    ('shop', '0004_userprofile_address'),
    ('shop', '0005_rename_dob_userprofile_date_of_birth_and_more'),
    ('shop', '0006_remove_userprofile_address_line1_and_more'),
    ('shop', '0007_userprofile_business_category_and_more'),
]

for app, migration_name in migrations_to_mark:
    try:
        # Check if already applied
        record = recorder.migration_qs.filter(app=app, name=migration_name).first()
        if record:
            print(f"✓ {app}.{migration_name} already marked as applied")
        else:
            recorder.record_applied(app, migration_name)
            print(f"✓ Marked {app}.{migration_name} as applied")
    except Exception as e:
        print(f"✗ Error with {migration_name}: {e}")

print("\n✅ Database setup complete!")
