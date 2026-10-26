# Next-generation graph OCR audit (2026-10-22)

Baseline: bc9a972336e1a50b88d8136435fb4253334c8c3e. Development branch: codex/graph-ocr-nextgen-20261022. No production deployment or main merge is authorized.

| Layer | Implemented before this branch | Missing / risk |
| --- | --- | --- |
| Vertex detection | Filled dots, hollow/coloured circles, separate detectors | No independent Qwen NODE inventory; detector panel splitting can confuse components with figures |
| Trace | Skeleton tangent walking, straight coverage, Hough rims, fitted curved ink corridors, route dedup | Only CV vertices; fixed margins can cut external arcs; 30-vertex / 48-path limits; no dashed-line evidence |
| Arrow | Paired wings near endpoints and along polylines | Advisory only; per-path direction is discarded in normalization |
| Fusion | Coordinate alignment and disagreement messages | Does not revise candidate selection using global route conflicts |
| Schema | Graph vertices, endpoints, numeric weights, labels | Drops edge IDs, paths, individual direction, style and evidence |
| Mathematics | NetworkX consistency checks | Checks do not prove image accuracy (retain this distinction) |
| Text | PP-OCRv6 Small, enhancement, native tiles, optional FormulaNet | No PP-DocLayoutV3 partition; formula pipeline also loads layout; all models share web process |
| UI | Structured review formatter, math rendering | Parallel identities collapsed; unknown direction rendered as undirected; original labels not always used |
| Regression | Original OUC 180506 and 181309, gold files; six-dimension plan | Other image paths and old tests referenced in docs are absent; generated fixtures are not historical originals |

Resource strategy must be measured, not assumed: isolate local inference in a serial, terminable subprocess, load DocLayout and Small in separate subprocess lifetimes, bound image pixels and wall time, monitor child RSS and cgroup memory. Preserve full-web-process headroom. Do not enable resident/co-resident mode without Linux 2-CPU/4-GiB measurements. No new model family and no local VLM.

Acceptance: unit and generated-pixel tests validate mechanisms only. Real accuracy requires independently transcribed original bytes, actual branch /ocr response, actual browser review dialog and six-dimension comparison. No production endpoint can validate code that has not been deployed there.
