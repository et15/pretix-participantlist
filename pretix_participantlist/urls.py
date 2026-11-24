from django.urls import re_path

from . import orderlist, views

_EVENT_PREFIX = r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/participantlist/"

urlpatterns = [
    re_path(
        r"^control/organizer/(?P<organizer>[^/]+)/participantlist/branding/$",
        views.BrandingUpdateView.as_view(),
        name="branding",
    ),
    re_path(
        r"^control/organizer/(?P<organizer>[^/]+)/participantlist/kinds/$",
        views.ListConfigurationListView.as_view(),
        name="kinds",
    ),
    re_path(
        r"^control/organizer/(?P<organizer>[^/]+)/participantlist/kinds/add$",
        views.ListConfigurationCreateView.as_view(),
        name="kinds.add",
    ),
    re_path(
        r"^control/organizer/(?P<organizer>[^/]+)/participantlist/kinds/placeholders$",
        views.ListConfigurationPlaceholdersView.as_view(),
        name="kinds.placeholders",
    ),
    re_path(
        r"^control/organizer/(?P<organizer>[^/]+)/participantlist/kinds/(?P<kind>\d+)/$",
        views.ListConfigurationUpdateView.as_view(),
        name="kinds.edit",
    ),
    re_path(
        r"^control/organizer/(?P<organizer>[^/]+)/participantlist/kinds/(?P<kind>\d+)/delete$",
        views.ListConfigurationDeleteView.as_view(),
        name="kinds.delete",
    ),
    re_path(
        r"^control/organizer/(?P<organizer>[^/]+)/participantlist/kinds/(?P<kind>\d+)/default$",
        views.ListConfigurationSetDefaultView.as_view(),
        name="kinds.default",
    ),
    re_path(
        _EVENT_PREFIX + r"orders/$",
        orderlist.OrderListView.as_view(),
        name="orders",
    ),
    re_path(
        _EVENT_PREFIX + r"orders/settings/$",
        orderlist.OrderListSettingsView.as_view(),
        name="orders.settings",
    ),
]
