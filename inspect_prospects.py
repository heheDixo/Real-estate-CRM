# inspect_prospects.py — read-only inspection of discovered leads
from collections import Counter
from database import _db
import json

db = _db()

# 1. Last 30 non-manual prospects
print("=" * 70)
print("LAST 30 DISCOVERED PROSPECTS")
print("=" * 70)
rows = (
    db.table("prospects")
    .select("id, company, domain, contact_name, contact_title, source, sector, city, added_at")
    .neq("source", "manual")
    .order("added_at", desc=True)
    .limit(30)
    .execute()
    .data
)
print(json.dumps(rows, indent=2, default=str))

# 2. Per-source dismiss/approve breakdown
print("\n" + "=" * 70)
print("SOURCE QUALITY BREAKDOWN")
print("=" * 70)
all_rows = (
    db.table("prospects")
    .select("source, dismissed, approved")
    .execute()
    .data
)

by_source: dict[str, dict] = {}
for r in all_rows:
    s = r.get("source") or "(null)"
    bucket = by_source.setdefault(s, {"total": 0, "dismissed": 0, "approved": 0})
    bucket["total"] += 1
    if r.get("dismissed"): bucket["dismissed"] += 1
    if r.get("approved"):  bucket["approved"]  += 1

print(f"{'source':25} {'total':>6} {'dismissed':>10} {'approved':>10} {'dismiss%':>10}")
print("-" * 70)
for s, b in sorted(by_source.items(), key=lambda x: -x[1]["total"]):
    pct = (b["dismissed"] / b["total"] * 100) if b["total"] else 0
    print(f"{s:25} {b['total']:>6} {b['dismissed']:>10} {b['approved']:>10} {pct:>9.1f}%")