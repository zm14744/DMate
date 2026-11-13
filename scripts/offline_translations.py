"""Compile reviewed, ID-based English overrides for the original offline packs."""
import hashlib
import json
from pathlib import Path
import re


CONCEPT_FIELDS = ("title", "summary", "definition", "explanation", "notation", "example", "common_mistakes")
QUESTION_FIELDS = ("title", "statement", "answer_text", "explanation", "grading_criteria")
HAN = re.compile(r"[\u3400-\u9fff]")


def display_record(row, kind):
    if kind == "concepts":
        return {key: row[key] for key in CONCEPT_FIELDS}
    record = {key: row[key] for key in QUESTION_FIELDS if key in row}
    record["answer_text"] = row.get("answer_text") or "、".join(row.get("answer", []))
    if "options" in row:
        record["options"] = row["options"]
    record["type"] = row["type"]
    return record


def source_manifest(concepts, questions):
    result = {"schema_version": 1}
    for kind, pack in (("concepts", concepts), ("questions", questions)):
        result[kind] = {}
        for row in pack[kind]:
            raw = json.dumps(display_record(row, kind), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            result[kind][row["id"]] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return result


def require(condition, message):
    if not condition:
        raise ValueError(message)


def english_text(value, label):
    require(isinstance(value, str) and value.strip(), label + ": missing English text")
    require(not HAN.search(value), label + ": untranslated Chinese content")


def compile_translations(root, concepts, questions):
    folder = Path(root) / "offline-content/i18n/en"
    manifest_path = folder / "source-manifest.json"
    require(manifest_path.exists(), "English translation source manifest is missing")
    expected = source_manifest(concepts, questions)
    recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    for kind in ("concepts", "questions"):
        require(recorded.get(kind) == expected[kind],
                kind + ": English translations need review after Chinese content changes")
    output = {"schema_version": 1, "language": "en",
              "source_pack_versions": {"concepts": concepts.get("pack_version"), "questions": questions.get("pack_version")},
              "rights_notice": "English translations of DMate's original Chinese learning content. Distribution terms are determined by the project rights holder; no additional open license is granted. Source bibliographies are retained in the Chinese packs.",
              "concepts": {}, "questions": {}}
    for index in range(4):
        path = folder / ("part-" + str(index) + ".json")
        require(path.exists(), "English translation shard is missing: " + path.name)
        shard = json.loads(path.read_text(encoding="utf-8"))
        require(shard.get("schema_version") == 1 and shard.get("language") == "en", path.name + ": invalid translation schema")
        for kind in ("concepts", "questions"):
            rows = shard.get(kind)
            require(isinstance(rows, dict), path.name + ": invalid " + kind)
            require(not (set(rows) & set(output[kind])), path.name + ": duplicate translation IDs")
            output[kind].update(rows)
    for kind, pack in (("concepts", concepts), ("questions", questions)):
        originals = {row["id"]: row for row in pack[kind]}
        require(set(originals) == set(output[kind]), kind + ": English translation ID coverage differs from Chinese content")
        for identifier, row in originals.items():
            translated = output[kind][identifier]
            require(isinstance(translated, dict), identifier + ": invalid English entry")
            fields = CONCEPT_FIELDS if kind == "concepts" else QUESTION_FIELDS
            allowed = set(fields) | ({"options"} if kind == "questions" and row.get("options") else set())
            require(set(translated) == allowed, identifier + ": unexpected or missing translated fields")
            for field in fields:
                label = identifier + "." + field
                value = translated.get(field)
                if kind == "concepts" and isinstance(row[field], list):
                    require(isinstance(value, list) and len(value) == len(row[field]), label + ": translated list changed length")
                    for index, item in enumerate(value):
                        english_text(item, label + "[" + str(index) + "]")
                else:
                    english_text(value, label)
            if kind == "questions" and row.get("options"):
                options = translated.get("options")
                require(isinstance(options, list), identifier + ": translated options are missing")
                require([item.get("key") for item in options] == [item["key"] for item in row["options"]],
                        identifier + ": English option keys/order differ from the original")
                for option in options:
                    english_text(option.get("text"), identifier + ".options." + option["key"])
                letters = re.findall(r"\b[A-Z]\b", translated["answer_text"])
                require(letters == row["answer"], identifier + ": English choice answer differs from the original")
    # Match canonical order so reviews and deployed snapshots remain stable.
    for kind, pack in (("concepts", concepts), ("questions", questions)):
        output[kind] = {row["id"]: output[kind][row["id"]] for row in pack[kind]}
    return output
