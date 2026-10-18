from django.db import models
from django.utils.crypto import get_random_string
from django.utils.translation import gettext_lazy as _
from pretix.base.models import LoggedModel, Organizer


def logo_upload_to(instance, filename):
    secret = get_random_string(
        length=16, allowed_chars="abcdefghijklmnopqrstuvwxyz0123456789"
    )
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"participantlist/{instance.organizer.slug}/logo-{secret}.{ext}"


class OrganizerBranding(LoggedModel):
    organizer = models.OneToOneField(
        Organizer, related_name="participantlist_branding", on_delete=models.CASCADE
    )
    logo = models.FileField(
        upload_to=logo_upload_to,
        null=True,
        blank=True,
        max_length=255,
        verbose_name=_("Logo"),
    )
    header_text = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("PDF header text"),
    )
    filename_prefix = models.CharField(
        max_length=64,
        blank=True,
        verbose_name=_("Download filename prefix"),
        help_text=_(
            "Used as the first part of the filename of generated PDF lists. "
            'Defaults to "Participant-List" if left empty.'
        ),
    )
    logo_width_mm = models.PositiveIntegerField(
        default=96,
        verbose_name=_("Logo max width (mm)"),
        help_text=_(
            "Maximum width of the logo in the PDF header. The logo is scaled down "
            "to fit within this box while keeping its aspect ratio."
        ),
    )
    logo_height_mm = models.PositiveIntegerField(
        default=42,
        verbose_name=_("Logo max height (mm)"),
        help_text=_("Maximum height of the logo in the PDF header."),
    )
    birth_date_question = models.CharField(
        max_length=190,
        blank=True,
        verbose_name=_("Birth date question"),
        help_text=_(
            "Internal reference (identifier) of the birth date question. For "
            'the age calculation (column "age"), it must be set to this value '
            "in every event of this organizer. If unset, the age column stays "
            "empty."
        ),
    )

    class Meta:
        verbose_name = _("Branding")
        verbose_name_plural = _("Branding")

    def __str__(self):
        return f"Branding ({self.organizer.name})"


class ListConfiguration(LoggedModel):
    organizer = models.ForeignKey(
        Organizer, related_name="participantlist_configs", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=190, verbose_name=_("Name"))
    default_fields = models.JSONField(
        default=list, verbose_name=_("Default selected fields")
    )
    sort_fields = models.JSONField(default=list, verbose_name=_("Sort by"))
    is_default = models.BooleanField(default=False, verbose_name=_("Default kind"))
    is_confidential = models.BooleanField(
        default=False,
        verbose_name=_("Confidential"),
        help_text=_(
            "Adds a “Confidential — do not distribute” notice to the footer of "
            "generated PDF lists of this kind."
        ),
    )
    filename_suffix = models.CharField(
        max_length=64,
        blank=True,
        verbose_name=_("Download filename suffix"),
        help_text=_(
            "Appended to the filename of generated PDF lists of this kind. "
            "Leave empty to omit it."
        ),
    )

    class Meta:
        verbose_name = _("List kind")
        verbose_name_plural = _("List kinds")
        ordering = ("-is_default", "name")

    def __str__(self):
        return f"{self.name} ({self.organizer.name})"
