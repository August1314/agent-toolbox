# voice-over-neural-tts

中文旁白配音工具链：神经 TTS 合成 → 后期链 → **实测**逐句时间戳。

产出直接可被视频工程消费（48kHz / mono / pcm_s16le / −16 LUFS），
并且每句的起止是 ffprobe 量出来的，不是按字数估的。

## 为什么是这两个后端

| 后端 | 引擎 | 联网 | 许可 | 中英混读 |
|---|---|---|---|---|
| `edge`（主） | Microsoft Edge 神经音色 | 生成时需联网 | LGPLv3 | ✅ 正确 |
| `melo`（兜底） | sherpa-onnx + MeloTTS zh_en | 完全离线 | MIT | ⚠️ 勉强 |

`--engine=auto`（默认）：先 edge，重试 3 次仍失败就整段回落 melo 并在 stderr 告警。

**被实测淘汰的候选**（别再试）：

- `sherpa-onnx` + `matcha-icefall-zh-baker`：**静默丢弃**所有拉丁词。
  `say -v` 无关，是引擎日志 `OOV word skipped: 'AI'`，且 "AI提醒过我" 与
  "提醒过我" 输出时长完全相同（1.18s = 1.18s）。文案里有 AI / agent / P 这类词就必炸。
  另外它的数据集（DataBaker）标注**非商用**。
- macOS `say`：峰值 −2.5 dBFS 顶满、频谱上字间大片宽带毛刺（电子味来源）、
  全局一个 `-r` 语速、无逐词时间戳。
- whisper/stable-ts 系对齐器：模型托管在 HuggingFace，国内网络取不到（实测 000）。

## 用法

```bash
# 1. 建环境（Python 3.11 venv + 159MB 离线兜底模型，约 1 分钟）
toolbox run voice-over-neural-tts --setup

# 2. 合成一段旁白
toolbox run voice-over-neural-tts \
  --text "我发现，我越来越丧失表达欲了。" \
  --out /tmp/seg-00.wav
# → {"durationSec":3.84,"engine":"edge","sentences":[{"text":"…","startSec":0.0,"endSec":3.84,"engine":"edge"}]}
```

换音色：`--voice zh-CN-XiaoxiaoNeural`（女声 Warm）/ `zh-CN-YunyangNeural`（男声 News，偏冷）。
调语气：`--rate=-10%`（相对语速）、`--pitch=-2Hz`（压掉朗读腔的亮尖）、`--pause=0.30`（句间静音秒数）。

## 关键设计（改之前先读）

**按整句切，不按逗号切。** 神经 TTS 的韵律是在"一句完整话"的上下文里生成的；
切成逗号碎片后每个碎片都被当作独立话语（各自降调），连起来听就是一串清单。
只在句末标点断开，碎片仍是完整句子，而句间停顿改由注入的静音精确控制。

**后期链顺序固定**：`highpass=80 → deesser → acompressor → loudnorm(两遍, linear=true)`。
先去齿音再压缩，否则压缩会把齿音一起抬上来；loudnorm 放最后且走两遍，
全片各段响度才一致（实测 10 段 LUFS 极差 0.70 dB、真峰齐平 −1.5 dBFS）。

**必须用 venv 的 Python 3.11**：系统 Python 3.14 装不上 sherpa-onnx 的 wheel。

## 契约

- 输入：一段中文旁白文本（可含英文/数字混排）
- 输出：一个 WAV + stdout 一行 JSON（时长与逐句起止）
- 限制：edge 后端需联网；渲染/剪辑阶段读的是已落盘的 WAV，所以**只有重录音色时才需要网络**
