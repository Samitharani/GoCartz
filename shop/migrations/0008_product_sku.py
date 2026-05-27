
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0007_userprofile_business_category_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='sku',
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
