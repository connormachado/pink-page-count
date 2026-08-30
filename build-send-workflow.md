Your build and install run:

```bash
>> make send
```

`make send` is `install` + `zip`: it builds, replaces `/Applications/Pink Page
Count.app`, writes the zip, and reveals it in Finder ready to AirDrop.

The artifact is **date-stamped and lives in `packaging/dist/`**:

```
packaging/dist/PinkPageCount-YYYY-MM-DD.zip
```

**Do not go back to a fixed `PinkPageCount.zip` at the repo root.** Two reasons,
and the first one is the one that bites:

- A fixed filename means macOS saves the second copy she receives as
  "PinkPageCount 2.zip" in her Downloads. She unzips the wrong build — the old
  one, still sitting there from last time — and there is no visible symptom. The
  app opens, works, and is a version behind. A date in the name means the file
  she just received is the one she opens.
- `make zip` re-runs `packaging/check_deployment_target.py` over the archive it
  just wrote (DECISIONS.md 15.8), because the zip is what actually gets
  AirDropped. Building it by hand with `ditto` skips that check, which is how
  REVIEW.md BLOCKER 1 shipped in the zip as well as in the bundle.

Then:

AirDrop that file, unzip on her Mac, drag to Applications
Right-click → Open → Open. If no dialog, System Settings → Privacy & Security → Open Anyway
Log one real entry, then confirm ~/Library/Application Support/PinkPageCount/entries.json exists on her machine and contains it
Show her: how to log, that closing the tab quits it, that double-clicking always brings it back, and where "Download a backup" is
