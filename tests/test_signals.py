import pytest
from django.test import RequestFactory
from django.urls import resolve, reverse

from pretix_participantlist import signals
from pretix_participantlist.signals import html_head_receiver, nav_event_receiver

pytestmark = pytest.mark.django_db


def _request(event, path=None, permissions=("event.orders:read",), query=""):
    export = reverse(
        "control:event.orders.export",
        kwargs={"organizer": event.organizer.slug, "event": event.slug},
    )
    request = RequestFactory().get((path or export) + query)
    request.event = event
    request.eventpermset = set(permissions)
    request.resolver_match = resolve(request.path)
    return request


def test_event_nav_links_straight_to_the_exporter(event):
    (entry,) = nav_event_receiver(event, request=_request(event))

    assert entry["url"].endswith("/orders/export/?identifier=participantlist_pdf")
    assert entry["active"] is False


def test_event_nav_is_active_on_the_exporter_form(event):
    request = _request(event, query="?identifier=participantlist_pdf")

    (entry,) = nav_event_receiver(event, request=request)

    assert entry["active"] is True


def test_event_nav_is_hidden_without_order_permission(event):
    assert nav_event_receiver(event, request=_request(event, permissions=())) == []


def test_export_page_loads_the_export_script(event, monkeypatch):
    monkeypatch.setattr(signals, "static", lambda path: f"/static/{path}")

    html = html_head_receiver(event, request=_request(event))

    assert (
        html == '<script src="/static/pretix_participantlist/export.js" defer></script>'
    )


def test_other_pages_do_not_load_the_export_script(event):
    request = _request(event)
    request.resolver_match = resolve(
        reverse(
            "control:event.index",
            kwargs={"organizer": event.organizer.slug, "event": event.slug},
        )
    )

    assert html_head_receiver(event, request=request) == ""
