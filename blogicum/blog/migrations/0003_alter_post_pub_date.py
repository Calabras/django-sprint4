import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0002_post_image_comment'),
    ]

    operations = [
        migrations.AlterField(
            model_name='post',
            name='pub_date',
            field=models.DateTimeField(
                default=django.utils.timezone.now,
                help_text=(
                    'Если установить дату и время в будущем — '
                    'можно делать отложенные публикации.'
                ),
                verbose_name='Дата и время публикации',
            ),
        ),
    ]
