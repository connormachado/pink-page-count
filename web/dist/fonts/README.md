# Vendored fonts

`fraunces-latin-var.woff2` — Fraunces (variable, `wght` 400–700, latin subset),
copied here once from the Google Fonts CDN and committed to the repo.

Licensed under the SIL Open Font License 1.1 — the full text is in `OFL.txt`
beside the font file, which is where the license requires it to travel.

DECISIONS.md §9.4: fonts are vendored, never fetched. Nothing in this app may
request this file — or any other asset — over the network at runtime. It is
served from `/fonts/` by Vite in dev and copied into the build output by Vite
in Phase 4.
