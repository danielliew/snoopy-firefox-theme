"""Load userChrome.css in a throwaway headless Firefox and check the computed styles.

Runs once with Firefox's default toolbar and once with flexible spaces around the URL bar.

Usage: .venv/bin/python tests/verify_userchrome.py [path/to/firefox]
Requires: pip install marionette_driver
"""

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from marionette_driver.marionette import Marionette

ROOT = Path(__file__).resolve().parent.parent
FIREFOX = sys.argv[1] if len(sys.argv) > 1 else "/Applications/Firefox.app/Contents/MacOS/firefox"
PORT = 2829

BASE_PREFS = {
    "toolkit.legacyUserProfileCustomizations.stylesheets": True,
    "sidebar.revamp": True,
    "sidebar.verticalTabs": True,
    "marionette.port": PORT,
    "browser.shell.checkDefaultBrowser": False,
    "browser.startup.homepage_override.mstone": "ignore",
    "datareporting.policy.dataSubmissionEnabled": False,
}

SPRING_LAYOUT = {
    "placements": {
        "nav-bar": [
            "sidebar-button", "back-button", "forward-button", "stop-reload-button",
            "customizableui-special-spring1", "vertical-spacer", "urlbar-container",
            "customizableui-special-spring2", "unified-extensions-button",
        ],
        "vertical-tabs": ["tabbrowser-tabs"],
    },
    "currentVersion": 26,
}

STYLES = """
const style = (sel, pseudo) => {
  const el = document.querySelector(sel);
  return el ? getComputedStyle(el, pseudo || null) : null;
};
const bg = (sel, pseudo) => {
  const s = style(sel, pseudo);
  return s && s.content !== "none" && s.backgroundImage !== "none" ? s.backgroundImage : "none";
};
const left = bg("#stop-reload-button + toolbarspring");
const right = bg("#urlbar-container + toolbarspring");
return {
  left: left !== "none" ? left : bg("#urlbar-container", "::before"),
  right: right !== "none" ? right : bg("#urlbar-container", "::after"),
  inactive: document.documentElement.matches(":-moz-window-inactive"),
  sidebar: style("#vertical-tabs").backgroundImage,
  sidebarPadding: style("#vertical-tabs").paddingBottom,
  navbarBg: style("#nav-bar").backgroundColor,
  tabText: style(".tabbrowser-tab").getPropertyValue("--tab-text-color").trim(),
  local: style("#identity-box", "::after").content,
};
"""


def sprite(value):
    """'url("chrome://.../assets/slow/snoopy-typing.png")' -> 'slow/snoopy-typing.png'."""
    if "assets/" not in value:
        return value
    return value.split("assets/", 1)[1].split('"')[0].rstrip(")")


def run(label, extra_prefs, failures):
    print(f"\n== {label} ==")
    profile = Path(tempfile.mkdtemp(prefix="snoopy-test-"))
    prefs = {**BASE_PREFS, **extra_prefs}
    (profile / "user.js").write_text(
        "".join(f"user_pref({json.dumps(k)}, {json.dumps(v)});\n" for k, v in prefs.items())
    )
    (profile / "chrome").symlink_to(ROOT / "userChrome")
    proc = subprocess.Popen(
        [FIREFOX, "--headless", "--marionette", "--remote-allow-system-access", "--no-remote",
         "--profile", str(profile)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def expect(what, actual, wanted, exact=False):
        ok = actual == wanted if exact else wanted in actual
        print(f"{'PASS' if ok else 'FAIL'}  {what}: {actual}")
        if not ok:
            failures.append(f"{label}: {what}")

    try:
        m = Marionette(host="127.0.0.1", port=PORT, startup_timeout=60)
        m.start_session()
        m.set_context(m.CONTEXT_CHROME)
        time.sleep(1)

        def styles():
            return m.execute_script(STYLES)

        def set_pref(pref, value):
            m.execute_script(
                "Services.prefs.setBoolPref(arguments[0], arguments[1]);", script_args=[pref, value]
            )
            time.sleep(0.3)

        s = styles()
        resting = "snoopy-sleeping.png" if s["inactive"] else "snoopy-typing.png"
        expect(f"Snoopy left of URL bar (window inactive: {s['inactive']})", sprite(s["left"]), resting, True)
        expect("Woodstock cart right of URL bar", sprite(s["right"]), "woodstock-cart.png", True)
        expect("Sidebar scene", sprite(s["sidebar"]), "doghouse-scene.png", True)
        expect("White nav bar", s["navbarBg"], "rgb(255, 255, 255)", True)
        expect("Ink tab text", s["tabText"], "#37352f", True)

        m.execute_script("gBrowser.selectedTab.setAttribute('busy', 'true');")
        expect("Snoopy dances while the tab loads", sprite(styles()["left"]), "snoopy-dance.png", True)
        m.execute_script("gBrowser.selectedTab.removeAttribute('busy');")

        set_pref("snoopy.easter-eggs.off", True)
        expect("easter-eggs.off keeps Snoopy typing", sprite(styles()["left"]), "snoopy-typing.png", True)

        set_pref("snoopy.animations.slow", True)
        expect("slow swaps to slow sprites", sprite(styles()["left"]), "slow/snoopy-typing.png", True)
        expect("slow applies to the cart", sprite(styles()["right"]), "slow/woodstock-cart.png", True)

        set_pref("snoopy.animations.paused", True)
        expect("paused wins over slow", sprite(styles()["left"]), "still/snoopy-typing.png", True)
        set_pref("snoopy.animations.paused", False)
        set_pref("snoopy.animations.slow", False)
        expect("prefs off restores normal", sprite(styles()["left"]), "snoopy-typing.png", True)
        set_pref("snoopy.easter-eggs.off", False)

        set_pref("snoopy.sidebar.hide-scene", True)
        s = styles()
        expect("hide-scene removes sidebar art", s["sidebar"], "none", True)
        expect("hide-scene removes sidebar padding", s["sidebarPadding"], "0px", True)
        set_pref("snoopy.sidebar.hide-scene", False)

        page = profile / "local.html"
        page.write_text("<title>local</title><p>hi</p>")
        m.set_context(m.CONTEXT_CONTENT)
        m.navigate(page.as_uri())
        m.set_context(m.CONTEXT_CHROME)
        time.sleep(0.5)
        expect("LOCAL tag on file:// page", styles()["local"], '"LOCAL"', True)

        m.execute_script("gBrowser.getFindBar().then(f => f.open());")
        time.sleep(0.5)
        expect(
            "Zigzag on find bar",
            m.execute_script("return getComputedStyle(gBrowser.getCachedFindBar()).backgroundImage;"),
            "svg",
        )
        m.delete_session()
    finally:
        proc.terminate()
        proc.wait(timeout=20)
        shutil.rmtree(profile, ignore_errors=True)


def main():
    failures = []
    run("default toolbar", {}, failures)
    run("flexible spaces", {"browser.uiCustomization.state": json.dumps(SPRING_LAYOUT)}, failures)
    print(f"\n{'all checks passed' if not failures else f'{len(failures)} failed:'}")
    for f in failures:
        print(f"  {f}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
