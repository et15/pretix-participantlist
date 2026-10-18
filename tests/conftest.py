import pytest
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Event, Item, Order, OrderPosition, Organizer


@pytest.fixture(autouse=True)
def _scopes_disabled():
    with scopes_disabled():
        yield


@pytest.fixture
def organizer():
    return Organizer.objects.create(name="Example Org", slug="example")


@pytest.fixture
def event(organizer):
    return Event.objects.create(
        organizer=organizer,
        name="Testcamp",
        slug="testcamp",
        date_from=now(),
        live=True,
    )


@pytest.fixture
def item(event):
    return Item.objects.create(event=event, name="Ticket", default_price=10)


@pytest.fixture
def order(event):
    return Order.objects.create(
        event=event,
        status=Order.STATUS_PAID,
        email="jane@example.org",
        datetime=now(),
        expires=now(),
        code="ABC12",
        total=10,
        sales_channel=event.organizer.sales_channels.get(identifier="web"),
    )


@pytest.fixture
def position(order, item):
    return OrderPosition.objects.create(
        order=order,
        item=item,
        price=10,
        attendee_name_parts={"_legacy": "Jane Doe"},
    )
