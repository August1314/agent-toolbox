# remotion-timeline-builder

Remotion 视频的「文案 → 实测时间轴」流水线。TTS 逐段合成 + ffprobe 实测时长 →
`public/timeline.json`，供 Remotion 按 `startFrame` / `durationInFrames` 驱动场景。

## 来源

- 实战验证：`expression-video` 项目（78.78s / 1080p30 成片跑通）
- license: MIT
- `vendor/build-timeline.mjs` **原样取自该项目，未改一字**

## 为什么需要它

时间轴**必须实测，不能估算**。TTS 语速因音色、标点而异，实测在 4.0–5.1 字/s 区间浮动。
按字数估时长会导致字幕与旁白累积漂移，场景越长偏得越远。

## 调用

```bash
# 放到目标项目
toolbox run remotion-timeline-builder --in <Remotion 项目目录>

# 然后在项目内执行
cd <项目> && node scripts/build-timeline.mjs
```

依赖检查（不跑渲染）：

```bash
toolbox run remotion-timeline-builder -- --selftest
```

## 契约

- **输入**：一个 Remotion 项目目录（含 `package.json` 与 `scripts/`）
- **输出**：`public/timeline.json` + `public/audio/seg-NN.aiff`
- **限制**：
  - 依赖 macOS `say`（离线 TTS，Tingting 音色）—— Linux 需替换为 espeak 等
  - 依赖 `ffprobe` / `ffmpeg`
  - 脚本内约定文案与 `src/narration.ts` 双向校验，两边不一致会直接退出

## 关键约定

- `scripts/build-timeline.mjs` 是文案 → 时间轴的**唯一入口**，改文案必须先跑它
- 文案在 `src/narration.ts` 与脚本里各存一份，脚本启动时校验一致性
- 生成 `seg-*.aiff` 后需转 wav 再喂 Remotion（内置 ffprobe 读不了 macOS AIFF）：
  `ffmpeg -i x.aiff -ar 44100 -ac 1 -c:a pcm_s16le x.wav`

## 关联

技法与 9 条踩坑清单 → `toolbox lookup remotion` 命中
`remotion-handdrawn-paper-style`（knowledge 类）。
