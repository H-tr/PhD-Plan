# PhD Plan

A private planner for the PhD: the week's plan, long- and short-term goals, a five-year roadmap with every deadline, research projects, internships and visits, admin, notes, and a logbook of what has been done. It is styled after [h-tr.github.io](https://h-tr.github.io/) and shares its light/dark choice.

Live page: <https://h-tr.github.io/PhD-Plan/> (signs in with a password; shows nothing without it).

## How it is put together

| Where | What | Visibility |
| --- | --- | --- |
| `main` → `docs/index.html` | The whole app: one HTML file with its CSS and JavaScript | Public, served by GitHub Pages |
| `main` → `docs/vault.json` | The GitHub token, encrypted with the sign-in password | Public, served by GitHub Pages |
| `data` branch → `data.json` | All plans | Private; never served |

The page reads and writes `data.json` through the GitHub API. Every save is a commit on the `data` branch, so the full history is in `git log data`, and two devices editing at once are merged automatically. Saves never touch `main`, so they do not trigger a Pages rebuild.

## First-time setup

1. **Create a token.** GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.
   - Repository access: *Only select repositories* → `H-tr/PhD-Plan`.
   - Permissions → Repository permissions → **Contents: Read and write**. Nothing else.
   - Pick an expiry you will remember (a year is reasonable) and put the date on the “Renew the planner’s GitHub token” to-do in Admin.
2. **Open** <https://h-tr.github.io/PhD-Plan/>, paste the token, and choose a sign-in password (twice). The page encrypts the token with the password and commits `docs/vault.json`.
3. **Other devices:** about a minute later (once Pages republishes), any device signs in with just the password.

## Security model

- The page itself contains no plans. The plans are only readable with the token, and the token is only stored in two forms: encrypted in `docs/vault.json`, and decrypted in the browser of a signed-in device.
- `vault.json` is public, so its strength is the password's: PBKDF2-SHA256 with 1,000,000 rounds, then AES-256-GCM. Use a passphrase of at least 12 characters (four or five random words) that is used nowhere else.
- **Same origin.** Every page on `h-tr.github.io` (the homepage, the project docs sites) shares one browser origin, so scripts on them could read this site's `localStorage`. By default the decrypted token and the cached plans therefore live in `sessionStorage` (this tab only, gone when it closes). *Keep me signed in* moves them to `localStorage`; use it only on your own devices.
- The page sets a Content Security Policy that only allows network requests to itself and `api.github.com`.
- **If the token leaks:** delete it on GitHub (that alone cuts off access), create a new one, connect with it, and set the password again in Settings.
- **If you forget the password:** connect with a new token on the sign-in screen (“Use a GitHub token instead”) and set a new password.

## Using it

- **This week:** pick to-dos from every section, mark a few as the week's focus, write the week's goals and the review. Weekly tasks reappear every week.
- **Roadmap:** the PhD arc (Aug 2026 – Jul 2031) with milestones; a month-by-month view of the next twelve months (deadlines and due to-dos); long-term, this-year and short-term goals with progress; the full list of milestones and deadlines. An ≈ marks a date estimated from the previous year.
- **Research / Experience / Admin:** each item has a status, to-dos with due dates, and a progress log. Click a to-do's text to edit it; ✎ edits the item.
- **Thinking:** the half-step-back (research) and full-step-back (career) checklists, fellowships and awards, channels, the paper-launch checklist, reading list, career notes, inbox and conversation notes.
- **Logbook:** a year-long activity heatmap and every note, completed to-do, status change and weekly review, by month. Click a day in the heatmap to see just that day.
- `/` focuses search; everything is editable and deletions can be undone.
- Settings: sync now, download/import a JSON backup, theme, password, sign out, and restore deleted sections.

## Changing the page

Edit `docs/index.html` (HTML, CSS and JavaScript are all in that file), change the `app-build` meta value at the top, and push to `main`. Open tabs will offer to reload once Pages has published the new version.

## What was seeded

The first `data.json` was drafted on 24 Oct 2026 from the homepage, the CV and GitHub repositories, plus a search of official pages for:

- NUS SoC PhD rules;
- A\*STAR AGS terms;
- conference deadlines (RSS 2027 is two-stage: extended abstract 4 Dec 2026);
- fellowships;
- summer 2027 internships;
- labs to visit.

Project statuses and goals are a first draft to correct; deadlines and rules carry their sources, and estimates are marked.
