"""Disposable, supervised dataset reader. Input/output contain no credentials."""

import json
import sys
from pathlib import Path

from website_agent.discovery_datasets import osm_query, overture_query
from website_agent.discovery_support import BoundedHTTP, Budget, DiscoveryFault, atomic_json
from website_agent.settings import DiscoveryConfig


def main():
    spec = json.loads(Path(sys.argv[1]).read_text())
    config = DiscoveryConfig.model_validate(spec["config"])
    budget = Budget(config)
    try:
        reader = overture_query if spec["query"]["source"] == "overture" else osm_query
        result = {"data": reader(config, spec["query"], BoundedHTTP(budget))}
    except DiscoveryFault as exc:
        result = {"fault": {"status": exc.status, "reason": exc.reason, "retry_after": exc.retry_after}}
    except MemoryError:
        result = {"fault": {"status": "deferred_resource_limit", "reason": "worker_memory"}}
    except Exception:
        result = {"fault": {"status": "failed_requires_operator", "reason": "dataset_schema_or_reader_error"}}
    result["requests"], result["bytes"] = budget.requests, budget.bytes
    atomic_json(sys.argv[2], result, config.max_disk_bytes // 2)


if __name__ == "__main__":
    main()
