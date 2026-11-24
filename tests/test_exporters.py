import base64
import datetime
import zipfile
from io import BytesIO
from types import SimpleNamespace

import pypdf
import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils.timezone import now
from pretix.base.models import (
    Event,
    Item,
    Order,
    OrderPosition,
    Question,
    QuestionAnswer,
)
from reportlab.lib.units import mm

from pretix_participantlist.exporters import (
    ALL_KINDS_VALUE,
    CUSTOM_COLUMNS_SETTING,
    CUSTOM_INCLUDE_PENDING_SETTING,
    CUSTOM_KIND_VALUE,
    CUSTOM_NAME_SETTING,
    CUSTOM_SORT_SETTING,
    AttendeeListCSVExporter,
    AttendeeListPDFExporter,
)
from pretix_participantlist.fields import extract_static_field
from pretix_participantlist.models import (
    ListConfiguration,
    OrganizerBranding,
)

pytestmark = pytest.mark.django_db


def _pdf_text(data):
    reader = pypdf.PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# A minimal valid 1x1 transparent PNG, used to exercise the branding logo path.
ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGNgAAIAAAUAAen63NgA"
    "AAAASUVORK5CYII="
)


def test_pdf_exporter_single_kind(event, position):
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=["name", "ticket", "signing"],
        is_default=True,
    )
    branding = OrganizerBranding.objects.create(
        organizer=event.organizer, header_text="Example Org"
    )
    branding.logo.save("logo.png", ContentFile(ONE_PIXEL_PNG), save=True)

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, content_type, data = exporter.render({"list": str(kind.pk)})

    assert content_type == "application/pdf"
    assert data
    assert len(data) > 100


def test_pdf_exporter_filename_defaults_to_tn_liste_prefix_without_suffix(
    event, position
):
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=["name"],
        is_default=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    filename, _content_type, _data = exporter.render({"list": str(kind.pk)})

    today = now().astimezone(event.timezone).strftime("%Y-%m-%d")
    assert filename == f"Participant-List_{event.slug}_{today}.pdf"


def test_pdf_exporter_filename_uses_custom_prefix_and_kind_suffix(event, position):
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=["name"],
        is_default=True,
        filename_suffix="Warteliste",
    )
    OrganizerBranding.objects.create(
        organizer=event.organizer, filename_prefix="Anwesenheit"
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    filename, _content_type, _data = exporter.render({"list": str(kind.pk)})

    today = now().astimezone(event.timezone).strftime("%Y-%m-%d")
    assert filename == f"Anwesenheit_{event.slug}_{today}_Warteliste.pdf"


def test_pdf_exporter_all_kinds_single_kind_stays_a_pdf(event, position):
    ListConfiguration.objects.create(
        organizer=event.organizer, name="A", default_fields=["name"], is_default=True
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    filename, content_type, data = exporter.render({"list": ALL_KINDS_VALUE})

    assert content_type == "application/pdf"
    assert filename.endswith(".pdf")
    assert data


def test_pdf_exporter_all_kinds_multiple_kinds_produces_archive(event, position):
    ListConfiguration.objects.create(
        organizer=event.organizer, name="A", default_fields=["name"], is_default=True
    )
    ListConfiguration.objects.create(
        organizer=event.organizer, name="B", default_fields=["ticket"]
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    filename, content_type, data = exporter.render({"list": ALL_KINDS_VALUE})

    assert content_type == "application/zip"
    assert filename.endswith(".zip")
    today = now().astimezone(event.timezone).strftime("%Y-%m-%d")
    assert filename == f"Participant-List_{event.slug}_{today}.zip"

    with zipfile.ZipFile(BytesIO(data)) as zf:
        names = sorted(zf.namelist())
        assert names == [
            f"Participant-List_{event.slug}_{today}_a.pdf",
            f"Participant-List_{event.slug}_{today}_b.pdf",
        ]
        for name in names:
            assert zf.read(name).startswith(b"%PDF")


def test_export_form_has_custom_list_choice_and_no_checkbox_fields(event):
    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    form_fields = exporter.export_form_fields

    assert list(form_fields) == [
        "list",
        "custom_name",
        "custom_columns",
        "custom_sort",
        "custom_include_pending",
        "custom_save",
    ]
    assert CUSTOM_KIND_VALUE in dict(form_fields["list"].choices)


def test_export_form_validates_custom_list_specs(event):
    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    form_fields = exporter.export_form_fields

    with pytest.raises(ValidationError):
        form_fields["custom_columns"].clean("name\nnope")
    with pytest.raises(ValidationError):
        form_fields["custom_sort"].clean("signing")
    assert form_fields["custom_columns"].clean("name\nemail+ticket")


def test_custom_list_uses_columns_and_sort_and_is_saved_with_event(
    event, item, position
):
    _make_position(event, item, "ZZZ99", "Zoe Ali")
    _make_position(event, item, "AAA11", "Alice Bauer")

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    filename, content_type, data = exporter.render(
        {
            "list": CUSTOM_KIND_VALUE,
            "custom_name": "Wanderliste",
            "custom_columns": "name\norder_code",
            "custom_sort": "-name",
        }
    )

    assert content_type == "application/pdf"
    today = now().astimezone(event.timezone).strftime("%Y-%m-%d")
    assert filename == f"Participant-List_{event.slug}_{today}.pdf"
    text = _pdf_text(data)
    assert "Wanderliste" in text
    assert text.index("Zoe Ali") < text.index("Jane Doe") < text.index("Alice Bauer")
    assert "ABC12" in text

    event.settings.flush()
    assert event.settings.get(CUSTOM_NAME_SETTING) == "Wanderliste"
    assert event.settings.get(CUSTOM_COLUMNS_SETTING) == "name\norder_code"
    assert event.settings.get(CUSTOM_SORT_SETTING) == "-name"

    fields = AttendeeListPDFExporter(
        event=event, organizer=event.organizer
    ).export_form_fields
    assert fields["custom_name"].initial == "Wanderliste"
    assert fields["custom_columns"].initial == "name\norder_code"
    assert fields["custom_sort"].initial == "-name"


def test_custom_list_with_question_column(event, position):
    question = Question.objects.create(
        event=event,
        question="Vegetarian?",
        type=Question.TYPE_BOOLEAN,
        identifier="vegetarian",
    )
    QuestionAnswer.objects.create(
        orderposition=position, question=question, answer="True"
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, _content_type, data = exporter.render(
        {
            "list": CUSTOM_KIND_VALUE,
            "custom_columns": "name\nquestion:vegetarian=Veggie",
            "custom_sort": "",
        }
    )

    text = _pdf_text(data)
    assert "Veggie" in text
    assert "True" not in text


def test_custom_list_column_title_replaces_field_names_in_header(event, position):
    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, _content_type, data = exporter.render(
        {
            "list": CUSTOM_KIND_VALUE,
            "custom_columns": "name=Teilnehmende\norder_code",
            "custom_sort": "",
        }
    )

    text = _pdf_text(data)
    assert "Teilnehmende" in text
    assert "Jane Doe" in text


def test_custom_list_without_columns_falls_back_to_name_and_ticket(event, position):
    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, _content_type, data = exporter.render(
        {"list": CUSTOM_KIND_VALUE, "custom_columns": "", "custom_sort": ""}
    )

    text = _pdf_text(data)
    assert "Jane Doe" in text
    assert "Custom list" in text  # default title when none is given


def test_kind_defaults_path_respects_stored_column_order(event, position):
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=["signing", "name", "ticket"],
        is_default=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    groups = exporter._resolve_groups(kind)

    assert groups == [
        [("static", "signing")],
        [("static", "name")],
        [("static", "ticket")],
    ]


def test_kind_defaults_path_supports_merged_columns(event, position):
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=[["email", "ticket"], "name"],
        is_default=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    groups = exporter._resolve_groups(kind)

    assert groups == [
        [("static", "email"), ("static", "ticket")],
        [("static", "name")],
    ]


def test_column_widths_uses_max_member_weight_for_groups(event, position):
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=[["email", "order_code"], "signing"],
        is_default=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    groups = exporter._resolve_groups(kind)
    doc = SimpleNamespace(width=500)
    widths = exporter._column_widths(doc, groups)

    assert len(widths) == 2
    assert widths[1] == pytest.approx(70 * mm)  # fixed signing width
    assert widths[0] == pytest.approx(doc.width - widths[1])
    assert all(w > 0 for w in widths)


def test_column_lines_renders_index_from_given_number(event, position):
    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)

    lines = exporter._column_lines(position, [("static", "index")], {}, 5)

    assert lines == ["5"]


def test_column_label_blank_for_index(event):
    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)

    assert exporter._column_label("static", "index") == ""


def test_column_label_unchanged_for_other_static_fields(event):
    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)

    assert exporter._column_label("static", "name") == "Name"


def test_pdf_exporter_renders_merged_column_values_stacked(event, position):
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=[["email", "order_code"]],
        is_default=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, _content_type, data = exporter.render({"list": str(kind.pk)})

    text = _pdf_text(data)
    assert "jane@example.org" in text
    assert "ABC12" in text


def test_pdf_exporter_uses_column_title(event, position):
    Question.objects.create(
        event=event,
        question="Do you have any allergies that we should know about?",
        type=Question.TYPE_TEXT,
        identifier="allergies",
    )
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=[{"tokens": ["question:allergies"], "label": "Allergien"}],
        is_default=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, _content_type, data = exporter.render({"list": str(kind.pk)})

    text = _pdf_text(data)
    assert "Allergien" in text
    assert "Do you have any allergies" not in text


def test_pdf_exporter_renders_boolean_answers_as_yes_no(event, position):
    question = Question.objects.create(
        event=event,
        question="Vegetarian?",
        type=Question.TYPE_BOOLEAN,
        identifier="vegetarian",
    )
    QuestionAnswer.objects.create(
        orderposition=position, question=question, answer="True"
    )
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=["name", "question:vegetarian"],
        is_default=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, _content_type, data = exporter.render({"list": str(kind.pk)})

    text = _pdf_text(data)
    assert "True" not in text
    assert "Yes" in text or "Ja" in text


def test_pdf_exporter_confidential_notice_and_page_header(event, position):
    position.street = "Hauptstr. 1"
    position.zipcode = "12345"
    position.city = "Musterstadt"
    position.save()

    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Vertrauliche Liste",
        default_fields=["name", "address"],
        is_default=True,
        is_confidential=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, _content_type, data = exporter.render({"list": str(kind.pk)})

    text = _pdf_text(data)
    assert "confidential" in text.lower()
    assert "do not distribute" in text.lower()
    assert "Hauptstr. 1" in text
    assert "12345 Musterstadt" in text
    assert str(event.name) in text
    assert settings.PRETIX_INSTANCE_NAME not in text


def test_pdf_exporter_shows_event_name_alongside_custom_branding_text(event, position):
    OrganizerBranding.objects.create(
        organizer=event.organizer, header_text="Custom Brand Name"
    )
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurzliste",
        default_fields=["name"],
        is_default=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, _content_type, data = exporter.render({"list": str(kind.pk)})

    text = _pdf_text(data)
    assert str(event.name) in text
    assert "Custom Brand Name" in text
    assert "Kurzliste" in text


def test_pdf_exporter_archive_entries_each_show_their_own_kind_name(event, position):
    ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kind A",
        default_fields=["name"],
        is_default=True,
    )
    ListConfiguration.objects.create(
        organizer=event.organizer, name="Kind B", default_fields=["name"]
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, _content_type, data = exporter.render({"list": ALL_KINDS_VALUE})
    today = now().astimezone(event.timezone).strftime("%Y-%m-%d")

    with zipfile.ZipFile(BytesIO(data)) as zf:
        text_a = _pdf_text(zf.read(f"Participant-List_{event.slug}_{today}_kind-a.pdf"))
        text_b = _pdf_text(zf.read(f"Participant-List_{event.slug}_{today}_kind-b.pdf"))

    assert "Kind A" in text_a
    assert "Kind B" not in text_a
    assert "Kind B" in text_b
    assert "Kind A" not in text_b


def test_pdf_exporter_non_confidential_kind_has_no_notice(event, position):
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Öffentliche Liste",
        default_fields=["name"],
        is_default=True,
        is_confidential=False,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, _content_type, data = exporter.render({"list": str(kind.pk)})

    assert "confidential" not in _pdf_text(data).lower()


def _make_position(event, item, code, name):
    order = Order.objects.create(
        event=event,
        status=Order.STATUS_PAID,
        email=f"{code.lower()}@example.org",
        datetime=now(),
        expires=now(),
        code=code,
        total=10,
        sales_channel=event.organizer.sales_channels.get(identifier="web"),
    )
    return OrderPosition.objects.create(
        order=order,
        item=item,
        price=10,
        attendee_name_parts={"_legacy": name},
    )


def test_sorted_positions_orders_by_configured_field(event, item, position):
    zoe = _make_position(event, item, "ZZZ99", "Zoe Ali")
    alice = _make_position(event, item, "AAA11", "Alice Bauer")
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=["name"],
        sort_fields=["name"],
        is_default=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    ordered = exporter._sorted_positions(kind)

    assert [p.pk for p in ordered] == [alice.pk, position.pk, zoe.pk]


def test_sorted_positions_supports_descending_order(event, item, position):
    zoe = _make_position(event, item, "ZZZ99", "Zoe Ali")
    alice = _make_position(event, item, "AAA11", "Alice Bauer")
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=["name"],
        sort_fields=["-name"],
        is_default=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    ordered = exporter._sorted_positions(kind)

    assert [p.pk for p in ordered] == [zoe.pk, position.pk, alice.pk]


def test_sorted_positions_supports_mixed_direction_multi_field_sort(event, item):
    # Primary key ("company", ascending) groups attendees by section; the
    # secondary key ("name", descending) breaks ties within a section.
    a_zoe = _make_position(event, item, "SEC1A", "Zoe Ali")
    a_amy = _make_position(event, item, "SEC1B", "Amy Ali")
    b_bob = _make_position(event, item, "SEC2A", "Bob Fischer")
    for position, company in [(a_zoe, "A"), (a_amy, "A"), (b_bob, "B")]:
        position.company = company
        position.save(update_fields=["company"])
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=["name"],
        sort_fields=["company", "-name"],
        is_default=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    ordered = exporter._sorted_positions(kind)

    assert [p.pk for p in ordered] == [a_zoe.pk, a_amy.pk, b_bob.pk]


def test_sorted_positions_without_sort_fields_keeps_query_order(event, item, position):
    zoe = _make_position(event, item, "ZZZ99", "Zoe Ali")
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=["name"],
        is_default=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    ordered = exporter._sorted_positions(kind)

    assert [p.pk for p in ordered] == [position.pk, zoe.pk]


def test_pdf_exporter_renders_rows_in_configured_sort_order(event, item, position):
    _make_position(event, item, "ZZZ99", "Zoe Ali")
    _make_position(event, item, "AAA11", "Alice Bauer")
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=["name"],
        sort_fields=["name"],
        is_default=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, _content_type, data = exporter.render({"list": str(kind.pk)})

    text = _pdf_text(data)
    assert text.index("Alice Bauer") < text.index("Jane Doe") < text.index("Zoe Ali")


def test_csv_exporter_iterate_list(event, position):
    exporter = AttendeeListCSVExporter(
        event=Event.objects.filter(pk=event.pk), organizer=event.organizer
    )
    rows = list(exporter.iterate_list({"fields": ["name", "ticket"]}))

    assert rows[0] == ["Name", "Ticket type"]
    assert len(rows) == 2
    assert rows[1][0] == "Jane Doe"


def test_csv_exporter_iterate_list_numbers_rows(event, item, position):
    _make_position(event, item, "ZZZ99", "Zoe Ali")
    exporter = AttendeeListCSVExporter(
        event=Event.objects.filter(pk=event.pk), organizer=event.organizer
    )
    rows = list(exporter.iterate_list({"fields": ["index", "name"]}))

    assert rows[0] == ["index", "Name"]
    assert rows[1:] == [[1, "Jane Doe"], [2, "Zoe Ali"]]


def test_csv_exporter_iterate_list_age(event, position):
    event.date_from = datetime.datetime(2026, 7, 20, 12, tzinfo=event.timezone)
    event.save()
    question = Question.objects.create(
        event=event,
        question="Geburtsdatum",
        type=Question.TYPE_DATE,
        identifier="geburtsdatum",
    )
    position.answers.create(question=question, answer="2012-08-01")
    OrganizerBranding.objects.create(
        organizer=event.organizer, birth_date_question="geburtsdatum"
    )
    exporter = AttendeeListCSVExporter(
        event=Event.objects.filter(pk=event.pk), organizer=event.organizer
    )
    rows = list(exporter.iterate_list({"fields": ["name", "age"]}))

    assert rows[0] == ["Name", "Age"]
    assert rows[1] == ["Jane Doe", 13]


def _second_event(event, slug="camp2"):
    other = Event.objects.create(
        organizer=event.organizer,
        name="Second camp",
        slug=slug,
        date_from=now() + datetime.timedelta(days=30),
        live=True,
    )
    return other, Item.objects.create(
        event=other, name="Ticket", default_price=10, admission=True, personalized=True
    )


def test_csv_exporter_offers_questions_of_all_events(event, position):
    other, _item = _second_event(event)
    Question.objects.create(
        event=event,
        question="Section?",
        type=Question.TYPE_STRING,
        identifier="section",
    )
    # same identifier on another event is still a single choice
    Question.objects.create(
        event=other,
        question="Section?",
        type=Question.TYPE_STRING,
        identifier="section",
    )
    Question.objects.create(
        event=other, question="Diet", type=Question.TYPE_STRING, identifier="diet"
    )
    exporter = AttendeeListCSVExporter(
        event=Event.objects.filter(organizer=event.organizer),
        organizer=event.organizer,
    )

    choices = dict(exporter.additional_form_fields["fields"].choices)

    assert choices["name"] == "Name"
    assert choices["question:section"] == "Section?"
    assert choices["question:diet"] == "Diet"
    assert "signing" not in choices
    assert len([k for k in choices if k.startswith("question:")]) == 2


def test_csv_exporter_iterate_list_questions(event, item, position):
    other, other_item = _second_event(event)
    q1 = Question.objects.create(
        event=event,
        question="Section?",
        type=Question.TYPE_STRING,
        identifier="section",
    )
    q2 = Question.objects.create(
        event=other,
        question="Section?",
        type=Question.TYPE_STRING,
        identifier="section",
    )
    position.answers.create(question=q1, answer="Wiesbaden")
    other_position = _make_position(other, other_item, "OTH01", "Max Mustermann")
    other_position.answers.create(question=q2, answer="Kassel")
    exporter = AttendeeListCSVExporter(
        event=Event.objects.filter(organizer=event.organizer),
        organizer=event.organizer,
    )

    rows = list(exporter.iterate_list({"fields": ["name", "question:section"]}))

    assert rows == [
        ["Name", "Section?"],
        ["Jane Doe", "Wiesbaden"],
        ["Max Mustermann", "Kassel"],
    ]


def test_csv_exporter_iterate_list_question_without_answer_is_empty(event, position):
    Question.objects.create(
        event=event,
        question="Section?",
        type=Question.TYPE_STRING,
        identifier="section",
    )
    exporter = AttendeeListCSVExporter(
        event=Event.objects.filter(pk=event.pk), organizer=event.organizer
    )

    rows = list(exporter.iterate_list({"fields": ["name", "question:section"]}))

    assert rows[1] == ["Jane Doe", ""]


def _csv_exporter(event):
    return AttendeeListCSVExporter(
        event=Event.objects.filter(pk=event.pk), organizer=event.organizer
    )


def _checkin(position, checkin_list, when, **kwargs):
    from pretix.base.models import Checkin

    return Checkin.objects.create(
        position=position, list=checkin_list, datetime=when, **kwargs
    )


def test_csv_exporter_offers_checkin_fields(event, position):
    choices = dict(_csv_exporter(event).additional_form_fields["fields"].choices)

    assert choices["checked_in"] == "Checked in"
    assert choices["last_checkin"] == "Last check-in"


def test_csv_exporter_iterate_list_checkin(event, item, position):
    checkin_list = event.checkin_lists.create(name="Main", all_products=True)
    _make_position(event, item, "WAIT1", "Waiting Wanda")
    failed = _make_position(event, item, "FAIL1", "Failed Fred")
    early = datetime.datetime(2026, 7, 20, 8, 0, tzinfo=datetime.UTC)
    late = datetime.datetime(2026, 7, 20, 14, 30, tzinfo=datetime.UTC)
    _checkin(position, checkin_list, early)
    _checkin(position, checkin_list, late)
    _checkin(position, checkin_list, late + datetime.timedelta(hours=2), type="exit")
    _checkin(failed, checkin_list, late, successful=False, error_reason="unpaid")

    rows = list(
        _csv_exporter(event).iterate_list(
            {"fields": ["name", "checked_in", "last_checkin"]}
        )
    )

    tz = event.timezone
    assert rows[0] == ["Name", "Checked in", "Last check-in"]
    assert rows[1:] == [
        ["Jane Doe", "Yes", late.astimezone(tz).strftime("%Y-%m-%d %H:%M")],
        ["Failed Fred", "No", ""],
        ["Waiting Wanda", "No", ""],
    ]


def test_csv_exporter_offers_checked_in_only_option(event, position):
    field = _csv_exporter(event).additional_form_fields["checked_in_only"]

    assert field.label == "Checked-in participants only"
    assert field.initial is False


def test_csv_exporter_can_list_checked_in_participants_only(event, item, position):
    checkin_list = event.checkin_lists.create(name="Main", all_products=True)
    _make_position(event, item, "WAIT1", "Waiting Wanda")
    failed = _make_position(event, item, "FAIL1", "Failed Fred")
    left = _make_position(event, item, "LEFT1", "Left Lena")
    exit_only = _make_position(event, item, "EXIT1", "Exit Emil")
    when = datetime.datetime(2026, 7, 20, 8, 0, tzinfo=datetime.UTC)
    _checkin(position, checkin_list, when)
    _checkin(position, checkin_list, when + datetime.timedelta(hours=1))
    _checkin(left, checkin_list, when)
    _checkin(left, checkin_list, when + datetime.timedelta(hours=2), type="exit")
    _checkin(exit_only, checkin_list, when, type="exit")
    _checkin(failed, checkin_list, when, successful=False, error_reason="unpaid")

    everyone = list(_csv_exporter(event).iterate_list({"fields": ["name"]}))
    checked_in = list(
        _csv_exporter(event).iterate_list(
            {"fields": ["index", "name"], "checked_in_only": True}
        )
    )

    assert len(everyone) == 6
    # Several entries still give one row; rows are numbered after filtering.
    assert checked_in == [["index", "Name"], [1, "Jane Doe"], [2, "Left Lena"]]


def test_csv_exporter_checked_in_only_combines_with_include_pending(
    event, item, position
):
    checkin_list = event.checkin_lists.create(name="Main", all_products=True)
    pending = _make_pending_position(event, item, "PEND1", "Pending Pia")
    _checkin(pending, checkin_list, datetime.datetime(2026, 7, 20, tzinfo=datetime.UTC))

    paid_only = list(
        _csv_exporter(event).iterate_list({"fields": ["name"], "checked_in_only": True})
    )
    with_pending = list(
        _csv_exporter(event).iterate_list(
            {"fields": ["name"], "checked_in_only": True, "include_pending": True}
        )
    )

    assert paid_only[1:] == []
    assert with_pending[1:] == [["Pending Pia"]]


def test_csv_exporter_checkin_fields_not_loaded_when_unused(
    event, position, django_assert_num_queries
):
    exporter = _csv_exporter(event)
    with django_assert_num_queries(4):
        list(exporter.iterate_list({"fields": ["name"]}))
    exporter = _csv_exporter(event)
    with django_assert_num_queries(5):
        list(exporter.iterate_list({"fields": ["name", "checked_in"]}))


def test_sorted_positions_orders_age_numerically(event, item, position):
    event.date_from = datetime.datetime(2026, 7, 20, 12, tzinfo=event.timezone)
    event.save()
    question = Question.objects.create(
        event=event,
        question="Geburtsdatum",
        type=Question.TYPE_DATE,
        identifier="geburtsdatum",
    )
    ten = _make_position(event, item, "TEN10", "Ten Kid")
    position.answers.create(question=question, answer="2017-01-01")  # 9
    ten.answers.create(question=question, answer="2016-01-01")  # 10
    OrganizerBranding.objects.create(
        organizer=event.organizer, birth_date_question="geburtsdatum"
    )
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=["name", "age"],
        sort_fields=["age"],
        is_default=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    ordered = exporter._sorted_positions(kind)

    assert [p.pk for p in ordered] == [position.pk, ten.pk]


def test_group_header_title_supports_literal_line_break(event):
    from pretix_participantlist.fields import ColumnGroup

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    group = ColumnGroup([("static", "email")], label="Kontakt\\n<Eltern>")
    assert exporter._group_header(group) == "Kontakt<br/>&lt;Eltern&gt;"


def _make_pending_position(event, item, code, name):
    position = _make_position(event, item, code, name)
    position.order.status = Order.STATUS_PENDING
    position.order.save(update_fields=["status"])
    return position


def test_pdf_exporter_leaves_out_pending_payments_by_default(event, item, position):
    _make_pending_position(event, item, "PEND1", "Pending Pia")
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=["name"],
        is_default=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, _content_type, data = exporter.render({"list": str(kind.pk)})

    text = _pdf_text(data)
    assert "Jane Doe" in text
    assert "Pending Pia" not in text


def test_pdf_exporter_kind_can_include_pending_payments(event, item, position):
    _make_pending_position(event, item, "PEND1", "Pending Pia")
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=["name"],
        is_default=True,
        include_pending=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, _content_type, data = exporter.render({"list": str(kind.pk)})

    text = _pdf_text(data)
    assert "Jane Doe" in text
    assert "Pending Pia" in text


def test_pdf_exporter_archive_applies_each_kinds_pending_setting(event, item, position):
    _make_pending_position(event, item, "PEND1", "Pending Pia")
    ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Paid only",
        default_fields=["name"],
        is_default=True,
    )
    ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Everyone",
        default_fields=["name"],
        include_pending=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, _content_type, data = exporter.render({"list": ALL_KINDS_VALUE})
    today = now().astimezone(event.timezone).strftime("%Y-%m-%d")

    with zipfile.ZipFile(BytesIO(data)) as zf:
        paid_only = _pdf_text(
            zf.read(f"Participant-List_{event.slug}_{today}_paid-only.pdf")
        )
        everyone = _pdf_text(
            zf.read(f"Participant-List_{event.slug}_{today}_everyone.pdf")
        )

    assert "Pending Pia" not in paid_only
    assert "Pending Pia" in everyone


def test_custom_list_can_include_pending_payments_and_remembers_choice(
    event, item, position
):
    _make_pending_position(event, item, "PEND1", "Pending Pia")
    custom = {"list": CUSTOM_KIND_VALUE, "custom_columns": "name", "custom_sort": ""}

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, _content_type, data = exporter.render(custom)
    assert "Pending Pia" not in _pdf_text(data)

    _filename, _content_type, data = exporter.render(
        {**custom, "custom_include_pending": True}
    )
    text = _pdf_text(data)
    assert "Jane Doe" in text
    assert "Pending Pia" in text

    event.settings.flush()
    assert event.settings.get(CUSTOM_INCLUDE_PENDING_SETTING, as_type=bool) is True
    fields = AttendeeListPDFExporter(
        event=event, organizer=event.organizer
    ).export_form_fields
    assert fields["custom_include_pending"].initial is True


def test_csv_exporter_can_include_pending_payments(event, item, position):
    _make_pending_position(event, item, "PEND1", "Pending Pia")

    paid_only = list(_csv_exporter(event).iterate_list({"fields": ["name"]}))
    everyone = list(
        _csv_exporter(event).iterate_list({"fields": ["name"], "include_pending": True})
    )

    assert paid_only[1:] == [["Jane Doe"]]
    assert everyone[1:] == [["Jane Doe"], ["Pending Pia"]]


def test_pdf_exporter_checked_in_column(event, item, position):
    checkin_list = event.checkin_lists.create(name="Main", all_products=True)
    _make_position(event, item, "WAIT1", "Waiting Wanda")
    _checkin(position, checkin_list, now())
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=["name", "status", "checked_in"],
        sort_fields=["-checked_in"],
        is_default=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, _content_type, data = exporter.render({"list": str(kind.pk)})

    text = _pdf_text(data)
    table = text[text.index("Name\nOrder status") :].splitlines()
    # Sorted by "checked in", descending: "Yes" before "No".
    assert table == [
        "Name",
        "Order status",
        "Checked in",
        "Jane Doe",
        "paid",
        "Yes",
        "Waiting Wanda",
        "paid",
        "No",
    ]


@pytest.mark.parametrize("language", ["en", "de"])
def test_sorting_by_checked_in_does_not_depend_on_language(
    event, item, position, language
):
    from django.utils import translation

    checkin_list = event.checkin_lists.create(name="Main", all_products=True)
    waiting = _make_position(event, item, "WAIT1", "Waiting Wanda")
    _checkin(position, checkin_list, now())
    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)

    def sorted_by(sort_field):
        kind = ListConfiguration(
            organizer=event.organizer,
            default_fields=["name", "checked_in"],
            sort_fields=[sort_field],
        )
        return [p.pk for p in exporter._sorted_positions(kind)]

    with translation.override(language):
        # The labels differ ("Yes"/"No" vs. "Ja"/"Nein") ...
        assert (
            extract_static_field(position, "checked_in")
            == {
                "en": "Yes",
                "de": "Ja",
            }[language]
        )
        # ... the order doesn't: not checked in first when ascending.
        assert sorted_by("checked_in") == [waiting.pk, position.pk]
        assert sorted_by("-checked_in") == [position.pk, waiting.pk]


def test_pdf_exporter_loads_checkins_only_for_kinds_that_use_them(event, item):
    def kind_with(fields, sort=()):
        return ListConfiguration(
            organizer=event.organizer, default_fields=fields, sort_fields=list(sort)
        )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    checkin_list = event.checkin_lists.create(name="Main", all_products=True)
    for code in ("AAA11", "BBB22"):
        _checkin(_make_position(event, item, code, code), checkin_list, now())

    for kind in (
        kind_with(["name", "checked_in"]),
        kind_with([["name", "checked_in"]]),
        kind_with(["name"], sort=["-checked_in"]),
    ):
        positions = exporter._sorted_positions(kind)
        assert all(hasattr(p, "entry_checkins") for p in positions)
    positions = exporter._sorted_positions(kind_with(["name"]))
    assert not any(hasattr(p, "entry_checkins") for p in positions)


def test_csv_exporter_offers_checked_in_next_to_status(event, position):
    keys = [
        key
        for key, _label in _csv_exporter(event).additional_form_fields["fields"].choices
    ]

    assert keys.count("checked_in") == 1
    assert keys.index("checked_in") == keys.index("status") + 1


def test_pdf_exporter_status_column_shows_order_status(event, item, position):
    _make_pending_position(event, item, "PEND1", "Pending Pia")
    kind = ListConfiguration.objects.create(
        organizer=event.organizer,
        name="Kurz",
        default_fields=["name", "status"],
        sort_fields=["name"],
        is_default=True,
        include_pending=True,
    )

    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, _content_type, data = exporter.render({"list": str(kind.pk)})

    text = _pdf_text(data)
    assert "Order status" in text
    assert "paid" in text
    assert "pending" in text


def test_csv_exporter_status_field(event, item, position):
    _make_pending_position(event, item, "PEND1", "Pending Pia")

    rows = list(
        _csv_exporter(event).iterate_list(
            {"fields": ["name", "status"], "include_pending": True}
        )
    )

    assert rows[0] == ["Name", "Order status"]
    assert rows[1:] == [["Jane Doe", "paid"], ["Pending Pia", "pending"]]


def test_export_form_offers_to_copy_a_kind_into_the_custom_list(event):
    ListConfiguration.objects.create(
        organizer=event.organizer,
        name='Kurz "A"',
        default_fields=["name", ["email", "ticket"]],
        sort_fields=["-name"],
        include_pending=True,
    )
    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)

    help_text = str(exporter.export_form_fields["list"].help_text)

    assert "participantlist-adopt" in help_text
    assert 'data-name="Kurz &quot;A&quot;"' in help_text
    assert 'data-columns="name\nemail+ticket"' in help_text
    assert 'data-sort="-name"' in help_text
    assert 'data-include-pending="1"' in help_text


def test_export_form_has_no_copy_button_without_kinds(event):
    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)

    assert not exporter.export_form_fields["list"].help_text


def test_custom_list_is_not_saved_when_save_is_unticked(event, position):
    exporter = AttendeeListPDFExporter(event=event, organizer=event.organizer)
    _filename, _content_type, data = exporter.render(
        {
            "list": CUSTOM_KIND_VALUE,
            "custom_name": "Wanderliste",
            "custom_columns": "name\norder_code",
            "custom_sort": "-name",
            "custom_include_pending": True,
            "custom_save": False,
        }
    )

    text = _pdf_text(data)
    assert "Wanderliste" in text
    assert "ABC12" in text

    event.settings.flush()
    assert not event.settings.get(CUSTOM_NAME_SETTING)
    assert not event.settings.get(CUSTOM_COLUMNS_SETTING)
    assert not event.settings.get(CUSTOM_SORT_SETTING)
    assert not event.settings.get(CUSTOM_INCLUDE_PENDING_SETTING, as_type=bool)


def test_csv_exporter_offers_event_fields_first_and_by_default(event, position):
    field = _csv_exporter(event).additional_form_fields["fields"]
    keys = [key for key, _label in field.choices]

    assert keys[:2] == ["event_slug", "event_name"]
    assert dict(field.choices)["event_slug"] == "Event slug"
    assert dict(field.choices)["event_name"] == "Event name"
    assert field.initial[:2] == ["event_slug", "event_name"]


def test_csv_exporter_lists_event_of_each_row(event, item, position):
    other = Event.objects.create(
        organizer=event.organizer,
        name="Wintercamp",
        slug="wintercamp",
        date_from=event.date_from + datetime.timedelta(days=30),
        live=True,
    )
    other_item = other.items.create(
        name="Ticket", default_price=10, admission=True, personalized=True
    )
    _make_position(other, other_item, "WIN01", "Winnie Frost")
    exporter = AttendeeListCSVExporter(
        event=Event.objects.filter(pk__in=[event.pk, other.pk]),
        organizer=event.organizer,
    )

    rows = list(exporter.iterate_list({"fields": ["event_slug", "event_name", "name"]}))

    assert rows == [
        ["Event slug", "Event name", "Name"],
        ["testcamp", "Testcamp", "Jane Doe"],
        ["wintercamp", "Wintercamp", "Winnie Frost"],
    ]


def test_csv_exporter_default_fields_include_event(event, position):
    rows = list(_csv_exporter(event).iterate_list({}))

    assert rows[0][:2] == ["Event slug", "Event name"]
    assert rows[1][:2] == ["testcamp", "Testcamp"]


def _position_for_item(position, item, positionid):
    return OrderPosition.objects.create(
        order=position.order,
        item=item,
        price=5,
        positionid=positionid,
        attendee_name_parts={"_legacy": f"Extra {positionid}"},
    )


def test_csv_exporter_lists_only_personalized_admission_tickets(event, position):
    extra = Item.objects.create(event=event, name="T-Shirt", default_price=5)
    unpersonalized = Item.objects.create(
        event=event, name="Day pass", default_price=5, admission=True
    )
    _position_for_item(position, extra, 2)
    _position_for_item(position, unpersonalized, 3)
    addon = _position_for_item(position, extra, 4)
    addon.addon_to = position
    addon.save()

    rows = list(_csv_exporter(event).iterate_list({"fields": ["name", "ticket"]}))

    assert rows == [["Name", "Ticket type"], ["Jane Doe", "Ticket"]]


def _pdf_text_fonts(data):
    """(text, font resource name) pairs drawn on the first page."""
    page = pypdf.PdfReader(BytesIO(data)).pages[0]
    drawn = []

    def visitor(text, _cm, _tm, font_dict, _size):
        if text.strip() and font_dict is not None:
            drawn.append((text.strip(), str(font_dict["/BaseFont"])))

    page.extract_text(visitor_text=visitor)
    return drawn


def test_pdf_exporter_prints_event_title_bold_and_date_regular(event, position):
    kind = ListConfiguration.objects.create(
        organizer=event.organizer, name="Kurz", default_fields=[["name"]]
    )
    _filename, _type, data = AttendeeListPDFExporter(
        event=event, organizer=event.organizer
    ).render({"list": str(kind.pk)})

    drawn = _pdf_text_fonts(data)
    title_fonts = {font for text, font in drawn if text == "Testcamp"}
    date_fonts = {
        font for text, font in drawn if text == event.get_date_range_display()
    }
    assert title_fonts and all(f.endswith("-Bold") for f in title_fonts)
    assert date_fonts and not any(f.endswith("-Bold") for f in date_fonts)
