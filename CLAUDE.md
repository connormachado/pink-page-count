# CLAUDE.md

Read DECISIONS.md before doing anything. It is authoritative for the schema,
the API contract, storage behavior, the day boundary, the non-scolding
constraint (§8), and the visual tokens (§9). If you think something there is
wrong, stop and say so — do not work around it.

## Rules

- Phased build, 5 phases. Do not build ahead of the current phase.
- Do not change the schema, storage semantics, or existing endpoints in app/
  without saying so in DECISIONS.md in the same commit. Adding new routes and
  new modules is expected.
- Never send or store a `pages` field. It is computed on read. Always.
- The server is the only source of truth for displayed numbers. No client-side
  arithmetic on totals.
- No CDN, no Google Fonts link, no external asset of any kind. Fully offline,
  always. This includes dev tooling output.
- No CORS middleware, ever. Bind 127.0.0.1 only.
- §8 binds every phase: no red states, no pace, no goals, no projections, no
  broken-streak messaging. If a stat reads as a reprimand, don't build it.
- If a change forces an edit to DECISIONS.md, make it in the same commit and
  say why.
- Ask before adding any runtime dependency.

## Commits and merges

You manage git for this project. Commit your own work with clear messages,
merge your branch when the session's verification passes, and say what you
did. Do not wait for approval on git operations. Never rewrite history on
main. Never commit anything under DATA_ROOT.

## Browser verification

You have Claude in Chrome. For any front-end work, verify in the browser
rather than reasoning about the DOM: load the page, check rendering at the
widths named in the brief, read the console for errors, and confirm network
requests for assets return 200. "It should render" is not verification.

## Commands

Run these from the repo root. Never assume an activated venv — always
invoke through .venv/bin/python.

```
./run.command                 start the server
.venv/bin/python -m pytest    backend tests
cd web && npm run dev         front end, dev server with /api proxy
packaging/build_app.sh        the frozen .app bundle (DECISIONS.md 15)
```
