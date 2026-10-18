import pytest
from django.db import IntegrityError

from pretix_participantlist.models import ListConfiguration, OrganizerBranding

pytestmark = pytest.mark.django_db


def test_create_list_configuration(organizer):
    kind = ListConfiguration.objects.create(
        organizer=organizer,
        name="Vollständig",
        default_fields=["name", "email", "ticket"],
        is_default=True,
    )
    assert kind.pk
    assert str(organizer.name) in str(kind)


def test_create_organizer_branding(organizer):
    branding = OrganizerBranding.objects.create(
        organizer=organizer, header_text="Example Org"
    )
    assert branding.pk
    assert not branding.logo


def test_organizer_branding_is_one_per_organizer(organizer):
    OrganizerBranding.objects.create(organizer=organizer)
    with pytest.raises(IntegrityError):
        OrganizerBranding.objects.create(organizer=organizer)


def test_organizer_branding_default_logo_size(organizer):
    branding = OrganizerBranding.objects.create(organizer=organizer)
    assert branding.logo_width_mm == 96
    assert branding.logo_height_mm == 42
