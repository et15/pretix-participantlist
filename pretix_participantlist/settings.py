"""Event settings keys of this plugin, registered with pretix' settings store."""

import json

from pretix.base.settings import settings_hierarkey

#: Check-in list used for "checked in" everywhere in this plugin (PDF and CSV
#: exports, order list): "" = entries on any check-in list, otherwise the ID
#: of one check-in list of the event. Chosen on the PDF export page.
CHECKIN_LIST_KEY = "participantlist_checkin_list"

#: Optional standard columns of the order list (see ``COLUMN_*``).
ORDERS_STANDARD_COLUMNS_KEY = "participantlist_orders_standard_columns"
COLUMN_DATETIME = "datetime"
COLUMN_PAYMENT = "payment"
ORDERS_STANDARD_COLUMNS_DEFAULT = [COLUMN_DATETIME, COLUMN_PAYMENT]

#: IDs (as strings) of the questions shown as extra columns of the order list.
ORDERS_QUESTION_COLUMNS_KEY = "participantlist_orders_question_columns"

#: Show the age column (question: the organizer's birth date question).
ORDERS_SHOW_AGE_KEY = "participantlist_orders_show_age"

#: Show the check-in column (list: ``CHECKIN_LIST_KEY``).
ORDERS_SHOW_CHECKIN_KEY = "participantlist_orders_show_checkin"

settings_hierarkey.add_default(CHECKIN_LIST_KEY, "", str)
settings_hierarkey.add_default(
    ORDERS_STANDARD_COLUMNS_KEY, json.dumps(ORDERS_STANDARD_COLUMNS_DEFAULT), list
)
settings_hierarkey.add_default(ORDERS_QUESTION_COLUMNS_KEY, "[]", list)
settings_hierarkey.add_default(ORDERS_SHOW_AGE_KEY, "False", bool)
settings_hierarkey.add_default(ORDERS_SHOW_CHECKIN_KEY, "False", bool)
