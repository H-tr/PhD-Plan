# Control Panel

A password-protected personal control panel:
- **Research:** where each project stands.
- **Resources:** live use of the lab's GPU servers.

It is styled after [h-tr.github.io](https://h-tr.github.io/) and shares that site's light/dark choice.

Live page: <https://h-tr.github.io/PhD-Plan/>

This repository is public, but your data in it is not readable. It is encrypted in the browser before they are saved, so GitHub only ever stores ciphertext. Without the password (or the recovery code) the page shows a sign-in box and the repository shows noise.

## How it is put together

| Where | What |
| --- | --- |
| `main` → `docs/index.html` | The whole app: one HTML file with its CSS and JavaScript, served by GitHub Pages |
| `main` → `docs/vault.json` | The data key and the GitHub token, wrapped under the password and, separately, under a recovery code |
| `data` branch → `data.json` | All plans, encrypted with the data key |

**Encryption:**
- A random 256-bit data key encrypts `data.json` with AES-256-GCM.
- `vault.json` holds that key twice:
  - once wrapped under the sign-in password;
  - once wrapped under a 120-bit recovery code.
- Each wrapping key comes from PBKDF2-SHA256 with 1,000,000 rounds.
- Changing the password only re-wraps the key, so the plans are never re-encrypted under a half-written key.

**Saving:**
- Every save is a commit on `data` with the generic message `plans: update`, so the history shows when you saved but not what.
- Two devices editing at once are merged automatically.
- Saves never touch `main`, so they do not trigger a Pages rebuild.

## First-time setup

1. **Create a token.** GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.
   - Repository access: *Only select repositories* → `H-tr/PhD-Plan`.
   - Permissions → Repository permissions → **Contents: Read and write**. Nothing else.
   - Choose an expiry you will remember (a year is reasonable).
2. **Open** <https://h-tr.github.io/PhD-Plan/>, paste the token, and choose a sign-in password (twice).
3. **Save the recovery code** it shows into your password manager. It is shown once, and it is the only way back if the password is forgotten.
4. **Import the first plans:** choose `private/seed-data.json` from the local copy of this folder. That file is git-ignored and never leaves your machine unencrypted. Or click *Start empty*.
5. **Other devices** sign in with just the password, once Pages has republished `vault.json` (about a minute).

## Security notes

- The encrypted files are public, so they are only as strong as the password. Use at least 12 characters (four or five random words make a good passphrase) and use it nowhere else.
- **Same origin.** Every page on `h-tr.github.io` (the homepage and the project docs sites) shares one browser origin, so scripts there could read this site's `localStorage`. For that reason, after sign-in the keys and the decrypted plans are kept in `sessionStorage` (this tab only, gone when it closes). *Keep me signed in* moves them to `localStorage`; use it only on your own devices.
- The page sets a Content Security Policy that allows network requests only to itself, `api.github.com`, tailnet hosts (`*.ts.net`, for the Resources tab) and `localhost` (for an SSH tunnel to a server).
- **Token leaked:** delete it on GitHub (that alone stops writes), make a new one, and use *Replace the token* in Settings.
- **Password forgotten:** type the recovery code into the password box, then choose a new password.
- **Token expired:** after the password, the page asks for a new token and locks it under the same password.

## Using it

- **Research:**
  - The deadlines you keep in view are at the top, as a countdown (*edit* changes them).
  - Each project has a status, to-dos with due dates, and a progress log.
  - Click a to-do's text to edit it; ✎ edits the project.
- **Resources:** live GPU, CPU and memory use of the lab servers, refreshed every 3 seconds while the tab is open.
  - Each GPU row shows who is using it, and the CPU and memory bars show their top users.
  - Each server runs a small agent published to the tailnet with `tailscale serve`; see [tools/server-monitor](tools/server-monitor/README.md).
- **Shortcuts:** `/` focuses search, and deletions can be undone.
- **Settings:** sync, backups (plain JSON, downloaded locally), theme, password, token, recovery code and sign-out.

## Changing the page

Edit `docs/index.html` (HTML, CSS and JavaScript are all in that file), change the `app-build` meta value at the top, and push to `main`. Open tabs will offer to reload once Pages has published the new version.
