"""CLI entry point: ``python -m dc_scraper [options]``."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from . import config
from .fetch import Fetcher
from .scraper import collect


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dc_scraper",
        description="Scrape a DCInside gallery's posts for a given day into SQLite.",
    )
    p.add_argument("--gallery", default=config.DEFAULT_GALLERY_ID,
                   help=f"gallery id (default: {config.DEFAULT_GALLERY_ID})")
    p.add_argument("--date", default=None,
                   help="single target date YYYY-MM-DD (default: today, local time)")
    p.add_argument("--date-from", default=None,
                   help="range start date YYYY-MM-DD (inclusive); use with --date-to")
    p.add_argument("--date-to", default=None,
                   help="range end date YYYY-MM-DD (inclusive); use with --date-from")
    p.add_argument("--db-path", default="dcinside.db",
                   help="SQLite file path (default: dcinside.db)")
    p.add_argument("--max-pages", type=int, default=config.DEFAULT_MAX_PAGES,
                   help="safety cap on list pages to crawl")
    p.add_argument("--delay-min", type=float, default=config.DELAY_MIN)
    p.add_argument("--delay-max", type=float, default=config.DELAY_MAX)
    p.add_argument("--no-comments", action="store_true",
                   help="skip comment collection")
    p.add_argument("--dry-run", action="store_true",
                   help="only count target posts; write nothing to the DB")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.date and (args.date_from or args.date_to):
        parser.error("--date cannot be combined with --date-from/--date-to")
    if args.date_from and args.date_to and args.date_from > args.date_to:
        parser.error(f"--date-from ({args.date_from}) must not be after --date-to ({args.date_to})")
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    fetcher = Fetcher(delay_min=args.delay_min, delay_max=args.delay_max)
    summary = collect(
        gallery_id=args.gallery,
        target_date=args.date,
        date_from=args.date_from,
        date_to=args.date_to,
        db_path=args.db_path,
        fetcher=fetcher,
        max_pages=args.max_pages,
        with_comments=not args.no_comments,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] in ("success", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
