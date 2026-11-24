## v0.4.0 (2026-11-24)

### BREAKING CHANGE

- pretix older than 2026.4.0 is no longer supported.

### Feat

- print the event title bold in the PDF header
- list only personalized admission tickets in the multi-event export
- add event slug and name columns to the multi-event export
- require pretix 2026.4.0 or newer
- log list kind, branding, custom list and export actions
- add "checked in" column next to order status
- add "checked-in participants only" option to multi-event export

### Fix

- log the "checked-in participants only" option of CSV exports
- accept only POST for making a list kind the default
- sort by "checked in" by value, not by the translated text

## v0.3.1 (2026-10-23)

### Feat

- hide custom list fields unless the custom list is selected

## v0.3.0 (2026-10-23)

### Feat

- grey out custom list fields unless the custom list is selected
- make saving the custom list optional
- copy a list kind into the custom list on the export page
- add order status column
- list only paid orders by default, add "include pending payments" option

## v0.2.0 (2026-10-18)

### Feat

- add participant list exporter
