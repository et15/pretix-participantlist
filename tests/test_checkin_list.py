"""The check-in list for "checked in", chosen on the PDF export page.

It is saved with the event and used by the PDF export, the multi-event CSV
export and the order list.
"""

import datetime
from io import BytesIO

import pypdf
import pytest
from django.utils.timezone import now
from pretix.base.models import (
    Checkin,
    Event,
    LogEntry,
    Order,
    OrderPosition,
    User,
)

from pretix_participantlist import logs
from pretix_participantlist.exporters import (
    CUSTOM_KIND_VALUE,
    AttendeeListCSVExporter,
    AttendeeListPDFExporter,
)
from pretix_participantlist.fields import (
    event_checkin_list,
    events_checkin_list_ids,
)
from pretix_participantlist.settings import CHECKIN_LIST_KEY

pytestmark = pytest.mark.django_db

WHEN = datetime.datetime(2026, 7, 20, 10, tzinfo=datetime.UTC)


def _pdf_text(data):
    reader = pypdf.PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _pdf(event, **kwargs):
    return AttendeeListPDFExporter(event=event, organizer=event.organizer, **kwargs)


def _csv(*events):
    return AttendeeListCSVExporter(
        event=Event.objects.filter(pk__in=[e.pk for e in events]),
        organizer=events[0].organizer,
    )


def _entry(position, checkin_list, **kwargs):
    return Checkin.all.create(
        position=position, list=checkin_list, datetime=WHEN, **kwargs
    )


def _custom_form(checkin_list_value, **extra):
    data = {
        "list": CUSTOM_KIND_VALUE,
        "custom_columns": "name\nchecked_in",
        "custom_save": False,
        "checkin_list": checkin_list_value,
    }
    data.update(extra)
    return data


@pytest.fixture
def user():
    return User.objects.create_user("admin@example.org", "secret")


@pytest.fixture
def lists(event):
    return (
        event.checkin_lists.create(name="Day 1"),
        event.checkin_lists.create(name="Day 2"),
    )


def test_pdf_form_offers_the_event_lists_and_preselects_the_saved_one(event, lists):
    day1, day2 = lists
    field = _pdf(event).export_form_fields["checkin_list"]
    assert list(field.choices) == [
        ("", "All check-in lists"),
        (str(day1.pk), "Day 1"),
        (str(day2.pk), "Day 2"),
    ]
    assert field.initial == ""

    event.settings.set(CHECKIN_LIST_KEY, str(day2.pk))
    assert _pdf(event).export_form_fields["checkin_list"].initial == str(day2.pk)


def test_pdf_export_saves_and_logs_the_checkin_list(event, position, lists, user):
    day1, _day2 = lists
    exporter = _pdf(event, permission_holder=user)

    exporter.render(_custom_form(str(day1.pk)))
    assert event_checkin_list(event) == day1
    (entry,) = LogEntry.objects.filter(action_type=logs.CHECKIN_LIST_CHANGED)
    assert entry.event == event
    assert entry.user == user
    assert entry.parsed_data == {CHECKIN_LIST_KEY: str(day1.pk)}
    assert "check-in list" in str(entry.display())
    (export,) = LogEntry.objects.filter(action_type=logs.EXPORT_PDF)
    assert export.parsed_data["checkin_list"] == str(day1.pk)

    # Unchanged: no second entry. Back to "any list": logged again.
    exporter.render(_custom_form(str(day1.pk)))
    assert LogEntry.objects.filter(action_type=logs.CHECKIN_LIST_CHANGED).count() == 1
    exporter.render(_custom_form(""))
    assert event_checkin_list(event) is None
    assert LogEntry.objects.filter(action_type=logs.CHECKIN_LIST_CHANGED).count() == 2


def test_pdf_export_ignores_unknown_lists(event, position, lists, organizer):
    other_event = Event.objects.create(
        organizer=organizer, name="Other", slug="other", date_from=now()
    )
    foreign = other_event.checkin_lists.create(name="Foreign")
    _pdf(event).render(_custom_form(str(foreign.pk)))
    assert event.settings.get(CHECKIN_LIST_KEY) == ""


def test_pdf_export_without_field_keeps_the_saved_list(event, position, lists):
    """Scheduled exports stored before the field existed use the saved list."""
    day1, _day2 = lists
    event.settings.set(CHECKIN_LIST_KEY, str(day1.pk))
    data = _custom_form("")
    del data["checkin_list"]
    _pdf(event).render(data)
    assert event_checkin_list(event) == day1
    assert not LogEntry.objects.filter(action_type=logs.CHECKIN_LIST_CHANGED).exists()


def test_pdf_checked_in_column_uses_the_chosen_list(event, position, lists):
    day1, day2 = lists
    _entry(position, day2)

    def checked_in(value):
        _name, _type, data = _pdf(event).render(_custom_form(value))
        text = _pdf_text(data)
        assert "Jane Doe" in text
        return "Yes" in text

    assert checked_in("") is True
    assert checked_in(str(day2.pk)) is True
    assert checked_in(str(day1.pk)) is False


def test_deleted_list_falls_back_to_any_list(event, lists):
    day1, _day2 = lists
    event.settings.set(CHECKIN_LIST_KEY, str(day1.pk))
    assert event_checkin_list(event) == day1
    assert events_checkin_list_ids([event]) == {event.pk: day1.pk}
    day1.delete()
    event.settings.flush()
    assert event_checkin_list(event) is None
    assert events_checkin_list_ids([event]) == {event.pk: None}


def _second_event(organizer, item):
    other = Event.objects.create(
        organizer=organizer, name="Zweitcamp", slug="zweitcamp", date_from=now()
    )
    other_item = other.items.create(
        name="Ticket", default_price=10, admission=True, personalized=True
    )
    order = Order.objects.create(
        event=other,
        status=Order.STATUS_PAID,
        email="max@example.org",
        datetime=now(),
        expires=now(),
        code="XYZ34",
        total=10,
        sales_channel=organizer.sales_channels.get(identifier="web"),
    )
    position = OrderPosition.objects.create(
        order=order,
        item=other_item,
        price=10,
        attendee_name_parts={"_legacy": "Max Muster"},
    )
    return other, position


def test_csv_uses_each_events_saved_list(event, item, position, lists, organizer):
    day1, day2 = lists
    other, other_position = _second_event(organizer, item)
    other_list = other.checkin_lists.create(name="Gate")
    _entry(position, day2)
    _entry(other_position, other_list)
    event.settings.set(CHECKIN_LIST_KEY, str(day1.pk))  # Jane only entered on Day 2
    # The other event keeps "any list": Max counts as checked in.

    rows = list(
        _csv(event, other).iterate_list(
            {"fields": ["name", "checked_in", "last_checkin"]}
        )
    )
    assert [r[:2] for r in rows[1:]] == [["Jane Doe", "No"], ["Max Muster", "Yes"]]
    assert rows[1][2] == ""
    assert rows[2][2] != ""

    only = list(
        _csv(event, other).iterate_list({"fields": ["name"], "checked_in_only": True})
    )
    assert only[1:] == [["Max Muster"]]

    event.settings.set(CHECKIN_LIST_KEY, str(day2.pk))
    only = list(
        _csv(event, other).iterate_list({"fields": ["name"], "checked_in_only": True})
    )
    assert only[1:] == [["Jane Doe"], ["Max Muster"]]


def test_copied_event_gets_its_own_checkin_list_and_questions(event, lists, organizer):
    _day1, day2 = lists
    question = event.questions.create(question="Sektion", identifier="sektion")
    event.settings.set(CHECKIN_LIST_KEY, str(day2.pk))
    event.settings.set("participantlist_orders_question_columns", [str(question.pk)])
    organizer.enable_plugin("pretix_participantlist")
    organizer.save()

    copy = Event.objects.create(
        organizer=organizer, name="Copy", slug="copy", date_from=now()
    )
    copy.copy_data_from(event)
    copy = Event.objects.get(pk=copy.pk)

    copied_list = event_checkin_list(copy)
    assert copied_list.event == copy
    assert copied_list.name == "Day 2"
    (copied_question,) = copy.questions.all()
    assert copy.settings.get(
        "participantlist_orders_question_columns", as_type=list
    ) == [str(copied_question.pk)]
