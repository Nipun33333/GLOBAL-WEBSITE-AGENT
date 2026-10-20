"""Zero-key Overture GeoParquet and explicitly licensed OSM data readers."""

import io
import json
import re
from urllib.parse import quote

from defusedxml import ElementTree as ET

from website_agent.discovery_support import DiscoveryFault, inside, permission, resource, schema

AWS = "https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com"
AZURE = "https://overturemapswestus2.blob.core.windows.net"
CATALOG = "https://stac.overturemaps.org/catalog.json"
OVERTURE_LICENSE = "CDLA-Permissive-2.0 / Apache-2.0 / CC0-1.0 (see per-record sources)"
OVERTURE_ATTRIBUTION = "Overture Maps Foundation; retain original sources and applicable license notices"
OSM_LICENSE = "ODbL-1.0"
OSM_ATTRIBUTION = "© OpenStreetMap contributors; https://www.openstreetmap.org/copyright"


class RangeFile(io.RawIOBase):
    def __init__(self, http, url, size):
        self.http, self.url, self.size, self.pos = http, url, size, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset + (self.pos if whence == 1 else self.size if whence == 2 else 0)
        if not 0 <= self.pos <= self.size:
            raise schema("invalid_parquet_offset")
        return self.pos

    def read(self, size=-1):
        size = min(self.size - self.pos, size if size >= 0 else self.size)
        if not size:
            return b""
        start, end = self.pos, self.pos + size - 1
        raw, headers = self.http.get(self.url, cap=size, headers={"Range": f"bytes={start}-{end}"})
        if len(raw) != size or headers.get("content-range") != f"bytes {start}-{end}/{self.size}":
            raise schema("invalid_or_partial_range")
        self.pos += size
        return raw


def release(config, http):
    if config.release != "latest":
        if not config.release_reference:
            raise permission("pinned_release_reference_required")
        return config.release
    data, _ = http.get(CATALOG, cap=2_000_000)
    value = json.loads(data).get("latest", "")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9]+", value):
        raise schema("catalog_release_schema_changed")
    return value


def objects(http, endpoint, version):
    """Bounded listing, not a download of the global dataset."""
    prefix = f"{version}/theme=places/type=place/"
    if endpoint == "aws":
        raw, _ = http.get(
            AWS + "/",
            params={"list-type": "2", "prefix": "release/" + prefix, "max-keys": 1000},
            cap=2_000_000,
        )
        tree = ET.fromstring(raw)
        if tree.findtext("{*}IsTruncated") == "true":
            raise resource("object_listing_budget")
        items = [(x.findtext("{*}Key"), x.findtext("{*}Size")) for x in tree.findall("{*}Contents")]
        base, expected = AWS + "/", "release/" + prefix
    else:
        raw, _ = http.get(
            AZURE + "/release",
            params={"restype": "container", "comp": "list", "prefix": prefix, "maxresults": 1000},
            cap=2_000_000,
        )
        tree = ET.fromstring(raw)
        if tree.findtext("NextMarker"):
            raise resource("object_listing_budget")
        items = [
            (x.findtext("Name"), x.findtext("Properties/Content-Length")) for x in tree.findall("Blobs/Blob")
        ]
        base, expected = AZURE + "/release/", prefix
    result = []
    for name, size in items:
        if not name or not name.startswith(expected) or ".." in name:
            raise schema("unexpected_object_path")
        if name.endswith(".parquet"):
            result.append((base + quote(name, safe="/=.-_"), int(size)))
    if not result:
        raise schema("release_has_no_place_objects")
    return sorted(result)


def overlaps(group, bbox):
    columns = {group.column(i).path_in_schema: group.column(i) for i in range(group.num_columns)}
    try:
        bounds = [columns["bbox." + k].statistics for k in ("xmin", "ymin", "xmax", "ymax")]
        if any(s is None or not s.has_min_max for s in bounds):
            return True
        return not (
            bounds[2].max < bbox[0]
            or bounds[0].min > bbox[2]
            or bounds[3].max < bbox[1]
            or bounds[1].min > bbox[3]
        )
    except KeyError:
        raise schema("missing_bbox_statistics_columns") from None


def overture_record(row, version):
    """Known legacy and current taxonomy shapes; unknown schemas fail closed."""
    bbox = row.get("bbox") or {}
    category = (row.get("taxonomy") or row.get("categories") or {}).get("primary")
    address = next((a for a in row.get("addresses") or [] if a.get("country") and a.get("locality")), {})
    websites = row.get("websites") or []
    if not (websites and address and category and row.get("names", {}).get("primary")):
        return None
    if row.get("operating_status") in {"permanently_closed", "closed"}:
        return None
    return {
        "provider": "overture",
        "provider_id": row["id"],
        "name": row["names"]["primary"],
        "url": websites[0],
        "country": address["country"],
        "city": address["locality"],
        "category": category,
        "lon": (bbox["xmin"] + bbox["xmax"]) / 2,
        "lat": (bbox["ymin"] + bbox["ymax"]) / 2,
        "release": version,
        "license": OVERTURE_LICENSE,
        "attribution": OVERTURE_ATTRIBUTION,
        "sources": row.get("sources") or [],
        "address": address,
    }


def overture_query(config, query, http):
    import pyarrow.parquet as pq

    version = query.get("resolved_release") or release(config, http)
    listing = objects(http, query["endpoint"], version)
    cursor = query.get("cursor") or {"file": 0, "group": 0, "row": 0}
    first = cursor["file"]
    results = []
    progress = dict(cursor)
    try:
        for file_index in range(first, min(len(listing), first + config.max_files_per_query)):
            progress = {"file": file_index, "group": 0, "row": 0}
            http.budget.check()
            url, size = listing[file_index]
            with RangeFile(http, url, size) as reader:
                parquet = pq.ParquetFile(
                    reader,
                    pre_buffer=False,
                    buffer_size=0,
                    thrift_string_size_limit=2_000_000,
                    thrift_container_size_limit=100_000,
                )
                names = set(parquet.schema_arrow.names)
                required = {"id", "names", "bbox", "addresses", "websites"}
                if not required <= names or not {"taxonomy", "categories"} & names:
                    raise schema()
                columns = sorted(
                    (required | {"taxonomy", "categories", "sources", "operating_status"}) & names
                )
                for group_index in range(
                    cursor["group"] if file_index == first else 0, parquet.num_row_groups
                ):
                    progress = {"file": file_index, "group": group_index, "row": 0}
                    group = parquet.metadata.row_group(group_index)
                    if not overlaps(group, query["bbox"]):
                        continue
                    if group.total_byte_size > config.max_memory_mb * 1024 * 1024 // 2:
                        raise resource("parquet_row_group_memory_budget")
                    row_index = 0
                    for batch in parquet.iter_batches(
                        batch_size=128, row_groups=[group_index], columns=columns, use_threads=False
                    ):
                        http.budget.check()
                        for row in batch.to_pylist():
                            row_index += 1
                            progress = {"file": file_index, "group": group_index, "row": row_index}
                            if (
                                file_index == first
                                and group_index == cursor["group"]
                                and row_index <= cursor["row"]
                            ):
                                continue
                            try:
                                candidate = overture_record(row, version)
                            except (KeyError, TypeError, ValueError):
                                continue
                            if (
                                candidate
                                and inside(query["bbox"], candidate["lon"], candidate["lat"])
                                and candidate["category"] in query["categories"]
                            ):
                                results.append(candidate)
                            if len(results) >= config.max_candidates:
                                return {
                                    "records": results,
                                    "cursor": {"file": file_index, "group": group_index, "row": row_index},
                                    "release": version,
                                    "exhausted": False,
                                }
        next_file = min(len(listing), first + config.max_files_per_query)
        return {
            "records": results,
            "cursor": {"file": next_file, "group": 0, "row": 0},
            "release": version,
            "exhausted": next_file == len(listing),
        }
    except DiscoveryFault as exc:
        if results or progress != cursor:
            return {
                "records": results,
                "cursor": progress,
                "release": version,
                "exhausted": False,
                "fault": {"status": exc.status, "reason": exc.reason, "retry_after": exc.retry_after},
            }
        raise


def osm_record(element, version):
    tags = element.get("tags", {})
    category = next(
        (
            f"{key}={tags[key]}"
            for key in ("shop", "amenity", "leisure", "craft", "office", "healthcare")
            if key in tags
        ),
        "",
    )
    point = element.get("center") or element
    if not (
        tags.get("name")
        and (tags.get("website") or tags.get("contact:website"))
        and tags.get("addr:city")
        and tags.get("addr:country")
        and category
    ):
        return None
    return {
        "provider": "osm",
        "provider_id": f"{element['type']}/{element['id']}",
        "name": tags["name"],
        "url": tags.get("website") or tags["contact:website"],
        "city": tags["addr:city"],
        "country": tags["addr:country"].upper(),
        "category": category,
        "lat": float(point["lat"]),
        "lon": float(point["lon"]),
        "release": version,
        "license": OSM_LICENSE,
        "attribution": OSM_ATTRIBUTION,
        "sources": [{"dataset": "OpenStreetMap", "record_id": f"{element['type']}/{element['id']}"}],
        "address": {k: v for k, v in tags.items() if k.startswith("addr:")},
    }


def osm_allowed(config):
    if not config.osm_database_obligations_accepted or not config.osm_license_review_reference:
        raise permission("osm_license_and_database_obligations_not_reviewed")


def osm_query(config, query, http):
    osm_allowed(config)
    records = []
    if query["source"] == "overpass":
        if not (
            config.overpass_private_or_contracted
            and config.overpass_commercial_use_authorized
            and config.overpass_agreement_reference
            and config.overpass_endpoint
        ):
            raise permission("overpass_commercial_endpoint_not_authorized")
        # One configured private/contracted endpoint. Never discover or rotate public servers.
        from website_agent.security import public_addresses

        public_addresses(config.overpass_endpoint)
        clauses = []
        w, s, e, n = query["bbox"]
        for cat in query["categories"]:
            if not re.fullmatch(r"[a-z_]+=[a-z_]+", cat):
                continue
            key, value = cat.split("=")
            clauses.append(f'nwr["{key}"="{value}"]({s},{w},{n},{e});')
        if not clauses:
            return {"records": [], "exhausted": True, "cursor": {}}
        q = "[out:json][timeout:15][maxsize:16777216];(" + "".join(clauses) + ");out center tags;"
        raw, _ = http.get(
            config.overpass_endpoint, params={"data": q}, cap=min(8_000_000, config.max_download_bytes)
        )
        data = json.loads(raw)
        if data.get("remark"):
            from website_agent.discovery_support import unavailable

            raise unavailable("overpass_partial_or_timeout")
        if not isinstance(data.get("elements"), list):
            raise schema("overpass_schema_changed")
        version = data.get("osm3s", {}).get("timestamp_osm_base", "")
        if not version:
            raise schema("osm_release_missing")
        elements = data["elements"]
    else:
        extract = next(
            (
                x
                for x in config.osm_extracts
                if x.get("country") == query["country"] and x.get("city") == query["city"]
            ),
            None,
        )
        if (
            not extract
            or extract.get("commercial_use_authorized") is not True
            or not extract.get("agreement_reference")
        ):
            raise permission("osm_regional_extract_not_authorized")
        from pathlib import Path

        path = Path(extract["path"]).resolve()
        if not path.is_relative_to(Path("private").resolve()) or not path.is_file():
            raise permission("osm_extract_requires_private_local_file")
        if path.stat().st_size > min(config.max_disk_bytes, config.max_download_bytes):
            raise resource("osm_extract_size_budget")
        # SHA-256 verifies the entire operator-provided regional extract before reading it.
        import hashlib

        with path.open("rb") as f:
            digest = hashlib.file_digest(f, "sha256").hexdigest()
        if digest != extract.get("sha256") or not extract.get("release"):
            raise schema("osm_extract_integrity_or_release")
        version = extract["release"]

        def nodes():
            # Streaming XML nodes; ways without reliable centers are deliberately skipped.
            with path.open("rb") as handle:
                parser = ET.iterparse(handle, events=("start", "end"))
                _, root = next(parser)
                if root.tag != "osm":
                    raise schema("osm_xml_schema_changed")
                for event, element in parser:
                    if event != "end":
                        continue
                    if element.tag == "node":
                        yield {
                            "type": "node",
                            **element.attrib,
                            "tags": {t.attrib["k"]: t.attrib["v"] for t in element.findall("tag")},
                        }
                        root.clear()
                    elif element.tag in {"way", "relation"}:
                        root.clear()

        elements = nodes()
    start = (query.get("cursor") or {}).get("row", 0)
    for index, element in enumerate(elements):
        http.budget.check()
        if index < start:
            continue
        try:
            candidate = osm_record(element, version)
        except (KeyError, TypeError, ValueError):
            continue
        if (
            candidate
            and inside(query["bbox"], candidate["lon"], candidate["lat"])
            and candidate["category"] in query["categories"]
        ):
            records.append(candidate)
        if len(records) >= config.max_candidates:
            return {"records": records, "cursor": {"row": index + 1}, "exhausted": False, "release": version}
    return {"records": records, "cursor": {}, "exhausted": True, "release": version}
