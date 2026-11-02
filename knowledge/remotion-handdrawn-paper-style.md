# Remotion 手绘纸张风视频：技法与工程约定

来源：`chenyuxiaojin/motionface-op55-handdrawn`（Motion Face 作者，MIT）+
`vibe-motion/remotion-starter`（MIT）+ 本次实战踩坑。
用途：任何"手绘/纸上写字/纸纹质感"的程序化视频。

---

## 一、四件套原语（可直接抄）

### 1. 描线生长（免测量）

```tsx
<path d={d} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - p} fill="none" />
```

`pathLength={1}` 把路径长度归一化到 1，`strokeDashoffset` 直接当进度用。
不需要测路径长度、不需要动画库。

### 2. 手写文字（clipPath 推进）

```tsx
<clipPath id={id}>
  <rect x={x - 30} y={y - size * 1.25} width={clipW} height={size * 1.8} />
</clipPath>
<text clipPath={`url(#${id})`}>{text}</text>
```

⚠️ **clip 宽度必须实测，不能手填**。手填 `width` 在换字体/换字号后会裁错
（整段被裁没或提前裁完）。用 canvas `measureText` 同步测量：

```ts
ctx.font = `${weight} ${size}px ${family}`;
const w = ctx.measureText(text).width;
```

⚠️ **测量要同步，不能放 useEffect**。放 useEffect 里首帧 width=0 →
组件不渲染 → 开头几十帧空白。同步测量（模块级缓存 ctx）才可靠。

### 3. 纸纹（两层噪声 + 暗角）

```xml
<filter id="grain">   <!-- 高频颗粒 -->
  <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="3" seed="7" stitchTiles="stitch"/>
  <feColorMatrix type="matrix" values="0 0 0 0 0.42  0 0 0 0 0.35  0 0 0 0 0.25  0 0 0 0.16 0"/>
</filter>
<filter id="blotch"> <!-- 低频洇痕 -->
  <feTurbulence type="fractalNoise" baseFrequency="0.006" numOctaves="2" seed="3"/>
</filter>
<radialGradient id="vignette" cx="50%" cy="48%" r="75%">
  <stop offset="60%" stopColor="#7A5F3C" stopOpacity={0}/>
  <stop offset="100%" stopColor="#7A5F3C" stopOpacity={0.22}/>
</radialGradient>
```

### 4. boil 抖动（手绘呼吸感）

```xml
<filter id="boil">
  <feTurbulence type="fractalNoise" baseFrequency="0.02" numOctaves="2" seed={seed}/>
  <feDisplacementMap in="SourceGraphic" scale="5" xChannelSelector="R" yChannelSelector="G"/>
</filter>
```

`seed = Math.floor(frame / 3) % 6` —— 每 3 帧换一次，确定性且不闪。

---

## 二、踩坑清单（都是实际卡住过的）

### A. 字体没加载 → 全片 fallback + 手写标题整段消失

**症状**：文字用 fallback 黑体；SVG clipPath 量到 fallback 字宽 → 手写标题被裁没。

**原因**：`@font-face` 从未注册。`loadFont` 必须在**模块顶层被 import 链触发**，
否则根本不会执行。

**修**：`src/index.ts` 顶层 `import './fonts'`（不能删）。

### B. delayRender 放在模块顶层 → 视频渲染 28s 超时

**症状**：`still` 渲染能过，全片渲染报
`A delayRender() "Loading fonts" was called but not cleared after 28000ms`。

**原因**：模块加载时机与多帧并发渲染的时序不同步。

**修**：字体加载的阻塞放到**组件内**用 `useEffect` + `delayRender`；
`fonts.ts` 只负责注册 `@font-face`，不阻塞。

### C. kit 的 SrtCaptions 必须挂在根层级

**症状**：字幕只显示最后几个字。

**原因**：组件内部用 `<Sequence from={page.startMs/fps}>` 按**绝对毫秒**定位，
并在 Sequence 内用 `useCurrentFrame()` 算相对毫秒。
把它包在别的 Sequence/容器里 → 相对帧与绝对时间对不上。

**修**：放根层级；卡片底衬另写一个绝对定位的兄弟节点。

### D. kit 的 createTikTokStyleCaptions 会把多屏合并成一页

**症状**：一屏 30 字的字幕溢出画面；或前一页时长盖住后一页。

**原因**：它的切页条件是「累计时长 > combineTokensWithinMilliseconds」
（默认 1000ms）。中文逐字时间戳下，一屏 30 字约 7 秒 >> 1000ms，
于是它认为"还没到切页点"，把连续多屏合并。

**修**（两条同时做）：
1. 自己按**字数**切页，每页首字前置一个空格（中文没有天然空格，
   kit 靠"以空格开头"判定新句起点）
2. 传 `combineMs={0}` → 每个空格都是硬分页点，kit 的分页结果与自己的完全一致

### E. 字幕断句要在标点处断

按字数硬断会切出「撼。」这种孤字尾页。策略：
硬标点（。！？）后断 > 软标点（，、；：）后断 > 硬断；
断点太靠前（切出 <4 字的页）就放弃标点断；收尾页 ≤2 字则合并回上一页。

### F. SVG 缩放必须绕自身中心

`scale()` 绕 SVG 原点。把 `<g transform="translate(x,y) scale(s)">` 用在
已定位的元素上 → 元素被拽向画面左上角。

**修**：拆成两层 g：
- 外层 g：`translate(x, y)` —— 只做绝对定位
- 内层 g：`translate(cx,cy) scale(s) translate(-cx,-cy)` —— 只做缩放

⚠️ **位移不能加两次**。外层已 translate(ox) 且内层又 translate(x)（x 含 ox）
→ 偏移翻倍。规矩：**绝对定位只在一层做**。

### G. Remotion 内置 ffprobe 读不了 macOS AIFF

**症状**：`Error while downloading .../seg-00.aiff ... Command failed with exit code 1`
（系统 ffprobe 能读，但 Remotion 用的是自带副本）

**修**：`say` 出 aiff 后用 ffmpeg 转 wav：
`ffmpeg -i x.aiff -ar 44100 -ac 1 -c:a pcm_s16le x.wav`

### H. Remotion 包版本必须全部一致

**症状**：`Version mismatch: Not all Remotion packages have the same version`

**修**：package.json 里所有 `remotion` / `@remotion/*` 锁同一版本（去掉 `^`），
`zod` 也要对上（`npx remotion versions` 会报）。

⚠️ 4.0.540 的 chrome-headless-shell 在本机报 UnhandledPromiseRejection，
4.0.489 正常 → **优先用能跑通的版本，不是最新版本**。

### I. npm 缓存有坏包

**症状**：`Cannot find module '.../@remotion/studio/dist/renderEntry.js'`
但 package.json 的 exports 里明明声明了这个文件。

**修**：`rm -rf node_modules package-lock.json && npm cache clean --force && npm install`

---

## 三、工程约定（本次实行的）

### 时间轴必须实测，不能估算

TTS 语速因音色/标点而异（本次实测 4.0–5.1 字/s）。做法：

```js
say -v Tingting -r 178 -o seg.aiff "文案"
dur = ffprobe -show_entries format=duration seg.wav   // 实测
start[i+1] = start[i] + dur[i] + gap
```

生成 `timeline.json` → Remotion 按 `startFrame` / `durationInFrames` 驱动场景。
改文案后重跑脚本，时间轴自动跟着变。

### 文案与脚本双向校验

`src/narration.ts`(TS) 与 `scripts/build-timeline.mjs`(MJS) 各存一份分段，
脚本启动时校验两边文本一致，不一致直接退出。
（MJS 跑在 Node 里 spawn `say`，不能 import TS。）

### 逐字字幕时间戳（无 ASR 的做法）

按字符权重分配段内时长：
汉字 1.0 / 拉丁与数字 0.55 / 空格 0.3 / 标点(停顿) 1.7

权重和按比例分摊该段实测时长 → 每个字的起止毫秒。
精度足够做逐字高亮，且完全离线零成本。

### 确定性红线

- 所有动画由 `useCurrentFrame()` 驱动
- 所有 `interpolate` 带 `{extrapolateLeft:'clamp', extrapolateRight:'clamp'}`
- 禁 `Math.random()` / `Date.now()` → 用 seeded PRNG（mulberry32）
- 禁 CSS `@keyframes` / `transition`
- 禁 `setTimeout` / `setInterval` / `useState` 驱动动画进度

**验收**：同一帧渲两次，逐字节一致（`cmp`）。
