#!/usr/bin/env python3
"""Validate the offline curriculum and export its shipping copies.

knowledge_graph.json defines broad topics, not the complete concept list.
Each topic has an overview with the original node ID, several independently
identified concepts, and exercises that reference those precise concepts.
Run normally after editing offline-content; --check never writes files.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from graphlib import TopologicalSorter
import json
from pathlib import Path
import re
from offline_translations import compile_translations


ROOT = Path(__file__).resolve().parents[1]
PACKS = ("concepts.zh-CN.json", "questions.zh-CN.json", "references.zh-CN.json")
TYPES = {"单项选择", "多项选择", "填空", "计算", "简答", "证明"}
DIFFICULTIES = {"基础", "中等", "进阶"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def indexed(rows, label):
    require(isinstance(rows, list) and rows, label + ": expected a nonempty list")
    ids = [item["id"] for item in rows]
    require(len(ids) == len(set(ids)), label + ": duplicate IDs")
    return dict(zip(ids, rows))


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def prepare(graph, concepts_pack, questions_pack, references_pack):
    """Derive navigation from concept links, then validate all curriculum edges."""
    cp, qp = deepcopy(concepts_pack), deepcopy(questions_pack)
    nodes = indexed(graph["nodes"], "graph")
    names = {node["name"]: node["id"] for node in nodes.values()}
    require(len(names) == len(nodes), "graph: duplicate topic names")
    for node in nodes.values():
        require(all(name in names for name in node["prerequisites"]),
                node["id"] + ": unknown graph prerequisite")
    TopologicalSorter({n["id"]: [names[p] for p in n["prerequisites"]]
                       for n in nodes.values()}).prepare()
    concepts = indexed(cp["concepts"], "concepts")
    questions = indexed(qp["questions"], "questions")
    sources = indexed(references_pack["sources"], "references")
    require(set(references_pack.get("topic_references", {})) == set(nodes),
            "reference registry must cover exactly the current graph topics")
    require(set(nodes) <= set(concepts), "missing topic overview concepts")
    require({f"q{i:02}" for i in range(1, 15)} <= set(questions),
            "legacy question IDs q01-q14 must remain for saved practice records")
    groups = defaultdict(list)
    for concept in concepts.values():
        topic = concept.get("graph_node_id")
        require(topic in nodes, concept["id"] + ": unknown graph_node_id")
        groups[topic].append(concept)
        require(concept["category"] == nodes[topic]["category"],
                concept["id"] + ": category differs from graph")
    for topic, node in nodes.items():
        overview = concepts[topic]
        require(overview["graph_node_id"] == topic, topic + ": wrong overview parent")
        overview["title"] = node["name"]
        overview["prerequisites"] = [names[p] for p in node["prerequisites"]]
        overview["related_concepts"] = [c["id"] for c in groups[topic] if c["id"] != topic]
        require(len(overview["related_concepts"]) >= 3,
                topic + ": expected at least three distinct detailed concepts")
        titles = [c["title"].strip() for c in groups[topic]]
        require(len(titles) == len(set(titles)), topic + ": duplicate concept titles within a topic")
    # Stable topic order keeps concept navigation aligned with the graph.
    cp["concepts"] = [concept for topic in nodes
                      for concept in [concepts[topic], *[c for c in groups[topic] if c["id"] != topic]]]
    by_concept, by_topic = defaultdict(list), defaultdict(list)
    for question in questions.values():
        refs = question.get("knowledge_points", [])
        require(refs and len(refs) == len(set(refs)), question["id"] + ": invalid concept references")
        require(all(ref in concepts for ref in refs), question["id"] + ": unknown concept reference")
        topics = list(dict.fromkeys(concepts[ref]["graph_node_id"] for ref in refs))
        question["graph_node_ids"] = topics
        require(question["category"] in {nodes[t]["category"] for t in topics},
                question["id"] + ": category differs from referenced topics")
        for ref in refs:
            by_concept[ref].append(question["id"])
        for topic in topics:
            by_topic[topic].append(question["id"])
    for concept in cp["concepts"]:
        cid, topic = concept["id"], concept["graph_node_id"]
        concept["related_questions"] = by_topic[cid] if cid in nodes else by_concept[cid]
        if cid != topic:
            require(by_concept[cid], cid + ": detailed concept has no exercise")
        for key in ("title", "summary", "definition", "explanation", "example", "source_note"):
            require(isinstance(concept.get(key), str) and concept[key].strip(), cid + ": missing " + key)
        for key in ("notation", "common_mistakes"):
            require(isinstance(concept.get(key), list) and concept[key]
                    and all(isinstance(x, str) and x.strip() for x in concept[key]), cid + ": invalid " + key)
        prereqs = concept.get("prerequisites", [])
        require(len(prereqs) == len(set(prereqs)) and all(p in concepts and p != cid for p in prereqs),
                cid + ": invalid prerequisite references")
    TopologicalSorter({c["id"]: c["prerequisites"] for c in concepts.values()}).prepare()
    statements = Counter("".join(q["statement"].split()) for q in questions.values())
    require(all(n == 1 for n in statements.values()), "duplicate exercise statements")
    for question in questions.values():
        qid = question["id"]
        for key in ("title", "statement", "explanation", "grading_criteria"):
            require(isinstance(question.get(key), str) and question[key].strip(), qid + ": missing " + key)
        require(question.get("type") in TYPES and question.get("difficulty") in DIFFICULTIES,
                qid + ": unsupported question type or difficulty")
        if question["type"] in {"单项选择", "多项选择"}:
            options, answers = question.get("options", []), question.get("answer", [])
            keys = [o["key"] for o in options]
            require(len(keys) >= 2 and len(keys) == len(set(keys))
                    and all(o.get("text", "").strip() for o in options), qid + ": invalid options")
            require(answers and len(answers) == len(set(answers)) and set(answers) <= set(keys),
                    qid + ": invalid choice answers")
            require(question["type"] != "单项选择" or len(answers) == 1, qid + ": multiple single-choice answers")
        else:
            require(isinstance(question.get("answer_text"), str) and question["answer_text"].strip(),
                    qid + ": missing written answer")
        require(question.get("source", {}).get("kind") == "DMate独立编写",
                qid + ": imported works require a separately licensed content pack")
    for topic in nodes:
        rows = [questions[qid] for qid in by_topic[topic]]
        require(len(rows) >= 8, topic + ": expected at least eight exercises")
        require(sum(any(concepts[ref]["id"] != concepts[ref]["graph_node_id"]
                        and concepts[ref]["graph_node_id"] == topic for ref in q["knowledge_points"])
                    for q in rows) >= 6, topic + ": expected at least six exercises on detailed concepts")
        require(len({q["type"] for q in rows}) >= 2, topic + ": insufficient exercise variety")
        require("基础" in {q["difficulty"] for q in rows}
                and len({q["difficulty"] for q in rows}) >= 2, topic + ": missing difficulty levels")
    for item in [*cp["concepts"], *qp["questions"]]:
        refs = item.get("references", []) if "definition" in item else item["source"].get("references", [])
        require(refs and all(r.get("source_id") in sources and r.get("section")
                             and r.get("url", "").startswith("https://") for r in refs),
                item["id"] + ": missing traceable reference sections")
        for ref in refs:
            source = sources[ref["source_id"]]
            prefix = source["repository_url"] + "/blob/" + source["revision"] + "/"
            require(ref["url"].startswith(prefix), item["id"] + ": reference must use its recorded immutable revision")
    for source in sources.values():
        for field in ("title", "authors", "revision", "license", "license_evidence_url", "retrieved_on", "usage"):
            require(source.get(field), source["id"] + ": missing provenance field " + field)
        require(source.get("commercial_use_permitted") is True,
                source["id"] + ": a noncommercial source cannot enter this reference registry")
        require("-NC-" not in source["license"].upper(), source["id"] + ": noncommercial license")
        require(re.fullmatch(r"[0-9a-f]{40}", source["revision"]), source["id"] + ": invalid source revision")
        require(re.fullmatch(r"[0-9a-f]{64}", source.get("license_evidence_sha256", "")),
                source["id"] + ": missing license evidence checksum")
    return cp, qp


def coverage_markdown(graph, concepts, questions):
    groups, exercises = defaultdict(list), Counter()
    for concept in concepts["concepts"]:
        if concept["id"] != concept["graph_node_id"]:
            groups[concept["graph_node_id"]].append(concept["title"])
    for question in questions["questions"]:
        exercises.update(question["graph_node_ids"])
    nodes = graph["nodes"]
    categories = list(dict.fromkeys(n["category"] for n in nodes))
    lines = ["# DMate 离线概念库与题库覆盖清单", "",
             f'当前覆盖 **{len(nodes)} 个图谱大类、{sum(map(len, groups.values()))} 个细分概念**，'
             f'另保留 {len(nodes)} 个大类概述，共 {len(concepts["concepts"])} 条可浏览概念与 '
             f'{len(questions["questions"])} 道练习。图谱节点不是细分概念总量的上限。', "",
             "- [完整概念数据](concepts.zh-CN.json)", "- [完整题目、答案与解析](questions.zh-CN.json)",
             "- [已核验版本、章节和许可证据](references.zh-CN.json)",
             "- [商业发行来源规则](SOURCES_AND_LICENSES.md)", "",
             "本清单由 `python scripts/sync_offline_content.py` 从实际内容生成。"
             "题目按关联大类计数；跨大类综合题可能在多个大类中出现。", "",
             "| 类别 | 图谱大类 | 细分概念 | 关联练习 |", "| --- | ---: | ---: | ---: |"]
    for category in categories:
        ids = [n["id"] for n in nodes if n["category"] == category]
        lines.append(f'| {category} | {len(ids)} | {sum(len(groups[i]) for i in ids)} | '
                     f'{sum(exercises[i] for i in ids)} |')
    for category in categories:
        lines.extend(["", "## " + category, "", "| 图谱大类 | 实际细分概念 | 关联练习 |", "| --- | --- | ---: |"])
        for node in nodes:
            if node["category"] == category:
                lines.append(f'| {node["name"]} | {"；".join(groups[node["id"]])} | {exercises[node["id"]]} |')
    lines.extend(["", "## 质量与许可状态", "",
                  "中文内容独立编写，英文译文翻译DMate自有内容；未翻译、改编或摘录第三方教材及习题的受保护表达。参考来源的许可证与原创包的发行条款分别记录。"
                  "非商业许可题目、未核清许可的网络题和高校试卷未进入本包。", "",
                  "结构检查涵盖全部图谱大类、细分概念、前置关系、题目关联、答案字段、难度层次与来源章节；"
                  "有限计算题另外使用程序核对。内容尚未经过独立教师逐题终审，不能将自动检查表述为人工审定。", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        graph = json.loads((ROOT / "knowledge_graph.json").read_text(encoding="utf-8"))
        packs = [json.loads((ROOT / "offline-content" / name).read_text(encoding="utf-8")) for name in PACKS]
        concepts, questions = prepare(graph, *packs)
        targets = {ROOT / "offline-content" / PACKS[0]: encoded(concepts),
                   ROOT / "offline-content" / PACKS[1]: encoded(questions)}
        for name, pack in zip(PACKS, (concepts, questions, packs[2])):
            targets[ROOT / "static/offline-content" / name] = encoded(pack)
        targets[ROOT / "static/offline-content/knowledge_graph.json"] = encoded(graph)
        targets[ROOT / "static/offline-content/translations.en.json"] = encoded(compile_translations(ROOT, concepts, questions))
        targets[ROOT / "offline-content/PREVIEW.zh-CN.md"] = coverage_markdown(graph, concepts, questions)
        changed = [path for path, content in targets.items()
                   if not path.exists() or path.read_text(encoding="utf-8") != content]
        if args.check and changed:
            parser.exit(1, "Offline content needs syncing: " + ", ".join(str(p.relative_to(ROOT)) for p in changed)
                        + "\nRun python scripts/sync_offline_content.py\n")
        if not args.check:
            for path in changed:
                path.write_text(targets[path], encoding="utf-8")
        print(f'{len(graph["nodes"])} topics; {len(concepts["concepts"])} concepts; '
              f'{len(questions["questions"])} exercises; coverage and references valid')
    except (ValueError, KeyError, TypeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
