
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0010_userprofile_vendor_request_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='CommissionSetting',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rate', models.FloatField(default=10.0)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Commission Setting',
                'verbose_name_plural': 'Commission Settings',
            },
        ),
    ]
