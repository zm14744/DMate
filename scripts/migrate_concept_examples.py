#!/usr/bin/env python3
"""Reproduce reviewed concept-example exercises without changing legacy records.

The checked-in manifest contains authored bilingual questions and difficulty
reasons. Original worked examples stay in the answer, not the exercise prompt.
Run after reviewing the manifest; --check never updates source or shipped files.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "offline-content/example-practice-migration.json"
CANONICAL_DIFFICULTIES = {"简单", "中等", "困难"}
GRADE_ZH = "根据题面给定对象和条件作答，给出所问结论及必要的计算或判断依据。与参考解答数学等价的正确表述同样可得分。"
GRADE_EN = "Use the objects and conditions stated in the question. Give the requested conclusions and the necessary calculations or justification. Mathematically equivalent correct formulations receive credit."


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text_sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def record_sha256(value):
    return text_sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def migrated_question(concept, english_concept, entry):
    cid = concept["id"]
    require(entry.get("question_id") == "q-example-" + cid, cid + ": unstable migrated question ID")
    require(entry.get("example_sha256") == text_sha256(concept["example"]),
            cid + ": source example changed; review the question and migration manifest")
    require(entry.get("english_example_sha256") == text_sha256(english_concept["example"]),
            cid + ": English source example changed; review the migration manifest")
    for key in ("statement_zh", "statement_en", "difficulty_reason_zh"):
        require(isinstance(entry.get(key), str) and entry[key].strip(), cid + ": missing " + key)
    require(entry.get("difficulty") in CANONICAL_DIFFICULTIES, cid + ": noncanonical migrated difficulty")
    require(entry.get("type") in {"计算", "简答", "证明"}, cid + ": invalid migrated exercise type")
    require(entry["statement_zh"].strip() != concept["example"].strip(), cid + ": answer used as question")
    require(entry["statement_en"].strip() != english_concept["example"].strip(), cid + ": English answer used as question")
    knowledge_points = entry.get("knowledge_points", [cid])
    require(isinstance(knowledge_points, list) and knowledge_points
            and all(isinstance(ref, str) and ref.strip() for ref in knowledge_points)
            and len(knowledge_points) == len(set(knowledge_points)),
            cid + ": invalid migrated concept references")
    explanation_zh = concept["example"] + "\n\n" + concept["explanation"]
    explanation_en = english_concept["example"] + "\n\n" + english_concept["explanation"]
    require(bool(entry.get("explanation_append_zh")) == bool(entry.get("explanation_append_en")),
            cid + ": explanation addition must have both languages")
    if entry.get("explanation_append_zh"):
        explanation_zh += "\n\n" + entry["explanation_append_zh"]
        explanation_en += "\n\n" + entry["explanation_append_en"]
    question = {
        "id": entry["question_id"], "title": concept["title"] + "：例题练习",
        "category": concept["category"], "knowledge_points": list(knowledge_points),
        "difficulty": entry["difficulty"], "type": entry["type"],
        "statement": entry["statement_zh"], "answer_text": concept["example"],
        "explanation": explanation_zh, "grading_criteria": GRADE_ZH,
        "source": {
            "kind": "DMate独立编写",
            "note": "从DMate自有概念例子改写为独立练习，保留原解答素材；未导入第三方题干。",
            "authors": "DMate（AI辅助编写）", "references": deepcopy(concept["references"]),
            "review_status": "题干、双语对应与原例条件经逐条核对，并有结构与有限算例检查；尚未经独立教师逐题终审。",
            "difficulty_rationale": entry["difficulty_reason_zh"],
            "migrated_from": {
                "kind": "concept_example", "concept_id": cid,
                "example_sha256": entry["example_sha256"],
                "english_example_sha256": entry["english_example_sha256"],
            },
        },
        "graph_node_ids": [concept["graph_node_id"]],
    }
    english = {
        "title": english_concept["title"] + ": example practice", "statement": entry["statement_en"],
        "answer_text": english_concept["example"], "explanation": explanation_en, "grading_criteria": GRADE_EN,
    }
    return question, english


def validate_example_migration(concepts, questions, translations, manifest):
    """Check complete source coverage, original answers and unchanged legacy IDs."""
    require(manifest.get("schema_version") == 1, "invalid example migration schema")
    entries = manifest.get("examples", {})
    concepts_by_id = {c["id"]: c for c in concepts["concepts"]}
    questions_by_id = {q["id"]: q for q in questions["questions"]}
    require(len(concepts_by_id) == len(concepts["concepts"]), "duplicate concept IDs in example migration")
    require(len(questions_by_id) == len(questions["questions"]), "duplicate question IDs in example migration")
    require(set(entries) == set(concepts_by_id), "example migration must cover every concept exactly once")
    legacy_ids = manifest.get("legacy_question_ids", [])
    require(legacy_ids and len(legacy_ids) == len(set(legacy_ids)), "invalid legacy exercise registry")
    require(set(legacy_ids) == set(manifest.get("legacy_question_sha256", {})), "legacy exercise hash coverage differs")
    for qid in legacy_ids:
        require(qid in questions_by_id, qid + ": legacy practice record disappeared")
        require(record_sha256(questions_by_id[qid]) == manifest["legacy_question_sha256"][qid],
                qid + ": legacy question changed during example migration")
        english_hashes = manifest.get("legacy_english_question_sha256", {})
        if english_hashes:
            require(qid in english_hashes and qid in translations["questions"]
                    and record_sha256(translations["questions"][qid]) == english_hashes[qid],
                    qid + ": legacy English question changed during example migration")
    for cid, concept in concepts_by_id.items():
        expected, english = migrated_question(concept, translations["concepts"][cid], entries[cid])
        require(all(ref in concepts_by_id for ref in expected["knowledge_points"]),
                cid + ": unknown migrated concept reference")
        require(all(concepts_by_id[ref]["id"] != concepts_by_id[ref]["graph_node_id"]
                    for ref in expected["knowledge_points"]),
                cid + ": migrated exercises must reference detailed concepts")
        require(all(concepts_by_id[ref]["graph_node_id"] == concept["graph_node_id"]
                    for ref in expected["knowledge_points"]),
                cid + ": migrated concept references leave the source topic")
        qid = expected["id"]
        require(questions_by_id.get(qid) == expected, cid + ": migrated exercise differs from reviewed manifest")
        require(translations["questions"].get(qid) == english, cid + ": English migrated exercise differs from review")
        require(qid in concept.get("related_questions", []), cid + ": migrated practice is not linked to concept")


def migration_targets(root):
    """Return deterministic source-file contents; this function never writes."""
    from offline_translations import compile_translations, source_manifest
    from sync_offline_content import prepare
    root = Path(root)
    manifest = load(root / MANIFEST)
    cp = load(root / "offline-content/concepts.zh-CN.json")
    qp = load(root / "offline-content/questions.zh-CN.json")
    # Existing translated material must already match its Chinese source.
    translations = compile_translations(root, cp, qp)
    entries = manifest.get("examples", {})
    require(set(entries) == {c["id"] for c in cp["concepts"]}, "example migration must cover every concept exactly once")
    current = {q["id"]: q for q in qp["questions"]}
    for qid in manifest.get("legacy_question_ids", []):
        require(qid in current and record_sha256(current[qid]) == manifest["legacy_question_sha256"][qid],
                qid + ": legacy question changed during example migration")
    cp, qp = deepcopy(cp), deepcopy(qp)
    cp["pack_version"] = qp["pack_version"] = manifest["target_pack_version"]
    qids = {entry["question_id"] for entry in entries.values()}
    qp["questions"] = [q for q in qp["questions"] if q["id"] not in qids]
    shards = [load(root / f"offline-content/i18n/en/part-{i}.json") for i in range(4)]
    for concept in cp["concepts"]:
        question, english = migrated_question(concept, translations["concepts"][concept["id"]], entries[concept["id"]])
        qp["questions"].append(question)
        shard = next(s for s in shards if concept["id"] in s["concepts"])
        shard["questions"][question["id"]] = english
    cp, qp = prepare(load(root / "knowledge_graph.json"), cp, qp, load(root / "offline-content/references.zh-CN.json"))
    # Newly added concepts can sit between existing topic groups. Canonicalize
    # translated question order as well so legacy-only inputs reproduce release
    # files regardless of when those examples were first added to a shard.
    for shard in shards:
        shard["questions"] = {question["id"]: shard["questions"][question["id"]]
                              for question in qp["questions"] if question["id"] in shard["questions"]}
    merged = {"concepts": translations["concepts"], "questions": {}}
    for shard in shards:
        merged["questions"].update(shard["questions"])
    validate_example_migration(cp, qp, merged, manifest)
    targets = {
        root / "offline-content/concepts.zh-CN.json": encoded(cp),
        root / "offline-content/questions.zh-CN.json": encoded(qp),
        root / "offline-content/i18n/en/source-manifest.json": encoded(source_manifest(cp, qp)),
    }
    targets.update({root / f"offline-content/i18n/en/part-{i}.json": encoded(shard) for i, shard in enumerate(shards)})
    return targets


def apply_migration(root, check=False):
    targets = migration_targets(root)
    changed = [path for path, content in targets.items()
               if not path.exists() or path.read_text(encoding="utf-8") != content]
    if check and changed:
        raise ValueError("Example migration outputs need syncing: " + ", ".join(str(path) for path in changed))
    if not check:
        for path in changed:
            path.write_text(targets[path], encoding="utf-8")
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        changed = apply_migration(ROOT, check=args.check)
        subprocess.run([sys.executable, str(ROOT / "scripts/sync_offline_content.py")]
                       + (["--check"] if args.check else []), cwd=ROOT, check=True)
        print(f"Reviewed example-practice migration is reproducible; {len(changed)} source files updated")
    except (ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
