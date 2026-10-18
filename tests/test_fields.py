import datetime

import pytest
from django.utils.timezone import now
from pretix.base.models import Event, OrderPosition, Question

from pretix_participantlist.fields import (
    birth_date_question_identifier,
    extract_static_field,
    format_column_spec,
    format_sort_spec,
    organizer_date_question_choices,
    organizer_question_details,
    parse_column_spec,
    parse_default_fields,
    parse_sort_spec,
    resolve_field_tokens,
    split_sort_direction,
)
from pretix_participantlist.models import OrganizerBranding

pytestmark = pytest.mark.django_db


def test_parse_default_fields_wraps_legacy_flat_list():
    assert parse_default_fields(["name", "ticket"]) == [["name"], ["ticket"]]


def test_parse_default_fields_preserves_groups():
    assert parse_default_fields([["email", "ticket"], "name"]) == [
        ["email", "ticket"],
        ["name"],
    ]


def test_parse_default_fields_drops_junk():
    assert parse_default_fields([123, [], "name", [""]]) == [["name"]]


def test_format_column_spec_round_trips():
    groups = [["email", "ticket"], ["name"], ["signing"]]
    assert format_column_spec(groups) == "email+ticket\nname\nsigning"


def test_parse_column_spec_valid(organizer):
    groups = parse_column_spec("name\nemail+ticket\n\nsigning", organizer)
    assert groups == [["name"], ["email", "ticket"], ["signing"]]


def test_parse_column_spec_rejects_unknown_token(organizer):
    with pytest.raises(ValueError):
        parse_column_spec("not_a_real_field", organizer)


def test_parse_column_spec_rejects_signing_in_group(organizer):
    with pytest.raises(ValueError):
        parse_column_spec("signing+name", organizer)


def test_parse_column_spec_rejects_duplicate_token(organizer):
    with pytest.raises(ValueError):
        parse_column_spec("name\nname", organizer)


def test_organizer_question_details_reports_type_and_events(organizer, event):
    other_event = Event.objects.create(
        organizer=organizer,
        name="Other camp",
        slug="othercamp",
        date_from=now(),
        live=True,
    )
    Question.objects.create(
        event=event,
        question="Allergies?",
        type=Question.TYPE_TEXT,
        identifier="allergies",
    )
    Question.objects.create(
        event=other_event,
        question="Allergies?",
        type=Question.TYPE_TEXT,
        identifier="allergies",
    )

    details = organizer_question_details(organizer)

    assert len(details) == 1
    detail = details[0]
    assert detail.identifier == "allergies"
    assert detail.question == "Allergies?"
    assert detail.type_label == "Multiline text"
    assert detail.events == ["othercamp", "testcamp"]


def test_organizer_question_details_empty_without_organizer():
    assert organizer_question_details(None) == []


def test_format_sort_spec_round_trips():
    assert format_sort_spec(["question:section", "name"]) == "question:section\nname"


def test_format_sort_spec_empty():
    assert format_sort_spec([]) == ""


def test_parse_sort_spec_valid(organizer):
    assert parse_sort_spec("name\n\nemail", organizer) == ["name", "email"]


def test_parse_sort_spec_rejects_signing(organizer):
    with pytest.raises(ValueError):
        parse_sort_spec("signing", organizer)


def test_parse_sort_spec_rejects_index(organizer):
    with pytest.raises(ValueError):
        parse_sort_spec("index", organizer)


def test_parse_sort_spec_rejects_unknown_token(organizer):
    with pytest.raises(ValueError):
        parse_sort_spec("not_a_real_field", organizer)


def test_parse_sort_spec_rejects_duplicate_token(organizer):
    with pytest.raises(ValueError):
        parse_sort_spec("name\nname", organizer)


def test_resolve_field_tokens_resolves_static_and_question(event):
    question = Question.objects.create(
        event=event,
        question="Section?",
        type=Question.TYPE_CHOICE,
        identifier="section",
    )
    resolved = resolve_field_tokens(["question:section", "name"], event)
    assert resolved == [("question", question, False), ("static", "name", False)]


def test_resolve_field_tokens_skips_unknown_question(event):
    assert resolve_field_tokens(["question:missing", "name"], event) == [
        ("static", "name", False)
    ]


def test_resolve_field_tokens_reads_descending_prefix(event):
    resolved = resolve_field_tokens(["-name", "email"], event)
    assert resolved == [("static", "name", True), ("static", "email", False)]


def test_split_sort_direction():
    assert split_sort_direction("-name") == ("name", True)
    assert split_sort_direction("name") == ("name", False)


def test_parse_sort_spec_accepts_descending_prefix(organizer):
    assert parse_sort_spec("-name\nemail", organizer) == ["-name", "email"]


def test_parse_sort_spec_dedups_by_base_token_regardless_of_direction(organizer):
    with pytest.raises(ValueError):
        parse_sort_spec("name\n-name", organizer)


def test_first_last_name_are_known_sort_tokens(organizer):
    assert parse_sort_spec("first_name\nlast_name", organizer) == [
        "first_name",
        "last_name",
    ]


def test_extract_static_field_first_and_last_name(order, item):
    position = OrderPosition.objects.create(
        order=order,
        item=item,
        price=10,
        attendee_name_parts={"given_name": "Jane", "family_name": "Doe"},
    )
    assert extract_static_field(position, "first_name") == "Jane"
    assert extract_static_field(position, "last_name") == "Doe"


def test_extract_static_field_first_and_last_name_empty_for_legacy_names(position):
    # The `position` fixture uses the legacy "full name only" import format,
    # which has no given/family name split.
    assert extract_static_field(position, "first_name") == ""
    assert extract_static_field(position, "last_name") == ""


def test_extract_static_field_index_returns_given_number(position):
    assert extract_static_field(position, "index", 3) == 3


def test_extract_static_field_index_empty_without_number(position):
    assert extract_static_field(position, "index") == ""


def _answer_birth_date(position, value, identifier="geburtsdatum", text="Geburtsdatum"):
    question = Question.objects.create(
        event=position.order.event,
        question=text,
        type=Question.TYPE_DATE,
        identifier=identifier,
    )
    position.answers.create(question=question, answer=value)


def _set_event_start(position, value):
    event = position.order.event
    event.date_from = datetime.datetime.combine(
        value, datetime.time(12), tzinfo=event.timezone
    )
    event.save()


def test_extract_static_field_age_on_first_event_day(position):
    _set_event_start(position, datetime.date(2026, 7, 20))
    _answer_birth_date(position, "2012-07-20")
    assert (
        extract_static_field(position, "age", birth_date_identifier="geburtsdatum")
        == 14
    )


def test_extract_static_field_age_before_birthday(position):
    _set_event_start(position, datetime.date(2026, 7, 20))
    _answer_birth_date(position, "2012-07-21")
    assert (
        extract_static_field(position, "age", birth_date_identifier="geburtsdatum")
        == 13
    )


def test_extract_static_field_age_uses_only_configured_question(position):
    _set_event_start(position, datetime.date(2026, 7, 20))
    _answer_birth_date(position, "1980-01-01", identifier="geburt_eltern")
    _answer_birth_date(position, "2012-01-01", identifier="dob", text="Anything")
    assert extract_static_field(position, "age", birth_date_identifier="dob") == 14


def test_extract_static_field_age_empty_without_configured_question(position):
    _answer_birth_date(position, "2012-01-01")
    assert extract_static_field(position, "age") == ""


def test_extract_static_field_age_empty_without_birth_date(position):
    assert (
        extract_static_field(position, "age", birth_date_identifier="geburtsdatum")
        == ""
    )


def test_birth_date_question_identifier_reads_branding(organizer):
    assert birth_date_question_identifier(organizer) == ""
    OrganizerBranding.objects.create(organizer=organizer, birth_date_question="dob")
    assert birth_date_question_identifier(organizer) == "dob"


def test_organizer_date_question_choices_only_lists_date_questions(event):
    Question.objects.create(
        event=event, question="Geburtsdatum", type=Question.TYPE_DATE, identifier="dob"
    )
    Question.objects.create(
        event=event, question="Allergies?", type=Question.TYPE_TEXT, identifier="all"
    )
    assert organizer_date_question_choices(event.organizer) == [("dob", "Geburtsdatum")]


def test_parse_default_fields_reads_labeled_groups():
    groups = parse_default_fields([{"tokens": ["email", "ticket"], "label": "Kontakt"}])
    assert groups == [["email", "ticket"]]
    assert groups[0].label == "Kontakt"


def test_parse_column_spec_reads_titles(organizer):
    groups = parse_column_spec(
        "name=Teilnehmer*in\nemail+ticket=A=B\nsigning", organizer
    )
    assert groups == [["name"], ["email", "ticket"], ["signing"]]
    assert [g.label for g in groups] == ["Teilnehmer*in", "A=B", ""]


def test_column_spec_with_titles_round_trips(organizer):
    text = "name=Teilnehmer*in\nemail+ticket\nsigning=Unterschrift"
    assert format_column_spec(parse_column_spec(text, organizer)) == text
