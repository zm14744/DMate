# 本域网页依赖

这里保留 DMate 网页实际使用的固定版本发布文件，供浏览器从网站本域加载；这些库不需要浏览器先访问 npm、jsDelivr 或其他公共代码镜像。

| 组件 | 版本 | 本域入口 |
| --- | --- | --- |
| MathJax | 3.2.2 | `mathjax-3.2.2/es5/tex-svg.js` |
| Marked | 15.0.12 | `marked-15.0.12/marked.umd.js` |
| DOMPurify | 3.2.6 | `dompurify-3.2.6/purify.min.js` |
| html2canvas | 1.4.1 | `html2canvas-1.4.1/html2canvas.min.js` |
| jsPDF | 2.5.2 | `jspdf-2.5.2/jspdf.umd.min.js` |
| Viz.js / Graphviz | 3.31.0 / 16.1.0 | `viz-js-3.31.0/viz-global.js` |
| Viz.js / Graphviz | 3.31.0 / 16.1.0 | `viz-js-3.31.0/viz-global.js` |

MathJax 的 `loader.paths.mathjax` 指向版本化的本域 `es5` 目录。除 SVG 主组件外，目录保留 TeX / MathML / AsciiMath 输入、输出与字体、菜单、辅助功能及语音规则所需的分段文件；这些资源按需读取，不会因放在目录中就在首屏全部下载。没有保留其他完整组合包及 Node 入口。原始库中的帮助网站或旧浏览器兼容分支可能包含外部 URL，不能把文件中的 URL 字面量等同于当前浏览器实际请求；当前网页的正常渲染与已核对的按需扩展均使用本域路径。

`manifest.json` 记录上游 npm 包版本、归档 URL、原始 `dist.integrity` SHA-512，以及每个分发文件的大小和 SHA256。取得发布归档后，先校验完整归档与官方 registry 元数据中的 `dist.integrity` 一致，再仅复制清单内文件；不要手工修改这些上游发布文件。各组件保留上游包随附的 LICENSE / LICENSE.md。

升级时使用新的版本目录，重新获取并验证官方发布归档，更新资源清单、模板入口和许可索引，并核对公式渲染、按需 TeX 扩展、富文本净化及导出。版本目录可由服务器按不可变资源缓存；业务脚本的更新规则仍由应用控制。


Viz.js 的 Graphviz bundle 保存在本域，数学图自动布局不再依赖 jsDelivr 或 GitHub Release 的临时可达性。该文件通过上游固定提交的 SHA-256 校验，来源、版本及许可记录在 `viz-js-3.31.0/manifest.json`。目录内同时保留 Viz.js、Graphviz 与 Expat 的许可文本；升级时使用新版本目录，不覆盖旧版本。

数学图布局使用本域固定的 Viz.js / Graphviz WASM bundle，按需加载，不请求 jsDelivr、npm 或 GitHub Release。`viz-js-3.31.0/manifest.json` 记录上游仓库、固定提交、源文件 blob、bundle SHA-256 和所含许可；升级时必须使用新的版本目录，并同步核对 SRI、Graphviz / Viz.js / Expat 许可及真实布局测试。不要覆盖已长期缓存的旧版本。
