import sqlite3

conn = sqlite3.connect("kdp_recon/data/kdp_recon.db")
conn.row_factory = sqlite3.Row
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
print("=== TABLES ===")
for (t,) in tables:
    n = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
    print(f"  {t}: {n} rows")

print("\n=== royalroad stories (3 rows) ===")
rows = conn.execute(
    "SELECT id, platform, external_id, title, author_name, rating_avg, "
    "review_count, follower_count, chapter_count, view_count, tags, status, scraped_at "
    "FROM stories WHERE platform='royalroad' LIMIT 3"
).fetchall()
for r in rows:
    print(dict(r))

print("\n=== non-null counts (stories) ===")
cols = [
    "title", "author_name", "rating_avg", "review_count", "follower_count",
    "chapter_count", "view_count", "tags", "status",
]
for c in cols:
    n = conn.execute(f"SELECT COUNT(*) FROM stories WHERE {c} IS NOT NULL AND {c} != ''").fetchone()[0]
    print(f"  {c}: {n}")
