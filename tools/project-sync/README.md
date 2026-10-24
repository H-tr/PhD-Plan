# Project sync

Shows each research project's open problems and what was recently solved, read from the project's own code repository, in that project's card on the Research page.

What it reads from each repository:
- **The to-do file**, e.g. `docs/todo.md`. Every markdown table with a `#` column and an `Item` column is read; other tables (measurements, results) are skipped.
  - The item's title is its **bold** text, and the rest of the cell is its detail.
  - The `Status` column sorts the item:

    | Status starts with | Shown as |
    | --- | --- |
    | `Fixed`, `Done`, `Solved`, `Resolved` or `Closed` | solved |
    | `TBD` | open, to decide |
    | `PARKED` | parked |
    | `OBSERVATION` | observation |
    | anything else, or no `Status` column | open |

  - Other columns (`Found`, `Evidence`, …) appear when the item is opened.
- **The pull requests merged in the last 60 days.** They are listed under *Solved*.

## How it works

1. **The panel's key pair.** At the first sign-in after this was added, the panel makes an RSA-OAEP key pair.
   - The private key is kept only inside the encrypted plans.
   - The public key is written to `tools/project-sync/panel-key.json`.
2. **The workflow.** `.github/workflows/projects.yml` runs every 30 minutes; it can also be started by hand from the Actions tab.
   - It reads the repositories with read-only tokens and seals the result to the panel's public key (a fresh AES-256-GCM key per run, wrapped with RSA-OAEP).
   - It force-pushes the result as the only commit of the `projects` branch (`projects.json`).
3. **The panel.** It decrypts `projects.json` with its private key, and checks for a new copy every 5 minutes while open.

Privacy:
- The repository names, the paths and the tokens live only in two Actions secrets. The workflow log is public, so it prints item letters, counts and HTTP codes, nothing else.
- The output is ciphertext, so the public repository shows nothing of the projects.

## Setup

1. **One read-only token per repository owner.** GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.
   - Resource owner: the user or organization that owns the project repository.
   - Repository access: *Only select repositories* → the project repositories of that owner.
   - Permissions → Repository permissions: **Contents: Read-only** and **Pull requests: Read-only**. Nothing else.
   - An organization may need to approve the token before it works (the token page shows *pending*).
2. **Two repository secrets** in this repository: Settings → Secrets and variables → Actions → New repository secret.
   - `PROJECT_REPOS`, one project per line: the id of its project in the panel (the letter on its card), the repository, and the path of its to-do file:

     ```
     A | owner/repository | docs/todo.md
     B | other-owner/other-repository | docs/todo.md
     ```

   - `PROJECT_TOKENS`, one line per repository owner:

     ```
     owner | github_pat_…
     other-owner | github_pat_…
     ```

3. **Run it once:** Actions → projects → Run workflow. The cards fill in when the panel next checks; Settings → Project sync → *Check now* checks at once.

## Maintenance

- **Errors** show in the project's card and in Settings → Project sync. For example, *not found* means the token cannot read that repository.
- **Expired token:** make a new one and update `PROJECT_TOKENS`.
- **Inactivity:** GitHub turns off scheduled workflows in a public repository after 60 days without activity. If that happens, Settings → Project sync shows the last sync getting old, and the Actions tab offers to turn the workflow back on.
