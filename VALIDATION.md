# 小乐校验顺序

## 1. 自动检查
在项目目录运行：
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_checks.ps1
```
按顺序检查指定 Python、numpy 1.24.3、所有 Python 文件语法、全部离线回归、Qt 离屏启动和退出。
离线检查不调用模型、不打开麦克风/摄像头。不能替代真人体验验收。
脚本会恢复 QT_QPA_PLATFORM 等环境变量，防止测试后正常窗口不显示。

## 2. 先调试文字
```powershell
& 'F:\anaconda3\python.exe' main.py --debug --no-asr --no-proactive
```
也可运行 `start_debug.cmd --no-asr --no-proactive`。
窗口先显示，连接模块随后加载；加载时可以编辑草稿，发送按钮就绪后启用。
本地模型会后台预载，记忆库可能需要较长预热。日志出现 Memory ready 才表示长期检索可用。

依次试：“你好” → “今天有点累” → “谢谢，随便聊两句” → “具体解释一下为什么会这样”。
确认简短闲聊与解释长度不同，没有机械凑句、反复固定结尾或展示原始 JSON。
生成时继续编辑草稿；已有内容不能被清空或覆盖。点击停止应停止后续演出和未执行动作。
断网/模型失败时旧气泡动画不能覆盖错误；重试的历史中不能多出未答复问题。
右键“复制完整回复”可取得上一条完整回答，方便检查长回复。
看 `data/logs/performance.jsonl`：first_text_preview_ms 是首段文字，first_sentence_ms 是首句完整对象；
total_ms 是后台对话完成时间，不包含最终气泡的全部阅读停顿。须区分冷启动与连续热对话。

## 3. 视觉与融合
输入“看看屏幕上显示什么”，再问“图里那个是什么”。
输入“看看我现在的表情”，确认摄像头只在明确请求时短暂打开。
输入“看看我和屏幕”，确认两路画面都参与同一次请求，不被混为同一个来源。
“我现在很累”不能打开摄像头；“刚才你说什么”不能因为之前看过摄像头而再次抓帧。
关闭/拔掉摄像头后再请求，看不到就说明获取失败，不能使用旧照片假装当前画面。
多显示器可在 .env 设置 SCREEN_MONITOR=2，编号按 mss 枚举顺序。

本地文字模型默认为 qwen3:8b，视觉模型默认为 Qwen3.5:9b，均使用非思考模式；日志模型字段用于确认实际后端。
关闭 Ollama 后测试云端回退，再恢复 Ollama，30 秒后应能恢复本地尝试。
`TEXT_BACKEND=cloud` 只将文字切云端；`VISION_BACKEND=cloud` 只将图像切云端。
若不希望模型常驻显存，设置 LOCAL_VISION_WARMUP=0；只用云端时同时设置两种 BACKEND=cloud。

## 4. 主动观察
重新启动，不带 --no-proactive。切换两个明显不同的窗口，然后暂时停止输入。
观察不会因自己的打字气泡/立绘触发；评估间隔至少 30 秒，发言间隔至少 45 秒。
输入、生成、桌面动作期间不能抢话。晚到评论最多留一条，并丢弃超过 12 秒的内容。
观察不是持续录像，也不保证每次切屏都评论。

## 5. ASR
重新启动，不带 --no-asr。最初 3 秒保持安静，核对麦克风名和原生采样率。
说完后的本地端点等待约 0.65 秒，另加 API 识别和模型生成时间。
空闲空输入框：转写显示后约 0.5 秒自动发送。
正在回复：只放入空输入框，需确认；已经有草稿：保持原稿并显示“语音待确认”。
右键“采用待确认语音”可合并待确认内容。修改转写后不应自动发送。
说“看看屏幕上有什么”，确认转写与画面走同一上下文。
测试噪音、短响声、连续说话、网络错误；不能无限积压录音，401 不应盲目重试，500 只重试一次。
当前不理解原始声音语气、音乐或环境事件；TTS 尚未加入。

## 6. 桌面操作与退出
请求“去维基百科搜搜蕾缪乐”：应打开编码 URL，后台定位并尝试点第一条自然结果。
核对状态栏执行反馈；没找到链接应说明未点击，不能伪报成功。
直接点击、输入和快捷键先确认；不允许多条动作同时抢鼠标/键盘。
真实网页坐标准确率仍须人工验收。鼠标移到屏幕角落可触发 PyAutoGUI 的安全停止机制。
生成/动作中右键退出：窗口隐藏并等待在途 QThread 结束，不应出现 destroyed while running。
待落库对话先写 pending journal，重启后按稳定 ID 恢复，不重复写入。
不能删除 data/memory_pending.json 来“清理缓存”，否则会丢失尚未落库的对话。

## 7. 单项诊断
```powershell
& 'F:\anaconda3\python.exe' tools/smoke_pipeline.py --repeat 3
& 'F:\anaconda3\python.exe' tools/smoke_pipeline.py --vision
& 'F:\anaconda3\python.exe' tools/smoke_capture.py
& 'F:\anaconda3\python.exe' tools/diagnose_memory.py
& 'F:\anaconda3\python.exe' test_asr.py
```
前两项用合成内容/图像验证真实模型，不写对话记忆、不执行桌面动作。
截图检查仅在内存中报告尺寸和耗时；记忆检查只读检索现有数据库。
ASR 脚本发送合成测试音，不打开麦克风；HTTP 200 仅证明端点与鉴权，不能证明语音准确率。
`tools/benchmark_models.py` 为明确选择的模型对比工具，输出在 data/logs/benchmark-时间戳.json。
