from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("compressor", "0003_alter_pdfjob_compatibility"),
    ]

    operations = [
        migrations.AddField(
            model_name="pdfjob",
            name="mode",
            field=models.CharField(
                choices=[
                    ("compress", "Comprimir"),
                    ("extract_images", "Extraer imágenes"),
                ],
                default="compress",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="pdfjob",
            name="image_count",
            field=models.IntegerField(default=0),
        ),
    ]
