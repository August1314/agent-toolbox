/**
 * build-timeline.mjs — 旁白生成 + 时间轴实测
 *
 * 流程:
 *   1. 逐段调用 scripts/voice/synth.py(神经 TTS + 后期链)产出 seg-NN.wav
 *      —— 段内按整句切、句间插可控停顿,每句起止由 ffprobe 实测
 *   2. 累加段时长 + 段间 gap,得到每段的绝对起始秒
 *   3. 产出 public/timeline.json / captions.srt / captions.json 供 Remotion 消费
 *
 * 输出(全部由本脚本生成,不手写):
 *   public/audio/seg-00.wav ... seg-NN.wav     每段旁白(48kHz/mono/-16 LUFS)
 *   public/timeline.json                       { fps, durationInFrames, segments:[...] }
 *
 * 用法: node scripts/build-timeline.mjs
 *   首次先跑 bash scripts/voice/setup.sh
 *   换音色/引擎:VOICE_ID=... ENGINE=auto|edge|melo node scripts/build-timeline.mjs
 */
import {spawnSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const AUDIO_DIR = path.join(ROOT, 'public', 'audio');
const VOICE_PY =
  process.env.VOICE_PY ?? path.join(ROOT, '.venv-voice', 'bin', 'python');
const SYNTH = path.join(ROOT, 'scripts', 'voice', 'synth.py');

/* ── 配置 ─────────────────────────────────────────────────────────── */
const ENGINE = process.env.ENGINE ?? 'auto'; // auto:edge 优先,失败回落离线 melo
const VOICE_ID = process.env.VOICE_ID ?? 'zh-CN-YunxiNeural'; // 男声,Novel 类
const RATE = process.env.RATE ?? '-10%'; // 相对语速,散文旁白偏慢
const PITCH = process.env.PITCH ?? '-2Hz'; // 略压音高,去掉朗读腔的亮尖
const PAUSE = process.env.PAUSE ?? '0.30'; // 句间静音(秒)
const FPS = 30;

/* ── 旁白分段(与 src/narration.ts 保持一致) ─────────────────────── */
/**
 * ⚠️ 这份数据与 src/narration.ts 重复,是刻意的:
 *    本脚本跑在 Node 里(要 spawn 合成器),不能 import TS。
 *    build-timeline 会校验两边一致 —— 不一致直接报错退出。
 */
const SEGMENTS = [
  {id: 'hook', text: '我发现，我越来越丧失表达欲了。'},
  {id: 'album', text: '今天翻出相册里很久以前的照片。风景照，有水，有山，有星空。时间是，2022年。'},
  {id: 'cage', text: '那时候整个县城都是我的天地。现在，我的身体只能活动在这座大学城岛上，在190乘70厘米的上床。'},
  {id: 'bike', text: '以前我骑着一辆很烂的自行车，爸爸送的，到处逛。人迹罕至的地方，只要我想，就能蹬过去。'},
  {id: 'coffee', text: '现在我细啜着一杯埃塞瑰夏美式，绕着学校走了一圈，却不知道去哪。'},
  {id: 'gray', text: '理想的地方我找不到，熟悉的地方我不想去。'},
  {id: 'filter', text: '香港澳门的街头，旧金山的海边，是加了十层去灰滤镜的清新。'},
  {id: 'analysis', text: 'AI提醒过我：我性格里P的属性太强，很多方向都探索，最后都不了了之。要把握广度，提升深度。'},
  {id: 'impulse', text: '可现在写着写着，也不知道为什么，突然就是想写。'},
  {id: 'outro', text: '那就让agent做成一个视频吧。为表达欲，加一点四年之后的震撼。'},
];

const GAP_SEC = 0.45;
const LEAD_IN_SEC = 0.6;
const TAIL_SEC = 1.6;

/* ── 工具 ─────────────────────────────────────────────────────────── */
/**
 * 句内逐字权重。
 *
 * 神经 TTS 的中文朗读语速也基本均匀,但标点处有停顿、拉丁字符/数字更快。
 * 所以句内按权重分摊该句【实测】时长:
 *   汉字 1.0 / 拉丁与数字 0.55 / 空格 0.3 / 标点(停顿) 1.7
 */
const charWeight = (ch) => {
  if (/[，。！？、；：""''（）《》…—]/.test(ch)) return 1.7;
  if (/[\s]/.test(ch)) return 0.3;
  if (/[a-zA-Z0-9]/.test(ch)) return 0.55;
  return 1.0;
};

/**
 * 一段旁白 → 逐字时间戳。
 *
 * 与旧版的区别:旧版把整段时长按字重一把摊平,句间停顿被算进了字的时长里
 * (于是"。"后面的字会比实际早出现)。现在每句的起止来自 synth.py 的
 * ffprobe 实测,句内再按字重分摊 —— 停顿归停顿,字归字。
 */
const charTimings = (seg) => {
  const cues = [];
  for (const s of seg.sentences) {
    const chars = [...s.text];
    const weights = chars.map(charWeight);
    const total = weights.reduce((a, b) => a + b, 0);
    const baseMs = (seg.startSec + s.startSec) * 1000;
    const durMs = (s.endSec - s.startSec) * 1000;
    let acc = 0;
    for (const [i, ch] of chars.entries()) {
      const fromMs = baseMs + (acc / total) * durMs;
      acc += weights[i];
      cues.push({
        text: ch,
        startMs: Math.round(fromMs),
        endMs: Math.round(baseMs + (acc / total) * durMs),
        segmentIndex: seg.index,
      });
    }
  }
  return cues;
};

const srtTime = (ms) => {
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  const x = Math.floor(ms % 1000);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(
    s,
  ).padStart(2, '0')},${String(x).padStart(3, '0')}`;
};

/**
 * 逐字 SRT。
 *
 * 关键细节:每段的首字前置一个空格 —— kit 的 createTikTokStyleCaptions
 * 靠「以空格开头」切页,中文没有空格,不这样处理会全片合并成一页。
 */
const buildSrt = (cues) => {
  const lines = [];
  let idx = 1;
  let prevSeg = -1;
  for (const c of cues) {
    const isFirstOfSegment = c.segmentIndex !== prevSeg;
    prevSeg = c.segmentIndex;
    const text =
      isFirstOfSegment && c.segmentIndex > 0 ? ` ${c.text}` : c.text;
    lines.push(
      String(idx++),
      `${srtTime(c.startMs)} --> ${srtTime(c.endMs)}`,
      text,
      '',
    );
  }
  return lines.join('\n');
};

/* ── 主流程 ───────────────────────────────────────────────────────── */
fs.mkdirSync(AUDIO_DIR, {recursive: true});

// 校验 TS 与本脚本的分段一致(防止两边漂移)
const tsPath = path.join(ROOT, 'src', 'narration.ts');
const tsSrc = fs.readFileSync(tsPath, 'utf8');
for (const seg of SEGMENTS) {
  const needle = `id: '${seg.id}'`;
  if (!tsSrc.includes(needle)) {
    console.error(`✗ 分段漂移:narration.ts 缺少 ${needle}`);
    process.exit(1);
  }
  const textInTs = tsSrc.match(
    new RegExp(`id: '${seg.id}',\\s*\\n\\s*text: '([^']*)'`),
  );
  if (!textInTs) {
    console.error(`✗ 分段漂移:无法从 narration.ts 解析 ${seg.id} 的文本`);
    process.exit(1);
  }
  if (textInTs[1] !== seg.text) {
    console.error(`✗ 分段漂移:${seg.id} 文本不一致`);
    console.error(`  ts  : ${textInTs[1]}`);
    console.error(`  mjs : ${seg.text}`);
    process.exit(1);
  }
}
console.log(`✓ 分段一致性校验通过(${SEGMENTS.length} 段)`);

const segments = [];
let cursor = LEAD_IN_SEC;

SEGMENTS.forEach((seg, i) => {
  const stem = `seg-${String(i).padStart(2, '0')}`;
  // 48kHz/mono/pcm_s16le —— 由 synth.py 统一重采样并过后期链
  const outWav = path.join(AUDIO_DIR, `${stem}.wav`);

  if (!fs.existsSync(VOICE_PY)) {
    console.error(`✗ 缺配音环境:${VOICE_PY}\n  先跑:bash scripts/voice/setup.sh`);
    process.exit(1);
  }
  // 值用 --opt=value 形式:argparse 会把裸 "-10%" 当成选项名
  const r = spawnSync(VOICE_PY, [
    SYNTH,
    `--text=${seg.text}`,
    `--out=${outWav}`,
    `--engine=${ENGINE}`,
    `--voice=${VOICE_ID}`,
    `--rate=${RATE}`,
    `--pitch=${PITCH}`,
    `--pause=${PAUSE}`,
  ], {encoding: 'utf8'});
  if (r.status !== 0) {
    console.error(`✗ ${seg.id} 合成失败:\n${r.stderr?.slice(-800) ?? ''}`);
    process.exit(1);
  }
  if (r.stderr?.trim()) console.log(`  ! ${r.stderr.trim().split('\n').pop()}`);
  const synth = JSON.parse(r.stdout.trim().split('\n').pop());

  segments.push({
    id: seg.id,
    index: i,
    text: seg.text,
    audio: `audio/${stem}.wav`,
    startSec: Number(cursor.toFixed(3)),
    durationSec: synth.durationSec,
    chars: seg.text.length,
    engine: synth.engine,
    // 段内相对秒 —— synth.py 实测,不是估算;字幕按它锚定
    sentences: synth.sentences,
  });
  console.log(
    `  ${String(i).padStart(2, '0')} ${seg.id.padEnd(9)} ` +
      `${synth.durationSec.toFixed(2)}s  ${seg.text.length}字  ` +
      `${synth.sentences.length}句  [${synth.engine}]`,
  );
  cursor += synth.durationSec + GAP_SEC;
});

const contentEnd = cursor - GAP_SEC;
const totalSec = contentEnd + TAIL_SEC;

const timeline = {
  fps: FPS,
  width: 1920,
  height: 1080,
  durationInFrames: Math.round(totalSec * FPS),
  voice: VOICE_ID,
  engine: ENGINE,
  rate: RATE,
  pitch: PITCH,
  pauseSec: Number(PAUSE),
  segments: segments.map((s) => ({
    ...s,
    startFrame: Math.round(s.startSec * FPS),
    durationInFrames: Math.round(s.durationSec * FPS),
  })),
};

fs.writeFileSync(
  path.join(ROOT, 'public', 'timeline.json'),
  JSON.stringify(timeline, null, 2),
);

// 逐字时间戳算一次,SRT 与 JSON 都从它出 —— 两份产物必须同源,否则字幕
// 高亮和 kit 分页会各自漂移。
const cues = segments.flatMap(charTimings);

// 逐字 SRT(供 kit 的 SrtCaptions 组件做词级高亮)
const srt = buildSrt(cues);
fs.writeFileSync(path.join(ROOT, 'public', 'captions.srt'), srt);

// 逐字 caption 数据(供 src/captions.ts 直接 import ——
// Remotion 的 webpack 不保证支持 ?raw loader,故同时输出 JSON)
const captionData = cues.map((c) => ({
  text: c.text,
  startMs: c.startMs,
  endMs: c.endMs,
  segmentIndex: c.segmentIndex,
}));
fs.writeFileSync(
  path.join(ROOT, 'public', 'captions.json'),
  JSON.stringify(captionData),
);

console.log(`\n✓ 总时长 ${totalSec.toFixed(2)}s / ${timeline.durationInFrames} 帧`);
console.log(`✓ 写入 public/timeline.json`);
console.log(`✓ 写入 public/captions.srt(逐字 ${srt.split('\n\n').length} 条)`);
console.log(`✓ 写入 public/captions.json(逐字 ${captionData.length} 条)`);
