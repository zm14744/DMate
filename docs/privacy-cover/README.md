# DMate 防窥页面独立设计稿

本次仅交付静态响应式设计页面，**没有**接入 DMate 的应用入口、快捷键、实际防窥切换逻辑，也没有修改应用功能或 main 分支；文件保存在 `ui/privacy-cover-responsive` 分支中。

## 文件
- `index.html`：唯一正式界面；完整单文件、无依赖、无网络请求。页面上只有居中原版图标。
- `preview.html`：仅用于评估三种主题和不同窗口/屏幕比例。工具栏不属于正式界面。

## 主题
- `?theme=light`：#f8fafc，使用 `dmate-tab-black-v52.svg` 原始路径。
- `?theme=dark`：#0d0d0d，使用 `dmate-tab-white-v52.svg` 原始路径。
- `?theme=navy`：#0f172a，使用 `dmate-tab-white-v52.svg` 原始路径。
- 不指定参数：遵循浏览器/操作系统的浅色、深色偏好。原 DMate 的深蓝主题可在后续接入时传入 `navy`。

适配：手机竖屏/横屏、平板、16:9、16:10、3:2、21:9、32:9、可变大小的应用窗口。使用 SVG、CSS vmin / dvh、CSS Grid 居中、安全区适配，无拉伸、无图像裁切。无浮动文字、按钮、密码框、渐变或彩色节点。

## 依据
- `zm14744/DMate/static/icons/dmate-tab-black-v52.svg`
- `zm14744/DMate/static/icons/dmate-tab-white-v52.svg`
- `zm14744/DMate/templates/index.html` 中主题最终有效背景值

注意：静态页面并不等于实际防窥功能，不负责遮挡系统通知、操作系统任务预览或其他程序窗口。
## 查看设计

在本目录打开 `index.html?theme=light`、`index.html?theme=dark`、`index.html?theme=navy` 查看三套背景。打开 `preview.html` 可以切换不同屏幕比例。

**状态：仅设计文件，未接入 DMate。**
