# The OrderGuard launch site

A static page in this folder: `index.html`, `site.css`, `site.js` and `data.json`, plus `theater/`, a static copy of the Swarm Theater.
No build step, no CDN, no external fonts or scripts.

## Where the numbers come from

Every figure on the page is a string or series in `data.json`. The page's HTML and JavaScript hold no figures of their own; tests
enforce that. `data.json` is written by:

```bash
.venv/bin/python scripts/build_site_data.py          # rebuild site/data.json and site/theater/ from the committed results
.venv/bin/python scripts/build_site_data.py --check  # exit 1 if either is stale
```

It reads `results/` (bench, red team, simulation, arena, risk, review, theater), `README.md`, `docs/PRODUCT.md` and `policies/`, and
records each input with its SHA-256 under `inputs`. Each fact carries the path of the file it came from, and the page links every chart
to its source. The forged-split example is decided by the real gate (`orderguard_app.services.check_order`), not typed in.
Rebuild after any results file or the README changes; `python/tests/site/test_site.py` fails until you do.

## Preview locally

```bash
python3 -m http.server 8000      # from the repository root, then open http://127.0.0.1:8000/site/
```

Serving from the repository root lets the source links (`../results/...`) resolve. Serving from inside `site/` also works; only the
source links then point outside the served folder. The page needs HTTP (it fetches `data.json`), so opening `index.html` as a file does not work.

## Publish on GitHub Pages

The workflow `.github/workflows/pages.yml` deploys this folder with the official Pages actions on every push to `main` that touches
`site/`. One-time step for the repository owner:

1. **Settings -> Pages -> Build and deployment -> Source: GitHub Actions.**
2. Push to `main` (or run the `pages` workflow by hand from the Actions tab).

The page then lives at `https://<owner>.github.io/<repo>/`, and the Swarm Theater at `.../theater/`. On a `github.io` address the
source links point at `https://github.com/<owner>/<repo>/blob/main/<path>` automatically. On a custom domain, put `owner/repo` in
the `<meta name="og-repo" content="">` tag of `index.html`; the static theater's source links then fall back to paths relative to the site.
