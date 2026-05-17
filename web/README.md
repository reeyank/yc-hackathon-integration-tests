# Web / install assets

Before launch, replace the literal tokens `OWNER` and `REPO` in
`install.sh`, `web/index.html`, and `web/ios-test.template` with your
GitHub org/user and repository name.

## Enable hosting (GitHub Pages)

1. Push this repo to `https://github.com/OWNER/REPO` (public).
2. Repo Settings → Pages → Source: deploy from `main` / `/web` folder
   (or root if `install.sh` is copied into `/web`).
3. Ensure `install.sh` is reachable at
   `https://OWNER.github.io/REPO/install.sh` (copy or symlink it into the
   published folder if Pages serves `/web`).
4. The landing page is then live at `https://OWNER.github.io/REPO/`.

The one command users run:

    curl -fsSL https://OWNER.github.io/REPO/install.sh | bash
