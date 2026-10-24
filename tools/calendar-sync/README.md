# Calendar sync

Brings meetings from Google Calendar, NUS Outlook, Feishu and other calendars into the Control Panel's *This week*.

A static page cannot read calendar links itself (browsers block it), so [`.github/workflows/calendar.yml`](../../.github/workflows/calendar.yml) does it every 15 minutes:

1. Read the calendars listed in the `CALENDAR_SOURCES` secret.
2. Expand the events from two weeks ago to ten weeks ahead, including recurring meetings, moved instances and skipped dates. A meeting that appears in two calendars shows once.
3. Encrypt the result with a fresh AES-256-GCM key, wrapped with the panel's RSA-OAEP public key (`public-key.json`, written when you turn calendar sync on in Settings).
4. Replace the single commit on the `calendar` branch.

The matching private key lives inside the panel's own encrypted data, so only the signed-in panel can read the calendar. The workflow log shows counts and error types, never links or event titles.

## Setting it up

1. In the panel: Settings → Calendar → **Turn on calendar sync**.
2. Get a private link for each calendar:
   - **Google:** calendar.google.com → Settings → your calendar → Integrate calendar → *Secret address in iCal format*.
   - **NUS Outlook:** outlook.office.com → Settings → Calendar → Shared calendars → *Publish a calendar*. Choose Calendar and "Can view all details", publish, then copy the ICS link.
   - **Feishu:** if Feishu Calendar's settings offer CalDAV sync, use the server address, user name and password it shows.
3. Add the repository secret `CALENDAR_SOURCES` (Settings → Secrets and variables → Actions), one calendar per line:

   ```
   Google | https://calendar.google.com/calendar/ical/…/basic.ics
   NUS    | https://outlook.office365.com/owa/calendar/…/calendar.ics
   Feishu | caldav | https://… | user name | password
   ```

   Or from a terminal: `gh secret set CALENDAR_SOURCES -R H-tr/PhD-Plan`, then paste the lines.
4. Wait up to 15 minutes, or run it at once from Actions → calendar → Run workflow.

Each link lets anyone who has it read that calendar, so keep the links only in the secret.

## Testing locally

```sh
pip install icalendar==7.3.0 recurring-ical-events==3.8.2 cryptography==50.0.2 caldav==3.6.0
CALENDAR_SOURCES="Test | file:///path/to/test.ics" python sync.py out.json public-key.json
```
