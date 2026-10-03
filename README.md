# Snoopy Vertical

Firefox theme based on [Snoopy (animated)](https://addons.mozilla.org/firefox/addon/snoopy-animated/), reworked for vertical tabs: sprites are swapped, centered around the URL bar, and sized to fit the single nav bar row.

Peanuts characters and artwork © Peanuts Worldwide LLC. This is a non-commercial fan project.

## Build

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python build.py
```

This writes `theme/images/header.png` and `dist/snoopy-vertical.xpi`. Sprite positions, sizes, and gaps are constants at the top of `build.py`.

## Try it

`about:debugging#/runtime/this-firefox` → **Load Temporary Add-on…** → pick `theme/manifest.json`. Click **Reload** there after rebuilding. Temporary add-ons are removed when Firefox restarts.

## Release

Release Firefox only installs signed add-ons, so each release is signed by Mozilla as an unlisted (private) add-on. Signing needs Node.js (`brew install node`) and an [AMO API key](https://addons.mozilla.org/developers/addon/api/key/). Keep the key out of the repo and chat; export it in your shell only.

1. Bump `version` in `theme/manifest.json` ([semver](https://semver.org); AMO rejects a version it has already signed).
2. Build and lint:

   ```sh
   .venv/bin/python build.py
   npx web-ext lint --source-dir theme
   ```

3. Test with **Load Temporary Add-on…** (see above).
4. Sign (takes a few minutes):

   ```sh
   export WEB_EXT_API_KEY='user:…' WEB_EXT_API_SECRET='…'
   npx web-ext sign --source-dir theme --channel unlisted --artifacts-dir dist/signed
   ```

5. Open the signed `.xpi` from `dist/signed/` in Firefox and click **Add**. It replaces the installed version.
6. Commit, tag, and push:

   ```sh
   git commit -am "Release vX.Y.Z"
   git tag vX.Y.Z
   git push --follow-tags
   ```

Signed files in `dist/` are not committed. Re-download any past signed version from the add-on's page in the [Developer Hub](https://addons.mozilla.org/developers/addons).

Changes to `userChrome/userChrome.css` don't need a release; restart Firefox to pick them up.

## Notion-style URL bar (optional)

The theme makes the URL bar transparent at rest and white while typing. Themes can't style hover, so `userChrome/userChrome.css` adds the white-on-hover state, rounded corners, soft shadows, and Notion-like result rows.

1. In `about:config`, set `toolkit.legacyUserProfileCustomizations.stylesheets` to `true`.
2. Symlink it into your profile so edits apply on restart (find `<profile>` via `about:support` → **Profile Folder**): `ln -sf "$PWD/userChrome/userChrome.css" "<profile>/chrome/userChrome.css"`
3. Restart Firefox.
