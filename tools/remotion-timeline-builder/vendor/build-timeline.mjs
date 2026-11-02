/**
 * build-timeline.mjs — 旁白生成 + 时间轴实测
 *
 * 流程:
 *   1. 逐段调用 macOS `say` 生成 aiff(零成本、离线、可重复)
 *   2. ffprobe 实测每段真实时长(不靠字数估算——语速因音色/标点而异)
 *   3. 累加段时长 + 段间 gap,得到每段的绝对起始秒
 *   4. 产出 public/timeline.json 供 Remotion 消费
 *
 * 输出(全部由本脚本生成,不手写):
 *   public/audio/seg-00.aiff ... seg-NN.aiff   每段旁白
 *   public/timeline.json                       { fps, durationInFrames, segments:[...] }
 *
 * 用法: node scripts/build-timeline.mjs
 */
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const AUDIO_DIR = path.join(ROOT, 'public', 'audio');

/* ── 配置 ─────────────────────────────────────────────────────────── */
const VOICE = process.env.VOICE ?? 'Tingting'; // macOS 中文音色
const RATE = process.env.RATE ?? '178'; // 语速(words/min),默认 178 偏慢,适合散文旁白
const FPS = 30;

/* ── 旁白分段(与 src/narration.ts 保持一致) ─────────────────────── */
/**
 * ⚠️ 这份数据与 src/narration.ts 重复,是刻意的:
 *    本脚本跑在 Node 里(要 spawn `say`),不能 import TS。
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
const sh = (cmd, args) =>
  execFileSync(cmd, args, {encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']});

const probeDuration = (file) => {
  const out = sh('ffprobe', [
    '-v', 'error',
    '-show_entries', 'format=duration',
    '-of', 'csv=p=0',
    file,
  ]).trim();
  return Number.parseFloat(out);
};

/**
 * 逐字时间戳权重。
 *
 * macOS `say` 的中文朗读语速基本均匀(实测 ~4.3 字/s),
 * 但标点处有停顿、拉丁字符/数字更快。所以按权重分配时长:
 *   汉字 1.0 / 拉丁与数字 0.55 / 空格 0.3 / 标点(停顿) 1.7
 * 权重和按比例分摊该段实测时长 —— 得到每个字的实际起止毫秒。
 */
const charWeight = (ch) => {
  if (/[，。！？、；：""''（）《》…—]/.test(ch)) return 1.7;
  if (/[\s]/.test(ch)) return 0.3;
  if (/[a-zA-Z0-9]/.test(ch)) return 0.55;
  return 1.0;
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
 * 生成逐字 SRT。
 *
 * 关键细节:每段的首字前置一个空格 —— kit 的 createTikTokStyleCaptions
 * 靠「以空格开头」切页,中文没有空格,不这样处理会全片合并成一页。
 */
const buildSrt = (segments) => {
  const lines = [];
  let idx = 1;
  for (const seg of segments) {
    const chars = [...seg.text];
    const weights = chars.map(charWeight);
    const total = weights.reduce((a, b) => a + b, 0);
    const startMs = seg.startSec * 1000;
    const durMs = seg.durationSec * 1000;

    let acc = 0;
    chars.forEach((ch, i) => {
      const fromMs = startMs + (acc / total) * durMs;
      acc += weights[i];
      const toMs = startMs + (acc / total) * durMs;
      // 首字前加空格 → 让 TikTok 分页在此断开
      const text = i === 0 && seg.index > 0 ? ` ${ch}` : ch;
      lines.push(
        String(idx++),
        `${srtTime(fromMs)} --> ${srtTime(toMs)}`,
        text,
        '',
      );
    });
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
  const tmpAiff = path.join(AUDIO_DIR, `${stem}.aiff`);
  // ⚠️ 必须转成 WAV:
  //    Remotion 内置的 ffprobe 对 macOS AIFF 支持不全,渲染时探测音频失败
  //    (系统 ffprobe 能读,但它用的是自带副本 → 渲染中断)。
  const outWav = path.join(AUDIO_DIR, `${stem}.wav`);

  sh('say', ['-v', VOICE, '-r', RATE, '-o', tmpAiff, seg.text]);
  sh('ffmpeg', [
    '-y',
    '-loglevel', 'error',
    '-i', tmpAiff,
    '-ar', '44100',
    '-ac', '1',
    '-c:a', 'pcm_s16le',
    outWav,
  ]);
  fs.unlinkSync(tmpAiff);

  const dur = probeDuration(outWav);
  segments.push({
    id: seg.id,
    index: i,
    text: seg.text,
    audio: `audio/${stem}.wav`,
    startSec: Number(cursor.toFixed(3)),
    durationSec: Number(dur.toFixed(3)),
    chars: seg.text.length,
  });
  console.log(
    `  ${String(i).padStart(2, '0')} ${seg.id.padEnd(9)} ` +
      `${dur.toFixed(2)}s  ${seg.text.length}字  ${(seg.text.length / dur).toFixed(2)}字/s`,
  );
  cursor += dur + GAP_SEC;
});

const contentEnd = cursor - GAP_SEC;
const totalSec = contentEnd + TAIL_SEC;

const timeline = {
  fps: FPS,
  width: 1920,
  height: 1080,
  durationInFrames: Math.round(totalSec * FPS),
  voice: VOICE,
  rate: RATE,
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

// 逐字 SRT(供 kit 的 SrtCaptions 组件做词级高亮)
const srt = buildSrt(segments);
fs.writeFileSync(path.join(ROOT, 'public', 'captions.srt'), srt);

// 逐字 caption 数据(供 src/captions.ts 直接 import ——
// Remotion 的 webpack 不保证支持 ?raw loader,故同时输出 JSON)
const captionData = [];
segments.forEach((seg) => {
  const chars = [...seg.text];
  const weights = chars.map(charWeight);
  const total = weights.reduce((a, b) => a + b, 0);
  const startMs = seg.startSec * 1000;
  const durMs = seg.durationSec * 1000;
  let acc = 0;
  chars.forEach((ch, i) => {
    const fromMs = startMs + (acc / total) * durMs;
    acc += weights[i];
    const toMs = startMs + (acc / total) * durMs;
    captionData.push({
      text: ch,
      startMs: Math.round(fromMs),
      endMs: Math.round(toMs),
      segmentIndex: seg.index,
    });
  });
});
fs.writeFileSync(
  path.join(ROOT, 'public', 'captions.json'),
  JSON.stringify(captionData),
);

console.log(`\n✓ 总时长 ${totalSec.toFixed(2)}s / ${timeline.durationInFrames} 帧`);
console.log(`✓ 写入 public/timeline.json`);
console.log(`✓ 写入 public/captions.srt(逐字 ${srt.split('\n\n').length} 条)`);
console.log(`✓ 写入 public/captions.json(逐字 ${captionData.length} 条)`);
