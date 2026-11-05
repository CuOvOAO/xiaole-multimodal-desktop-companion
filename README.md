# 小乐桌面伴侣

Windows 11 上运行的 PyQt6 桌面 AI 伴侣。文字默认使用本地 Ollama `qwen3:8b`，
屏幕与摄像头按需使用本地 `Qwen3.5:9b`；关闭思考，失败后回退 SiliconFlow。ASR 使用 SiliconFlow。
本轮复盘、性能实测和后续限制见 [优化报告](OPTIMIZATION_REPORT.md)。
2026-10-01 的角色表达、延迟与自适应气泡改动见 [本轮体验调整](EXPERIENCE_UPDATE.md)。
2026-10-02 的记忆链路修复、连续对话实测和仍有的模型理解问题见 [记忆检查记录](MEMORY_UPDATE.md)。
2026-10-04 的文字/视觉模型拆分、实测结果和显存限制见 [模型切换记录](MODEL_SWITCH.md)。
2026-10-07 的窗口缩放、默认安静陪伴和电脑操作边界见 [窗口与能力说明](WINDOW_AND_CAPABILITIES.md)。
同日后续修复了历史错误回复污染，以及操作只返回承诺不执行的问题；该说明中的“后续纠正”包含复现方法和限制。

## 运行

1. 现有 `.env` 已保留；首次配置时按 `.env.example` 填写密钥，勿覆盖已有配置。
2. 确保 Ollama 已启动，并已安装 `qwen3:8b` 与 `Qwen3.5:9b`。
3. 双击 `start_debug.cmd`，或者先关闭语音输入和主动观察进行文字调试：

```powershell
& 'F:\anaconda3\python.exe' main.py --debug --no-asr --no-proactive
```

## 验证

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_checks.ps1
```

检查顺序见 [校验指南](VALIDATION.md)。脚本会恢复测试用环境变量，不影响随后启动正常窗口。

`F:\anaconda3\python.exe -m pip check` 可用于检查整个 base 环境，但当前 base
会报告若干与本项目无关的历史包冲突，因此不作为项目通过条件。
建议后续按 `requirements.txt` 创建独立 Python 3.9 环境，不要升级本项目要求的
`numpy==1.24.3`。

## 隐私与桌面操作

- 摄像头只在用户明确要求查看时按需打开，抓帧后立即释放。
- 默认安静陪伴，不主动分析屏幕或插话。手动开启主动观察后，变化检测先在本机做像素差分；模型资源许可时才调用视觉推理。
- 本地模型失败会回退云端，因此请求画面可能上传 SiliconFlow；仅用本地的强制隐私模式尚未实现。
- 普通搜索直接打开结果页，不弹确认、不自动点击结果。打开应用/网址、点击、输入、快捷键、滚动及搜索后自动点结果仍需确认；键盘操作确认后留 3 秒切换窗口，焦点仍在小乐时取消。
- `data/memory_pending.json` 是待落库对话日志，可在模型预热期间提前退出后恢复；包含对话明文，勿公开提交。
- `data/session_state.json` 保存最近普通文字交流，重启时恢复 72 小时内最多 24 轮；包含聊天明文，勿公开提交。
- 性能日志不含图片、密钥或对话文本；模型与界面冷启动耗时不能用热身结果代替。
- TTS、系统托盘、开机自启和 Windows 安装包尚未实现。

## 全新安装

在 Windows 上安装 Python 3.9 和 Ollama 后，运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
ollama pull qwen3:8b
ollama pull Qwen3.5:9b
.\.venv\Scripts\python.exe main.py
```

编辑 `.env` 填写自己的 SiliconFlow API 密钥；不要提交该文件。
主要技术包括 Python、PyQt6、Ollama、OpenAI 兼容 API、ChromaDB、OpenCV 和 sounddevice。
功能包括文字对话、语音转写、对话记忆、按需屏幕/摄像头理解及经确认的桌面操作。
