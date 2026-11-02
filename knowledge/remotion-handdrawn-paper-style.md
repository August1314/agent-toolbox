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

⚠️ **它按参数匀速，不按弧长匀速**。疏密不均的贝塞尔上，笔尖会忽快忽慢
（本次实测：环上一段 90° 弧走得很慢，另一段嗖地过去）。
要"一支笔在写"的观感，用 `@remotion/paths` 的 `evolvePath` / `getPointAtLength`
走真实弧长；`pathLength={1}` 只适合粗细均匀的描边。

⚠️ **路径长度必须现算**。本次把环的 `strokeDasharray` 写死成屏幕上量到的 `1760`，
`getLength` 实测是 `2638` → "已走过"永远只涂到 2/3。几何常量一律
`getLength(d)` 现算 + 模块级缓存，不要抄屏幕上的数字。

⚠️ **"绝对 M + 相对 m" 会让弧长原点跑到别处**。
`M 960 470 m -560 0 a …` 这种写法下，`getPointAtLength(d, 0)` 返回的是被 `m`
偏移掉的 `M` 点（这里是圆心），不是环的起点 → 沿弧长取点会在第一帧把人
瞬移到环的另一端。要么写绝对起点，要么把 `m` 折进 `M`。

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

---

## 四、编排层重写（第二轮）踩的坑

第一轮只解决"一个画面怎么画出来"，第二轮解决"多个画面怎么连成一件事"。
坑全部在编排层，而且**没有一个能靠看代码发现**。

### K. 匀速行程不能套弹簧

给骑车、走路、雾带横扫这类**穿越画面**的位移加 `spring()`，
对象会在终点自己刹车、顿一下 —— 因为弹簧的目标是"落到那个值"，
而行程的物理语义是"以恒定速度经过"。

**规矩**：弹簧只用于**有落点**的位移（入场、翻牌、回弹）；
穿越型位移保持线性，并把理由写进注释，防止下一个人"统一风格"时又加回去。

### L. `CameraMotionBlur` 的 `samples=1` 不是恒等变换

它按 `currentFrame - offset + 1` 取帧，相当于整体渲染到约 **0.5 帧之后**。
想"关掉"它必须**条件包裹子树**（`{blur ? <CameraMotionBlur>…</> : children}`），
不能传 `samples=1` —— 否则画面与音画错位半帧，逐字高亮跟着漂。

### M. headless Chrome 没有 GL，而修复方式很脆

`@remotion/light-leaks` 报 `Failed to acquire WebGL context`。
4.0.489 没有 `Config.setChromiumOpenGlRenderer`，只能在 CLI 传 `--gl=angle`。
**一旦把 `--gl=angle` 写进 npm scripts，任何绕过 scripts 直接调 `remotion` 的用法都会崩**
（本次就踩了：脚本里能跑，`npx remotion still` 手测就挂）。
把渲染参数放在**能被绕过的地方**是设计缺陷，能进 config 就别进 shell。

### N. 手绘感要用相干噪声，不是白噪声

逐点独立的 `Math.random()` 抖动看起来是"毛刺"；**空间平滑的噪声场**
（`noise2D` 连续场 / `feTurbulence` 位移）才读得出"手不稳"。
而且多个对象要**共用同一个场**，才会被读成"同一股气流"——
各抖各的，观感是贴纸，不是画。

### O. 位移只加一层：`translate` 加两次 = 偏移翻倍

（同 §二 F，第二轮又踩了一次变体：外层 g 已 `translate(ox)`，
内层 `x` 里又含 `ox`）。**绝对定位只在一层做**，缩放单独一层：
`translate(cx,cy) scale(s) translate(-cx,-cy)`。

### P. "看起来接了"的假动作 —— 编排层只能用像素验收

`Filter.tsx` 的注释写着"两道半幅画面被弹簧推开"，实际 `splitX` 是个常量，
弹簧只作用在 opacity 上。**注释与像素不一致，就是没接上。**
改成 `const edge = remap(sp(frame, …), 1920, 960)` 才算真的推开。
编排层的验收必须是**静帧**（或从成片回读），不是读代码、也不是看日志。

### Q. 固定帧窗口会被上游改动捅破

动画窗口写死 `durationInFrames: 37` 之类，配音剪掉静音后段长变短，
Hook 的荧光笔弹簧溢出 7 帧。
**规矩**：段内动画按 `durationInFrames` 取比例，不写绝对帧号；
改任何影响时长的环节之后，重跑一遍"所有写死帧号 ≤ 段长"的扫描。

---

## 五、配音链：神经 TTS 的静音陷阱

### R. 神经 TTS 每句自带首尾静音 → 字幕跑到人声前面

`say` 的静音很短，神经 TTS（edge-tts / sherpa-onnx）句间静音可达上百毫秒。
时间轴按"句起点"排，引擎给的起点里却含着一段静音 →
**画面已经动了，声音还没到**，逐字高亮整体前移。

**只有从渲染好的 MP4 里回读 PCM 量 onset 才能发现**：
`build-timeline` 的日志一切正常，索引里 `verified: true`，
`toolbox run` 也返回了 JSON —— 中间每一层都"成功"，错的是层间的隐含假设。

修：`silenceremove` 剪静音（保留约 50ms 起音保护，防爆破音）→ 剪完再量实测时长；
剪完的段长变化要回灌时间轴，否则 Q 类溢出。

### S. 观感比较前必须归一化干扰量

五个候选引擎的响度不一致，直接 A/B 一定是"响一点的那个赢"—— 测的是增益不是质感。
先全部归一到 −16 LUFS（并看 True Peak / LRA），再让人挑。
同类干扰量：画幅、DPI、时长、取样位置、字体大小。
**不归一化的比较结论不能进索引。**

### T. 烟测要用本任务最刁的那条样本，检查"丢了什么"

`matcha-icefall-zh` 的日志里 `OOV word skipped: 'AI'` —— 它**正常退出**、
**输出了 wav**、**时长也合理**，只是把拉丁词悄悄丢了。
只断言"有输出"的烟测抓不到。文案里必须放中英混排 + 数字 + 百分号，
然后**回读文本比对**（ASR 或字形对齐），看丢了什么，而不是看产了什么。

### U. 按整句切，不按逗号切

逗号级切分会让引擎在逗号处重新起音，听起来是"一串碎片"。
以句（。！？）为单位送，引擎内部自己断；字幕分页再按字数与标点策略切。

---

## 六、复用别人 kit 的正确姿势（第二轮的做法）

参考 kit 里有大量"看代码手痒想重写"的部分。这一轮的做法可以复用到任何 kit：

| 做法 | 本次落地 | 为什么 |
|---|---|---|
| **走官方扩展点，不改 vendor** | kit 的 `Stage` + `subjectAt` 相机系统，通过官方 `StageStep.easing` 槽注入自己的 spring 曲线 | 一行 vendor 都没动，升级 kit 时直接替换目录即可 |
| **拿能力，别拿布局** | `FloatingCard` / `SideList` 挂在 `Camera` **外面** | 相机推的是"场景"，卡片留在不动的层上，才读得出纵深；挂进去会一起被推走 |
| **成批拿官方包** | 6 个 `@remotion/*` 包直接用 | 一个包解决一个环节，比自写省一整轮 |
| **不用也要留判断记录** | `CameraMotionBlur`：位移约 1px/帧，代价是 samples 倍重渲染 → 判不用；`makePolygon/makeStar`：零视觉增益 → 判不用 | 没有这行记录，下一个人会"重新发现"并误以为漏了什么 |

**质感件使用率**（收了 N 个质感件、实际用了几个）是这类任务的唯一有效体检指标。
第一轮是 1/9（`spring()` 调用 0 次），第二轮 8/8。
比值低说明还在按"输入输出契不契合"筛质感件 —— 那是功能型的筛法。

**注释与像素一致性扫描**：`Easing.*` / `Math.random` / `spring(` 这类
grep 指标必须**排除注释**，否则第一轮那种"注释里写了弹簧、代码里是常量"
会一路绿灯。机械扫描一旦能被注释骗过，团队就会放弃它。
