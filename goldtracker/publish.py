"""Write a read-only copy of the dashboard for GitHub Pages.

    python -m goldtracker publish            # writes ./site
    python -m goldtracker publish --push     # ...then git add/commit/push the site folder

The site is the same dashboard page in "static mode": it reads data/meta.json, data/deals.json and
data/history.json instead of the local API. Deals are ranked with the offers in MY_OFFERS (plus any
public sale coupons), so visitors can filter but not change cards. The SQLite database never leaves
your computer. Anything in site/ is public on GitHub Pages: no personal data is written there.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from . import db
from .config import ROOT, Settings
from .offers import load_offers
from .rates import IST
from .ranking import rank
from .status import build_meta

STATIC_INDEX = Path(__file__).parent / "web" / "static" / "index.html"
MARKER = "<script>"


def _static_page() -> str:
    html = STATIC_INDEX.read_text(encoding="utf-8")
    i = html.rindex(MARKER)  # the page's main script is the last <script>
    flag = '<script>window.GT_STATIC = true;</script>\n'
    return html[:i] + flag + html[i:]


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def publish(settings: Settings, now: datetime | None = None) -> dict:
    out = Path(settings.publish_dir)
    (out / "data").mkdir(parents=True, exist_ok=True)
    with db.open_db(settings.db_path) as conn:
        meta = build_meta(conn, settings, now)
        deals = rank(conn, load_offers(settings.offers_path), held=set(settings.my_offers),
                     include_first_order=False, rate_sources=settings.rate_sources)
        history = {d.product_id: db.price_history(conn, d.product_id, 30) for d in deals}
    meta["published_at"] = (now or datetime.now(IST)).isoformat(timespec="seconds")
    # Only what the page needs; keep the public file small and free of local paths
    meta["my_offers"] = [o["id"] for o in meta["offers"] if o["id"] in settings.my_offers]
    _write_json(out / "data" / "meta.json", meta)
    _write_json(out / "data" / "deals.json", {"count": len(deals), "deals": [d.as_dict() for d in deals]})
    _write_json(out / "data" / "history.json", {str(k): v for k, v in history.items()})
    (out / "index.html").write_text(_static_page(), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    result = {"dir": str(out), "deals": len(deals), "pushed": False}
    if settings.publish_git_push:
        result["pushed"] = git_push(out)
    return result


def git_push(site_dir: Path, repo: Path = ROOT) -> bool:
    """Commit and push only the site folder. Returns False if there was nothing new."""
    rel = str(Path(site_dir).resolve().relative_to(repo.resolve()))
    subprocess.run(["git", "-C", str(repo), "add", rel], check=True)
    if subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--quiet", "--", rel]).returncode == 0:
        return False
    stamp = datetime.now(IST).strftime("%d %b %H:%M")
    subprocess.run(["git", "-C", str(repo), "commit", "-m", f"Update deals ({stamp} IST)", "--", rel], check=True)
    subprocess.run(["git", "-C", str(repo), "push"], check=True)
    return True
