# HabitFlame on GitHub Pages

The canonical HabitFlame site is https://habitflame.vishutdhar.com, built from
the habitflame-web repository. Edit pages there, never here.

This repository keeps the old addresses under
https://vishutdhar.github.io/HabitFlame-Public/ working. App Store Connect
links its support and privacy pages here. Every page is a byte for byte copy
of the custom domain page, whose canonical link and og:url point at the custom
domain, so search engines treat the two as one page.

To update the mirror after a change in habitflame-web:

    python3 scripts/sync-mirror.py ~/Code/habitflame-web
    python3 scripts/verify-pages.py --source ~/Code/habitflame-web

`--source` also runs habitflame-web's own verifier on that checkout, so the
copy is only accepted when the canonical pages pass their checks.

After the custom domain deploys, `python3 scripts/verify-pages.py --live`
confirms the mirror matches what it serves.

googled95610149d8bb2dd.html verifies this address in Google Search Console.
Keep it.
