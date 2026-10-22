from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pretix_participantlist", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="listconfiguration",
            name="include_pending",
            field=models.BooleanField(default=False),
        ),
    ]
