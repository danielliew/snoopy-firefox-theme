#!/bin/sh
# Install the Snoopy Vertical userChrome extras into your default Firefox profile.
#
#   curl -fsSL https://raw.githubusercontent.com/danielliew/snoopy-firefox-theme/main/install.sh | sh
#
# Options (environment variables):
#   SNOOPY_PROFILE=/path/to/profile   install into this profile instead of the default
#   SNOOPY_VERSION=v1.8.0             install a specific release instead of the latest
#   FIREFOX_DIR=/path                 folder containing profiles.ini (auto-detected)
set -eu

REPO="danielliew/snoopy-firefox-theme"
THEME_URL="https://github.com/$REPO/releases/latest/download/snoopy-vertical.xpi"
if [ -n "${SNOOPY_VERSION:-}" ]; then
  ZIP_URL="https://github.com/$REPO/releases/download/$SNOOPY_VERSION/userChrome.zip"
else
  ZIP_URL="https://github.com/$REPO/releases/latest/download/userChrome.zip"
fi

fail() { echo "snoopy: $*" >&2; exit 1; }

find_firefox_dir() {
  for dir in \
    "$HOME/Library/Application Support/Firefox" \
    "$HOME/.mozilla/firefox" \
    "$HOME/snap/firefox/common/.mozilla/firefox" \
    "$HOME/.var/app/org.mozilla.firefox/.mozilla/firefox"; do
    [ -f "$dir/profiles.ini" ] && { echo "$dir"; return; }
  done
}

find_profile() {
  ini="$1/profiles.ini"
  # Firefox 67+ records each install's default profile in an [Install...] section.
  path=$(awk -F= '/^\[Install/ {s=1; next} /^\[/ {s=0} s && $1 == "Default" {print $2; exit}' "$ini")
  if [ -z "$path" ]; then
    path=$(awk -F= '
      /^\[/ { if (d && p != "") exit; p = ""; d = 0 }
      $1 == "Path" { p = $2 }
      $1 == "Default" && $2 == "1" { d = 1 }
      END { if (d && p != "") print p }' "$ini")
  fi
  [ -n "$path" ] || return 0
  case "$path" in
    /*) echo "$path" ;;
    *) echo "$1/$path" ;;
  esac
}

command -v curl >/dev/null || fail "curl is required"
command -v unzip >/dev/null || fail "unzip is required"

profile="${SNOOPY_PROFILE:-}"
if [ -z "$profile" ]; then
  firefox_dir="${FIREFOX_DIR:-$(find_firefox_dir)}"
  [ -n "$firefox_dir" ] || fail "couldn't find Firefox's profiles.ini; set SNOOPY_PROFILE to your profile folder (about:support > Profile Folder)"
  profile=$(find_profile "$firefox_dir")
  [ -n "$profile" ] || fail "couldn't find a default profile in $firefox_dir/profiles.ini; set SNOOPY_PROFILE"
fi
[ -d "$profile" ] || fail "profile folder not found: $profile"
echo "Profile: $profile"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
echo "Downloading $ZIP_URL"
curl -fsSL "$ZIP_URL" -o "$tmp/userChrome.zip" || fail "download failed"
unzip -q "$tmp/userChrome.zip" -d "$tmp/chrome"
[ -f "$tmp/chrome/userChrome.css" ] || fail "downloaded zip has no userChrome.css"

if [ -e "$profile/chrome" ] || [ -L "$profile/chrome" ]; then
  backup="$profile/chrome.backup-$(date +%Y%m%d-%H%M%S)-$$"
  mv "$profile/chrome" "$backup"
  echo "Moved your existing chrome folder to $backup"
fi
mv "$tmp/chrome" "$profile/chrome"
echo "Installed userChrome extras into $profile/chrome"

pref='user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);'
if ! grep -qsF "$pref" "$profile/user.js"; then
  printf '%s\n' "$pref" >> "$profile/user.js"
  echo "Enabled custom stylesheets in user.js"
fi

cat <<EOF

Done. Restart Firefox (quit fully, then reopen) to load the extras.
Theme: open this link in Firefox and click Add (it updates itself after that):
  $THEME_URL
Settings: see https://github.com/$REPO#settings
EOF
