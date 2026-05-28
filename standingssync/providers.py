"""ESI client for standingssync."""

from pathlib import Path

from esi.openapi_clients import ESIClientProvider

from standingssync import __version__

spec_file = Path(__file__).parent / "openapi_2025-12-16.json"

esi = ESIClientProvider(
    compatibility_date="2025-12-16",
    ua_appname="aa-standingssync",
    ua_version=__version__,
    operations=[
        "DeleteCharactersCharacterIdContacts",
        "GetAlliancesAllianceIdContacts",
        "GetCharactersCharacterIdContacts",
        "GetCharactersCharacterIdContactsLabels",
        "GetWars",
        "GetWarsWarId",
        "PostCharactersCharacterIdContacts",
        "PutCharactersCharacterIdContacts",
    ],
    spec_file=spec_file,
)
