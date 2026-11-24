from django.db import migrations


ROLE_PERMISSIONS = {
    "Operatore": {
        "company": {"add_company": "Can add azienda"},
        "assessment": {
            "add_assessment": "Can add assessment",
            "view_assessment": "Can view assessment",
            "publish_assessment": "Pubblica le valutazioni",
            "revise_assessment": "Apri correzioni alle valutazioni pubblicate",
        },
        "revision": {"change_revision": "Can change revision"},
        "catalogversion": {"change_catalogversion": "Can change catalog version"},
    },
    "Cliente": {
        "assessment": {"view_own_assessment": "Consulta le valutazioni pubblicate della propria azienda"},
    },
}


def configure_portal(apps, schema_editor):
    database = schema_editor.connection.alias
    Catalog = apps.get_model("portal", "Catalog")
    MethodVersion = apps.get_model("portal", "MethodVersion")
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    Catalog.objects.using(database).get_or_create(pk=1)
    MethodVersion.objects.using(database).get_or_create(code="gxp-v1")
    for role, model_permissions in ROLE_PERMISSIONS.items():
        group, _ = Group.objects.using(database).get_or_create(name=role)
        for model, codenames in model_permissions.items():
            content_type, _ = ContentType.objects.using(database).get_or_create(app_label="portal", model=model)
            for codename, name in codenames.items():
                permission, _ = Permission.objects.using(database).get_or_create(
                    content_type=content_type, codename=codename, defaults={"name": name}
                )
                group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [("portal", "0001_initial")]
    operations = [migrations.RunPython(configure_portal, migrations.RunPython.noop)]
