"""Validate reviewed changes to exercise concept links against their originals."""
from copy import deepcopy
import hashlib
import json


def record_digest(record):
    raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_classification_manifest(concepts, questions, manifest):
    """Only the recorded concept associations may differ from original records."""
    def require(condition, message):
        if not condition:
            raise ValueError("question classification: " + message)

    require(manifest.get("schema_version") == 1, "unsupported manifest schema")
    require(manifest.get("target_pack_version") == questions.get("pack_version"), "pack version differs")
    entries = manifest.get("assignments")
    require(isinstance(entries, dict) and entries, "missing reviewed assignments")
    by_concept = {row["id"]: row for row in concepts["concepts"]}
    by_question = {row["id"]: row for row in questions["questions"]}
    for qid, entry in entries.items():
        require(qid in by_question, qid + ": exercise disappeared")
        question = by_question[qid]
        previous, assigned = entry.get("previous_concept_ids"), entry.get("concept_ids")
        require(isinstance(previous, list) and previous and len(set(previous)) == len(previous)
                and all(cid in by_concept for cid in previous), qid + ": invalid original concepts")
        require(isinstance(assigned, list) and assigned and len(set(assigned)) == len(assigned)
                and all(cid in by_concept and cid != by_concept[cid]["graph_node_id"] for cid in assigned),
                qid + ": assignments must contain distinct detailed concepts")
        require(all(cid in assigned for cid in previous if cid != by_concept[cid]["graph_node_id"]),
                qid + ": existing detailed association disappeared")
        require({by_concept[cid]["graph_node_id"] for cid in previous}
                == {by_concept[cid]["graph_node_id"] for cid in assigned}, qid + ": graph modules changed")
        require(isinstance(entry.get("reason_zh"), str) and entry["reason_zh"].strip(), qid + ": missing classification reason")
        require(question["knowledge_points"] == assigned, qid + ": reviewed assignments differ")
        require(record_digest(question) == entry.get("classified_record_sha256"), qid + ": reviewed record changed")
        original = deepcopy(question)
        original["knowledge_points"] = previous
        require(record_digest(original) == entry.get("original_record_sha256"),
                qid + ": original content or metadata changed beyond concept associations")
