#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MOSS-TTS-Nano 本地一键部署（moss-tts-nano-deploy 技能主脚本）

用法：
    python deploy.py                # 完整部署
    python deploy.py --dry-run      # 只检查并打印计划
    python deploy.py --skip-pip --skip-models   # 只做克隆+补丁+启动脚本

部署产物（全部在本脚本所在目录下）：
    MOSS-TTS-Nano/          官方仓库（git clone）
    venv/                   独立 Python 环境
    启动朗读演示.bat         网页版启动脚本（自动开浏览器）
    bin/moss-tts.py         命令行包装（--text/--text-file/--voice/--list-voices）

只依赖 Python 标准库；requests 在装依赖步骤后可用（模型下载用）。
"""
import argparse
import os
import subprocess
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 技能根目录（scripts/ 的上级）
REPO = os.path.join(SKILL_DIR, "MOSS-TTS-Nano")
VENV_DIR = os.path.join(SKILL_DIR, "venv")
REPO_URL = "https://github.com/OpenMOSS/MOSS-TTS-Nano.git"
# GitHub 直连失败时的备用镜像（国内常用）
REPO_URL_MIRRORS = [
    "https://gh-proxy.com/https://github.com/OpenMOSS/MOSS-TTS-Nano.git",
    "https://gitclone.com/github.com/OpenMOSS/MOSS-TTS-Nano",
]
PY_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
HF_MIRROR = "https://hf-mirror.com"

MODEL_REPOS = [
    ("OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX", "MOSS-TTS-Nano-100M-ONNX",
     "browser_poc_manifest.json"),
    ("OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX", "MOSS-Audio-Tokenizer-Nano-ONNX",
     "codec_browser_onnx_meta.json"),
]

PIP_TORCH = ["torch==2.7.0", "torchaudio==2.7.0"]
PIP_PACKAGES = [
    "numpy>=1.24", "fastapi>=0.110.0", "python-multipart>=0.0.9",
    "sentencepiece>=0.1.99", "transformers==4.57.1", "uvicorn>=0.29.0",
    "soundfile", "onnxruntime>=1.20.0", "huggingface_hub", "requests",
]

BAT_TEMPLATE = """@echo off
title MOSS-TTS-Nano TTS Server - KEEP THIS WINDOW OPEN
start "" "http://127.0.0.1:18083"
"{python}" "{app}"
pause
"""

WRAPPER_TEMPLATE = '''#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""moss-tts.py —— MOSS-TTS-Nano 命令行包装。必须用 venv 的 python 运行。"""
import json
import os
import subprocess
import sys

REPO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "MOSS-TTS-Nano")
MANIFEST = os.path.join(REPO, "models", "MOSS-TTS-Nano-100M-ONNX", "browser_poc_manifest.json")


def list_voices() -> None:
    with open(MANIFEST, encoding="utf-8") as f:
        voices = json.load(f)["builtin_voices"]
    for v in voices:
        print(v["voice"])
    print(f"（共 {len(voices)} 个内置音色；默认 Junhao。也可用 --prompt-audio-path 参考音频克隆音色）")


def main() -> None:
    args = sys.argv[1:]
    if "--list-voices" in args:
        list_voices()
        return
    while "-o" in args:
        i = args.index("-o")
        args[i:i + 2] = ["--output-audio-path"] + ([args[i + 1]] if i + 1 < len(args) else [])
    for flag in ("--text-file", "--output-audio-path", "--prompt-audio-path"):
        if flag in args:
            i = args.index(flag)
            if i + 1 < len(args) and not os.path.isabs(args[i + 1]):
                args[i + 1] = os.path.abspath(args[i + 1])
    if "--enable-wetext-processing" not in args and "--disable-wetext-processing" not in args:
        args.append("--disable-wetext-processing")
    if not any(a in ("--text", "--text-file") for a in args):
        print("用法: python moss-tts.py --text \\"文字\\" [-o 输出.wav] [--voice 音色名]")
        print("      python moss-tts.py --text-file 文章.txt -o 朗读版.wav")
        print("      python moss-tts.py --list-voices")
        sys.exit(2)
    sys.exit(subprocess.call([sys.executable, os.path.join(REPO, "infer_onnx.py"), *args], cwd=REPO))


if __name__ == "__main__":
    main()
'''

# ---------------- patches ----------------
PATCH_TNP_OLD = """    if enable_wetext:
        if text_normalizer_manager is None:
            raise RuntimeError("WeTextProcessing manager is unavailable.")
"""
PATCH_TNP_NEW = """    wetext_manager_ready = False
    if enable_wetext and text_normalizer_manager is not None:
        try:
            wetext_manager_ready = text_normalizer_manager.ensure_ready().ready
        except Exception as exc:  # manager itself failed; degrade gracefully
            logging.warning("WeTextProcessing manager check failed: %s", exc)
    if enable_wetext and not wetext_manager_ready:
        # WeTextProcessing 未安装（Windows 无 pynini wheel）时不再中断合成，
        # 降级为仅 robust 文本规整（moss-tts-nano-deploy 补丁）。
        logging.warning(
            "WeTextProcessing unavailable, skipping wetext normalization (robust normalizer only)."
        )
        enable_wetext = False

    if enable_wetext:
"""

PATCH_APP_OLD = """                normalization_snapshot = self.text_normalizer_manager.ensure_ready()
                if normalization_snapshot.failed:
                    raise RuntimeError(normalization_snapshot.error or normalization_snapshot.message)
"""
PATCH_APP_NEW = """                normalization_snapshot = self.text_normalizer_manager.ensure_ready()
                if normalization_snapshot.failed:
                    # WeTextProcessing 未安装（Windows 无 pynini wheel）时不再让预热失败，
                    # 降级为仅 robust 文本规整继续服务（moss-tts-nano-deploy 补丁）。
                    logging.warning(
                        "WeTextProcessing unavailable, warmup continues without it: %s",
                        normalization_snapshot.error or normalization_snapshot.message,
                    )
"""

ZH_REPLACEMENTS = [
    ("<title>MOSS-TTS-Nano ONNX Demo</title>", "<title>MOSS-TTS-Nano 语音合成</title>"),
    ('<button class="top-tab active" type="button" aria-selected="true">Voice Clone</button>',
     '<button class="top-tab active" type="button" aria-selected="true">音色克隆朗读</button>'),
    ("<strong>Voice Clone</strong>", "<strong>音色克隆朗读</strong>"),
    (">Demo</label>", ">演示音频</label>"),
    ('<label for="prompt-audio-upload">Prompt Speech</label>', '<label for="prompt-audio-upload">参考音频（可选，克隆音色用）</label>'),
    ('<label for="text">Text</label>', '<label for="text">要念的文字</label>'),
    ('<label for="max-new-frames">Max New Frames</label>', '<label for="max-new-frames">单段长度上限（帧）</label>'),
    ("Voice Clone Max Text Tokens", "音色克隆分块大小"),
    ("Max TTS Batch Size (0=auto)", "TTS 批大小（0=自动）"),
    ("Max Codec Batch Size (0=auto)", "编解码批大小（0=自动）"),
    ("CPU Threads", "CPU 线程数"),
    ("Sampling Mode", "采样模式"),
    (">Seed</label>", ">随机种子</label>"),
    ("Text Temperature", "文本温度"),
    ("Audio Temperature", "音频温度"),
    ("Audio Repetition Penalty", "音频重复惩罚"),
    ("Do Sample (derived from Sampling Mode)", "随机采样（跟随采样模式）"),
    (" Enable WeTextProcessing</label>", " 文本智能规整（本机未启用，内置规整已生效）</label>"),
    ("Enable normalize_tts_text", "基础文本清理"),
    ("Realtime Streaming Decode", "实时流式播放"),
    ("Initial Playback Delay (s)", "起播延迟（秒）"),
    ('<button id="generate-btn" type="button">Generate</button>', '<button id="generate-btn" type="button">开始合成</button>'),
    ("Pause Playback", "暂停播放"),
    ("Refresh Warmup Status", "刷新状态"),
    ("Warmup Status", "服务状态"),
    ("Text Normalization Status", "文本规整状态"),
    ("Run Status", "运行状态"),
    ("Normalized Text", "规整后的文本"),
    ("Playback Script", "朗读稿"),
    ("Generated Speech", "合成音频"),
]
PATCH_MARK = "moss-tts-nano-deploy 补丁"


def say(msg: str) -> None:
    print(msg, flush=True)


def venv_python() -> str:
    return os.path.join(VENV_DIR, "Scripts", "python.exe") if os.name == "nt" else os.path.join(VENV_DIR, "bin", "python")


def step_clone(args: argparse.Namespace) -> None:
    if os.path.isdir(os.path.join(REPO, ".git")):
        say("1/7 仓库已存在，跳过 clone")
        return
    say(f"1/7 克隆官方仓库 {REPO_URL} ...")
    if args.dry_run:
        return
    for url in [REPO_URL, *REPO_URL_MIRRORS]:
        try:
            subprocess.check_call(["git", "clone", "--depth", "1", url, REPO])
            return
        except subprocess.CalledProcessError:
            say(f"  clone 失败（{url}），尝试下一个源...")
    raise SystemExit("[错误] 所有克隆源均失败，请检查网络后重试")


def step_venv(args: argparse.Namespace) -> None:
    if os.path.isfile(venv_python()):
        say("2/7 venv 已存在，跳过")
        return
    say("2/7 创建独立 Python 环境（venv）...")
    if not args.dry_run:
        subprocess.check_call([sys.executable, "-m", "venv", VENV_DIR])


def step_pip(args: argparse.Namespace) -> None:
    if args.skip_pip:
        say("3/4 跳过依赖安装（--skip-pip）")
        return
    say("3/7 安装依赖（清华镜像，首次 10~20 分钟）...")
    if args.dry_run:
        return
    subprocess.check_call([venv_python(), "-m", "pip", "install", "-U", "pip", "-i", PY_MIRROR])
    for packages in (PIP_TORCH, PIP_PACKAGES):
        subprocess.check_call([venv_python(), "-m", "pip", "install", *packages, "-i", PY_MIRROR])


def step_models(args: argparse.Namespace) -> None:
    if args.skip_models:
        say("4/7 跳过模型下载（--skip-models）")
        return
    say("4/7 检查模型文件...")
    for repo_id, local_name, sentinel in MODEL_REPOS:
        out_dir = os.path.join(REPO, "models", local_name)
        if os.path.isfile(os.path.join(out_dir, sentinel)):
            say(f"  {local_name}: 已存在，跳过")
            continue
        import requests

        session = requests.Session()
        say(f"  {local_name}: 从 {HF_MIRROR} 下载...")
        if args.dry_run:
            continue
        os.makedirs(out_dir, exist_ok=True)
        tree = session.get(f"{HF_MIRROR}/api/models/{repo_id}/tree/main", timeout=60).json()
        for item in tree:
            name = item["path"]
            if name.startswith("."):
                continue
            dst = os.path.join(out_dir, name)
            say(f"    下载 {name}（{item.get('size', 0) // 1024 // 1024}MB）")
            with session.get(f"{HF_MIRROR}/{repo_id}/resolve/main/{name}", stream=True, timeout=600) as r:
                r.raise_for_status()
                with open(dst, "wb") as w:
                    for chunk in r.iter_content(1 << 20):
                        w.write(chunk)


def apply_patch(path: str, old: str, new: str, label: str, args: argparse.Namespace) -> None:
    with open(path, encoding="utf-8") as f:
        content = f.read()
    if PATCH_MARK in content and label == "zh":
        say(f"  {os.path.basename(path)}: 补丁已存在，跳过")
        return
    if old not in content:
        if label == "zh" or new in content:
            say(f"  {os.path.basename(path)}: 补丁已存在，跳过")
            return
        raise SystemExit(f"[错误] {path} 内容与预期不符，补丁应用失败（上游代码可能已更新）")
    say(f"  {os.path.basename(path)}: 应用{label}补丁")
    if not args.dry_run:
        with open(path, "w", encoding="utf-8") as w:
            w.write(content.replace(old, new, 1))


def step_patches(args: argparse.Namespace) -> None:
    say("5/7 打 Windows 兼容补丁（幂等）...")
    if not os.path.isfile(os.path.join(REPO, "text_normalization_pipeline.py")):
        raise SystemExit(f"[错误] 仓库不完整：{REPO}")
    apply_patch(os.path.join(REPO, "text_normalization_pipeline.py"), PATCH_TNP_OLD, PATCH_TNP_NEW, "wetext 降级", args)
    apply_patch(os.path.join(REPO, "app.py"), PATCH_APP_OLD, PATCH_APP_NEW, "预热降级", args)
    zh_block = (
        "    # 中文界面（moss-tts-nano-deploy 补丁）：把主要界面文案替换为中文\n"
        "    zh_replacements = " + repr(ZH_REPLACEMENTS) + "\n"
        "    for old, new in zh_replacements:\n"
        "        html = html.replace(old, new)\n"
        "    return html"
    )
    path = os.path.join(REPO, "app_onnx.py")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    if "zh_replacements" in content:
        say("  app_onnx.py: 中文界面补丁已存在，跳过")
    else:
        anchor = "        1,\n    )\n    return html"
        if anchor not in content:
            raise SystemExit("[错误] app_onnx.py 内容与预期不符（上游代码可能已更新）")
        say("  app_onnx.py: 应用中文界面补丁")
        if not args.dry_run:
            with open(path, "w", encoding="utf-8") as w:
                w.write(content.replace(anchor, "        1,\n    )\n" + zh_block, 1))


def step_products(args: argparse.Namespace) -> None:
    say("6/7 生成启动脚本...")
    if os.name == "nt":
        bat = BAT_TEMPLATE.format(python=venv_python(), app=os.path.join(REPO, "app_onnx.py"))
        dst = os.path.join(SKILL_DIR, "启动朗读演示.bat")
        say(f"  生成 {dst}")
        if not args.dry_run:
            with open(dst, "w", encoding="ascii") as w:
                w.write(bat)
    bin_dir = os.path.join(SKILL_DIR, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    wrapper = os.path.join(bin_dir, "moss-tts.py")
    say(f"  生成 {wrapper}")
    if not args.dry_run:
        with open(wrapper, "w", encoding="utf-8") as w:
            w.write(WRAPPER_TEMPLATE)


def step_verify(args: argparse.Namespace) -> None:
    say("7/7 验证（编译检查 + 音色列表）...")
    if not os.path.isfile(venv_python()):
        say("  （未装依赖，跳过运行验证）")
        return
    if not args.dry_run:
        for rel in ("infer_onnx.py", "app_onnx.py", "app.py", "text_normalization_pipeline.py"):
            subprocess.check_call([venv_python(), "-m", "py_compile", os.path.join(REPO, rel)])
        manifest = os.path.join(REPO, "models", "MOSS-TTS-Nano-100M-ONNX", "browser_poc_manifest.json")
        if os.path.isfile(manifest):
            subprocess.check_call([venv_python(), os.path.join(SKILL_DIR, "bin", "moss-tts.py"), "--list-voices"])
        else:
            say("  （模型未下载，跳过音色列表验证）")


def main() -> int:
    parser = argparse.ArgumentParser(description="MOSS-TTS-Nano 一键部署")
    parser.add_argument("--dry-run", action="store_true", help="只检查并打印计划")
    parser.add_argument("--skip-pip", action="store_true", help="跳过依赖安装")
    parser.add_argument("--skip-models", action="store_true", help="跳过模型下载")
    args = parser.parse_args()

    say("== MOSS-TTS-Nano 本地部署 ==")
    if args.dry_run:
        say("（dry-run 模式：只检查，不改动）")
    step_clone(args)
    step_venv(args)
    step_pip(args)
    step_models(args)
    step_patches(args)
    step_products(args)
    step_verify(args)
    say("== 部署完成 ==")
    say("网页版：双击 启动朗读演示.bat（黑窗口别关）")
    say("命令行：<venv python> bin/moss-tts.py --text-file 文章.txt -o 朗读.wav")
    return 0


if __name__ == "__main__":
    sys.exit(main())
