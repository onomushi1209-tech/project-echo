#!/usr/bin/env python
"""Real-source smoke test for a vertical's Source Registry.

NOT part of the pytest suite -- pytest must never depend on network access
(see docs/SOURCE_INTELLIGENCE.md). Run this manually:

    python scripts/smoke_test_sources.py [--vertical ai]

Makes exactly one real HTTP request per *enabled* source, through the
actual echo.source fetch/adapter stack -- no retry loop beyond the fetch
layer's own bounded retry, no bypass of robots/WAF/rate limits, no bulk
crawling. Reports success/failure per source. Exits non-zero only if the
script itself errors; an unreachable *source* is reported in the output,
never turned into a nonzero exit code -- an external outage must not fail
CI or be confused with a code defect.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from echo.config.settings import get_settings  # noqa: E402
from echo.models.enums import SourceType  # noqa: E402
from echo.source.adapters import ADAPTERS, AdapterError, load_fixture  # noqa: E402
from echo.source.http_client import fetch  # noqa: E402
from echo.source.registry import enabled_sources  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--vertical", default="ai", help="Vertical id to check (default: ai)")
    args = parser.parse_args()

    settings = get_settings()
    sources = enabled_sources(args.vertical, config_dir=settings.config_dir)

    if not sources:
        print(f"No enabled sources for vertical '{args.vertical}'.")
        return 0

    print(f"Real-source smoke test for vertical '{args.vertical}' -- {len(sources)} enabled source(s).")
    print("One request per source, no retries beyond the fetch layer's own cap, no bypass.\n")

    results: list[tuple[str, bool, str]] = []
    for source in sources:
        if source.source_type == SourceType.STATIC_FIXTURE:
            fixture_path = settings.fixtures_dir / f"{source.id}.json"
            try:
                records = load_fixture(fixture_path)
                results.append((source.id, True, f"fixture OK, {len(records)} item(s)"))
            except AdapterError as exc:
                results.append((source.id, False, f"fixture error: {exc}"))
            continue

        outcome = fetch(str(source.url))
        if not outcome.ok:
            results.append((source.id, False, f"{outcome.error_type}: {outcome.message}"))
            continue

        adapter = ADAPTERS.get(source.source_type)
        if adapter is None:
            results.append((source.id, False, f"no adapter registered for {source.source_type}"))
            continue

        try:
            records = adapter(outcome.body or b"")
            results.append((source.id, True, f"HTTP {outcome.status_code}, {len(records)} item(s) parsed"))
        except AdapterError as exc:
            results.append((source.id, False, f"fetched but failed to parse: {exc}"))

    for source_id, ok, detail in results:
        status = "OK  " if ok else "FAIL"
        print(f"[{status}] {source_id}: {detail}")

    succeeded = sum(1 for _, ok, _ in results if ok)
    print(f"\n{succeeded}/{len(results)} enabled source(s) reachable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
