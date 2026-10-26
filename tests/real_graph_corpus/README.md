# 用户原始对话图论测试集

范围是用户此前连续提供的**全部图论原图与对应 DMate 实际识别结果**。不是仓库已取回图片的集合，也不是高校 PDF 重裁剪或生成图的集合。

当前 `manifest.json` 中 `enumeration_complete=false`，`expected_case_count=null`。这表示原始对话材料尚未完整导入；不表示全部样本只有两张。`missing_materials` 按已知批次范围列出待恢复材料，准确总数待原始对话清单核对。

每个 `cases/<id>/` 保留：

- `original.*`：原始字节及 SHA256；不得重绘、锐化或重编码覆盖。
- `original_ocr.json`（或原始截图/文字文件）：当时真实识别结果，保持原文。
- `original_dialog.png`、`original_capture.json`：有保存时保留真实弹窗和采集记录。
- `ground_truth.json`：独立查看原图得到的正确图结构，不从 DMate 结果反推。
- `evaluation.json`：点边、题干、公式渲染、描述准确、描述统一、图形分隔六维记录，并注明评价的是历史版本还是新分支。

已归档的两张海洋大学原图，其原始识别结果从历史 Actions 39739842459 恢复，并以 SHA256 与原图逐一匹配。它们的历史识别存在错误，不能当作当前分支已通过的准确率结果。未取得的材料必须继续标记缺失，不能用其他来源替代。

导入已整理的本地材料：

```sh
python scripts/graph_corpus.py import /absolute/path/intake-index.json
python scripts/graph_corpus.py validate
python scripts/graph_corpus.py validate --full
```

`intake-index.json` 明确逐图对应，例：

```json
{"cases":[{"id":"batch01_case01","batch_id":"batch01","institution":"原来源",
"source_kind":"conversation_original","conversation_id":"原对话ID","message_id":"原消息ID",
"image":"原图.png","original_ocr":"当时实际识别结果.json","ground_truth":"独立正确结构.json",
"ground_truth_independently_reviewed":true}]}
```

索引中的路径相对于索引所在目录；原始识别结果和正确结构尚缺时可省略，导入后仍视为未齐。导入不会自动宣布全量完成。只有逐条对照原始对话确认所有图片/结果、批次及准确总数后，才可以填写完整清单状态。

真实 API 工作流在 `validate --full` 通过前不会开展全量回归。现有几何单元测试、展示契约测试和两张原图的资源测量继续明确标为局部验证。
