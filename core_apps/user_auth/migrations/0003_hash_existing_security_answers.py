from django.contrib.auth.hashers import identify_hasher, make_password
from django.db import migrations


def hash_answers(apps, schema_editor):
    User = apps.get_model('user_auth', 'User')
    for user in User.objects.using(schema_editor.connection.alias).exclude(security_answer='').iterator():
        try:
            identify_hasher(user.security_answer)
        except ValueError:
            User.objects.using(schema_editor.connection.alias).filter(pk=user.pk).update(
                security_answer=make_password(user.security_answer),
            )


class Migration(migrations.Migration):
    dependencies = [('user_auth', '0002_remove_user_otp_remove_user_otp_expiry_time_and_more')]
    operations = [migrations.RunPython(hash_answers, migrations.RunPython.noop)]
