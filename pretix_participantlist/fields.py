import datetime
from collections import namedtuple

from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy
from pretix.base.models import Question

# pretix' own catalog translates a plain "Signature" as "Signatur", which would
# win over ours; the message context keeps our "Unterschrift" effective.
STATIC_FIELD_CHOICES = [
    ("index", _("Index")),
    ("name", _("Name")),
    ("first_name", _("First name")),
    ("last_name", _("Last name")),
    ("age", _("Age")),
    ("email", _("Email")),
    ("order_code", _("Order code")),
    ("status", _("Order status")),
    ("ticket", _("Ticket type")),
    ("company", _("Company")),
    ("address", _("Address")),
    ("signing", pgettext_lazy("static_field", "Signature")),
]

#: Static fields whose value depends on row position rather than attendee
#: data, so they can't be used as a sort key.
NON_SORTABLE_STATIC_FIELDS = {"signing", "index"}

STATIC_FIELD_KEYS = [key for key, _label in STATIC_FIELD_CHOICES]

QUESTION_TOKEN_PREFIX = "question:"


def question_token(identifier):
    return f"{QUESTION_TOKEN_PREFIX}{identifier}"


QuestionPlaceholder = namedtuple(
    "QuestionPlaceholder", ["identifier", "question", "type_label", "events"]
)


def organizer_question_details(organizer):
    """Distinct question identifiers across an organizer's events, with details."""
    if not organizer:
        return []
    seen = {}
    qs = (
        Question.objects.filter(event__organizer=organizer)
        .select_related("event")
        .order_by("position")
    )
    for q in qs:
        if not q.identifier:
            continue
        entry = seen.setdefault(
            q.identifier,
            {
                "question": str(q.question),
                "type_label": str(q.get_type_display()),
                "events": set(),
            },
        )
        entry["events"].add(q.event.slug)
    return [
        QuestionPlaceholder(
            identifier, data["question"], data["type_label"], sorted(data["events"])
        )
        for identifier, data in seen.items()
    ]


def organizer_date_question_choices(organizer):
    """Like ``organizer_question_choices``, limited to date questions."""
    if not organizer:
        return []
    choices = {}
    qs = Question.objects.filter(
        event__organizer=organizer, type=Question.TYPE_DATE
    ).order_by("position")
    for q in qs:
        if q.identifier:
            choices.setdefault(q.identifier, str(q.question))
    return list(choices.items())


def organizer_question_choices(organizer):
    """Distinct (identifier, question text) pairs across an organizer's events."""
    return [(d.identifier, d.question) for d in organizer_question_details(organizer)]


COLUMN_GROUP_SEPARATOR = "+"
COLUMN_LABEL_SEPARATOR = "="


class ColumnGroup(list):
    """Tokens (or resolved columns) sharing one stacked PDF column.

    ``label`` is the optional header title of the column; when empty, the
    header falls back to the labels of the individual members.
    """

    def __init__(self, items=(), label=""):
        super().__init__(items)
        self.label = label


def parse_default_fields(raw):
    """Normalize a stored ``default_fields`` value into a list of column groups.

    A group is 1+ tokens that share a single stacked PDF column, optionally
    with a header label. Accepts the legacy flat-list-of-tokens shape (each
    token becomes its own singleton group), lists of token lists, and
    ``{"tokens": [...], "label": "..."}`` dicts, so kinds saved before column
    grouping/ordering/labels existed keep working unmodified.
    """
    groups = []
    for item in raw or []:
        label = ""
        if isinstance(item, str):
            tokens = [item]
        elif isinstance(item, (list, tuple)):
            tokens = item
        elif isinstance(item, dict):
            tokens = item.get("tokens") or []
            label = item.get("label")
            label = label if isinstance(label, str) else ""
        else:
            continue
        tokens = [t for t in tokens if isinstance(t, str) and t]
        if tokens:
            groups.append(ColumnGroup(tokens, label))
    return groups


def serialize_column_groups(groups):
    """Storable ``default_fields`` value; unlabeled groups stay plain lists."""
    return [
        {"tokens": list(group), "label": group.label}
        if getattr(group, "label", "")
        else list(group)
        for group in groups
    ]


def format_column_spec(groups):
    """Serialize column groups into the "+"-per-line DSL text for editing."""
    lines = []
    for group in groups:
        line = COLUMN_GROUP_SEPARATOR.join(group)
        label = getattr(group, "label", "")
        if label:
            line += COLUMN_LABEL_SEPARATOR + label
        lines.append(line)
    return "\n".join(lines)


def _known_column_tokens(organizer):
    tokens = set(STATIC_FIELD_KEYS)
    tokens.update(
        question_token(identifier)
        for identifier, _label in organizer_question_choices(organizer)
    )
    return tokens


SORT_DESCENDING_PREFIX = "-"


def split_sort_direction(token):
    """Split a "-"-prefixed sort token into (base_token, descending)."""
    if token.startswith(SORT_DESCENDING_PREFIX):
        return token[len(SORT_DESCENDING_PREFIX) :], True
    return token, False


def parse_sort_spec(text, organizer):
    """Parse one sort field per line into an ordered list of tokens.

    A field may be prefixed with "-" for descending order (e.g. "-name").
    Unlike columns, sort fields can't be grouped/stacked and "signing" isn't
    a sortable value. Raises ValueError with a human-readable message on
    invalid input.
    """
    known = _known_column_tokens(organizer) - NON_SORTABLE_STATIC_FIELDS
    seen = set()
    tokens = []
    for raw_line in (text or "").splitlines():
        raw_token = raw_line.strip()
        if not raw_token:
            continue
        token, _descending = split_sort_direction(raw_token)
        if token not in known:
            raise ValueError(_('Unknown field "%s".') % token)
        if token in seen:
            raise ValueError(_('Field "%s" is used more than once.') % token)
        seen.add(token)
        tokens.append(raw_token)
    return tokens


def format_sort_spec(tokens):
    """Serialize a flat list of sort tokens into the one-per-line DSL text."""
    return "\n".join(tokens or [])


def resolve_field_tokens(tokens, event):
    """Resolve flat, optionally "-"-prefixed sort tokens against an event.

    Returns a list of (col_kind, field, descending) tuples. Question
    identifiers with no matching question on this event are skipped, same
    as the column-grouping resolution does.
    """
    parsed = [split_sort_direction(t) for t in tokens]
    identifiers = {
        token[len(QUESTION_TOKEN_PREFIX) :]
        for token, _descending in parsed
        if token.startswith(QUESTION_TOKEN_PREFIX)
    }
    questions_by_identifier = {
        q.identifier: q
        for q in Question.objects.filter(event=event, identifier__in=identifiers)
    }
    resolved = []
    for token, descending in parsed:
        if token.startswith(QUESTION_TOKEN_PREFIX):
            question = questions_by_identifier.get(token[len(QUESTION_TOKEN_PREFIX) :])
            if question:
                resolved.append(("question", question, descending))
        elif token in STATIC_FIELD_KEYS:
            resolved.append(("static", token, descending))
    return resolved


def parse_column_spec(text, organizer):
    """Parse the "+"-per-line DSL into column groups, validating tokens.

    A line may end in "=Title" to set the column's header; only the first "="
    splits, so the title itself may contain "+" or "=". Raises ValueError with
    a human-readable message on invalid input.
    """
    known = _known_column_tokens(organizer)
    seen = set()
    groups = []
    for raw_line in (text or "").splitlines():
        spec, _sep, label = raw_line.partition(COLUMN_LABEL_SEPARATOR)
        tokens = [t.strip() for t in spec.split(COLUMN_GROUP_SEPARATOR)]
        tokens = [t for t in tokens if t]
        if not tokens:
            continue
        for token in tokens:
            if token not in known:
                raise ValueError(_('Unknown field "%s".') % token)
            if token in seen:
                raise ValueError(_('Field "%s" is used more than once.') % token)
            seen.add(token)
        if "signing" in tokens and len(tokens) > 1:
            raise ValueError(_("“Signature” can't be combined with another field."))
        groups.append(ColumnGroup(tokens, label.strip()))
    return groups


def _invoice_address(position):
    try:
        return position.order.invoice_address
    except ObjectDoesNotExist:
        return None


def _attendee_name(position):
    if position.attendee_name:
        return position.attendee_name
    ia = _invoice_address(position)
    if ia and ia.name:
        return ia.name
    return position.order.email or ""


def _name_part(position, key):
    """A single name-scheme part (e.g. "given_name"), where available.

    Not every pretix name scheme has separate given/family name parts (the
    legacy "full name only" import format doesn't), so this can come back
    empty even when ``_attendee_name`` has a value.
    """
    parts = position.attendee_name_parts or {}
    value = parts.get(key)
    if not value:
        ia = _invoice_address(position)
        if ia:
            value = (ia.name_parts or {}).get(key)
    return value or ""


def _attendee_email(position):
    return position.attendee_email or position.order.email or ""


def _attendee_company(position):
    if position.company:
        return position.company
    ia = _invoice_address(position)
    if ia and ia.company:
        return ia.company
    return ""


def _address_parts(position):
    street = position.street
    zipcode = position.zipcode
    city = position.city
    country = position.country
    if not (street or zipcode or city):
        ia = _invoice_address(position)
        if ia:
            street, zipcode, city, country = ia.street, ia.zipcode, ia.city, ia.country
    return [
        street,
        f"{zipcode or ''} {city or ''}".strip(),
        str(country.name) if country else "",
    ]


def _attendee_address(position):
    return ", ".join(p for p in _address_parts(position) if p)


def address_lines(position):
    """Return the non-empty address parts, for callers that render one per line."""
    return [p for p in _address_parts(position) if p]


def _ticket_name(position):
    name = str(position.item.name)
    if position.variation:
        name = f"{name} – {position.variation.value}"
    return name


def birth_date_question_identifier(organizer):
    """The organizer-wide identifier of the birth date question, or ""."""
    from .models import OrganizerBranding

    branding = OrganizerBranding.objects.filter(organizer=organizer).first()
    return branding.birth_date_question if branding else ""


def _birth_date(position, identifier):
    if not identifier:
        return None
    for answer in position.answers.all():
        if answer.question.identifier != identifier:
            continue
        try:
            return datetime.date.fromisoformat(answer.answer)
        except ValueError:
            return None
    return None


def _event_start_date(position):
    event = position.order.event
    if position.subevent_id:
        return position.subevent.date_from.astimezone(event.timezone).date()
    return event.date_from.astimezone(event.timezone).date()


def _attendee_age(position, birth_date_identifier):
    """Age in full years on the event's first day, from the birth date answer.

    The birth date is the answer to the question with the organizer's
    configured identifier; without such an answer the age is empty.
    """
    birth_date = _birth_date(position, birth_date_identifier)
    if not birth_date:
        return ""
    start = _event_start_date(position)
    age = start.year - birth_date.year
    if (start.month, start.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def extract_static_field(position, key, index=None, birth_date_identifier=""):
    if key == "index":
        return index if index is not None else ""
    if key == "name":
        return _attendee_name(position)
    if key == "first_name":
        return _name_part(position, "given_name")
    if key == "last_name":
        return _name_part(position, "family_name")
    if key == "age":
        return _attendee_age(position, birth_date_identifier)
    if key == "email":
        return _attendee_email(position)
    if key == "order_code":
        return position.order.code
    if key == "status":
        return str(position.order.get_status_display())
    if key == "ticket":
        return _ticket_name(position)
    if key == "company":
        return _attendee_company(position)
    if key == "address":
        return _attendee_address(position)
    if key == "signing":
        return ""
    return ""
