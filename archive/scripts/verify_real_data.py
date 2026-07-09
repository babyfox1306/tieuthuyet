import json
import re
import sqlite3

from kdp_recon.core.html_cache import load_html
from kdp_recon.scrapers.royalroad import reparse_cached

fid = "120928"
html = load_html("royalroad", fid, "story")
print("HTML cache exists:", html is not None)
print("HTML size bytes:", len(html) if html else 0)
print("Live URL: https://www.royalroad.com/fiction/" + fid)

if html:
    for script in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        if '"@type":"Book"' in script or '"@type": "Book"' in script:
            ld = json.loads(script)
            ar = ld.get("aggregateRating", {})
            views = ld.get("interactionStatistic", {})
            print("From cached page JSON-LD:")
            print("  title:", ld.get("name"))
            print("  rating:", ar.get("ratingValue"), "/ ratings:", ar.get("ratingCount"))
            print("  views:", views.get("userInteractionCount"))
            break

parsed = reparse_cached(fid)
print("Parser output:", parsed.get("title"), parsed.get("rating_avg"), parsed.get("review_count"), parsed.get("view_count"))

row = sqlite3.connect("kdp_recon/data/kdp_recon.db").execute(
    "SELECT title, rating_avg, review_count, view_count, scraped_at FROM stories WHERE external_id=?",
    (fid,),
).fetchone()
print("DB:", row)
