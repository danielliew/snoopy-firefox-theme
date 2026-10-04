"""Load userChrome.css in a throwaway headless Firefox and check the computed styles.

Runs once with Firefox's default toolbar and once with flexible spaces around the URL bar.

Usage: uv run tests/verify_userchrome.py [path/to/firefox]
"""

import base64
import io
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from marionette_driver.by import By
from marionette_driver.marionette import Marionette
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent
FIREFOX = sys.argv[1] if len(sys.argv) > 1 else "/Applications/Firefox.app/Contents/MacOS/firefox"
PORT = 2829
PAPER = "rgb(251, 245, 230)"

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
  urlbarBg: style("#urlbar > .urlbar-background").backgroundColor,
  tabboxRadius: style("#tabbrowser-tabbox").borderTopLeftRadius,
  tabText: style(".tabbrowser-tab").getPropertyValue("--tab-text-color").trim(),
  local: style("#identity-box", "::after").content,
};
"""


def sprite(value):
    """'url("chrome://.../assets/slow/snoopy-typing.png")' -> 'slow/snoopy-typing.png'."""
    if "assets/" not in value:
        return value
    return value.split("assets/", 1)[1].split('"')[0].rstrip(")")


def run(label, extra_prefs, failures, dark=False):
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
        m.set_window_rect(width=1280, height=800)
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
        if dark:
            expect("dark mode keeps Firefox's toolbar color", "paper" if s["navbarBg"] == PAPER else "kept", "kept", True)
            expect("dark mode keeps Firefox's tab text", "ink" if s["tabText"] == "#37352f" else "kept", "kept", True)
            expect("dark mode keeps Firefox's content corners", s["tabboxRadius"], "0px", True)
        else:
            expect("Paper nav bar", s["navbarBg"], PAPER, True)
            expect("White URL bar", s["urlbarBg"], "rgb(255, 255, 255)", True)
            expect("Rounded page card", s["tabboxRadius"], "8px", True)
            expect("Ink tab text", s["tabText"], "#37352f", True)

        def resized(width, height):
            m.set_window_rect(width=width, height=height)
            time.sleep(0.4)
            return styles()

        s = resized(900, 800)
        expect("900px wide: cart steps aside", s["right"], "none", True)
        expect("900px wide: Snoopy stays", sprite(s["left"]), "snoopy-typing.png", True)
        s = resized(700, 800)
        expect("700px wide: Snoopy steps aside", s["left"], "none", True)
        s = resized(1280, 600)
        expect("600px tall: sidebar scene steps aside", s["sidebar"], "none", True)
        expect("600px tall: sidebar padding released", s["sidebarPadding"], "0px", True)
        s = resized(1280, 800)
        expect("back to 1280x800: sprites return", sprite(s["left"]) + " " + sprite(s["right"]) + " " + sprite(s["sidebar"]),
               "snoopy-typing.png woodstock-cart.png doghouse-scene.png", True)

        m.execute_script("gBrowser.selectedTab.setAttribute('busy', 'true');")
        expect("Snoopy dances while the tab loads", sprite(styles()["left"]), "snoopy-dance.png", True)
        m.execute_script("gBrowser.selectedTab.removeAttribute('busy');")

        m.execute_script("gBrowser.selectedTab.setAttribute('soundplaying', 'true');")
        expect("Joe Cool while a tab plays sound", sprite(styles()["left"]), "joe-cool.png", True)
        m.execute_script("gBrowser.selectedTab.setAttribute('muted', 'true');")
        expect("muted tab brings Snoopy back", sprite(styles()["left"]), "snoopy-typing.png", True)
        m.execute_script("gBrowser.selectedTab.removeAttribute('soundplaying'); gBrowser.selectedTab.removeAttribute('muted');")

        skate = m.execute_script("""
          BrowserCommands.openTab();
          const stack = gBrowser.selectedTab.querySelector('.tab-stack');
          const after = getComputedStyle(stack, '::after');
          const anims = stack.getAnimations({subtree: true}).map(a => a.animationName + ':' + a.playState);
          return {visibility: after.visibility, image: after.backgroundImage, anims: anims.join(',')};
        """)
        expect("new tab skater is visible", skate["visibility"], "visible", True)
        expect("new tab skater has a skate sprite", sprite(skate["image"]), "skate-")
        expect("new tab skate animation is running", skate["anims"], "snoopy-skate:running")

        def tab_shot(ms):
            m.execute_script("""
              const tab = gBrowser.selectedTab; tab.id = 'skate-probe';
              const a = tab.querySelector('.tab-stack').getAnimations({subtree: true}).find(a => a.animationName === 'snoopy-skate');
              a.pause(); a.currentTime = arguments[0];
            """, script_args=[ms])
            time.sleep(0.3)
            png = base64.b64decode(m.screenshot(element=m.find_element(By.ID, "skate-probe")))
            return Image.open(io.BytesIO(png)).convert("RGB")

        mid, done = tab_shot(900), tab_shot(10_000)
        changed = sum(1 for p in ImageChops.difference(mid, done).getdata() if max(p) > 40)
        expect("skater is actually painted over the tab", "painted" if changed > 50 else f"{changed} px", "painted", True)
        m.execute_script("gBrowser.selectedTab.removeAttribute('id');")
        set_pref("snoopy.animations.paused", True)
        hidden = m.execute_script("return getComputedStyle(gBrowser.selectedTab.querySelector('.tab-stack'), '::after').visibility;")
        expect("paused hides the skater", hidden, "hidden", True)
        set_pref("snoopy.animations.paused", False)
        m.execute_script("gBrowser.removeTab(gBrowser.selectedTab);")

        replays = m.execute_script("""
          const tabs = [0, 1, 2].map(() => gBrowser.addTrustedTab('about:blank'));
          return new Promise(resolve => setTimeout(() => {
            gBrowser.selectedTab = tabs[1];
            gBrowser.removeTab(tabs[0]);
            const sidebar = document.querySelector('sidebar-main');
            sidebar.toggleAttribute('expanded', false);
            sidebar.toggleAttribute('expanded', true);
            const running = gBrowser.tabs.flatMap(t => t.querySelector('.tab-stack').getAnimations({subtree: true}))
              .filter(a => a.animationName === 'snoopy-skate' && a.playState === 'running').length;
            tabs.slice(1).forEach(t => gBrowser.removeTab(t));
            resolve(String(running));
          }, 4500));
        """, script_timeout=10000)
        expect("switching, closing, and collapsing don't replay the skate", replays, "0", True)

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

        expanded = m.execute_script("return document.querySelector('sidebar-main').hasAttribute('expanded');")
        m.execute_script("document.querySelector('sidebar-main').toggleAttribute('expanded', arguments[0]);", script_args=[not expanded])
        s = styles()
        if expanded:
            expect("Collapsed sidebar shows Snoopy reading", sprite(s["sidebar"]), "snoopy-reading.png", True)
        else:
            expect("Expanded sidebar shows the doghouse", sprite(s["sidebar"]), "doghouse-scene.png", True)
        m.execute_script("document.querySelector('sidebar-main').toggleAttribute('expanded', arguments[0]);", script_args=[expanded])

        open_tabs = m.execute_script("""
          const n = gBrowser.tabs.length, selected = gBrowser.selectedTab;
          for (let i = 0; i < 30; i++) gBrowser.addTrustedTab('about:blank');
          gBrowser.selectedTab = selected;
          SidebarController._state.launcherExpanded = false;
          return n;
        """)
        time.sleep(1.5)
        room = m.execute_script("""
          const box = document.getElementById('tabbrowser-arrowscrollbox').shadowRoot.querySelector('[part~=scrollbox]');
          const bg = gBrowser.selectedTab.querySelector('.tab-background').getBoundingClientRect();
          return Math.round(box.getBoundingClientRect().left + box.clientWidth - bg.right);
        """)
        m.execute_script("""
          SidebarController._state.launcherExpanded = true;
          gBrowser.tabs.slice(arguments[0]).forEach(t => gBrowser.removeTab(t));
        """, script_args=[open_tabs])
        expect(f"Collapsed, overflowing tab strip fits the selected tab's shadow ({room}px spare)", room >= 2, True, True)

        set_pref("snoopy.color.typing", True)
        s = styles()
        expect("color.typing colors Snoopy", sprite(s["left"]), "color/snoopy-typing.png", True)
        expect("color.typing leaves the doghouse ink", sprite(s["sidebar"]), "doghouse-scene.png", True)
        set_pref("snoopy.animations.slow", True)
        expect("color and slow combine", sprite(styles()["left"]), "color/slow/snoopy-typing.png", True)
        set_pref("snoopy.animations.paused", True)
        expect("color and paused combine", sprite(styles()["left"]), "color/still/snoopy-typing.png", True)
        set_pref("snoopy.animations.paused", False)
        set_pref("snoopy.animations.slow", False)
        set_pref("snoopy.color.typing", False)
        set_pref("snoopy.color.all", True)
        expect("color.all colors the doghouse", sprite(styles()["sidebar"]), "color/doghouse-scene.png", True)
        set_pref("snoopy.color.all", False)
        set_pref("snoopy.ink.cart", True)
        expect("ink.cart inks the cart", sprite(styles()["right"]), "ink/woodstock-cart.png", True)
        set_pref("snoopy.ink.cart", False)
        expect("color prefs off restore defaults", sprite(styles()["left"]) + " " + sprite(styles()["right"]),
               "snoopy-typing.png woodstock-cart.png", True)

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
        zigzag = m.execute_script("return getComputedStyle(gBrowser.getCachedFindBar()).backgroundImage;")
        if dark:
            expect("dark mode skips the find bar zigzag", zigzag, "none", True)
        else:
            expect("Zigzag on find bar", zigzag, "svg")
        m.delete_session()
    finally:
        proc.terminate()
        proc.wait(timeout=20)
        shutil.rmtree(profile, ignore_errors=True)


def main():
    failures = []
    light = {"ui.systemUsesDarkTheme": 0}
    run("default toolbar", light, failures)
    run("flexible spaces", {**light, "browser.uiCustomization.state": json.dumps(SPRING_LAYOUT)}, failures)
    run("dark mode", {"ui.systemUsesDarkTheme": 1}, failures, dark=True)
    print(f"\n{'all checks passed' if not failures else f'{len(failures)} failed:'}")
    for f in failures:
        print(f"  {f}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
