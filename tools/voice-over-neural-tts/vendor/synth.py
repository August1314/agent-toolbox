#!/usr/bin/env python3
"""
synth.py — 旁白合成 + 后期(单一入口,两个后端)

契约:
    输入一段旁白文本 → 输出一个 48kHz/mono/pcm_s16le 的 WAV,
    并在 stdout 打印 JSON:
        {"durationSec": float,
         "engine": "edge" | "melo",
         "sentences": [{"text","startSec","endSec"}]}

为什么按【整句】切、不按逗号切:
    神经 TTS 的韵律是在"一句完整话"的上下文里生成的。切成逗号级碎片后,
    每个碎片都被当成独立话语(各自降调),连起来听就是一串清单 —— 比不切还差。
    只在句末标点(。!?;…)断开,碎片仍是完整句子,韵律不被破坏;
    而句间停顿改由我们注入的静音精确控制(这本身就是旁白质感的一部分)。

顺带解决的老问题:
    旧管线用 `say` 整段合成,句间停顿是引擎黑箱给的,字幕时间戳只能按字重估算。
    现在每句的起止是 ffprobe 实测的 —— 字幕锚到真实边界上。

后端:
    edge — Microsoft Edge 神经音色(在线,LGPLv3)。中英混读正确。
    melo — sherpa-onnx + MeloTTS zh_en(完全离线,MIT,44.1kHz)。
    engine=auto:先 edge,失败重试 3 次,仍失败则整段回落 melo 并告警。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

# VOICE_HOME:环境/模型的落地目录(工程根或工具库目录);也可单独用
# VOICE_PY / MELO_MODEL_DIR 覆盖。
_HOME = os.environ.get('VOICE_HOME') or os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..'))
VENV_PY = os.environ.get('VOICE_PY', os.path.join(_HOME, '.venv-voice', 'bin', 'python'))
MELO_DIR = os.environ.get(
    'MELO_MODEL_DIR',
    os.path.join(_HOME, '.voice-models', 'vits-melo-tts-zh_en'),
)
SR = 48000

SENT_SPLIT = re.compile(r'(?<=[。．！？!？；;…])')


def split_sentences(text):
    """按句末标点切,保留标点;丢弃空碎片。"""
    parts = [p.strip() for p in SENT_SPLIT.split(text) if p and p.strip()]
    return parts or [text.strip()]


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(f'command failed: {cmd[:4]}…\n{r.stderr[-500:]}')
    return r


def probe_dur(path):
    out = run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
               '-of', 'csv=p=0', path]).stdout.strip()
    return float(out)


def to_wav(src, dst):
    """统一成 48k/mono/pcm_s16le —— 后面才能用 concat demuxer 无损拼接。"""
    run(['ffmpeg', '-y', '-loglevel', 'error', '-i', src,
         '-ar', str(SR), '-ac', '1', '-c:a', 'pcm_s16le', dst])


# 神经 TTS 会在每句首尾垫静音(实测 edge 一句 3.84s 里只有 2.69s 是声音)。
# 不剪掉的话:①"句间停顿"= 引擎垫的 0.9s + 我们注入的 0.3s,根本不受控;
# ②字幕时长按含静音的句长分摊 → 字幕比声音早出现;③全片被垫出十几秒。
# 两端各留 50ms 保护,免得首字的爆破音/尾字的摩擦音被切掉。
TRIM = ('silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,'
        'areverse,'
        'silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,'
        'areverse')


def trim_silence(path):
    """就地剪掉一句的首尾静音。"""
    tmp = path + '.trim.wav'
    run(['ffmpeg', '-y', '-loglevel', 'error', '-i', path, '-af', TRIM,
         '-ar', str(SR), '-ac', '1', '-c:a', 'pcm_s16le', tmp])
    os.replace(tmp, path)


# ── 后端 ──────────────────────────────────────────────────────────────
def synth_edge(text, out_wav, voice, rate, pitch):
    if not os.path.isfile(VENV_PY):
        raise RuntimeError(f'缺 venv:{VENV_PY}(先跑 scripts/voice/setup.sh)')
    last = None
    for attempt in range(1, 4):
        tmp = out_wav + '.mp3'
        r = subprocess.run(
            [VENV_PY, '-m', 'edge_tts', '--voice', voice,
             f'--rate={rate}', f'--pitch={pitch}',
             '--write-media', tmp, '--text', text],
            capture_output=True, text=True)
        if r.returncode == 0 and os.path.getsize(tmp) > 1000:
            to_wav(tmp, out_wav)
            os.remove(tmp)
            return
        last = r.stderr[-300:]
        os.remove(tmp) if os.path.exists(tmp) else None
        time.sleep(1.5 * attempt)
    raise RuntimeError(f'edge-tts 三次失败:{last}')


_melo = None


def synth_melo(text, out_wav, speed):
    global _melo
    if not os.path.isdir(MELO_DIR):
        raise RuntimeError(f'缺 Melo 模型:{MELO_DIR}(先跑 scripts/voice/setup.sh)')
    if _melo is None:
        import sherpa_onnx as s
        d = MELO_DIR
        v = s.OfflineTtsVitsModelConfig(
            model=f'{d}/model.onnx', lexicon=f'{d}/lexicon.txt',
            tokens=f'{d}/tokens.txt', data_dir='', dict_dir=f'{d}/dict',
            noise_scale=0.6, noise_scale_w=0.8, length_scale=1.0)
        mc = s.OfflineTtsModelConfig()
        mc.vits = v
        mc.num_threads = 4
        _melo = s.OfflineTts(s.OfflineTtsConfig(
            model=mc,
            rule_fsts=f'{d}/date.fst,{d}/number.fst,{d}/phone.fst'))
    import sherpa_onnx as s
    a = _melo.generate(text, sid=0, speed=speed)
    tmp = out_wav + '.raw.wav'
    s.write_wave(tmp, a.samples, a.sample_rate)
    to_wav(tmp, out_wav)
    os.remove(tmp)


# ── 后期链 ────────────────────────────────────────────────────────────
# 顺序有讲究:先去高频毛刺(de-esser)再压缩,否则压缩会把齿音一起抬上来;
# loudnorm 放最后且走【两遍】,linear=true 才不会动态压 —— 全片各段响度一致,
# 而不是每段各自为政(旧管线就是峰值 -2.5dBFS 顶满、段间忽响忽轻)。
POST = ('highpass=f=80,deesser=i=0.3,'
        'acompressor=threshold=0.1:ratio=3:attack=20:release=250:makeup=1')


def measure_loudness(path):
    r = run(['ffmpeg', '-hide_banner', '-nostats', '-i', path,
             '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json',
             '-f', 'null', '-'])
    t = r.stderr
    return json.loads(t[t.find('{'):t.rfind('}') + 1])


def post_process(src, dst):
    m = measure_loudness(src)
    ln = (f'loudnorm=I=-16:TP=-1.5:LRA=11'
          f':measured_I={m["input_i"]}:measured_TP={m["input_tp"]}'
          f':measured_LRA={m["input_lra"]}:measured_thresh={m["input_thresh"]}'
          f':offset={m["target_offset"]}:linear=true')
    run(['ffmpeg', '-y', '-loglevel', 'error', '-i', src,
         '-af', f'{POST},{ln}', '-ar', str(SR), '-ac', '1',
         '-c:a', 'pcm_s16le', dst])


# ── 主流程 ────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--text', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--engine', default='auto', choices=['auto', 'edge', 'melo'])
    ap.add_argument('--voice', default='zh-CN-YunxiNeural')
    ap.add_argument('--rate', default='-10%')
    ap.add_argument('--pitch', default='-2Hz')
    ap.add_argument('--speed', type=float, default=0.85, help='Melo 语速(<1 更慢)')
    ap.add_argument('--pause', type=float, default=0.30, help='句间静音(秒)')
    a = ap.parse_args()

    sents = split_sentences(a.text)
    work = tempfile.mkdtemp(prefix='voice-')
    try:
        pieces = []
        used = []
        for i, s in enumerate(sents):
            w = os.path.join(work, f's{i}.wav')
            engine = a.engine
            if engine in ('auto', 'edge'):
                try:
                    synth_edge(s, w, a.voice, a.rate, a.pitch)
                    engine = 'edge'
                except Exception as e:
                    if engine == 'edge':
                        raise
                    print(f'  ! edge 失败,回落 melo:{e}', file=sys.stderr)
                    synth_melo(s, w, a.speed)
                    engine = 'melo'
            elif engine == 'melo':
                synth_melo(s, w, a.speed)
            trim_silence(w)
            used.append(engine)
            pieces.append((s, w))

        gap = os.path.join(work, 'gap.wav')
        run(['ffmpeg', '-y', '-loglevel', 'error',
             '-f', 'lavfi', '-i', f'anullsrc=r={SR}:cl=mono',
             '-t', f'{a.pause:.3f}', '-c:a', 'pcm_s16le', gap])

        lst = os.path.join(work, 'list.txt')
        seq = []
        for i, (_, w) in enumerate(pieces):
            seq.append(w)
            if i < len(pieces) - 1:
                seq.append(gap)
        with open(lst, 'w') as f:
            for p in seq:
                f.write(f"file '{p}'\n")

        raw = os.path.join(work, 'raw.wav')
        run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
             '-i', lst, '-c', 'copy', raw])
        post_process(raw, a.out)

        # 每句起止 = 实测句长 + 实测停顿,逐句累加 —— 不是估算
        d = probe_dur(a.out)
        out = []
        cur = 0.0
        for i, (text, w) in enumerate(pieces):
            sd = probe_dur(w)
            out.append({'text': text,
                        'startSec': round(cur, 3),
                        'endSec': round(cur + sd, 3),
                        'engine': used[i]})
            cur += sd
            if i < len(pieces) - 1:
                cur += probe_dur(gap)

        print(json.dumps({'durationSec': round(d, 3),
                          'engine': '+'.join(sorted(set(used))),
                          'sentences': out}, ensure_ascii=False))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
