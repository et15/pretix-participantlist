import re
import zipfile
from collections import OrderedDict
from io import BytesIO
from typing import ClassVar
from xml.sax.saxutils import escape

from django import forms
from django.db.models import Prefetch
from django.utils.functional import cached_property
from django.utils.text import slugify
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy
from pretix.base.exporter import BaseExporter, ListExporter
from pretix.base.models import Checkin, Order, OrderPosition, Question
from pretix.plugins.reports.exporters import ReportlabExportMixin
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    Flowable,
    Paragraph,
    Table,
    TableStyle,
)

from .fields import (
    NON_SORTABLE_STATIC_FIELDS,
    QUESTION_TOKEN_PREFIX,
    STATIC_FIELD_CHOICES,
    ColumnGroup,
    address_lines,
    birth_date_question_identifier,
    extract_static_field,
    parse_column_spec,
    parse_default_fields,
    parse_sort_spec,
    question_token,
    resolve_field_tokens,
    serialize_column_groups,
)
from .models import ListConfiguration, OrganizerBranding

ALL_KINDS_VALUE = "__all__"
CUSTOM_KIND_VALUE = "__custom__"
CUSTOM_NAME_SETTING = "participantlist_custom_name"
CUSTOM_COLUMNS_SETTING = "participantlist_custom_columns"
CUSTOM_SORT_SETTING = "participantlist_custom_sort"
STATIC_FIELD_LABELS = dict(STATIC_FIELD_CHOICES)
DEFAULT_FILENAME_PREFIX = "Participant-List"
FILENAME_UNSAFE_RE = re.compile(r'[\\/:*?"<>|]')


def _sanitize_filename_part(value):
    return FILENAME_UNSAFE_RE.sub("", value).strip()


HEADER_FONT_SIZE = 12
HEADER_BRAND_FONT_SIZE = 17
HEADER_LINE1_Y = 12 * mm
HEADER_LINE2_Y = 17 * mm
HEADER_RULE_Y = 26 * mm
HEADER_LINE_A_Y = 33 * mm
HEADER_LINE_B_Y = 41 * mm
HEADER_EXTRA_SPACE = 30 * mm
HEADER_TEXT_LOGO_GAP = 8 * mm
DEFAULT_LOGO_WIDTH_MM = 96
DEFAULT_LOGO_HEIGHT_MM = 42
SIGNING_COLUMN_WIDTH = 70 * mm
COLUMN_WEIGHTS = {
    "index": 0.5,
    "age": 0.6,
    "name": 2.2,
    "email": 2.4,
    "order_code": 1.1,
    "ticket": 1.6,
    "company": 1.6,
    "address": 2.4,
}
DEFAULT_COLUMN_WEIGHT = 1.6


class SigningSpaceFlowable(Flowable):
    """Reserved blank space for a hand-written signature. Deliberately draws nothing."""

    def __init__(self, width=SIGNING_COLUMN_WIDTH, height=12 * mm):
        super().__init__()
        self.width = width
        self.height = height

    def wrap(self, availWidth, availHeight):
        self.width = min(self.width, availWidth)
        return self.width, self.height

    def draw(self):
        pass


def _position_queryset(event):
    return (
        OrderPosition.objects.filter(
            order__event=event,
            order__status__in=(Order.STATUS_PAID, Order.STATUS_PENDING),
        )
        .select_related("order", "item", "variation", "order__invoice_address")
        .prefetch_related("answers", "answers__question")
        .order_by("order__code", "positionid")
    )


class AttendeeListPDFExporter(ReportlabExportMixin, BaseExporter):
    identifier = "participantlist_pdf"
    verbose_name = _("Participant list (PDF)")
    category = pgettext_lazy("export_category", "Participant list")
    description = _(
        "Download a PDF attendee list using one of the list kinds configured in the "
        "organizer settings."
    )

    @cached_property
    def _birth_date_identifier(self):
        return birth_date_question_identifier(self.event.organizer)

    @property
    def pagesize(self):
        return landscape(A4)

    def _spec_validator(self, parser):
        organizer = self.event.organizer

        def validate(value):
            try:
                parser(value, organizer)
            except ValueError as exc:
                raise forms.ValidationError(str(exc)) from exc

        return validate

    @property
    def export_form_fields(self):
        kinds = list(ListConfiguration.objects.filter(organizer=self.event.organizer))
        kind_choices = (
            [(ALL_KINDS_VALUE, _("(All kinds)"))]
            + [(str(k.pk), k.name) for k in kinds]
            + [(CUSTOM_KIND_VALUE, _("Custom list"))]
        )
        default_kind = next(
            (k for k in kinds if k.is_default), kinds[0] if kinds else None
        )
        tokens = [key for key, _label in STATIC_FIELD_CHOICES]
        sortable_tokens = [t for t in tokens if t not in NON_SORTABLE_STATIC_FIELDS]

        return OrderedDict(
            [
                (
                    "list",
                    forms.ChoiceField(
                        label=_("List kind"),
                        choices=kind_choices,
                        initial=str(default_kind.pk)
                        if default_kind
                        else ALL_KINDS_VALUE,
                        widget=forms.RadioSelect
                        if len(kind_choices) <= 5
                        else forms.Select,
                    ),
                ),
                (
                    "custom_name",
                    forms.CharField(
                        label=_("Custom list: title"),
                        max_length=190,
                        required=False,
                        initial=self.event.settings.get(CUSTOM_NAME_SETTING) or "",
                        help_text=_(
                            'Only used for the kind "Custom list", saved with '
                            "this event. Shown in the header of the PDF. Defaults "
                            'to "Custom list" if left empty.'
                        ),
                    ),
                ),
                (
                    "custom_columns",
                    forms.CharField(
                        label=_("Custom list: columns"),
                        widget=forms.Textarea(attrs={"rows": 8}),
                        required=False,
                        initial=self.event.settings.get(CUSTOM_COLUMNS_SETTING) or "",
                        validators=[self._spec_validator(parse_column_spec)],
                        help_text=_(
                            'Only used for the kind "Custom list", saved with '
                            "this event. One column per line, in the order they "
                            "should appear in the PDF. Combine two or more fields "
                            'into a single stacked column by joining them with "+", '
                            'e.g. "email+ticket". Append "=Title" to set the column '
                            'header, e.g. "email+ticket=Contact"; without it the '
                            "header is made up of the fields' own names; use \\n in "
                            "the title for a line break. Static fields: %s. "
                            'Questions: "question:<identifier>".'
                        )
                        % ", ".join(tokens),
                    ),
                ),
                (
                    "custom_sort",
                    forms.CharField(
                        label=_("Custom list: sort by"),
                        widget=forms.Textarea(attrs={"rows": 4}),
                        required=False,
                        initial=self.event.settings.get(CUSTOM_SORT_SETTING) or "",
                        validators=[self._spec_validator(parse_sort_spec)],
                        help_text=_(
                            'Only used for the kind "Custom list", saved with '
                            "this event. One field per line, in priority order. "
                            'Prefix a field with "-" for descending order, e.g. '
                            '"-name". Static fields: %s.'
                        )
                        % ", ".join(sortable_tokens),
                    ),
                ),
            ]
        )

    def render(self, form_data):
        self.form_data = form_data
        kind_value = form_data.get("list") or ALL_KINDS_VALUE
        if kind_value == CUSTOM_KIND_VALUE:
            self._save_custom_definition(form_data)
        elif kind_value == ALL_KINDS_VALUE:
            kinds = list(
                ListConfiguration.objects.filter(organizer=self.event.organizer)
            )
            if len(kinds) > 1:
                return self._render_archive(form_data, kinds)
        organizer = self.event.organizer
        branding = OrganizerBranding.objects.filter(organizer=organizer).first()
        kind = self._resolve_kind(form_data, organizer)
        filename = f"{self._build_filename(branding, kind)}.pdf"
        return filename, "application/pdf", self.create(form_data)

    def _custom_kind(self, form_data, organizer):
        """An unsaved ``ListConfiguration`` built from the custom list texts."""
        columns = parse_column_spec(form_data.get("custom_columns"), organizer)
        sort_fields = parse_sort_spec(form_data.get("custom_sort"), organizer)
        return ListConfiguration(
            organizer=organizer,
            name=(form_data.get("custom_name") or "").strip() or str(_("Custom list")),
            default_fields=serialize_column_groups(columns),
            sort_fields=sort_fields,
        )

    def _save_custom_definition(self, form_data):
        for setting, key in (
            (CUSTOM_NAME_SETTING, "custom_name"),
            (CUSTOM_COLUMNS_SETTING, "custom_columns"),
            (CUSTOM_SORT_SETTING, "custom_sort"),
        ):
            value = form_data.get(key) or ""
            if (self.event.settings.get(setting) or "") != value:
                self.event.settings.set(setting, value)

    def _resolve_kind(self, form_data, organizer):
        kind_value = form_data.get("list") or ALL_KINDS_VALUE
        if kind_value == CUSTOM_KIND_VALUE:
            return self._custom_kind(form_data, organizer)
        if kind_value == ALL_KINDS_VALUE:
            return ListConfiguration.objects.filter(organizer=organizer).first()
        return ListConfiguration.objects.filter(
            organizer=organizer, pk=kind_value
        ).first()

    def _filename_date(self):
        tz = self.event.timezone
        return now().astimezone(tz).strftime("%Y-%m-%d")

    def _build_filename(self, branding, kind, fallback_suffix=""):
        prefix = (
            _sanitize_filename_part(
                (branding.filename_prefix if branding else "")
                or DEFAULT_FILENAME_PREFIX
            )
            or DEFAULT_FILENAME_PREFIX
        )
        parts = [prefix, self.event.slug, self._filename_date()]
        suffix = (
            _sanitize_filename_part(kind.filename_suffix)
            if kind and kind.filename_suffix
            else ""
        ) or fallback_suffix
        if suffix:
            parts.append(suffix)
        return "_".join(parts)

    def _render_archive(self, form_data, kinds):
        organizer = self.event.organizer
        branding = OrganizerBranding.objects.filter(organizer=organizer).first()
        buffer = BytesIO()
        used_names = set()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for kind in kinds:
                pdf_data = self.create({**form_data, "list": str(kind.pk)})
                fallback_suffix = slugify(kind.name) or str(kind.pk)
                base_name = self._build_filename(
                    branding, kind, fallback_suffix=fallback_suffix
                )
                name = base_name
                suffix = 2
                while name in used_names:
                    name = f"{base_name}-{suffix}"
                    suffix += 1
                used_names.add(name)
                zf.writestr(f"{name}.pdf", pdf_data)
        archive_name = self._build_filename(branding, None)
        return (
            f"{archive_name}.zip",
            "application/zip",
            buffer.getvalue(),
        )

    def get_frames(self, doc):
        from reportlab.platypus import Frame

        self.frame = Frame(
            doc.leftMargin,
            doc.bottomMargin,
            doc.width,
            doc.height - HEADER_EXTRA_SPACE,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
            id="normal",
        )
        return [self.frame]

    def get_story(self, doc, form_data):
        # render() routes any "(all kinds)" export with more than one kind
        # through _render_archive (one PDF per kind), so by the time we get
        # here there is at most a single kind to render.
        organizer = self.event.organizer
        branding = OrganizerBranding.objects.filter(organizer=organizer).first()
        self._branding = branding
        kind = self._resolve_kind(form_data, organizer)

        self._confidential = bool(kind and kind.is_confidential)
        self._current_kind_name = kind.name if kind else None

        return self._build_section(doc, kind, form_data)

    def _groups_from_kind(self, kind):
        """Respect the kind's configured column order and grouping."""
        raw_groups = parse_default_fields(kind.default_fields)
        identifiers = {
            token[len(QUESTION_TOKEN_PREFIX) :]
            for group in raw_groups
            for token in group
            if token.startswith(QUESTION_TOKEN_PREFIX)
        }
        questions_by_identifier = {
            q.identifier: q
            for q in Question.objects.filter(
                event=self.event, identifier__in=identifiers
            )
        }

        groups = []
        for raw_group in raw_groups:
            group = ColumnGroup(label=raw_group.label)
            for token in raw_group:
                if token.startswith(QUESTION_TOKEN_PREFIX):
                    question = questions_by_identifier.get(
                        token[len(QUESTION_TOKEN_PREFIX) :]
                    )
                    if question:
                        group.append(("question", question))
                elif token in STATIC_FIELD_LABELS:
                    group.append(("static", token))
            if group:
                groups.append(group)
        return groups

    def _resolve_groups(self, kind):
        groups = self._groups_from_kind(kind) if kind else []
        return groups or [
            ColumnGroup([("static", "name")]),
            ColumnGroup([("static", "ticket")]),
        ]

    def _sorted_positions(self, kind):
        positions = list(_position_queryset(self.event))
        if not kind or not kind.sort_fields:
            return positions
        sort_fields = resolve_field_tokens(kind.sort_fields, self.event)
        if not sort_fields:
            return positions

        def sort_value(position, col_kind, field):
            if col_kind == "question":
                answers_by_question = {a.question_id: a for a in position.answers.all()}
                answer = answers_by_question.get(field.pk)
                return str(answer).lower() if answer else ""
            value = extract_static_field(
                position, field, birth_date_identifier=self._birth_date_identifier
            )
            if field == "age" and value != "":
                # Zero-pad so ages sort numerically ("9" before "10").
                return f"{value:03d}"
            return str(value).lower()

        # Python's sort is stable, so sorting once per key from least to
        # most significant (each with its own direction) yields a correct
        # combined multi-key, mixed-direction sort.
        for col_kind, field, descending in reversed(sort_fields):
            positions.sort(
                key=lambda p, k=col_kind, f=field: sort_value(p, k, f),
                reverse=descending,
            )
        return positions

    def _column_widths(self, doc, groups):
        def is_signing(group):
            return any(key == "signing" for _col_kind, key in group)

        def group_weight(group):
            return max(
                COLUMN_WEIGHTS.get(key, DEFAULT_COLUMN_WEIGHT)
                for _col_kind, key in group
            )

        fixed_total = sum(SIGNING_COLUMN_WIDTH for g in groups if is_signing(g))
        weight_sum = sum(group_weight(g) for g in groups if not is_signing(g))
        available = doc.width - fixed_total

        widths = []
        for group in groups:
            if is_signing(group):
                widths.append(SIGNING_COLUMN_WIDTH)
            else:
                widths.append(available * group_weight(group) / weight_sum)
        return widths

    def _column_label(self, col_kind, key):
        if col_kind == "static":
            if key == "index":
                return ""
            return str(STATIC_FIELD_LABELS[key])
        return str(key.question)

    def _group_header(self, group):
        """The group's own title, else its members' labels stacked."""
        label = getattr(group, "label", "")
        if label:
            # A literal backslash-n in the title is a line break; the column
            # spec is line-based, so a real newline can't be typed there.
            return "<br/>".join(escape(part) for part in label.split("\\n"))
        return "<br/>".join(
            escape(self._column_label(col_kind, key)) for col_kind, key in group
        )

    def _column_lines(self, position, group, answers_by_question, index):
        lines = []
        for col_kind, key in group:
            if col_kind == "question":
                answer = answers_by_question.get(key.pk)
                if answer:
                    # QuestionAnswer.to_string() renders booleans as "Yes"/"No"
                    # (translated) and formats dates/choices/files sensibly,
                    # instead of exposing the raw stored answer string.
                    lines.append(str(answer))
            elif key == "address":
                lines.extend(address_lines(position))
            elif key != "signing":
                value = extract_static_field(
                    position, key, index, self._birth_date_identifier
                )
                if value != "":
                    lines.append(str(value))
        return lines

    def _build_section(self, doc, kind, form_data):
        elements = []

        groups = self._resolve_groups(kind)

        styles = getSampleStyleSheet()
        header_style = ParagraphStyle(
            "TableHeader",
            parent=styles["Normal"],
            fontSize=9,
            leading=11,
            textColor=colors.black,
            fontName="Helvetica-Bold",
        )
        cell_style = ParagraphStyle(
            "TableCell", parent=styles["Normal"], fontSize=9, leading=11
        )

        headers = [
            Paragraph(self._group_header(group), header_style) for group in groups
        ]
        table_data = [headers]

        for index, position in enumerate(self._sorted_positions(kind), start=1):
            answers_by_question = {a.question_id: a for a in position.answers.all()}
            row = []
            for group in groups:
                if group == [("static", "signing")]:
                    row.append(SigningSpaceFlowable())
                    continue
                lines = self._column_lines(position, group, answers_by_question, index)
                text = "<br/>".join(escape(line) for line in lines)
                row.append(Paragraph(text, cell_style))
            table_data.append(row)

        col_widths = self._column_widths(doc, groups)
        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.white),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                    ("TOPPADDING", (0, 1), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                    # Bold rule separating the header row from the table body
                    # (also repeated under the header on following pages).
                    ("LINEBELOW", (0, 0), (-1, 0), 2, colors.black),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elements.append(table)
        return elements

    def _logo_box_size(self):
        branding = getattr(self, "_branding", None)
        if not (branding and branding.logo):
            return None
        width = (branding.logo_width_mm or DEFAULT_LOGO_WIDTH_MM) * mm
        height = (branding.logo_height_mm or DEFAULT_LOGO_HEIGHT_MM) * mm
        return width, height

    def _fit_text(self, text, font_name, font_size, max_width):
        lines = simpleSplit(text, font_name, font_size, max_width)
        if len(lines) > 1:
            return lines[0] + " …"
        return text

    def page_header(self, canvas, doc):
        font_name = "OpenSans"
        bold_font_name = "OpenSansBd"
        branding = getattr(self, "_branding", None)
        box_size = self._logo_box_size()
        reserved_width = (box_size[0] + HEADER_TEXT_LOGO_GAP) if box_size else 0
        text_max_width = (
            self.pagesize[0] - doc.leftMargin - doc.rightMargin - reserved_width
        )

        # Above the rule: the event name and date range, as before.
        canvas.setFont(font_name, HEADER_FONT_SIZE)
        canvas.drawString(
            doc.leftMargin,
            self.pagesize[1] - HEADER_LINE1_Y,
            self._fit_text(
                str(self.event.name), font_name, HEADER_FONT_SIZE, text_max_width
            ),
        )
        canvas.drawString(
            doc.leftMargin,
            self.pagesize[1] - HEADER_LINE2_Y,
            self._fit_text(
                self.event.get_date_range_display(),
                font_name,
                HEADER_FONT_SIZE,
                text_max_width,
            ),
        )

        rule_y = self.pagesize[1] - HEADER_RULE_Y
        canvas.setStrokeColorRGB(0, 0, 0)
        canvas.line(doc.leftMargin, rule_y, self.pagesize[0] - doc.rightMargin, rule_y)

        # Below the rule, beside the logo: the branding name (bold) and the
        # current list kind's name (same font, not bold).
        header_text = (
            branding.header_text if branding and branding.header_text else ""
        ) or str(self.event.name)
        canvas.setFont(bold_font_name, HEADER_BRAND_FONT_SIZE)
        canvas.drawString(
            doc.leftMargin,
            self.pagesize[1] - HEADER_LINE_A_Y,
            self._fit_text(
                header_text, bold_font_name, HEADER_BRAND_FONT_SIZE, text_max_width
            ),
        )

        kind_name = getattr(self, "_current_kind_name", None)
        if kind_name:
            canvas.setFont(font_name, HEADER_BRAND_FONT_SIZE)
            canvas.drawString(
                doc.leftMargin,
                self.pagesize[1] - HEADER_LINE_B_Y,
                self._fit_text(
                    kind_name, font_name, HEADER_BRAND_FONT_SIZE, text_max_width
                ),
            )

        self._draw_logo(canvas, doc, rule_y, box_size)

    def _draw_logo(self, canvas, doc, rule_y, box_size):
        branding = getattr(self, "_branding", None)
        if not box_size:
            return
        try:
            with branding.logo.open("rb") as fh:
                data = fh.read()
        except OSError:
            return

        image = ImageReader(BytesIO(data))
        native_width, native_height = image.getSize()
        box_width, box_height = box_size
        scale = min(box_width / native_width, box_height / native_height)
        draw_width = native_width * scale
        draw_height = native_height * scale
        x = self.pagesize[0] - doc.rightMargin - draw_width
        y = rule_y - draw_height / 2
        canvas.drawImage(image, x, y, width=draw_width, height=draw_height, mask="auto")

    def page_footer(self, canvas, doc):
        super().page_footer(canvas, doc)
        if not getattr(self, "_confidential", False):
            return

        canvas.saveState()
        font_size = 8
        bold_part = str(_("confidential"))
        rest_part = " – " + str(_("do not distribute"))
        bold_width = stringWidth(bold_part, "OpenSansBd", font_size)
        rest_width = stringWidth(rest_part, "OpenSans", font_size)
        x = (self.pagesize[0] - bold_width - rest_width) / 2
        y = 10 * mm
        canvas.setFont("OpenSansBd", font_size)
        canvas.drawString(x, y, bold_part)
        canvas.setFont("OpenSans", font_size)
        canvas.drawString(x + bold_width, y, rest_part)
        canvas.restoreState()


class AttendeeListCSVExporter(ListExporter):
    identifier = "participantlist_csv"
    verbose_name = _("Participant list (CSV, multiple events)")
    category = pgettext_lazy("export_category", "Participant list")
    description = _(
        "Download attendees across multiple events as a single CSV/XLSX file."
    )

    CSV_FIELD_CHOICES: ClassVar = [c for c in STATIC_FIELD_CHOICES if c[0] != "signing"]
    #: Per-position data that only the multi-event export offers.
    CHECKIN_FIELD_CHOICES: ClassVar = [
        ("checked_in", _("Checked in")),
        ("last_checkin", _("Last check-in")),
    ]
    DEFAULT_CSV_FIELDS: ClassVar = ["name", "email", "order_code", "ticket"]

    def _question_choices(self):
        """One (token, label) choice per question identifier on the events.

        The same identifier on several events is a single column; the label
        is taken from the first event's question text.
        """
        labels = {}
        questions = (
            Question.objects.filter(event__in=self.events)
            .exclude(identifier="")
            .order_by("position", "pk")
        )
        for question in questions:
            labels.setdefault(question.identifier, str(question.question))
        return [
            (question_token(identifier), label) for identifier, label in labels.items()
        ]

    @property
    def additional_form_fields(self):
        return OrderedDict(
            [
                (
                    "fields",
                    forms.MultipleChoiceField(
                        label=_("Fields"),
                        choices=self.CSV_FIELD_CHOICES
                        + self.CHECKIN_FIELD_CHOICES
                        + self._question_choices(),
                        initial=self.DEFAULT_CSV_FIELDS,
                        widget=forms.CheckboxSelectMultiple,
                        required=False,
                    ),
                ),
            ]
        )

    def get_filename(self):
        return "participant_list_all"

    def _csv_header(self, key, question_labels):
        if key.startswith(QUESTION_TOKEN_PREFIX):
            identifier = key[len(QUESTION_TOKEN_PREFIX) :]
            return question_labels.get(identifier, identifier)
        if key == "index":
            return "index"
        return str(
            dict(self.CHECKIN_FIELD_CHOICES).get(key) or STATIC_FIELD_LABELS[key]
        )

    @staticmethod
    def _checkin_value(position, key):
        """Check-in data from the position's successful entry check-ins.

        "Checked in" means at least one successful entry on any check-in list
        of the event, whether or not the person has left again since.
        """
        entries = position.entry_checkins
        if key == "checked_in":
            return str(_("Yes") if entries else _("No"))
        if not entries:
            return ""
        last = max(c.datetime for c in entries)
        return last.astimezone(position.order.event.timezone).strftime("%Y-%m-%d %H:%M")

    def iterate_list(self, form_data):
        fields = form_data.get("fields") or self.DEFAULT_CSV_FIELDS
        question_labels = {
            token[len(QUESTION_TOKEN_PREFIX) :]: label
            for token, label in self._question_choices()
        }
        yield [self._csv_header(key, question_labels) for key in fields]

        qs = (
            OrderPosition.objects.filter(
                order__event__in=self.events,
                order__status__in=(Order.STATUS_PAID, Order.STATUS_PENDING),
            )
            .select_related(
                "order", "item", "variation", "order__invoice_address", "order__event"
            )
            .prefetch_related("answers", "answers__question")
            .order_by("order__event__date_from", "order__code", "positionid")
        )
        checkin_keys = {key for key, _label in self.CHECKIN_FIELD_CHOICES}
        if checkin_keys.intersection(fields):
            qs = qs.prefetch_related(
                Prefetch(
                    "all_checkins",
                    queryset=Checkin.objects.filter(
                        successful=True, type=Checkin.TYPE_ENTRY
                    ),
                    to_attr="entry_checkins",
                )
            )
        birth_date_identifier = birth_date_question_identifier(self.organizer)
        for index, position in enumerate(qs, start=1):
            answers = {a.question.identifier: str(a) for a in position.answers.all()}
            row = []
            for key in fields:
                if key.startswith(QUESTION_TOKEN_PREFIX):
                    row.append(answers.get(key[len(QUESTION_TOKEN_PREFIX) :], ""))
                elif key in checkin_keys:
                    row.append(self._checkin_value(position, key))
                else:
                    row.append(
                        extract_static_field(
                            position, key, index, birth_date_identifier
                        )
                    )
            yield row
