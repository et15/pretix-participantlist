from django.utils.translation import gettext_lazy

from . import __version__

try:
    from pretix.base.plugins import PLUGIN_LEVEL_ORGANIZER, PluginConfig
except ImportError:
    raise RuntimeError(
        "Please use pretix 2026.9.0 or above to run this plugin!",
    ) from None


class PluginApp(PluginConfig):
    default = True
    name = "pretix_participantlist"
    verbose_name = "Participant List Export"

    class PretixPluginMeta:
        name = gettext_lazy("Participant List Export")
        author = "ET15"
        description = gettext_lazy(
            "Exports attendees as customizable participant lists (PDF and CSV) "
            "and lists the attendees of each order"
        )
        visible = True
        version = __version__
        category = "FORMAT"
        compatibility = "pretix>=2026.9.0"
        level = PLUGIN_LEVEL_ORGANIZER
        settings_links = []
        navigation_links = []

    def ready(self):
        from . import logs, settings, signals  # NOQA
