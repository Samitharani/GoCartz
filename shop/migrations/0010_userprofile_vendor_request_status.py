
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0009_order_orderitem'),
    ]

    def update_vendor_request_status(apps, schema_editor):
        UserProfile = apps.get_model('shop', 'UserProfile')
        UserProfile.objects.filter(role='seller', is_vendor=True, is_vendor_approved=True).update(vendor_request_status='approved')

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='vendor_request_status',
            field=models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending', max_length=10),
        ),
        migrations.RunPython(update_vendor_request_status, migrations.RunPython.noop),
    ]
