"""Read-only, explicit projection of HBlink4 repeater patterns."""

import json
from pathlib import Path


def read_operators(config_path: Path):
    with Path(config_path).open(encoding="utf-8") as source:
        config = json.load(source)
    patterns = config.get("repeater_configurations", {}).get("patterns", [])
    operators = []
    for pattern in patterns:
        match = pattern.get("match", {})
        ranges = match.get("id_ranges", [])
        safe_match = {
            "id_ranges": ranges if isinstance(ranges, list) else [],
            "ids": match.get("ids", []) if isinstance(match.get("ids", []), list) else [],
            "callsigns": match.get("callsigns", []) if isinstance(match.get("callsigns", []), list) else [],
        }
        entry = {"name": str(pattern.get("name", "Unnamed pattern")), "match": safe_match,
                 "base_id": None, "essid": None, "range": None}
        if (len(ranges) == 1 and isinstance(ranges[0], list) and len(ranges[0]) == 2
                and all(type(x) is int for x in ranges[0])):
            start, end = ranges[0]
            entry["range"] = f"{start}-{end}"
            if (start >= 100000000 and end == start + 99 and start % 100 == 0
                    and len(str(start)) == 9 and len(str(end)) == 9
                    and not safe_match["ids"] and not safe_match["callsigns"]):
                entry["base_id"] = start // 100
                entry["essid"] = "00-99"
        operators.append(entry)
    return operators
