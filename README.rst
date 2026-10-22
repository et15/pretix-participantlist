Participant List Export
==========================

This is a plugin for `pretix`_. 

Exports attendees as customizable participant lists (PDF and CSV)

Features
--------

- **PDF participant list** for a single event (landscape A4), available in the
  event's export page and as a shortcut in the event menu.
- **List kinds**: named column selections that an organizer defines once and
  that are then available in every event, each with an optional sort order,
  download filename prefix/suffix, a "confidential" marker and an option to
  also list participants whose order is still pending (unpaid); by default only
  paid orders are listed.
- **Custom list**: per event, columns can also be typed in directly, one per
  line. Join fields with ``+`` to stack them in one column and append ``=Title``
  to set the column header, e.g. ``email+ticket=Contact``. A button on the
  export page copies a list kind into the custom list fields as a starting
  point.
- **Fields**: index, name, first/last name, age, email, order code, order
  status, ticket type, company, address, a signature column and any question
  with an identifier (``question:<identifier>``). The age is computed from the organizer-wide
  birth date question.
- **Branding**: logo and header text of the PDF, configured per organizer.
- **CSV/XLSX export** across multiple events.

The plugin is activated for the organizer and then available in all its events.

Development setup
-----------------

1. Make sure that you have a working `pretix development setup`_.

2. Clone this repository.

3. Activate the virtual environment you use for pretix development.

4. Execute ``pip install -e .`` within this directory to register this application with pretix's plugin registry.

5. Execute ``make`` within this directory to compile translations.

6. Restart your local pretix server. You can now use the plugin from this repository for your events by enabling it in
   the 'plugins' tab in the settings.

This plugin has CI set up to enforce a few code style rules with `Ruff`_. To
check locally, you need it installed::

    pip install ruff

To check your plugin for rule violations, run::

    ruff format --check .
    ruff check .

You can auto-fix most of these issues by running::

    ruff format .
    ruff check --fix .

To automatically check for these issues before you commit, you can run ``.install-hooks.sh``.

Commits in this repository follow `Conventional Commits`_ and releases are
cut with `Commitizen`_ (``cz bump``), which updates the version in
``pyproject.toml`` and ``pretix_participantlist/__init__.py``, writes
``CHANGELOG.md`` and creates the matching git tag. The version starts at
0.1.0; while it is 0.x, breaking changes bump the minor version.


Quick start without a pretix checkout
-------------------------------------

To run the tests and the style checks you do not need a full pretix development
setup. With `uv`_, a few commands create a throwaway environment that contains
the plugin and pretix from its git master branch::

    uv venv
    source .venv/bin/activate
    uv pip install -e . --group dev --group test
    make
    pytest tests
    ruff check .

``make`` needs GNU gettext (Debian package ``gettext``). To try the plugin in a
running pretix, use the development setup above instead.


License
-------


Copyright 2026 ET15

Released under the terms of the Apache License 2.0



.. _pretix: https://github.com/pretix/pretix
.. _pretix development setup: https://docs.pretix.eu/en/latest/development/setup.html
.. _Ruff: https://docs.astral.sh/ruff/
.. _uv: https://docs.astral.sh/uv/
.. _Conventional Commits: https://www.conventionalcommits.org/
.. _Commitizen: https://commitizen-tools.github.io/commitizen/
