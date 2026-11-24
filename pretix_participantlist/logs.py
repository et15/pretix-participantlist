"""Log entries of this plugin: action types, helpers and their display.

The texts are registered with pretix's ``log_entry_types`` registry, which
replaces the deprecated ``logentry_display`` signal. See
https://docs.pretix.eu/dev/development/implementation/logging.html
"""

from django.db.models.fields.files import FieldFile
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from pretix.base.logentrytypes import (
    EventLogEntryType,
    LogEntryType,
    NoOpShredderMixin,
    log_entry_types,
)
from pretix.base.models import User
from pretix.base.models.auth import UserWithStaffSession

from .models import ListConfiguration, OrganizerBranding

PREFIX = "pretix_participantlist"
BRANDING_CHANGED = f"{PREFIX}.branding.changed"
KIND_ADDED = f"{PREFIX}.kind.added"
KIND_CHANGED = f"{PREFIX}.kind.changed"
KIND_DELETED = f"{PREFIX}.kind.deleted"
KIND_DEFAULT = f"{PREFIX}.kind.default"
CUSTOM_LIST_CHANGED = f"{PREFIX}.custom_list.changed"
EXPORT_PDF = f"{PREFIX}.export.pdf"
EXPORT_CSV = f"{PREFIX}.export.csv"

KIND_LOG_FIELDS = (
    "name",
    "default_fields",
    "sort_fields",
    "is_default",
    "is_confidential",
    "include_pending",
    "filename_suffix",
)


def snapshot(obj, fields):
    """JSON-serializable values of ``fields`` on ``obj`` (files by name)."""
    result = {}
    for field in fields:
        value = getattr(obj, field)
        if isinstance(value, FieldFile):
            value = value.name or None
        result[field] = value
    return result


def changes(before, after):
    """The entries of ``after`` whose value differs from ``before``."""
    return {k: v for k, v in after.items() if before.get(k) != v}


def actor_kwargs(permission_holder):
    """``log_action`` keyword arguments naming who ran an export.

    ``permission_holder`` is the exporter's user, staff-session wrapper,
    API token or device; ``None`` logs the entry without actor.
    """
    if permission_holder is None:
        return {}
    if isinstance(permission_holder, UserWithStaffSession):
        return {"user": permission_holder.user}
    if isinstance(permission_holder, User):
        return {"user": permission_holder}
    # API token or device; ``log_action`` ignores anything else.
    return {"auth": permission_holder}


class OrganizerObjectLogEntryType(NoOpShredderMixin, LogEntryType):
    """Entries on an organizer-level object of this plugin.

    Links to the object's page in the organizer area. The log data holds
    configuration only, no personal data, so there is nothing to shred.
    """

    content_type = None
    object_link_viewname = None
    object_link_argname = None

    def get_object_link_info(self, logentry):
        content = logentry.content_object
        if not content:
            if logentry.content_type_id:
                return {"val": _("(deleted)")}
            return None
        if not isinstance(content, self.content_type):
            return None
        kwargs = {"organizer": logentry.organizer.slug}
        if self.object_link_argname:
            kwargs[self.object_link_argname] = content.pk
        return {
            "href": reverse(self.object_link_viewname, kwargs=kwargs),
            "val": self.object_link_display_name(content),
        }

    def object_link_display_name(self, content_object):
        return str(content_object)


@log_entry_types.new_from_dict(
    {
        BRANDING_CHANGED: _("The participant list branding has been changed."),
    }
)
class BrandingLogEntryType(OrganizerObjectLogEntryType):
    content_type = OrganizerBranding
    object_link_viewname = "plugins:pretix_participantlist:branding"

    def object_link_display_name(self, content_object):
        return _("Participant list branding")


class KindLogEntryType(OrganizerObjectLogEntryType):
    content_type = ListConfiguration
    object_link_wrapper = _("List kind {val}")
    object_link_viewname = "plugins:pretix_participantlist:kinds.edit"
    object_link_argname = "kind"

    def object_link_display_name(self, content_object):
        return content_object.name


@log_entry_types.new_from_dict(
    {
        KIND_ADDED: _("The list kind has been created."),
        KIND_CHANGED: _("The list kind has been changed."),
        KIND_DELETED: _('The list kind "{name}" has been deleted.'),
    }
)
class CoreKindLogEntryType(KindLogEntryType):
    pass


@log_entry_types.new_from_dict(
    {
        KIND_DEFAULT: _("The list kind has been made the default list kind."),
    }
)
class KindDefaultLogEntryType(KindLogEntryType):
    def display(self, logentry, data):
        if data.get("automatic"):
            return _(
                "The list kind has been made the default list kind automatically, "
                "because the previous default list kind was deleted."
            )
        return super().display(logentry, data)


@log_entry_types.new_from_dict(
    {
        CUSTOM_LIST_CHANGED: _(
            "The saved custom participant list of this event has been changed."
        ),
    }
)
class CustomListLogEntryType(NoOpShredderMixin, EventLogEntryType):
    pass


@log_entry_types.new_from_dict(
    {
        EXPORT_PDF: _('The participant list "{list_name}" has been exported (PDF).'),
    }
)
class PDFExportLogEntryType(NoOpShredderMixin, EventLogEntryType):
    def display(self, logentry, data):
        if data.get("list") == "__all__":  # exporters.ALL_KINDS_VALUE
            return _("The participant lists of all list kinds have been exported.")
        # A scheduled export may name a list kind that was deleted since.
        return super().display(
            logentry, {**data, "list_name": data.get("list_name") or "?"}
        )


@log_entry_types.new_from_dict(
    {
        EXPORT_CSV: _(
            "A participant list has been exported (CSV/Excel) for these events: "
            "{events}."
        ),
    }
)
class CSVExportLogEntryType(NoOpShredderMixin, LogEntryType):
    def display(self, logentry, data):
        return super().display(
            logentry, {**data, "events": ", ".join(data.get("events") or [])}
        )
