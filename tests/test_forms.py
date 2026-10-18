import pytest
from pretix.base.models import Question

from pretix_participantlist.forms import (
    BrandingForm,
    ListConfigurationForm,
)
from pretix_participantlist.models import (
    ListConfiguration,
    OrganizerBranding,
)

pytestmark = pytest.mark.django_db


def test_branding_form_exposes_logo_size_fields():
    form = BrandingForm()
    assert "logo_width_mm" in form.fields
    assert "logo_height_mm" in form.fields


def test_branding_form_offers_date_questions_for_birth_date(organizer, event):
    Question.objects.create(
        event=event,
        question="Geburtsdatum",
        type=Question.TYPE_DATE,
        identifier="geburtsdatum",
    )
    Question.objects.create(
        event=event,
        question="Allergies?",
        type=Question.TYPE_TEXT,
        identifier="allergies",
    )
    branding = OrganizerBranding.objects.create(organizer=organizer)
    form = BrandingForm(instance=branding)
    assert form.fields["birth_date_question"].choices == [
        ("", "---------"),
        ("geburtsdatum", "Geburtsdatum (geburtsdatum)"),
    ]


def test_branding_form_keeps_unknown_stored_birth_date_question(organizer):
    branding = OrganizerBranding.objects.create(
        organizer=organizer, birth_date_question="old_dob"
    )
    form = BrandingForm(instance=branding)
    assert ("old_dob", "old_dob (old_dob)") in form.fields[
        "birth_date_question"
    ].choices


def test_branding_form_saves_birth_date_question(organizer, event):
    Question.objects.create(
        event=event,
        question="Geburtsdatum",
        type=Question.TYPE_DATE,
        identifier="geburtsdatum",
    )
    branding = OrganizerBranding.objects.create(organizer=organizer)
    form = BrandingForm(
        data={
            "header_text": "",
            "filename_prefix": "",
            "logo_width_mm": 96,
            "logo_height_mm": 42,
            "birth_date_question": "geburtsdatum",
        },
        instance=branding,
    )
    assert form.is_valid(), form.errors
    form.save()
    branding.refresh_from_db()
    assert branding.birth_date_question == "geburtsdatum"


def test_columns_text_help_lists_static_fields_and_links_to_placeholders(
    organizer, event
):
    Question.objects.create(
        event=event,
        question="Allergies?",
        type=Question.TYPE_TEXT,
        identifier="allergies",
    )
    form = ListConfigurationForm(organizer=organizer)
    help_text = str(form.fields["columns_text"].help_text)
    assert "name" in help_text
    assert "signing" in help_text
    # The long, per-question token list moved to its own page; only a link remains.
    assert "question:allergies" not in help_text
    assert (
        f"/control/organizer/{organizer.slug}/participantlist/kinds/placeholders"
        in help_text
    )


def test_saving_kind_with_columns_text(organizer):
    form = ListConfigurationForm(
        data={"name": "Kurz", "columns_text": "name\nemail+ticket"},
        organizer=organizer,
    )
    assert form.is_valid(), form.errors
    kind = form.save(commit=False)
    kind.organizer = organizer
    kind.save()
    assert kind.default_fields == [["name"], ["email", "ticket"]]


def test_columns_text_rejects_unknown_token(organizer):
    form = ListConfigurationForm(
        data={"name": "Kurz", "columns_text": "not_a_real_field"},
        organizer=organizer,
    )
    assert not form.is_valid()
    assert "columns_text" in form.errors


def test_editing_kind_prefills_columns_text_from_stored_fields(organizer):
    kind = ListConfiguration.objects.create(
        organizer=organizer,
        name="Kurz",
        default_fields=[["email", "ticket"], "name"],
    )
    form = ListConfigurationForm(instance=kind, organizer=organizer)
    assert form.initial["columns_text"] == "email+ticket\nname"


def test_saving_kind_with_sort_text(organizer):
    form = ListConfigurationForm(
        data={"name": "Kurz", "columns_text": "name", "sort_text": "name\nemail"},
        organizer=organizer,
    )
    assert form.is_valid(), form.errors
    kind = form.save(commit=False)
    kind.organizer = organizer
    kind.save()
    assert kind.sort_fields == ["name", "email"]


def test_saving_kind_with_descending_sort_text(organizer):
    form = ListConfigurationForm(
        data={"name": "Kurz", "columns_text": "name", "sort_text": "-name"},
        organizer=organizer,
    )
    assert form.is_valid(), form.errors
    kind = form.save(commit=False)
    kind.organizer = organizer
    kind.save()
    assert kind.sort_fields == ["-name"]


def test_sort_text_rejects_signing(organizer):
    form = ListConfigurationForm(
        data={"name": "Kurz", "columns_text": "name", "sort_text": "signing"},
        organizer=organizer,
    )
    assert not form.is_valid()
    assert "sort_text" in form.errors


def test_editing_kind_prefills_sort_text_from_stored_fields(organizer):
    kind = ListConfiguration.objects.create(
        organizer=organizer,
        name="Kurz",
        default_fields=["name"],
        sort_fields=["email", "name"],
    )
    form = ListConfigurationForm(instance=kind, organizer=organizer)
    assert form.initial["sort_text"] == "email\nname"


def test_saving_kind_with_column_titles(organizer):
    form = ListConfigurationForm(
        data={
            "name": "Kurz",
            "columns_text": "name=Teilnehmer*in\nemail+ticket=A+B\norder_code",
        },
        organizer=organizer,
    )
    assert form.is_valid(), form.errors
    kind = form.save(commit=False)
    kind.organizer = organizer
    kind.save()
    assert kind.default_fields == [
        {"tokens": ["name"], "label": "Teilnehmer*in"},
        {"tokens": ["email", "ticket"], "label": "A+B"},
        ["order_code"],
    ]


def test_editing_kind_prefills_columns_text_with_titles(organizer):
    kind = ListConfiguration.objects.create(
        organizer=organizer,
        name="Kurz",
        default_fields=[{"tokens": ["email", "ticket"], "label": "Kontakt"}, "name"],
    )
    form = ListConfigurationForm(instance=kind, organizer=organizer)
    assert form.initial["columns_text"] == "email+ticket=Kontakt\nname"
