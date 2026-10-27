# DMate 图形编辑器整理与原图描绘接入前检查（2026-10-27）

基线：`main` 的 `70272ae2395d`。本次只做**前端数据模型与视图解耦、回归测试补充、工具库存审计**。不修改生产部署、模型请求、`/ocr`、确认接口或解题行为，不删除旧识别流程。

## 已整理的代码

- `static/graph-editor-model.js`：从原有编辑器提取纯数据模型；保留顶点/边的添加、修改、删除、自环、重边、撤销、子图移动/合并、数据导入和校验，不依赖浏览器 DOM。
- `static/graph-editor.js`：保留现有 SVG 绘制、属性控件、用户交互和确认入口；在浏览器使用 `DMateGraphEditorModel`，Node 测试环境从同目录导入同一模块；原有 `DMateGraphEditor` 公共 API 不变。
- `templates/index.html`：先加载数据模型再加载视图，更新资源查询版本防止旧缓存与拆分文件混用。
- `tests/test_visual_graph_editor.py`：浏览器内联资源顺序与正式页面一致；增加数据模块/视图使用同一模型的 Node 回归。

这是**无意改变用户体验的预备整理**。当前 SVG 仍在独立结构预览中自动排布顶点；尚未实现原图叠加、拖动顶点/控制点、框选范围或直接描线。

## 核查结果与接入决策

| 工具 / 能力 | 当前依赖或位置 | 决定 |
| --- | --- | --- |
| SVG、DOM、原生 Pointer Events | 浏览器原生；`static/graph-editor.js` 使用 SVG | 继续使用，不额外增加 Konva/Fabric |
| `d3-zoom` | 当前**没有** JS 构建、npm 依赖或此库的引入 | 后续交互阶段才接入，固定版本、自托管，不能仅加一个远程 CDN URL |
| OpenCV / Pillow / NumPy | `requirements.txt`、`image_evidence.py`、`graph_line_tracer.py` | 已有，不再引入重复图像库 |
| PaddleOCR / PP-DocLayoutV3 | `paddleocr[doc-parser]` 与按需版面/文字 worker | 已有，优先复用 |
| sknw | `requirements-agents.txt` 已固定 `sknw==0.15`；`graph_sknw_plugin.py` | **已声明并有接入代码**，按疑难线迹调用；不是待安装的主工具 |
| NetworkX、JSON Schema | `requirements.txt`、`requirements-agents.txt` | 已有，保持边实例和用户确认的结构校验 |
| LangGraph | `requirements-agents.txt`、`graph_fast_pipeline.py` | 已有，不再另加一套编排系统 |
| Qwen/GLM 与 DeepSeek | `vision_provider.py`、当前快速识别流程及解题路径 | 不改密钥和路由；默认是否停止 GLM 要先做真实同图对比 |

`d3-zoom` 的官方 3.0.0 包依赖 `d3-selection`、`d3-drag`、`d3-dispatch`、`d3-interpolate`、`d3-transition`。当前仓库没有 Node 构建链，也无 `package.json`；直接向 HTML 引用模块包并不能保证能独立运行。真正接入时应选定经过测试的**自托管浏览器构建**（包含所需依赖）、记录版本和许可，并以本地/国内无 CDN 场景进行回归。参考：https://d3js.org/d3-zoom 与 https://github.com/d3/d3-zoom 。

## 下一轮“原图上描绘”的数据与交互契约

1. 维持**数学对象**与**绘图对象**分层。数学对象持有稳定的图/点/边 ID、原图标签、端点、方向、权值；绘图对象持有原图尺寸、子图范围、顶点坐标及边路径，通过 ID 关联。图形仅改变画法不应改动拓扑。
2. 现有 `graph_semantic_schema.py` 的语义投影会丢弃绘图坐标与路径；`graph_confirmation.py` 当前只保存确认后的数学结构。新绘图数据必须显式校验并完整往返（草稿→编辑→确认→重开），但不得仅把旧候选对象原样透传给解题。
3. 坐标统一使用与**已校正方向的原图**对应的规范值；明确 0..1 相对坐标及其映射关系。缩放与平移只影响视图变换，不修改数学端点或原图坐标。
4. 未命名点：`label=null`，生成稳定的显示编号①②③；不将显示编号写成原图真实名称。原图已经使用同类符号时避让。未命名边不在“边：”栏目生成假边名，但每条边保留独立 ID 和逐条“关系”。
5. 编辑器新增原图背景与透明 SVG 图层，使用 `Pointer Events` 处理移动点、连边、自环、重边与控制点；使用 d3-zoom 的交互缩放时必须与编辑模式隔离，避免拖点触发画布平移；手机双指缩放要有真实浏览器验收。
6. 图类型独立选择：有向/无向、带权/无权。AI 提供候选，用户可改；系统不把有歧义的方向或缺失权值自动当成已确认。
7. 「点、边、关系」由程序按确认数据确定性生成；图形描述只写外观，不提前判断同构或解答题目。用户确认与主动解题仍是两步。
8. 优先将用户指定的框选范围作用到原图显示和局部重识别，现有子图数学清单/移动功能继续复用。

## 不应现在删除的遗留部分

`ocr_nextgen.py` 仍暴露 `staged`、`qwen-simple-candidate`、`evidence-two-pass`、`agent-tools`、`agent-tools-strict` 等入口，仓库保留对应测试和历史比较工具。**这轮没有删除任一入口**。应先建立调用方和环境配置引用表，再按离线回归结果逐个退役；不能因为文件数多就直接删除。OpenCV/透印/阴影/箭头/曲线算法仍是初稿的依据，不能作为“旧全自动识别代码”统统砍掉。

## 下一轮必须跑的验收

- Node：`node --check static/graph-editor-model.js`、`node --check static/graph-editor.js` 和 `node --check static/script.js`。
- Python/浏览器：`pytest -q tests/test_visual_graph_editor.py`，同时覆盖桌面和移动视图；再跑 `tests/test_editable_batch_browser.py` 与相关确认接口回归。
- 加几何功能后，必须测试用户拖动/重开坐标不漂移、重边/反向弧保留独立路径、框选局部不会改变其他图、无名点编号稳定、旧图数据可导入。
- 再用真实原图首响应测试图类型、阴影/透印、交叉防穿透、重边及细箭头；模型调用成功或结构合法不等于自动识别正确。

当前提交没有调用付费视觉模型、没有修改 `main`、没有部署 Zeabur，未来独立绘图功能也必须先在开发分支验证。
