from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('blog', '0003_alter_post_pub_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='post',
            name='is_author_published',
            field=models.BooleanField(
                default=True, verbose_name='Опубликовано автором',
            ),
        ),
    ]
