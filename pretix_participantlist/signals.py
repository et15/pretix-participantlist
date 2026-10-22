from django.dispatch import receiver
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from pretix.base.signals import (
    register_data_exporters,
    register_multievent_data_exporters,
)
from pretix.control.signals import html_head, nav_event, nav_organizer


@receiver(register_data_exporters, dispatch_uid="participantlist_export_pdf")
def register_pdf_exporter(sender, **kwargs):
    from .exporters import AttendeeListPDFExporter

    return AttendeeListPDFExporter


@receiver(register_multievent_data_exporters, dispatch_uid="participantlist_export_csv")
def register_csv_exporter(sender, **kwargs):
    from .exporters import AttendeeListCSVExporter

    return AttendeeListCSVExporter


@receiver(nav_organizer, dispatch_uid="participantlist_nav_organizer")
def nav_organizer_receiver(sender, request, organizer, **kwargs):
    if not request.user.has_organizer_permission(
        organizer, "organizer.settings.general:write", request=request
    ):
        return []

    url = request.resolver_match
    url_name = url.url_name if url else None

    kinds_url = reverse(
        "plugins:pretix_participantlist:kinds", kwargs={"organizer": organizer.slug}
    )
    branding_url = reverse(
        "plugins:pretix_participantlist:branding", kwargs={"organizer": organizer.slug}
    )

    active_kinds = bool(url_name and url_name.startswith("kinds"))
    active_branding = url_name == "branding"

    # A single top-level entry with its own "children" gets its own sidebar
    # section instead of being nested under the generic Settings menu.
    return [
        {
            "label": _("Participant list"),
            "url": kinds_url,
            "icon": "list-alt",
            "active": active_kinds or active_branding,
            "children": [
                {
                    "label": _("List kinds"),
                    "url": kinds_url,
                    "active": active_kinds,
                },
                {
                    "label": _("Branding"),
                    "url": branding_url,
                    "active": active_branding,
                },
            ],
        },
    ]


@receiver(nav_event, dispatch_uid="participantlist_nav_event")
def nav_event_receiver(sender, request, **kwargs):
    """Shortcut to the PDF exporter, skipping the list on the Export page."""
    from .exporters import AttendeeListPDFExporter

    if "event.orders:read" not in request.eventpermset:
        return []

    identifier = AttendeeListPDFExporter.identifier
    export_url = reverse(
        "control:event.orders.export",
        kwargs={
            "organizer": request.event.organizer.slug,
            "event": request.event.slug,
        },
    )
    url = request.resolver_match
    active = bool(
        url
        and url.url_name == "event.orders.export"
        and request.GET.get("identifier") == identifier
    )
    return [
        {
            "label": _("Participant list"),
            "url": f"{export_url}?identifier={identifier}",
            "icon": "list-alt",
            "active": active,
        },
    ]


@receiver(html_head, dispatch_uid="participantlist_html_head")
def html_head_receiver(sender, request, **kwargs):
    """Load the export page script that copies a list kind into the custom list."""
    url = request.resolver_match
    if not (url and url.url_name == "event.orders.export"):
        return ""
    return format_html(
        '<script src="{}" defer></script>',
        static("pretix_participantlist/export.js"),
    )
