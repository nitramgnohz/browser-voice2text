# Voice2Text 使用说明

Voice2Text 将当前 Chrome 或 Brave 标签页的声音发送到本机 Whisper 服务，显示原文临时字幕和定稿文字。识别时不调用 ViiTor、Ollama 或其他翻译服务。

## 安装本地服务

在克隆或解压后的 `Voice2Text` 项目目录中执行：

```bash
./voice2text-run setup
./voice2text-run start
./voice2text-run status
./voice2text-run copy-key
```

`setup` 使用项目自己的 `.venv` 安装 Python 依赖，将模型保存在项目 `.local/models/`，首次运行需要下载约 460 MB 权重。若终端无法直连模型站点，可让该命令使用你已配置的网络代理；不要把连接密钥发给第三方。

`start` 只绑定 `127.0.0.1:8766`，加载模型后才报告就绪。`copy-key` 将连接密钥放入本机剪贴板，不在终端打印密钥。`status` 检查进程身份和模型就绪状态；`stop` 只结束由本项目启动并能核对身份的进程。

## 加载扩展

1. 在 Chrome 输入 `chrome://extensions`，在 Brave 输入 `brave://extensions`。
2. 开启开发者模式，点击“加载已解压的扩展程序”，选择项目中的 `extension/` 目录。
3. 打开 Voice2Text 的 **Settings**，粘贴刚复制的本地连接密钥，保存，并点击 **Check service**。
4. 打开普通 HTTP(S) 视频页面，点击 Voice2Text 图标，选择识别语言并点击 **Start captions**。
5. 页面会显示字幕面板。**Copy** 复制当前文字，**Clear** 清空当前显示，**Stop** 完成尾音识别后停止。停止后可在面板点击 **Start** 再次采音；运行中点击 **Restart** 会先完成旧会话的尾音，再从当前标签页开始新会话。点击 **Hide** 会收起面板但继续转写；页面右上角会出现 **Voice2Text** 恢复按钮，点击即可重新显示面板。标题旁的 ◐ 滑块可将面板背景透明度调到 30%–100%，文字和按钮保持清晰，设置会保存在本机浏览器。新会话会清空面板中的旧文字，如需保留请先 Copy。浏览器重新加载扩展后，需要先通过工具栏图标重新启动一次。

**Detect automatically** 会检查每段短音频的语言；当窗口内出现可信的中英切换时，会在切换处分别识别两侧，适合中文与英文按段交替的视频。同一句话中夹杂少量另一种语言、无停顿的快速切换或其他语言组合不保证准确。纯中文或纯英文视频选对应语言更稳。无论语言选项如何，都只转写原文，不翻译。

如果页面上同时出现黑色的“实时字幕”气泡和 Voice2Text 面板，前者通常是 Chrome 自带的实时字幕。可在 Chrome「设置 → 无障碍功能 → 实时字幕」关闭，以免两套字幕同时显示。

Chrome 和 Brave 共用程序，但需要分别加载扩展、分别粘贴一次连接密钥。服务同一时间只处理一个浏览器标签页。

## 从扩展弹窗启动本地服务

扩展弹窗可以显示服务状态、端口和 PID。要启用 **Start backend**，需要先分别在 Chrome / Brave 加载扩展，并记录各自扩展详情页显示的 32 位 ID；随后回到项目目录运行 `./voice2text-run`，选择 **Install browser launcher**，按提示输入 Chrome 与 Brave 的扩展 ID（未使用的浏览器留空）。该步骤把仅允许已登记扩展 ID 调用的 Native Messaging host 注册到 macOS 用户级浏览器目录。Brave 版本可能读取 Chrome 兼容目录或自己的用户目录，因此安装器会在两处写入同一份受限注册文件。注册后完全退出并重新打开对应浏览器，弹窗即可启动本地服务。

Native Messaging host 需要本机已完成 `setup`，并依赖项目目录保持原位；移动项目后需重新执行注册。若不安装该桥接，仍可通过 `./voice2text-run start` 启动服务，扩展弹窗只显示当前服务状态。

## 状态与限制

- 插件从用户点击开始采集当前标签页声音；采集时维持原视频的声音播放。
- 普通 HTTP(S) 页面受支持；浏览器内部页面、扩展页面、受保护媒体和仅视频元素进入全屏时的字幕覆盖，须单独实测。全屏视频如无法覆盖，退出全屏后文字仍可在页面面板查看。
- 源音频是本地 16 kHz 单声道 PCM，识别模型为 `mlx-community/whisper-small-mlx`。系统语音样本已运行，真实视频和连续运行表现以验证记录为准。
- 临时文字可能被后续语音修正。自动识别语言的效果取决于音频长度和清晰度；已知语言可手动指定以减少误识别。
- 当前每次观看只保留最近 2,000 个字幕段；页面关闭后不保存原始音频或识别文本。
- 服务端无法访问 Apple GPU 时不能启动 MLX 模型。可通过 `./voice2text-run check` 和 `.local/server.log` 检查。

## 关闭与打包

```bash
./voice2text-run stop
./voice2text-run package
```

分发包在 `dist/Voice2Text.zip`。它包含程序、依赖锁和文档；不包含模型、密钥、测试音频、日志或浏览器配置。新机器解压后仍需执行 `setup`。
