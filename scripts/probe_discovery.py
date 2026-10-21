"""Bounded public dataset diagnostic: no website visits, database, credentials or account APIs."""

import argparse
import json
from collections import Counter
from pathlib import Path

import yaml

from website_agent.discovery_engine import run_reader
from website_agent.discovery_support import Budget, DiscoveryFault, atomic_json
from website_agent.settings import Config, SearchArea


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", choices=["GB"], default="GB")
    parser.add_argument("--city", default="London")
    parser.add_argument("--niche", default="salons")
    parser.add_argument("--endpoint", choices=["aws", "azure"], default="aws")
    parser.add_argument("--bbox", nargs=4, type=float)
    args = parser.parse_args()
    config = Config.model_validate(yaml.safe_load(Path("config/settings.yml").read_text()))
    location = next(x for x in config.locations if x.country == args.country and x.city == args.city)
    bbox = args.bbox or location.bbox
    SearchArea(country=location.country, city=location.city, bbox=bbox)
    if not (
        location.bbox[0] <= bbox[0] < bbox[2] <= location.bbox[2]
        and location.bbox[1] <= bbox[1] < bbox[3] <= location.bbox[3]
    ):
        parser.error("Diagnostic bbox must fit the configured city bounds")
    taxonomy = yaml.safe_load(Path(config.discovery.taxonomy_path).read_text())
    query = {
        "source": "overture",
        "endpoint": args.endpoint,
        "country": location.country,
        "city": location.city,
        "bbox": bbox,
        "categories": taxonomy["niches"][args.niche]["primary"]["overture"],
        "cursor": {},
    }
    budget = Budget(config.discovery)
    try:
        result = run_reader(config.discovery, query, budget)
        summary = {k: v for k, v in result.items() if k != "records"}
        summary["candidate_count"] = len(result["records"])
        summary["source_localities"] = dict(Counter(x["city"] for x in result["records"]))
        summary["source_categories"] = dict(Counter(x["category"] for x in result["records"]))
        summary["status"] = (result.get("fault") or {}).get("status", "dataset_probe_only")
    except DiscoveryFault as exc:
        result = {}
        summary = {"status": exc.status, "reason": exc.reason}
    summary.update(
        endpoint=args.endpoint,
        bbox=bbox,
        requests=budget.requests,
        bytes=budget.bytes,
        elapsed_seconds=round(budget.clock() - budget.started, 3),
        websites_verified=0,
        businesses_inserted=0,
        transfer_counts_are_upper_bounds=getattr(budget, "accounting_unknown", False),
    )
    atomic_json(
        Path("private") / f"discovery-probe-{args.endpoint}.json",
        {"summary": summary, "data": result},
        config.discovery.max_disk_bytes // 2,
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary["status"] == "dataset_probe_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())
