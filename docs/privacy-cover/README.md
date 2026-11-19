# DMate 防窥页面独立设计稿

本目录保留 `ui/privacy-cover-responsive` 分支的响应式设计稿。正式界面的视觉及拓扑生长动画已接入离线版；运行时使用 `static/offline.html`、`static/offline.css`、`static/offline-shell.js` 和 `static/offline-privacy-motion.js`，按应用当前主题显示。

## 文件
- `index.html`：静态图标设计稿；完整单文件、无依赖、无网络请求。页面上只有居中原版图标。
- `preview.html`：仅用于评估三种主题和不同窗口/屏幕比例。工具栏不属于正式界面。
- `topology-growth.html`：分支原版拓扑生长动画预览；从中央沿图标连线向外生长，740ms 后静止。

## 主题
- `?theme=light`：#f8fafc，使用 `dmate-tab-black-v52.svg` 原始路径。
- `?theme=dark`：#0d0d0d，使用 `dmate-tab-white-v52.svg` 原始路径。
- `?theme=navy`：#0f172a，使用 `dmate-tab-white-v52.svg` 原始路径。
- 不指定参数：设计稿遵循浏览器/操作系统的浅色、深色偏好；实际离线界面跟随应用当前主题。

适配：手机竖屏/横屏、平板、16:9、16:10、3:2、21:9、32:9、可变大小的应用窗口。使用 SVG、CSS vmin / dvh、CSS Grid 居中、安全区适配，无拉伸、无图像裁切。无浮动文字、按钮、密码框、渐变或彩色节点。

## 依据
- `zm14744/DMate/static/icons/dmate-tab-black-v52.svg`
- `zm14744/DMate/static/icons/dmate-tab-white-v52.svg`
- `zm14744/DMate/templates/index.html` 中主题最终有效背景值

注意：静态页面并不等于实际防窥功能，不负责遮挡系统通知、操作系统任务预览或其他程序窗口。
## 查看设计

在本目录打开 `index.html?theme=light`、`index.html?theme=dark`、`index.html?theme=navy` 查看三套背景。打开 `preview.html` 可以切换不同屏幕比例。

**状态：已接入离线版。** 每次打开离线版（包括刷新、从在线版返回和历史返回）自动播放拓扑生长动画。开场期间只有居中的原版 Logo，不显示 Eye 按钮；动画完成且原页面、草稿恢复后自动进入工作区，避免短暂显示错误的页面。

电脑与手机的手动隐藏按钮仍打开全屏防窥界面，保留左上角的 Eye 恢复按钮；动画完成后保持图标，直到手动恢复。侧栏、浮动图谱及其他弹层都位于遮挡界面之下。恢复内容、页面进入后台或关闭时停止动画；开启系统“减少动态效果”时直接显示完整图标，开场仍在页面就绪后自动进入。动画资源随离线页面缓存，无需联网。预览稿中的点击、空格及 R 重播不进入正式界面。
