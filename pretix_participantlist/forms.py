from django import forms
from django.conf import settings
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from pretix.base.forms import SettingsForm
from pretix.control.forms import ExtFileField

from .fields import (
    NON_SORTABLE_STATIC_FIELDS,
    STATIC_FIELD_CHOICES,
    birth_date_question_identifier,
    event_birth_date_question,
    event_checkin_list,
    format_column_spec,
    format_sort_spec,
    organizer_date_question_choices,
    parse_column_spec,
    parse_default_fields,
    parse_sort_spec,
    serialize_column_groups,
)
from .models import ListConfiguration, OrganizerBranding
from .settings import (
    COLUMN_DATETIME,
    COLUMN_PAYMENT,
    ORDERS_QUESTION_COLUMNS_KEY,
    ORDERS_SHOW_AGE_KEY,
    ORDERS_SHOW_CHECKIN_KEY,
    ORDERS_STANDARD_COLUMNS_KEY,
)


class BrandingForm(forms.ModelForm):
    logo = ExtFileField(
        required=False,
        label=_("Logo"),
        ext_whitelist=settings.FILE_UPLOAD_EXTENSIONS_IMAGE,
        max_size=settings.FILE_UPLOAD_MAX_SIZE_IMAGE,
        help_text=_("Shown in the header of every generated PDF list."),
    )

    class Meta:
        model = OrganizerBranding
        fields = (
            "logo",
            "header_text",
            "logo_width_mm",
            "logo_height_mm",
            "filename_prefix",
            "birth_date_question",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        organizer = getattr(self.instance, "organizer", None)
        choices = list(organizer_date_question_choices(organizer))
        current = self.instance.birth_date_question
        if current and current not in {identifier for identifier, _l in choices}:
            # Keep a stored identifier selectable even if no event uses it
            # (anymore), so saving the form doesn't silently clear it.
            choices.append((current, current))
        field = self.fields["birth_date_question"]
        self.fields["birth_date_question"] = forms.ChoiceField(
            label=field.label,
            help_text=field.help_text,
            required=False,
            choices=[("", "---------")]
            + [
                (identifier, f"{label} ({identifier})") for identifier, label in choices
            ],
        )


class ListConfigurationForm(forms.ModelForm):
    columns_text = forms.CharField(
        label=_("Columns"),
        widget=forms.Textarea(attrs={"rows": 8}),
        required=False,
        help_text=_(
            "One column per line, in the order they should appear in the PDF. "
            "Combine two or more fields into a single stacked column by "
            'joining them with "+", e.g. "email+ticket". Append "=Title" to set '
            'the column header, e.g. "email+ticket=Contact"; without it the '
            "header is made up of the fields' own names; use \\n in the title "
            "for a line break."
        ),
    )
    sort_text = forms.CharField(
        label=_("Sort by"),
        widget=forms.Textarea(attrs={"rows": 4}),
        required=False,
        help_text=_(
            "One field per line, in priority order (the first line is the "
            "primary sort key, further lines break ties). Prefix a field "
            'with "-" for descending order, e.g. "-name". Leave empty to '
            "keep attendees in the order they were registered."
        ),
    )

    class Meta:
        model = ListConfiguration
        fields = ("name", "is_confidential", "include_pending", "filename_suffix")

    def __init__(self, *args, organizer=None, **kwargs):
        self.organizer = organizer
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            groups = parse_default_fields(self.instance.default_fields)
            self.initial["columns_text"] = format_column_spec(groups)
            self.initial["sort_text"] = format_sort_spec(self.instance.sort_fields)

        tokens = [key for key, _label in STATIC_FIELD_CHOICES]
        sortable_tokens = [t for t in tokens if t not in NON_SORTABLE_STATIC_FIELDS]
        help_text = format_html(
            "{} {}",
            self.fields["columns_text"].help_text,
            _("Static fields: %s.") % ", ".join(tokens),
        )
        sort_help_text = format_html(
            "{} {}",
            self.fields["sort_text"].help_text,
            _("Static fields: %s.") % ", ".join(sortable_tokens),
        )
        if organizer:
            placeholders_link = format_html(
                '<a href="{}" target="_blank">{}</a>',
                reverse(
                    "plugins:pretix_participantlist:kinds.placeholders",
                    kwargs={"organizer": organizer.slug},
                ),
                _("Show available placeholders"),
            )
            help_text = format_html("{} {}", help_text, placeholders_link)
            sort_help_text = format_html("{} {}", sort_help_text, placeholders_link)
        self.fields["columns_text"].help_text = help_text
        self.fields["sort_text"].help_text = sort_help_text

    def clean_columns_text(self):
        text = self.cleaned_data.get("columns_text", "")
        try:
            return parse_column_spec(text, self.organizer)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc

    def clean_sort_text(self):
        text = self.cleaned_data.get("sort_text", "")
        try:
            return parse_sort_spec(text, self.organizer)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc

    def save(self, commit=True):
        self.instance.default_fields = serialize_column_groups(
            self.cleaned_data["columns_text"]
        )
        self.instance.sort_fields = self.cleaned_data["sort_text"]
        return super().save(commit=commit)


class OrderListSettingsForm(SettingsForm):
    """Choose the optional columns of the order list ("Orders by attendee")."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        event = self.obj
        self.fields[ORDERS_STANDARD_COLUMNS_KEY] = forms.MultipleChoiceField(
            label=_("Columns"),
            required=False,
            widget=forms.CheckboxSelectMultiple,
            choices=[
                (COLUMN_DATETIME, _("Order date")),
                (COLUMN_PAYMENT, _("Payment method")),
            ],
        )
        self.fields[ORDERS_QUESTION_COLUMNS_KEY] = forms.MultipleChoiceField(
            label=_("Questions as columns"),
            help_text=_(
                "The answers to these questions are shown as additional columns "
                "in the attendee order list, in the order of the questions."
            ),
            required=False,
            widget=forms.CheckboxSelectMultiple,
            choices=[
                (str(q.pk), str(q.question))
                for q in event.questions.order_by("position", "pk")
            ],
        )

        age_question = event_birth_date_question(event)
        if age_question:
            age_help = _(
                'Uses the question "{question}". The column shows the age on the '
                "first day of the event; in an event series, on the date the "
                "ticket is for."
            ).format(question=age_question.question)
        elif birth_date_question_identifier(event.organizer):
            age_help = _(
                'This event has no date question with the identifier "{identifier}" '
                "set as birth date question in the organizer settings (Participant "
                "list → Branding), so the column stays hidden."
            ).format(identifier=birth_date_question_identifier(event.organizer))
        else:
            age_help = _(
                "No birth date question is set in the organizer settings "
                "(Participant list → Branding), so the column stays hidden."
            )
        self.fields[ORDERS_SHOW_AGE_KEY] = forms.BooleanField(
            label=_("Age"), required=False, help_text=age_help
        )

        checkin_list = event_checkin_list(event)
        self.fields[ORDERS_SHOW_CHECKIN_KEY] = forms.BooleanField(
            label=_("Check-in status"),
            required=False,
            help_text=_(
                "Shows whether the attendees have entered at least once, on the "
                "check-in list chosen on the participant list export page "
                "(currently: {list}). Exits, failed scans and add-on products are "
                "not taken into account."
            ).format(
                list=checkin_list.name if checkin_list else _("All check-in lists")
            ),
        )
