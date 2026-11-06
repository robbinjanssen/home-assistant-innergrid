# AGENTS.md

Guidance for AI coding agents working on this repository. Human contributors:
see [CONTRIBUTING](.github/CONTRIBUTING.md).

## Project

A Home Assistant custom integration (distributed through HACS) for the energy
and building data that the Innergrid energy management platform publishes for
a customer site over
MQTT. Domain: `innergrid`. The MQTT connection and the parsing of the
messages live in the
[`innergrid`](https://github.com/robbinjanssen/python-innergrid)
library (same owner). Fix parsing in the library rather than working around it
here.

```text
custom_components/innergrid/
  __init__.py      setup and unload; devices may always be removed
  config_flow.py   user, reconfigure and reauth steps; checks for data below
                   the prefix (the hub starts reauth when the login is rejected)
  hub.py           runs the library's listen() with reconnects, keeps the
                   latest Update per key and notifies entities; stale data;
                   stores the latest data and restores it on setup
  entity.py        devices, the base entity, EntityTarget and setup_discovery
  sensor.py        sensor descriptions per Kind; meter sensors from the units
  binary_sensor.py binary sensor descriptions per Kind
  control.py       base of the charge point controls: send via the REST API,
                   show the new session values right away
  select.py, number.py, datetime.py, text.py, switch.py
                   the charge point controls (only with the REST API)
  event.py         a session event per charge point, fired by the charge
                   point's events topic (events are not stored)
  diagnostics.py   redacts the login and the names of people charging
  strings.json, translations/{en,nl}.json
tests/             pytest-homeassistant-custom-component tests, message fixtures
```

## Commands

The project uses [uv](https://docs.astral.sh/uv/) and
[prek](https://github.com/j178/prek).

```sh
uv sync                        # create .venv with Home Assistant and dev tools
uv run prek install            # git hook running all checks on commit
uv run prek run --all-files    # Ruff, mypy, pylint, codespell, yamllint, ...
uv run pytest                  # tests; CI requires 70% coverage
```

Run all hooks and tests before committing. The hooks refuse commits to `main`;
work on a branch.

## Requirements and the library

- Python 3.14.2+ and Home Assistant 2026.10.0+ (`hacs.json`, README).
- `manifest.json` pins the released library version that users install.
- For development, `pyproject.toml` takes the library from its `main` branch.
  `uv.lock` pins a commit, so after merging library changes run
  `uv lock --upgrade-package innergrid`. To test library changes before they
  are merged, temporarily use `{ path = "../python-innergrid", editable = true }`.
- Release the library before an integration release that depends on it, and
  bump the manifest to that version.

## Conventions

- **Discovery**: the platform's topics are retained (the Milesight sensors'
  are not). Entities are added when the first message of their topic arrives: `setup_discovery` calls the
  platform's targets function for every update and adds targets it has not
  seen. A description's `exists_fn` decides whether the data has the value.
- **Removals**: an empty message is a `Removal`; `hub.async_remove` drops the
  data, `setup_discovery` removes the entities of the key (also disabled ones),
  and devices without entities are removed. Restored data of the platform that
  has not arrived `REMOVAL_GRACE` after connecting is removed the same way.
- **Topic prefix**: the slug of the customer site; the config key stays
  `topic_prefix`.
- **Devices**: one device per meter, with its circuit's sensors (they are added
  once the meter is known). A Zaptec meter belongs to the charge point with the
  same name and waits until it is known. Meters wait for the site: the totals
  of the site's grid, production and consumption meters are on the site's
  device (`SITE_METER_TOTALS`), not on the meter's. Device identifiers and
  unique IDs start with the topic prefix; keep them stable for existing users.
- **Storage**: the hub saves the latest payloads (`_payload_to_store` drops
  unused parts) at most every `STORAGE_SAVE_DELAY` seconds, on unload and when
  Home Assistant stops, and restores them on setup. Restored data is available
  until it is stale, also before the connection is made.
- **Entities**: `_attr_has_entity_name = True` with a `translation_key`. Meter
  sensors use the unit in the payload (`QUANTITY_TYPES`); only power and energy
  are enabled by default.
- **Translations**: Home Assistant loads `translations/*.json` for custom
  integrations. When changing `strings.json`, update `en` and `nl` too;
  `test_translations` checks that every translation key exists.
- **Reloading**: use `async_update_reload_and_abort`; do not add a config entry
  update listener next to it.
- **REST API**: optional (`api_url`, `api_email`, `api_password`). The hub
  fetches the space names on setup (a failure is only logged) and the controls
  change charge point sessions; `hub.async_update_session` shows a change until
  the platform publishes the charge point again. Tests mock `InnergridApi`.
- **Privacy**: the names of people charging are only shown while a vehicle is
  connected. Diagnostics redact them, including the energy manager's charge
  point resources, which are named like "Lader 10 (Bob)". Never commit real names in
  fixtures.

## Tests

- Tests replace `Innergrid.listen` with `FakeListen` and publish messages
  with `send()`, using the fixtures in `tests/fixtures/`, copied from the
  library's tests.
- Add a test for every bug fix that fails without the fix.

## Pull requests and releases

- Every pull request needs one of these labels: `breaking-change`, `bugfix`,
  `hotfix`, `documentation`, `enhancement`, `refactor`, `performance`,
  `new-feature`, `maintenance`, `ci`, `dependencies`, `skip-changelog`.
- Release Drafter derives the next version from the labels. Bump `version` in
  `manifest.json` and `pyproject.toml` to match before a release.
- Renovate keeps dependencies up to date and automerges minor and patch
  updates.
