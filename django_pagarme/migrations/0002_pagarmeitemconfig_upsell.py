# Generated by Django 3.0.4 on 2020-07-22 20:09

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('django_pagarme', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='pagarmeitemconfig',
            name='upsell',
            field=models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='django_pagarme.PagarmeItemConfig'),
        ),
    ]