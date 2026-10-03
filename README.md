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

## Install permanently

Release Firefox only installs signed add-ons. Sign it as an unlisted (private) add-on with an [AMO API key](https://addons.mozilla.org/developers/addon/api/key/):

```sh
npx web-ext sign --source-dir theme --channel unlisted --api-key "$AMO_JWT_ISSUER" --api-secret "$AMO_JWT_SECRET"
```

Then open the generated `.xpi` in Firefox. Bump `version` in `theme/manifest.json` before each re-sign.

## Notion-style URL bar (optional)

The theme makes the URL bar transparent at rest and white while typing. Themes can't style hover, so `userChrome/userChrome.css` adds the white-on-hover state, rounded corners, soft shadows, and Notion-like result rows.

1. In `about:config`, set `toolkit.legacyUserProfileCustomizations.stylesheets` to `true`.
2. Copy `userChrome/userChrome.css` into `<profile>/chrome/userChrome.css` (find `<profile>` via `about:support` → **Profile Folder**).
3. Restart Firefox.
