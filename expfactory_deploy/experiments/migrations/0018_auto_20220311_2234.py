# Generated by Django 3.1.7 on 2022-03-11 22:34

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('experiments', '0017_auto_20220311_2201'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='experimentinstance',
            name='exp_commit',
        ),
    ]
