# Snoopy Vertical

Firefox theme based on [Snoopy (animated)](https://addons.mozilla.org/firefox/addon/snoopy-animated/), reworked for vertical tabs (expanded and collapsed) with a comic-strip look.

It has two parts:

- **`theme/`**: a signed Firefox theme with the Peanuts colors (paper tab sidebar, inked selected tab and URL bar) and a centered fallback animation.
- **`userChrome/`**: optional CSS and assets for what themes can't do: sprites pinned next to the reload button and URL bar, a Charlie Brown zigzag under the toolbar, hover styles, and easter eggs.

Peanuts characters and artwork © Peanuts Worldwide LLC. This is a non-commercial fan project. Animations from the official [Peanuts GIPHY account](https://giphy.com/peanuts): [sleeping](https://giphy.com/gifs/2rJw85F0vFJN0SLn3X), [happy dance](https://giphy.com/gifs/7xIMPoVGL2yzu), [Woodstock flying](https://giphy.com/gifs/jptAHfCnH8rSgVSjcE), [doghouse](https://giphy.com/gifs/SvKTWdJjUDcklNyQ0k).

## Easter eggs

- Snoopy falls asleep on his doghouse when the Firefox window is in the background.
- Snoopy does his happy dance while the current page loads.
- Woodstock flutters into the empty toolbar space you hover.
- Snoopy's doghouse sits at the bottom of the expanded tab sidebar; a lone Woodstock when collapsed.

## Build

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python build.py
```

This writes `theme/images/header.png`, the 2x (Retina) animations in `userChrome/assets/`, and `dist/snoopy-vertical.xpi`. Source art lives in `source/`; sizes and frame-rate caps are constants at the top of `build.py`.

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
   git add -A && git commit -m "Release vX.Y.Z"
   git tag vX.Y.Z
   git push --follow-tags
   ```

Signed files in `dist/` are not committed. Re-download any past signed version from the add-on's page in the [Developer Hub](https://addons.mozilla.org/developers/addons).

Changes under `userChrome/` don't need a release; restart Firefox to pick them up.

## userChrome (sprites, zigzag, easter eggs)

1. In `about:config`, set `toolkit.legacyUserProfileCustomizations.stylesheets` to `true`.
2. Link the folder as your profile's `chrome` folder (find `<profile>` via `about:support` → **Profile Folder**; move any existing `chrome` folder aside first): `ln -s "$PWD/userChrome" "<profile>/chrome"`
3. Restart Firefox.
