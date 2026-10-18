"""One-off: carry data over from pretix-jdavhe-tnliste to pretix-participantlist.

Run once after deploying the new plugin and applying its migrations, with the
Python of the existing pretix installation (same user and config as the pretix
service, so it talks to the production database):

    python migrate_tnliste_to_participantlist.py

Alternatively: python -m pretix shell -c "exec(open('migrate_tnliste_to_participantlist.py').read())"

Safe to run again: organizers that already have data in the new plugin are skipped.
The old tables are only read, never modified or dropped.
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pretix.settings")
django.setup()

from django.db import connection, transaction  # noqa: E402
from django_scopes import scopes_disabled  # noqa: E402
from pretix.base.models import (  # noqa: E402
    Event,
    Event_SettingsStore,
    Organizer,
    ScheduledEventExport,
    ScheduledOrganizerExport,
)

OLD, NEW = "pretix_jdavhe_tnliste", "pretix_participantlist"
OLD_KEY, NEW_KEY = "jdavhe_tnliste_", "participantlist_"
IDENTIFIERS = {
    "jdavhe_tnliste_pdf": "participantlist_pdf",
    "jdavhe_tnliste_csv": "participantlist_csv",
}
COPY = {  # table suffix -> columns to copy (id is left to the new table's sequence)
    "listconfiguration": "organizer_id, name, default_fields, sort_fields, is_default, "
    "is_confidential, filename_suffix",
    "organizerbranding": "organizer_id, logo, header_text, filename_prefix, "
    "logo_width_mm, logo_height_mm, birth_date_question",
}


def run():
    tables = set(connection.introspection.table_names())
    with transaction.atomic(), connection.cursor() as cur:
        for suffix, cols in COPY.items():
            old, new = f"{OLD}_{suffix}", f"{NEW}_{suffix}"
            if old not in tables:
                print(f"{old}: not found, skipped")
                continue
            if new not in tables:
                raise RuntimeError(f"{new} missing - apply the new plugin's migrations first")
            cur.execute(
                f"INSERT INTO {new} ({cols}) SELECT {cols} FROM {old} "
                f"WHERE organizer_id NOT IN (SELECT organizer_id FROM {new})"
            )
            print(f"{suffix}: copied {cur.rowcount} row(s)")

        # activate the new plugin wherever the old one was active
        for model in (Organizer, Event):
            n = 0
            for obj in model.objects.filter(plugins__contains=OLD):
                mods = [m for m in obj.plugins.split(",") if m and m != OLD]
                if NEW not in mods:
                    mods.append(NEW)
                obj.plugins = ",".join(mods)
                obj.save(update_fields=["plugins"])
                n += 1
            print(f"{model.__name__}: plugin switched on {n} object(s)")

        # per-event "custom list" settings
        n = 0
        for row in Event_SettingsStore.objects.filter(key__startswith=OLD_KEY):
            new_key = NEW_KEY + row.key[len(OLD_KEY):]
            if not Event_SettingsStore.objects.filter(object=row.object, key=new_key).exists():
                Event_SettingsStore.objects.create(object=row.object, key=new_key, value=row.value)
                n += 1
        print(f"event settings: copied {n} key(s)")

        # saved export schedules
        for model in (ScheduledEventExport, ScheduledOrganizerExport):
            n = sum(
                model.objects.filter(export_identifier=old).update(export_identifier=new)
                for old, new in IDENTIFIERS.items()
            )
            print(f"{model.__name__}: {n} schedule(s) updated")

    for event in Event.objects.all():
        event.settings.flush()


with scopes_disabled():
    run()
