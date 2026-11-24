import pytest
from pretix.base.models import Event, LogEntry, Team, User

from pretix_participantlist import logs
from pretix_participantlist.exporters import (
    ALL_KINDS_VALUE,
    CUSTOM_COLUMNS_SETTING,
    CUSTOM_KIND_VALUE,
    AttendeeListCSVExporter,
    AttendeeListPDFExporter,
)
from pretix_participantlist.models import ListConfiguration, OrganizerBranding

pytestmark = pytest.mark.django_db

BASE = "/control/organizer/example/participantlist"


@pytest.fixture
def user():
    return User.objects.create_user("admin@example.org", "secret")


@pytest.fixture
def admin_client(client, organizer, user):
    organizer.enable_plugin("pretix_participantlist")
    organizer.save()
    team = Team.objects.create(
        organizer=organizer, name="Admins", all_organizer_permissions=True
    )
    team.members.add(user)
    client.login(email=user.email, password="secret")
    return client


@pytest.fixture
def kind(organizer):
    return ListConfiguration.objects.create(
        organizer=organizer, name="Kurz", default_fields=[["name"]], is_default=True
    )


def _entries(action):
    return list(LogEntry.objects.filter(action_type=action).order_by("pk"))


def _kind_post(**overrides):
    data = {
        "name": "Lang",
        "columns_text": "name\nemail",
        "sort_text": "name",
        "filename_suffix": "",
    }
    data.update(overrides)
    return data


def test_kind_added_is_logged(admin_client, organizer, user):
    response = admin_client.post(f"{BASE}/kinds/add", _kind_post())
    assert response.status_code == 302

    (entry,) = _entries(logs.KIND_ADDED)
    kind = ListConfiguration.objects.get(name="Lang")
    assert entry.content_object == kind
    assert entry.user == user
    assert entry.organizer == organizer
    assert entry.event is None
    assert entry.parsed_data["name"] == "Lang"
    assert entry.parsed_data["sort_fields"] == ["name"]
    assert entry.parsed_data["is_default"] is True  # first kind becomes default
    assert str(entry.display()) == "The list kind has been created."
    link = str(entry.display_object)
    assert "Lang" in link
    assert f"{BASE}/kinds/{kind.pk}/" in link


def test_kind_changed_logs_only_changed_fields(admin_client, kind):
    response = admin_client.post(
        f"{BASE}/kinds/{kind.pk}/",
        _kind_post(name="Kurz", columns_text="name\r\nemail", sort_text=""),
    )
    assert response.status_code == 302

    (entry,) = _entries(logs.KIND_CHANGED)
    assert entry.content_object == kind
    assert set(entry.parsed_data) == {"default_fields"}
    assert str(entry.display()) == "The list kind has been changed."


def test_kind_saved_unchanged_is_not_logged(admin_client, kind):
    admin_client.post(
        f"{BASE}/kinds/{kind.pk}/",
        _kind_post(name="Kurz", columns_text="name", sort_text=""),
    )
    assert _entries(logs.KIND_CHANGED) == []


def test_kind_deleted_and_automatic_default_are_logged(admin_client, organizer, kind):
    other = ListConfiguration.objects.create(organizer=organizer, name="Lang")

    response = admin_client.post(f"{BASE}/kinds/{kind.pk}/delete")
    assert response.status_code == 302

    (deleted,) = _entries(logs.KIND_DELETED)
    assert deleted.parsed_data == {"id": kind.pk, "name": "Kurz"}
    assert str(deleted.display()) == 'The list kind "Kurz" has been deleted.'
    assert "(deleted)" in str(deleted.display_object)

    (promoted,) = _entries(logs.KIND_DEFAULT)
    assert promoted.content_object == other
    assert promoted.parsed_data["automatic"] is True
    assert "automatically" in str(promoted.display())


def test_set_default_is_logged(admin_client, organizer, kind):
    other = ListConfiguration.objects.create(organizer=organizer, name="Lang")

    response = admin_client.post(f"{BASE}/kinds/{other.pk}/default")
    assert response.status_code == 302

    (entry,) = _entries(logs.KIND_DEFAULT)
    assert entry.content_object == other
    assert entry.parsed_data == {
        "automatic": False,
        "previous": {"id": kind.pk, "name": "Kurz"},
    }
    assert str(entry.display()) == (
        "The list kind has been made the default list kind."
    )

    # Making the current default the default again changes nothing.
    admin_client.post(f"{BASE}/kinds/{other.pk}/default")
    assert len(_entries(logs.KIND_DEFAULT)) == 1


def test_set_default_rejects_get(admin_client, organizer, kind):
    other = ListConfiguration.objects.create(organizer=organizer, name="Lang")

    response = admin_client.get(f"{BASE}/kinds/{other.pk}/default")

    assert response.status_code == 405
    other.refresh_from_db()
    assert other.is_default is False
    assert _entries(logs.KIND_DEFAULT) == []


def test_branding_change_is_logged(admin_client, organizer, user):
    response = admin_client.post(
        f"{BASE}/branding/",
        {
            "header_text": "JDAV",
            "logo_width_mm": 96,
            "logo_height_mm": 42,
            "filename_prefix": "",
            "birth_date_question": "",
        },
    )
    assert response.status_code == 302

    (entry,) = _entries(logs.BRANDING_CHANGED)
    assert entry.content_object == OrganizerBranding.objects.get(organizer=organizer)
    assert entry.user == user
    assert entry.parsed_data == {"header_text": "JDAV"}
    assert str(entry.display()) == "The participant list branding has been changed."
    assert f"{BASE}/branding/" in str(entry.display_object)


def test_entries_are_shown_in_organizer_log(admin_client, kind):
    admin_client.post(f"{BASE}/kinds/{kind.pk}/delete")

    response = admin_client.get("/control/organizer/example/logs")
    assert response.status_code == 200
    content = response.content.decode()
    assert "The list kind &quot;Kurz&quot; has been deleted." in content


@pytest.mark.parametrize(
    "method,url,data",
    [
        ("post", "/kinds/add", _kind_post()),
        ("post", "/kinds/{kind}/", _kind_post(name="Neu")),
        ("post", "/kinds/{kind}/delete", {}),
        ("post", "/kinds/{kind}/default", {}),
        ("post", "/branding/", {"header_text": "X"}),
    ],
)
def test_no_permission_no_change_and_no_log(
    client, organizer, kind, user, method, url, data
):
    organizer.enable_plugin("pretix_participantlist")
    organizer.save()
    team = Team.objects.create(
        organizer=organizer,
        name="Readers",
        all_organizer_permissions=False,
        limit_organizer_permissions={},
    )
    team.members.add(user)
    client.login(email=user.email, password="secret")
    count = LogEntry.objects.count()

    response = getattr(client, method)(BASE + url.format(kind=kind.pk), data)

    assert response.status_code in (403, 404)
    assert LogEntry.objects.count() == count
    kind.refresh_from_db()
    assert kind.name == "Kurz"


def test_pdf_export_is_logged_with_user(event, position, kind, user):
    exporter = AttendeeListPDFExporter(
        event=event, organizer=event.organizer, permission_holder=user
    )
    exporter.render({"list": str(kind.pk)})

    (entry,) = _entries(logs.EXPORT_PDF)
    assert entry.event == event
    assert entry.user == user
    assert entry.parsed_data["list"] == str(kind.pk)
    assert entry.parsed_data["kinds"] == [{"id": kind.pk, "name": "Kurz"}]
    assert (
        str(entry.display()) == 'The participant list "Kurz" has been exported (PDF).'
    )


def test_pdf_export_of_all_kinds_is_logged(event, position, kind):
    ListConfiguration.objects.create(organizer=event.organizer, name="Lang")
    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    exporter.render({"list": ALL_KINDS_VALUE})

    (entry,) = _entries(logs.EXPORT_PDF)
    assert entry.user is None
    assert len(entry.parsed_data["kinds"]) == 2
    assert str(entry.display()) == (
        "The participant lists of all list kinds have been exported."
    )


def test_custom_list_export_logs_saved_definition_once(event, position, user):
    form_data = {
        "list": CUSTOM_KIND_VALUE,
        "custom_name": "Wanderliste",
        "custom_columns": "name\norder_code",
        "custom_sort": "",
        "custom_save": True,
    }
    exporter = AttendeeListPDFExporter(
        event=event, organizer=event.organizer, permission_holder=user
    )
    exporter.render(form_data)
    exporter.render(form_data)  # unchanged definition: no second entry

    (changed,) = _entries(logs.CUSTOM_LIST_CHANGED)
    assert changed.event == event
    assert changed.user == user
    assert changed.parsed_data[CUSTOM_COLUMNS_SETTING] == "name\norder_code"
    assert "custom participant list" in str(changed.display())

    exports = _entries(logs.EXPORT_PDF)
    assert len(exports) == 2
    assert exports[0].parsed_data["list_name"] == "Wanderliste"
    assert exports[0].parsed_data["custom"]["columns"] == [["name"], ["order_code"]]


def test_export_of_deleted_kind_displays_placeholder(event, position):
    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    exporter.render({"list": "999999"})

    (entry,) = _entries(logs.EXPORT_PDF)
    assert str(entry.display()) == 'The participant list "?" has been exported (PDF).'


def test_csv_export_is_logged_on_organizer(event, position, user):
    exporter = AttendeeListCSVExporter(
        event=Event.objects.filter(pk=event.pk),
        organizer=event.organizer,
        permission_holder=user,
    )
    exporter.render({"_format": "default", "fields": ["name"]})

    (entry,) = _entries(logs.EXPORT_CSV)
    assert entry.event is None
    assert entry.organizer == event.organizer
    assert entry.user == user
    assert entry.parsed_data == {
        "events": [event.slug],
        "fields": ["name"],
        "include_pending": False,
        "format": "default",
    }
    assert str(entry.display()) == (
        "A participant list has been exported (CSV/Excel) for these events: "
        f"{event.slug}."
    )


def test_log_entries_contain_no_attendee_data(event, position, kind):
    AttendeeListPDFExporter(event=event, organizer=event.organizer).render(
        {"list": str(kind.pk)}
    )
    AttendeeListCSVExporter(
        event=Event.objects.filter(pk=event.pk), organizer=event.organizer
    ).render({"_format": "default", "fields": ["name", "email"]})

    for entry in LogEntry.objects.filter(action_type__startswith=logs.PREFIX):
        assert "Jane Doe" not in entry.data
        assert "jane@example.org" not in entry.data
