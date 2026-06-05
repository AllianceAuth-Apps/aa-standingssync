# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [Unreleased] - yyyy-mm-dd

## [3.0.0b1] - 2026-05-04

This release adds support for Alliance Auth V5 and contains breaking changes.

### Update notes

If you updating from a previous version please also update the periodic tasks configuration in your local settings.
This does not change the frequency of updates, but reduces potential load peaks on FC's servers, which can be caused by many installations making the same requests to FC's servers at the same time.
The new configuration is:

```python
CELERYBEAT_SCHEDULE['standingssync.run_regular_sync'] = {
    'task': 'standingssync.tasks.run_regular_sync',
    'schedule': 7200
}
```

### Changed

- BREAKING CHANGE: Now requires Python 3.10
- Added support for AA 5
- Removed logger tag
- Migrated ESI client to OpenAPI
- Reworked logic for fetching wars to accommodate rate limit constraints
- Modernized test suite

## [2.0.0] - 2026-03-26

### Update notes

This release requires Alliance Auth 4.0 or greater.

Please update the value for `'schedule'` of the related periodic task in your local settings.
This change will help reduce peak load on CCP's servers.

The new default configuration looks like this:

```python
# settings for standingssync
CELERYBEAT_SCHEDULE['standingssync.run_regular_sync'] = {
    'task': 'standingssync.tasks.run_regular_sync',
    'schedule': 7200
}
```

### Changed

- BREAKING CHANGE: Support dropped for AA3
- Templates migrated to AA4 / Bootstrap 5
- Added basic protection against ESI rate limit issues

## [1.10.0] - 2023-12-28

### Changed

- Added support for AA4
- Added pylint checks
- Storing ESI contacts to disk can now be enabled through the new setting `STANDINGSSYNC_STORE_ESI_CONTACTS_ENABLED`, an not longer by enabling DEBUG mode.
- Improved test suite
- Refactoring

## [1.9.0] - 2023-07-01

### Changed

- Migrate build process to PEP 621
- Removed local swagger spec file
- Migrate to AA 3 and support support for AA 2
- Add support for Python 3.11
- Fixed various pylint issues
- Fixed various typing issues

### Fixed

- Update breaks when alliance contacts contain faction contacts

## [1.8.1] - 2023-02-16

### Changed

- War participants on current wars page now links to ZKB instead of dotlan

### Fixed

- Breaks when trying to filter by character on admin page

## [1.8.0] - 2023-02-16

### Added

- New page showing the current alliance wars
- Show and filter wars by state on admin site
- Ability to delete all contacts of a character from the admin site

### Changed

- Reverted back to partial sync logic, i.e. `STANDINGSSYNC_REPLACE_CONTACTS = False` will no longer update  alliance contacts
- Now requires Python 3.8 or higher

## [1.7.0] - 2023-02-12

### Added

- Ability to update wars from the admin site

### Changed

- The contacts sync logic has been reworked:
  - Replacing contacts will now add, delete and update contacts individually instead of recreating all contacts from scratch.
  - Characters are now synced every time the manager sync is running, instead of only when alliance contacts / WTs have changed
  - Synced characters are now also updated when the in-game contacts of the character has changed
- Instead of reporting the latest error on the admin site, most severe errors during manager sync will now result in exceptions which will result in tasks failing. These can be tracked with tools like Task Monitor. Errors are still also reported in the log files.
- Update are reported as "fresh" as long as the sync has run successfully within the configured timeout.
- Wars are no longer synced when the feature is deactivated
- The button for adding sync chars is now inactive when no matching alliance was found for the current user
- Adding an alliance character now also triggers syncing of all wars to get the war targets (when enabled)

## [1.6.0] - 2023-01-29

### Update notes

IMPORTANT: Please make sure to update to 1.5.0 first, before installing this update. This is because, this update continues the consolidation of database migrations, which was started in 1.5.0.

### Changed

- Remove support for Python 3.7
- Add support for Python 3.10
- Remove squashed migrations which are now obsolete from 1.5.0

## [1.5.0] - 2022-08-08

### Update notes

This update will temporarily remove all contacts and wars. After you completed the installation, please manually trigger the update task to fetch contacts and wars again (or wait for it to run from schedule):

```bash
celery -A myauth call standingssync.tasks.run_regular_sync
```

### Changed

- Migrated proprietary EveEntity to EveUniverse's EveEntity to enable ID to Name resolution
- Update tasks are running with lower priority then default

### Fixed

- Fix: Not all active wars are shown in the app (#13)
- No longer creates own character as contact when syncing

## [1.4.1] - 2022-07-29

### Added

- Show allies on EveWar admin site

### Fixed

- Search on EveWar page does not work

## [1.4.0] - 2022-07-20

### Added

- Show entities and wars on admin site

## [1.3.1] - 2022-06-18

### Changed

- Add wheel to PyPI deployment
- Switch to local swagger spec file
- Add tests to distribution package

## [1.3.0] - 2022-03-02

### Changed

- Remove support for Python 3.6
- Remove support for Django 3.1

### Fixed

- SessionMiddleware() in tests requires additional parameter

### Changed

## [1.2.2] - 2022-03-01

### Changed

- Remove deprecations that are being remove in Django 4

## [1.2.1] - 2021-10-28

### Changed

- Added CI tests for AA 2.9+ (Python 3.7+, Django 3.2), removed CI tests for AA < 2.9 (Python 3.6, Django 3.1)

## [1.2.0] - 2021-08-05

### Added

- Status indicator for sync ok on admin site for both managers and characters

## [1.2.0b4] - 2021-03-01

### Added

- Ability to also sync war targets to alt characters. Please see settings on how to activate this feature. [#5](https://gitlab.com/ErikKalkoken/aa-standingssync/-/issues/5)

### Changed

- Remove support for Django 2
- UI refresh
- Migrated to allianceauth-app-utils
- Codecov integration

## [1.1.4] - 2020-10-09

### Changed

- Changed logo to better reflect what this app does
- Now logs to to extensions logger
- Add improved logging for standing rejections
- Added tests

### Fixed

- Minor fixes

## [1.1.3] - 2020-09-24

### Changed

- Added Django 3 to test suite
- Reformatted with new Black version

## [1.1.2] - 2020-07-04

### Changed

- Added Black as mandatory linter
- Added support for django-esi 2.x and backwards compatibility for 1.x

## [1.1.1] - 2020-06-30

### Changed

- Update to Font Awesome v5. Thank you Peter Pfeufer for your contribution!

## [1.1.0] - 2020-05-28

### Changed

- Drops support for Python 3.5
- Updated dependency for django-esi to exclude 2.0
- Added timeout to ESI requests

## [1.0.4] - 2020-04-19

### Fixed

- New attempt to reduce the memory leaks in celery workers

## [1.0.3] - 2020-04-12

### Changed

- Sync status now updated at the end of the process, not at the beginning

### Fixed

- Corrected required permission for adding sync managers
- Minor bugfixes
- Improved test coverage

## [1.0.2] - 2020-02-28

### Added

- Version number for this app now shown on admin site

### Fixed

- Bug: Standing value was sometimes not synced correctly for contacts

## [1.0.1] - 2019-12-19

### Changed

- Improved error handling of contacts sync process
- Improved layout of messages

## [1.0.0] - 2019-10-02

### Added

- First release
