from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import (
    Checkin,
    Customer,
    Event,
    InvoiceAddress,
    Order,
    OrderPayment,
    Organizer,
    Question,
    Team,
    User,
)

from pretix_participantlist.fields import age_on
from pretix_participantlist.models import OrganizerBranding

URL = "/control/event/demo/kurs/participantlist/orders/"


# Fixtures of the former pretix-ordersummary tests; they override the
# conftest fixtures of the same name in this module.
@pytest.fixture
def organizer():
    with scopes_disabled():
        # Bank transfer is a hybrid plugin: it must be active for the organizer too.
        return Organizer.objects.create(
            name="Demo Organizer",
            slug="demo",
            plugins="pretix.plugins.banktransfer,pretix_participantlist",
        )


@pytest.fixture
def event(organizer):
    with scopes_disabled():
        ev = Event.objects.create(
            organizer=organizer,
            name="Kletterkurs",
            slug="kurs",
            date_from=now() + timedelta(days=30),
            plugins="pretix.plugins.banktransfer",
        )
        ev.settings.payment_banktransfer__enabled = True
        return ev


@pytest.fixture
def item(event):
    with scopes_disabled():
        return event.items.create(name="Teilnahme", default_price=Decimal("10.00"))


@pytest.fixture
def addon_item(event):
    with scopes_disabled():
        return event.items.create(name="Leihausrüstung", default_price=Decimal("5.00"))


def _make_user(organizer, event, email, permissions):
    user = User.objects.create_user(email, "dummy-password")
    with scopes_disabled():
        team = Team.objects.create(
            organizer=organizer, name=email, limit_event_permissions=permissions
        )
        team.members.add(user)
        team.limit_events.add(event)
    return user


@pytest.fixture
def admin_client(client, organizer, event):
    user = _make_user(
        organizer, event, "admin@example.org", {"event.orders:read": True}
    )
    client.login(email=user.email, password="dummy-password")
    return client


@pytest.fixture
def unprivileged_client(client, organizer, event):
    user = _make_user(organizer, event, "nobody@example.org", {})
    client.login(email=user.email, password="dummy-password")
    return client


@pytest.fixture
def admin_settings_client(client, organizer, event):
    user = _make_user(
        organizer,
        event,
        "settings@example.org",
        {"event.orders:read": True, "event.settings.general:write": True},
    )
    client.login(email=user.email, password="dummy-password")
    return client


def _order(event, code, **kwargs):
    defaults = {
        "status": Order.STATUS_PENDING,
        "email": f"{code.lower()}@example.org",
        "datetime": now(),
        "expires": now() + timedelta(days=10),
        "total": Decimal("10.00"),
        "locale": "en",
        "sales_channel": event.organizer.sales_channels.get(identifier="web"),
    }
    defaults.update(kwargs)
    return Order.objects.create(event=event, code=code, **defaults)


def _position(order, item, name, **kwargs):
    return order.all_positions.create(
        item=item,
        price=Decimal("10.00"),
        attendee_name_parts={"full_name": name},
        **kwargs,
    )


@pytest.mark.django_db
def test_requires_permission(unprivileged_client):
    assert unprivileged_client.get(URL).status_code == 403


@pytest.mark.django_db
def test_404_if_plugin_inactive(admin_settings_client, organizer):
    organizer.plugins = "pretix.plugins.banktransfer"
    organizer.save()
    assert admin_settings_client.get(URL).status_code == 404
    assert admin_settings_client.get(URL + "settings/").status_code == 404


@pytest.mark.django_db
def test_attendee_names_instead_of_invoice_name(admin_client, event, item, addon_item):
    with scopes_disabled():
        o = _order(event, "ABC12")
        InvoiceAddress.objects.create(order=o, name_parts={"full_name": "Paula Payer"})
        main = _position(o, item, "Anna Alpin")
        _position(o, item, "Bert Berg")
        _position(o, addon_item, "Addon Person", addon_to=main)
    html = admin_client.get(URL).content.decode()
    assert "Anna Alpin" in html
    assert "Bert Berg" in html
    assert "Addon Person" not in html
    assert "Paula Payer" not in html


@pytest.mark.django_db
def test_fallback_customer_then_invoice(admin_client, organizer, event, item):
    with scopes_disabled():
        customer = Customer.objects.create(
            organizer=organizer,
            email="c@example.org",
            name_parts={"full_name": "Carla Konto"},
        )
        o1 = _order(event, "CUST1", customer=customer)
        InvoiceAddress.objects.create(order=o1, name_parts={"full_name": "Not Shown"})
        _position(o1, item, "")
        o2 = _order(event, "INVO1")
        InvoiceAddress.objects.create(order=o2, name_parts={"full_name": "Ida Invoice"})
        _position(o2, item, "")
        o3 = _order(event, "COMP1")
        InvoiceAddress.objects.create(
            order=o3, company="Sektion Beispiel", is_business=True
        )
    html = admin_client.get(URL).content.decode()
    assert "Carla Konto" in html
    assert "Not Shown" not in html
    assert "Ida Invoice" in html
    assert "Sektion Beispiel" in html
    assert "Name from customer account" in html
    assert "Name from invoice address" in html


@pytest.mark.django_db
def test_canceled_order_keeps_names(admin_client, event, item):
    with scopes_disabled():
        o = _order(event, "CANC1", status=Order.STATUS_CANCELED)
        _position(o, item, "Clara Cancel", canceled=True)
    html = admin_client.get(URL, {"status": "c"}).content.decode()
    assert "Clara Cancel" in html


@pytest.mark.django_db
def test_payment_method(admin_client, event, item):
    with scopes_disabled():
        paid = _order(event, "PAID1", status=Order.STATUS_PAID)
        _position(paid, item, "Paula Paid")
        paid.payments.create(
            provider="banktransfer",
            amount=paid.total,
            state=OrderPayment.PAYMENT_STATE_FAILED,
        )
        paid.payments.create(
            provider="free",
            amount=paid.total,
            state=OrderPayment.PAYMENT_STATE_CONFIRMED,
        )
        pending = _order(event, "PEND1")
        _position(pending, item, "Pia Pending")
        pending.payments.create(
            provider="banktransfer",
            amount=pending.total,
            state=OrderPayment.PAYMENT_STATE_CREATED,
        )
    resp = admin_client.get(URL)
    rows = {o.code: o.payment_methods for o in resp.context["orders"]}
    assert rows["PAID1"] == ["Free of charge"]
    assert rows["PEND1"] == ["Bank transfer"]


@pytest.mark.django_db
def test_search_by_attendee(admin_client, event, item):
    with scopes_disabled():
        _position(_order(event, "FIND1"), item, "Findable Person")
        _position(_order(event, "HIDE1"), item, "Other Person")
    resp = admin_client.get(URL, {"query": "findable"})
    assert [o.code for o in resp.context["orders"]] == ["FIND1"]


@pytest.mark.django_db
def test_navigation_entry(admin_client, event):
    html = admin_client.get("/control/event/demo/kurs/orders/").content.decode()
    assert URL in html


@pytest.mark.django_db
def test_multiple_tickets_no_fallback_and_no_duplicates(
    admin_client, organizer, event, item
):
    with scopes_disabled():
        customer = Customer.objects.create(
            organizer=organizer,
            email="c@example.org",
            name_parts={"full_name": "Kunde Konto"},
        )
        o = _order(event, "MULT1", customer=customer)
        InvoiceAddress.objects.create(order=o, name_parts={"full_name": "Rech Nung"})
        _position(o, item, "Anna Alpin")
        _position(o, item, "")
        _position(o, item, "Anna Alpin")
        _position(o, item, "Bert Berg")
    resp = admin_client.get(URL)
    row = resp.context["orders"][0]
    assert row.attendee_names == ["Anna Alpin", "Bert Berg"]
    assert row.name_source == "attendee"
    html = resp.content.decode()
    assert "Kunde Konto" not in html
    assert "Rech Nung" not in html


def _question(event, item, text, identifier, **kwargs):
    q = event.questions.create(question=text, identifier=identifier, type="S", **kwargs)
    q.items.add(item)
    return q


@pytest.mark.django_db
def test_settings_page_and_question_columns(
    admin_settings_client, event, item, addon_item
):
    with scopes_disabled():
        sektion = _question(event, item, "Sektion", "sektion", position=2)
        shoe = _question(event, addon_item, "Shoe size", "shoe", position=1)
        hidden = _question(event, item, "Not selected", "other", position=3)
        o = _order(event, "QUES1")
        main = _position(o, item, "Anna Alpin")
        second = _position(o, item, "Bert Berg")
        addon = _position(o, addon_item, "", addon_to=main)
        main.answers.create(question=sektion, answer="Frankfurt")
        second.answers.create(question=sektion, answer="Frankfurt")
        main.answers.create(question=hidden, answer="secret")
        addon.answers.create(question=shoe, answer="42")

    settings_url = URL + "settings/"
    html = admin_settings_client.get(settings_url).content.decode()
    assert "Sektion" in html and "Shoe size" in html

    resp = admin_settings_client.post(
        settings_url,
        {"participantlist_orders_question_columns": [str(sektion.pk), str(shoe.pk)]},
    )
    assert resp.status_code == 302

    resp = admin_settings_client.get(URL)
    # Columns follow the position of the questions, not the selection.
    assert [q.pk for q in resp.context["questions"]] == [shoe.pk, sektion.pk]
    row = resp.context["orders"][0]
    assert row.question_values == [["42"], ["Frankfurt"]]
    assert "secret" not in resp.content.decode()


@pytest.mark.django_db
def test_order_level_question(admin_settings_client, event, item):
    with scopes_disabled():
        q = event.questions.create(
            question="Sektion",
            identifier="sektion",
            type="S",
            container_type=Question.ContainerType.ORDER,
        )
        o = _order(event, "ORDQ1")
        _position(o, item, "Anna Alpin")
        o.answers.create(question=q, answer="Kassel")
        event.settings.participantlist_orders_question_columns = [str(q.pk)]
    resp = admin_settings_client.get(URL)
    assert resp.context["orders"][0].question_values == [["Kassel"]]


@pytest.mark.django_db
def test_settings_requires_permission(admin_client):
    assert admin_client.get(URL + "settings/").status_code == 403


def _codes(resp):
    return [o.code for o in resp.context["orders"]]


@pytest.mark.django_db
def test_status_filter(admin_client, event, item):
    with scopes_disabled():
        _position(_order(event, "PEND1"), item, "A")
        _position(_order(event, "PAID1", status=Order.STATUS_PAID), item, "B")
        _position(_order(event, "EXPI1", status=Order.STATUS_EXPIRED), item, "C")
        _position(_order(event, "CANC1", status=Order.STATUS_CANCELED), item, "D")
        # Canceled with paid fee: status stays "paid", all positions canceled.
        fee = _order(event, "FEEC1", status=Order.STATUS_PAID)
        _position(fee, item, "E", canceled=True)

    def codes(status):
        return sorted(_codes(admin_client.get(URL, {"status": status})))

    assert codes("") == ["EXPI1", "PAID1", "PEND1"]
    assert codes("all") == ["CANC1", "EXPI1", "FEEC1", "PAID1", "PEND1"]
    assert codes("n") == ["PEND1"]
    assert codes("p") == ["PAID1"]
    assert codes("e") == ["EXPI1"]
    assert codes("c") == ["CANC1", "FEEC1"]
    assert codes("nonsense") == ["EXPI1", "PAID1", "PEND1"]


@pytest.mark.django_db
def test_sorting(admin_settings_client, organizer, event, item):
    client = admin_settings_client
    with scopes_disabled():
        q = _question(event, item, "Sektion", "sektion")
        event.settings.participantlist_orders_question_columns = [str(q.pk)]
        o1 = _order(event, "AAAA1", datetime=now() - timedelta(days=3))
        p1 = _position(o1, item, "bert Berg")
        p1.answers.create(question=q, answer="Kassel")
        o2 = _order(event, "BBBB2", datetime=now() - timedelta(days=1))
        _position(o2, item, "")
        InvoiceAddress.objects.create(
            order=o2, name_parts={"full_name": "Carla Invoice"}
        )
        o3 = _order(event, "CCCC3", datetime=now() - timedelta(days=2))
        p3 = _position(o3, item, "Anna Alpin")
        p3.answers.create(question=q, answer="Frankfurt")
        o4 = _order(event, "DDDD4", datetime=now())
        _position(o4, item, "")

    def codes(ordering):
        return _codes(client.get(URL, {"ordering": ordering}))

    assert codes("") == ["DDDD4", "BBBB2", "CCCC3", "AAAA1"]  # default: newest first
    assert codes("code") == ["AAAA1", "BBBB2", "CCCC3", "DDDD4"]
    assert codes("-code") == ["DDDD4", "CCCC3", "BBBB2", "AAAA1"]
    assert codes("datetime") == ["AAAA1", "CCCC3", "BBBB2", "DDDD4"]
    # Case-insensitive, fallback names included, orders without a name last.
    assert codes("attendee") == ["CCCC3", "AAAA1", "BBBB2", "DDDD4"]
    assert codes("-attendee") == ["BBBB2", "AAAA1", "CCCC3", "DDDD4"]
    # Orders without an answer come last (in order of creation).
    assert codes(f"q{q.pk}") == ["CCCC3", "AAAA1", "BBBB2", "DDDD4"]
    assert codes("payment") == codes("")  # not sortable: default order
    html = client.get(URL).content.decode()
    assert f"ordering=-q{q.pk}" in html
    assert "ordering=-attendee" in html


@pytest.mark.django_db
def test_live_filter_returns_only_results(admin_client, event, item):
    with scopes_disabled():
        _position(_order(event, "LIVE1"), item, "Lena Live")
        _position(_order(event, "LIVE2", status=Order.STATUS_CANCELED), item, "Carl")
    page = admin_client.get(URL).content.decode()
    assert 'id="participantlist-orders-filter"' in page
    assert "pretix_participantlist/orderlist.js" in page

    resp = admin_client.get(
        URL, {"status": "c"}, headers={"X-Requested-With": "XMLHttpRequest"}
    )
    html = resp.content.decode()
    assert "<html" not in html
    assert 'id="participantlist-orders-filter"' not in html
    assert "LIVE2" in html
    assert "LIVE1" not in html
    # Sort links keep the current filter.
    assert "status=c" in html


def _entry(position, checkin_list, **kwargs):
    return Checkin.all.create(position=position, list=checkin_list, **kwargs)


@pytest.mark.django_db
def test_checkin_column(admin_settings_client, event, item, addon_item):
    client = admin_settings_client
    with scopes_disabled():
        day1 = event.checkin_lists.create(name="Day 1")
        day2 = event.checkin_lists.create(name="Day 2")
        # One attendee, entered on day 2 only.
        p = _position(_order(event, "ONE01"), item, "Anna")
        _entry(p, day2)
        # Two attendees: one entered (and left again), one only failed scans.
        o = _order(event, "TWO02")
        a = _position(o, item, "Bert")
        b = _position(o, item, "Carl")
        _entry(a, day1)
        _entry(a, day1, type=Checkin.TYPE_EXIT)
        _entry(b, day1, successful=False, error_reason="invalid")
        # Add-ons do not count, also not their check-ins.
        addon = _position(o, addon_item, "", addon_to=a)
        _entry(addon, day1)
        # Nobody entered.
        _position(_order(event, "NONE3"), item, "Dora")

    resp = client.get(URL)
    assert resp.context["checkin_list"] is None
    assert "ordering=-checkin" not in resp.content.decode()

    resp = client.post(URL + "settings/", {"participantlist_orders_show_checkin": "on"})
    assert resp.status_code == 302
    settings_html = client.get(URL + "settings/").content.decode()
    assert "currently: All check-in lists" in settings_html

    def counts(value):
        # The list is chosen on the PDF export page and saved with the event.
        with scopes_disabled():
            event.settings.participantlist_checkin_list = value
        resp = client.get(URL)
        return {
            o.code: (o.checkins_entered, o.checkins_total)
            for o in resp.context["orders"]
        }

    assert counts("") == {"ONE01": (1, 1), "TWO02": (1, 2), "NONE3": (0, 1)}
    assert counts(str(day1.pk)) == {"ONE01": (0, 1), "TWO02": (1, 2), "NONE3": (0, 1)}
    html = client.get(URL).content.decode()
    assert "Day 1" in html  # name of the selected list in the header
    assert "ordering=-checkin" in html  # sortable column is shown
    settings_html = client.get(URL + "settings/").content.decode()
    assert "currently: Day 1" in settings_html

    # Sorting: by number of attendees counted as entered.
    counts("")
    resp = client.get(URL, {"ordering": "checkin"})
    assert [o.code for o in resp.context["orders"]] == ["NONE3", "ONE01", "TWO02"]
    resp = client.get(URL, {"ordering": "-checkin"})
    assert [o.code for o in resp.context["orders"]][2] == "NONE3"


@pytest.mark.django_db
def test_checkin_column_deleted_list_counts_any_list(
    admin_settings_client, event, item
):
    with scopes_disabled():
        p = _position(_order(event, "ORD01"), item, "Anna")
        _entry(p, event.checkin_lists.create(name="Day 1"))
        event.settings.participantlist_orders_show_checkin = True
        event.settings.participantlist_checkin_list = "999999"
    resp = admin_settings_client.get(URL, {"ordering": "checkin"})
    assert resp.context["checkin_list_any"]
    assert resp.context["orders"][0].checkins_entered == 1


@pytest.mark.django_db
def test_settings_page_without_questions(admin_settings_client):
    html = admin_settings_client.get(URL + "settings/").content.decode()
    assert "This event has no questions yet." in html
    assert "participantlist_orders_show_checkin" in html
    assert "participantlist_orders_show_age" in html


@pytest.mark.django_db
def test_optional_standard_columns(admin_settings_client, event, item):
    client = admin_settings_client
    with scopes_disabled():
        o = _order(event, "STD01", status=Order.STATUS_PAID)
        _position(o, item, "Anna")
        o.payments.create(
            provider="free", amount=o.total, state=OrderPayment.PAYMENT_STATE_CONFIRMED
        )

    # Shown by default.
    resp = client.get(URL)
    html = resp.content.decode()
    assert resp.context["show_datetime"] and resp.context["show_payment"]
    assert "Payment method" in html and "ordering=-datetime" in html
    assert resp.context["orders"][0].payment_methods == ["Free of charge"]
    settings_html = client.get(URL + "settings/").content.decode()
    assert (
        'name="participantlist_orders_standard_columns" value="datetime"'
        in settings_html
    )

    def save(columns):
        resp = client.post(
            URL + "settings/", {"participantlist_orders_standard_columns": columns}
        )
        assert resp.status_code == 302
        return client.get(URL)

    resp = save(["payment"])
    html = resp.content.decode()
    assert not resp.context["show_datetime"] and resp.context["show_payment"]
    assert "ordering=-datetime" not in html
    assert "Free of charge" in html

    resp = save([])
    html = resp.content.decode()
    assert not resp.context["show_datetime"] and not resp.context["show_payment"]
    assert "Payment method" not in html
    assert "Free of charge" not in html
    assert not hasattr(resp.context["orders"][0], "payment_methods")
    # Newest first stays the default order, also without the date column.
    assert client.get(URL, {"ordering": "datetime"}).status_code == 200


def test_age_on():
    from datetime import date

    assert age_on(date(2015, 7, 10), date(2027, 7, 10)) == 12
    assert age_on(date(2015, 7, 11), date(2027, 7, 10)) == 11
    assert age_on(date(2015, 12, 31), date(2027, 1, 1)) == 11
    # Born on 29 February: one year older from 1 March in non-leap years.
    assert age_on(date(2012, 2, 29), date(2027, 2, 28)) == 14
    assert age_on(date(2012, 2, 29), date(2027, 3, 1)) == 15


@pytest.mark.django_db
def test_age_column(admin_settings_client, event, item, addon_item):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    client = admin_settings_client
    with scopes_disabled():
        event.settings.timezone = "Europe/Berlin"
        # 00:30 in Berlin on 10 July is still 9 July in UTC: the event's
        # time zone decides which day is the first day.
        event.date_from = datetime(2027, 7, 10, 0, 30, tzinfo=ZoneInfo("Europe/Berlin"))
        event.save()
        dob = event.questions.create(
            question="Date of birth", identifier="dob", type="D"
        )
        dob.items.add(item)
        text_q = _question(event, item, "Sektion", "sektion")

        o1 = _order(event, "AGE01")
        a = _position(o1, item, "Anna")
        a.answers.create(question=dob, answer="2015-07-10")
        b = _position(o1, item, "Ben")
        b.answers.create(question=dob, answer="2015-07-10")
        addon = _position(o1, addon_item, "", addon_to=a)
        addon.answers.create(question=dob, answer="1990-01-01")
        o2 = _order(event, "AGE02")
        c = _position(o2, item, "Carla")
        c.answers.create(question=dob, answer="2015-07-11")
        _position(_order(event, "AGE03"), item, "No answer")

    settings_html = client.get(URL + "settings/").content.decode()
    assert "No birth date question is set" in settings_html

    with scopes_disabled():
        # A text question with the identifier does not count, only date questions.
        OrganizerBranding.objects.create(
            organizer=event.organizer, birth_date_question=text_q.identifier
        )
    settings_html = client.get(URL + "settings/").content.decode()
    assert 'no date question with the identifier "sektion"' in settings_html
    with scopes_disabled():
        OrganizerBranding.objects.filter(organizer=event.organizer).update(
            birth_date_question="dob"
        )
    settings_html = client.get(URL + "settings/").content.decode()
    assert 'Uses the question "Date of birth"' in settings_html

    resp = client.post(
        URL + "settings/",
        {
            "participantlist_orders_standard_columns": ["datetime"],
            "participantlist_orders_show_age": "on",
        },
    )
    assert resp.status_code == 302
    resp = client.get(URL)
    ages = {o.code: o.ages for o in resp.context["orders"]}
    # Equal ages are not merged; add-ons are ignored.
    assert ages == {"AGE01": [12, 12], "AGE02": [11], "AGE03": []}
    assert "ordering=-age" in resp.content.decode()

    def codes(ordering):
        return [
            o.code for o in client.get(URL, {"ordering": ordering}).context["orders"]
        ]

    assert codes("age") == ["AGE02", "AGE01", "AGE03"]
    assert codes("-age") == ["AGE01", "AGE02", "AGE03"]


@pytest.mark.django_db
def test_age_column_event_series_and_order_question(admin_settings_client, event, item):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    berlin = ZoneInfo("Europe/Berlin")
    with scopes_disabled():
        event.settings.timezone = "Europe/Berlin"
        event.has_subevents = True
        event.date_from = datetime(2027, 1, 1, 10, 0, tzinfo=berlin)
        event.save()
        summer = event.subevents.create(
            name="Summer", date_from=datetime(2027, 7, 10, 10, 0, tzinfo=berlin)
        )
        dob = event.questions.create(
            question="Date of birth", identifier="dob", type="D"
        )
        o = _order(event, "SER01")
        p = _position(o, item, "Anna", subevent=summer)
        p.answers.create(question=dob, answer="2015-07-10")
        order_dob = event.questions.create(
            question="Contact person born",
            identifier="cdob",
            type="D",
            container_type=Question.ContainerType.ORDER,
        )
        o2 = _order(event, "ORD02")
        _position(o2, item, "Ben")
        o2.answers.create(question=order_dob, answer="2000-06-01")
        event.settings.participantlist_orders_show_age = True
        branding = OrganizerBranding.objects.create(
            organizer=event.organizer, birth_date_question="dob"
        )
    rows = {o.code: o.ages for o in admin_settings_client.get(URL).context["orders"]}
    # Age on the date of the ticket (10 July 2027), not on the series start.
    assert rows["SER01"] == [12]

    with scopes_disabled():
        branding.birth_date_question = "cdob"
        branding.save()
    rows = {o.code: o.ages for o in admin_settings_client.get(URL).context["orders"]}
    assert rows["ORD02"] == [26]


@pytest.mark.django_db
def test_age_column_hidden_for_non_date_question(admin_settings_client, event, item):
    with scopes_disabled():
        q = _question(event, item, "Sektion", "sektion")
        event.settings.participantlist_orders_show_age = True
        OrganizerBranding.objects.create(
            organizer=event.organizer, birth_date_question=q.identifier
        )
        _position(_order(event, "ORD01"), item, "Anna")
    resp = admin_settings_client.get(URL, {"ordering": "age"})
    assert resp.context["age_question"] is None
    assert not hasattr(resp.context["orders"][0], "ages")
