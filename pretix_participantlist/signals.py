from django.dispatch import receiver
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from pretix.base.signals import (
    event_copy_data,
    register_data_exporters,
    register_multievent_data_exporters,
)
from pretix.control.signals import (
    html_head,
    nav_event,
    nav_event_settings,
    nav_organizer,
)


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


def _event_url_kwargs(request):
    return {"organizer": request.organizer.slug, "event": request.event.slug}


def _is_orders_page(request, url_name):
    url = request.resolver_match
    return bool(
        url
        and url.namespace == "plugins:pretix_participantlist"
        and url.url_name == url_name
    )


@receiver(nav_event, dispatch_uid="participantlist_orders_nav")
def nav_event_orders_receiver(sender, request, **kwargs):
    """Add the order list as a sub-item of the built-in "Orders" menu."""
    from .orderlist import PERMISSION

    if PERMISSION not in request.eventpermset:
        return []
    return [
        {
            "label": _("Orders by attendee"),
            "url": reverse(
                "plugins:pretix_participantlist:orders",
                kwargs=_event_url_kwargs(request),
            ),
            "parent": reverse(
                "control:event.orders", kwargs=_event_url_kwargs(request)
            ),
            "active": _is_orders_page(request, "orders"),
        }
    ]


@receiver(nav_event_settings, dispatch_uid="participantlist_orders_nav_settings")
def nav_event_settings_receiver(sender, request, **kwargs):
    """Add the order list settings page to the event settings menu."""
    from .orderlist import SETTINGS_PERMISSION

    if SETTINGS_PERMISSION not in request.eventpermset:
        return []
    return [
        {
            "label": _("Orders by attendee"),
            "url": reverse(
                "plugins:pretix_participantlist:orders.settings",
                kwargs=_event_url_kwargs(request),
            ),
            "active": _is_orders_page(request, "orders.settings"),
        }
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


@receiver(event_copy_data, dispatch_uid="participantlist_event_copy_data")
def event_copy_data_receiver(sender, other, question_map, checkin_list_map, **kwargs):
    """Point the copied settings at the new event's check-in list and questions.

    pretix copies the settings store as is, so the IDs would still name objects
    of the original event.
    """
    from .settings import CHECKIN_LIST_KEY, ORDERS_QUESTION_COLUMNS_KEY

    value = other.settings.get(CHECKIN_LIST_KEY, as_type=str) or ""
    new_list = checkin_list_map.get(int(value)) if value.isdigit() else None
    sender.settings.set(CHECKIN_LIST_KEY, str(new_list.pk) if new_list else "")

    question_ids = other.settings.get(ORDERS_QUESTION_COLUMNS_KEY, as_type=list) or []
    sender.settings.set(
        ORDERS_QUESTION_COLUMNS_KEY,
        [
            str(question_map[int(pk)].pk)
            for pk in question_ids
            if str(pk).isdigit() and int(pk) in question_map
        ],
    )
