"""Strict, dictionary-bound global alias snapshots; no fuzzy counting or text edits."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from ocr_artifacts.digest import sha256_json_compact
from ocr_keywords.alias_map import _fold

SCHEMA = "alias-rules-v1"


def normalized(value):
    return unicodedata.normalize("NFC", value).casefold()


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"Alias {name} must be a nonblank, trimmed string")
    return value


def freeze_rules(path, dictionary):
    """Read once, fail closed, normalize/deduplicate, and bind to the dictionary."""
    raw = Path(path).read_bytes()
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key in alias rules")
            result[key] = value
        return result
    data = json.loads(raw, object_pairs_hook=unique_object)
    fields = {"schema_version", "updated_at_utc", "curator", "normalization_policy",
              "approved_global_aliases", "disallowed_false_positives"}
    if not isinstance(data, dict) or set(data) != fields or data["schema_version"] != SCHEMA:
        raise ValueError("Unsupported or incomplete alias rules schema")
    if data["normalization_policy"] != "NFC_CASEFOLD":
        raise ValueError("Alias rules require NFC_CASEFOLD")
    _text(data["curator"], "curator")
    moment = datetime.fromisoformat(_text(data["updated_at_utc"], "timestamp").replace("Z", "+00:00"))
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("Alias rule timestamp requires a timezone")
    canonical = {normalized(k["keyword"]): k for k in dictionary["canonical_keywords"]}
    rules, verdicts, owners = {}, {}, {}
    for field, status in (("approved_global_aliases", "ACCEPTED"), ("disallowed_false_positives", "REJECTED")):
        mapping = data[field]
        if not isinstance(mapping, dict):
            raise ValueError("Alias rule groups must be objects")
        for target, aliases in mapping.items():
            entry = canonical.get(normalized(_text(target, "target")))
            if entry is None:
                raise ValueError(f"Alias target is absent from the frozen dictionary: {target}")
            if not isinstance(aliases, list):
                raise ValueError("Alias variants must be a list")
            for value in aliases:
                value = {"alias": value} if isinstance(value, str) else value
                if not isinstance(value, dict) or not set(value) <= {"alias", "required_before", "required_after"}:
                    raise ValueError("Unsupported alias/context rule fields")
                alias = normalized(_text(value.get("alias"), "variant"))
                if ("\n" in alias or "\r" in alias or len(alias.split()) < 2
                        or _fold(alias) != _fold(normalized(entry["keyword"]))
                        or alias == normalized(entry["keyword"])):
                    raise ValueError("Alias must be a nonliteral, same-base multiword diacritic variation")
                owner = owners.setdefault(alias, entry["id"])
                if owner != entry["id"]:
                    raise ValueError("One global alias cannot target multiple keywords")
                key = (entry["id"], alias)
                if key in verdicts and verdicts[key] != status:
                    raise ValueError("Conflicting approved/disallowed alias")
                verdicts[key] = status
                rule = {"keyword_id": entry["id"], "keyword": entry["keyword"], "alias": alias, "status": status,
                        **{name: normalized(_text(value[name], name)) for name in ("required_before", "required_after") if name in value}}
                rule_id = "rule-" + sha256_json_compact(rule)[:24]
                rules[rule_id] = {"rule_id": rule_id, **rule}
    result = {"schema_version": SCHEMA, "normalization_policy": "NFC_CASEFOLD", "curator": data["curator"],
              "updated_at_utc": data["updated_at_utc"], "dictionary_snapshot_hash": dictionary["snapshot_sha256"],
              "source_sha256": hashlib.sha256(raw).hexdigest(), "rules": [rules[k] for k in sorted(rules)]}
    result["snapshot_sha256"] = sha256_json_compact(result)
    return result


def validate_frozen_rules(snapshot, dictionary):
    payload = {k: v for k, v in snapshot.items() if k != "snapshot_sha256"}
    if (snapshot.get("schema_version") != SCHEMA or snapshot.get("snapshot_sha256") != sha256_json_compact(payload)
            or snapshot.get("dictionary_snapshot_hash") != dictionary["snapshot_sha256"]):
        raise ValueError("Alias rules snapshot/dictionary identity mismatch")


def match_rule(candidate, text, snapshot):
    """Context is literal within the same paragraph; missing context stays pending."""
    before, after = text[:candidate.match_start], text[candidate.match_end:]
    before = normalized(re.split(r"\r?\n[ \t]*\r?\n", before)[-1]).rstrip()
    after = normalized(re.split(r"\r?\n[ \t]*\r?\n", after)[0]).lstrip()
    for rule in snapshot["rules"]:
        if rule["keyword_id"] != candidate.keyword_id or rule["alias"] != normalized(candidate.observed_text):
            continue
        if "required_before" in rule and not re.search(r"(?<!\w)" + re.escape(rule["required_before"]) + r"\Z", before):
            continue
        if "required_after" in rule and not re.match(re.escape(rule["required_after"]) + r"(?!\w)", after):
            continue
        return rule
    return None
