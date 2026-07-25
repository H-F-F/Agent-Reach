#!/bin/bash
# 小宇宙播客转文字脚本
# 用法: bash transcribe.sh [--polish] <小宇宙链接> [输出文件路径]
# 环境变量: GROQ_API_KEY (必须)
#
# --polish: 转录后调用 Groq Llama 3.3 70B 给文稿补中文标点+合理分段
#           （Whisper 对中文标点支持较弱，开启后阅读体验显著更好）

set -euo pipefail

MAX_PAGE_BYTES=$((5 * 1024 * 1024))
MAX_AUDIO_BYTES=$((512 * 1024 * 1024))
MAX_AUDIO_SECONDS=$((4 * 60 * 60))
MAX_CHUNKS=24
MAX_API_RESPONSE_BYTES=$((16 * 1024 * 1024))
CURL_CONNECT_TIMEOUT=10
CURL_PAGE_TIMEOUT=60
CURL_AUDIO_TIMEOUT=1800
CURL_API_TIMEOUT=180
FFPROBE_TIMEOUT=30

POLISH=0
while [ $# -gt 0 ]; do
    case "$1" in
        --polish) POLISH=1; shift ;;
        --) shift; break ;;
        -h|--help)
            echo "用法: bash transcribe.sh [--polish] <小宇宙链接> [输出文件路径]"
            exit 0 ;;
        --*)
            echo "未知选项: $1" >&2
            exit 1 ;;
        *) break ;;
    esac
done

URL="${1:?用法: bash transcribe.sh [--polish] <小宇宙链接> [输出文件路径]}"
OUTPUT="${2:-/tmp/podcast_transcript.txt}"

case "$URL" in
    https://www.xiaoyuzhoufm.com/episode/*|https://xiaoyuzhoufm.com/episode/*) ;;
    *)
        echo "❌ 请输入小宇宙官方 HTTPS 节目链接" >&2
        exit 1
        ;;
esac

for binary in curl perl python3 ffprobe ffmpeg; do
    if ! command -v "$binary" >/dev/null 2>&1; then
        echo "❌ 缺少依赖: $binary" >&2
        exit 1
    fi
done

WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/agent-reach-xiaoyuzhou.XXXXXX")
chmod 700 "$WORK_DIR"

cleanup() {
    if [ -n "${WORK_DIR:-}" ] && [ -d "$WORK_DIR" ]; then
        rm -rf -- "$WORK_DIR"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

# Try env var first, then agent-reach config.yaml
if [ -z "${GROQ_API_KEY:-}" ]; then
    CONFIG_FILE="$HOME/.agent-reach/config.yaml"
    if [ -f "$CONFIG_FILE" ]; then
        GROQ_API_KEY=$(
            CONFIG_FILE="$CONFIG_FILE" python3 <<'PY' 2>/dev/null || true
import os
from pathlib import Path

import yaml

config_file = Path(os.environ["CONFIG_FILE"])
with config_file.open(encoding="utf-8") as handle:
    config = yaml.safe_load(handle) or {}
print(config.get("groq_api_key", ""))
PY
        )
    fi
fi
GROQ_API_KEY="${GROQ_API_KEY:?请设置 GROQ_API_KEY 环境变量或运行 agent-reach configure groq-key}"

# Groq API 限制: 25MB per file
MAX_CHUNK_SIZE_MB=20
AUDIO_BITRATE="64k"
AUTH_HEADER_FILE="$WORK_DIR/groq-auth-header"
printf 'Authorization: Bearer %s\n' "$GROQ_API_KEY" > "$AUTH_HEADER_FILE"
chmod 600 "$AUTH_HEADER_FILE"

echo "📻 小宇宙播客转文字"
echo "===================="

# Step 1: 提取音频 URL 和标题
echo "🔍 正在解析页面..."
PAGE=$(
    curl --fail --silent --show-error --location \
        --connect-timeout "$CURL_CONNECT_TIMEOUT" \
        --max-time "$CURL_PAGE_TIMEOUT" \
        --max-filesize "$MAX_PAGE_BYTES" \
        -- "$URL"
)
AUDIO_URL=$(echo "$PAGE" | perl -ne 'if (/(https:\/\/media\.xyzcdn\.net\/[^"]*\.(?:m4a|mp3))/i) { print "$1\n"; exit }')
TITLE=$(echo "$PAGE" | perl -ne 'if (/"title":"([^"]*)"/) { print "$1\n"; exit }')

if [ -z "$AUDIO_URL" ]; then
    echo "❌ 无法从页面提取音频链接"
    exit 1
fi

echo "📝 标题: $TITLE"
echo "🔗 音频: $AUDIO_URL"

# Step 2: 下载音频
echo "⬇️  正在下载音频..."
EXT="${AUDIO_URL##*.}"
AUDIO_PATH="$WORK_DIR/original.$EXT"
curl --fail --silent --show-error --location \
    --connect-timeout "$CURL_CONNECT_TIMEOUT" \
    --max-time "$CURL_AUDIO_TIMEOUT" \
    --max-filesize "$MAX_AUDIO_BYTES" \
    --output "$AUDIO_PATH" \
    -- "$AUDIO_URL"
AUDIO_SIZE=$(stat -c%s "$AUDIO_PATH" 2>/dev/null || stat -f%z "$AUDIO_PATH")
if [ "$AUDIO_SIZE" -gt "$MAX_AUDIO_BYTES" ]; then
    echo "❌ 音频超过 512 MiB 安全上限" >&2
    exit 1
fi
echo "📦 文件大小: $((AUDIO_SIZE / 1024 / 1024))MB"

# Step 3: 获取时长
DURATION=$(
    AUDIO_PATH="$AUDIO_PATH" \
    FFPROBE_TIMEOUT="$FFPROBE_TIMEOUT" \
    python3 <<'PY'
import math
import os
import subprocess
import sys

try:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            os.environ["AUDIO_PATH"],
        ],
        capture_output=True,
        text=True,
        timeout=int(os.environ["FFPROBE_TIMEOUT"]),
        check=False,
    )
except subprocess.TimeoutExpired:
    sys.stderr.write("❌ ffprobe 读取音频时长超时\n")
    raise SystemExit(1)

if result.returncode != 0:
    sys.stderr.write(f"❌ ffprobe 无法读取音频: {result.stderr[:200]}\n")
    raise SystemExit(1)

try:
    duration = float(result.stdout.strip())
except ValueError:
    sys.stderr.write("❌ ffprobe 返回了无效的音频时长\n")
    raise SystemExit(1)

if not math.isfinite(duration) or duration <= 0:
    sys.stderr.write("❌ 音频时长必须为正数\n")
    raise SystemExit(1)

print(math.ceil(duration))
PY
)
if [ "$DURATION" -gt "$MAX_AUDIO_SECONDS" ]; then
    echo "❌ 音频超过 4 小时时长上限" >&2
    exit 1
fi
DURATION_MIN=$((DURATION / 60))
DURATION_SEC=$((DURATION % 60))
echo "⏱️  时长: ${DURATION_MIN}分${DURATION_SEC}秒"

# Step 4: 转为低码率单声道 MP3
echo "🔄 正在转码..."
ffmpeg -y -i "$AUDIO_PATH" -t "$MAX_AUDIO_SECONDS" \
    -b:a "$AUDIO_BITRATE" -ac 1 "$WORK_DIR/mono.mp3" 2>/dev/null
MONO_SIZE=$(stat -c%s "$WORK_DIR/mono.mp3" 2>/dev/null || stat -f%z "$WORK_DIR/mono.mp3")
echo "📦 转码后: $((MONO_SIZE / 1024 / 1024))MB"

# Step 5: 按大小切片
MAX_BYTES=$((MAX_CHUNK_SIZE_MB * 1024 * 1024))

if [ "$MONO_SIZE" -le "$MAX_BYTES" ]; then
    # 不需要切片
    cp "$WORK_DIR/mono.mp3" "$WORK_DIR/chunk_0.mp3"
    NUM_CHUNKS=1
    echo "📎 无需切片"
else
    # 计算需要几个 chunk
    NUM_CHUNKS=$(( (MONO_SIZE + MAX_BYTES - 1) / MAX_BYTES ))
    if [ "$NUM_CHUNKS" -gt "$MAX_CHUNKS" ]; then
        echo "❌ 音频需要切分为 $NUM_CHUNKS 段，超过 $MAX_CHUNKS 段上限" >&2
        exit 1
    fi
    CHUNK_DURATION=$(( DURATION / NUM_CHUNKS + 10 ))  # 加 10 秒缓冲
    echo "✂️  切分为 $NUM_CHUNKS 段 (每段约 $((CHUNK_DURATION / 60)) 分钟)..."

    for ((i = 0; i < NUM_CHUNKS; i++)); do
        START=$((i * CHUNK_DURATION))
        ffmpeg -y -i "$WORK_DIR/mono.mp3" -ss "$START" -t "$CHUNK_DURATION" \
            -c copy "$WORK_DIR/chunk_${i}.mp3" 2>/dev/null
        CHUNK_BYTES=$(stat -c%s "$WORK_DIR/chunk_${i}.mp3" 2>/dev/null || stat -f%z "$WORK_DIR/chunk_${i}.mp3")
        if [ "$CHUNK_BYTES" -gt "$MAX_BYTES" ]; then
            echo "❌ 第 $((i + 1)) 段超过 ${MAX_CHUNK_SIZE_MB}MB 上限" >&2
            exit 1
        fi
        echo "   段 $((i+1))/$NUM_CHUNKS: $((CHUNK_BYTES / 1024 / 1024))MB"
    done
fi

# Step 6: 调用 Groq Whisper API 转录
echo "🎙️  正在转录 (Groq Whisper large-v3)..."

call_whisper() {
    local chunk_path="$1"
    curl --silent --show-error \
        --connect-timeout "$CURL_CONNECT_TIMEOUT" \
        --max-time "$CURL_API_TIMEOUT" \
        --max-filesize "$MAX_API_RESPONSE_BYTES" \
        --write-out "\n%{http_code}" \
        https://api.groq.com/openai/v1/audio/transcriptions \
        --header "@$AUTH_HEADER_FILE" \
        --form "file=@$chunk_path" \
        --form model="whisper-large-v3" \
        --form language="zh" \
        --form prompt="以下是一段中文普通话播客录音，请输出包含完整中文标点（，。？！：；“”‘’）的转写文本。" \
        --form response_format="text"
}

for ((i = 0; i < NUM_CHUNKS; i++)); do
    echo -n "   段 $((i+1))/$NUM_CHUNKS... "

    if ! RESPONSE=$(call_whisper "$WORK_DIR/chunk_${i}.mp3"); then
        echo "❌ API 网络请求失败"
        exit 1
    fi

    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    BODY=$(echo "$RESPONSE" | sed '$d')

    if [ "$HTTP_CODE" != "200" ]; then
        echo "❌ API 错误 (HTTP $HTTP_CODE)"
        echo "$BODY"

        # 如果是速率限制，等待后重试
        if [ "$HTTP_CODE" = "429" ]; then
            # 从错误信息中提取等待时间，默认 150 秒，最多等待 5 分钟
            WAIT_MINUTES=$(echo "$BODY" | perl -ne 'if (/in (\d+)m/) { print "$1\n"; exit }')
            WAIT_MINUTES=${WAIT_MINUTES:-2}
            case "$WAIT_MINUTES" in
                *[!0-9]*) WAIT_MINUTES=2 ;;
            esac
            WAIT_SEC=$((WAIT_MINUTES * 60 + 30))
            if [ "$WAIT_SEC" -gt 300 ]; then
                WAIT_SEC=300
            fi
            echo "   ⏳ 速率限制，等待 ${WAIT_SEC} 秒后重试..."
            sleep "$WAIT_SEC"
            if ! RESPONSE=$(call_whisper "$WORK_DIR/chunk_${i}.mp3"); then
                echo "   ❌ 重试网络请求失败"
                exit 1
            fi
            HTTP_CODE=$(echo "$RESPONSE" | tail -1)
            BODY=$(echo "$RESPONSE" | sed '$d')

            if [ "$HTTP_CODE" != "200" ]; then
                echo "   ❌ 重试失败"
                exit 1
            fi
        else
            exit 1
        fi
    fi

    echo "$BODY" > "$WORK_DIR/transcript_${i}.txt"
    CHARS=$(wc -m < "$WORK_DIR/transcript_${i}.txt")
    echo "✅ ($CHARS 字)"
done

# Step 6.5 (可选): 用 Llama 3.3 70B 给文稿补标点+分段
if [ "$POLISH" = "1" ]; then
    echo "✨ 正在润色（Llama 3.3 70B 加标点+分段）..."
    for ((i = 0; i < NUM_CHUNKS; i++)); do
        echo -n "   段 $((i+1))/$NUM_CHUNKS... "
        IN_FILE="$WORK_DIR/transcript_${i}.txt" \
        OUT_FILE="$WORK_DIR/polished_${i}.txt" \
        GROQ_API_KEY="$GROQ_API_KEY" \
        python3 <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

KEY = os.environ["GROQ_API_KEY"]
IN_FILE = Path(os.environ["IN_FILE"])
OUT_FILE = Path(os.environ["OUT_FILE"])

MODEL = "llama-3.3-70b-versatile"
MAX_DEPTH = 3
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
PROMPT_TMPL = (
    "以下是一段中文普通话播客的语音转写片段，由于 Whisper 对中文标点支持较弱，"
    "整段几乎没有标点。请你**只做一件事**：在合适位置补充中文标点（，。！？：；），"
    "可以适度分段。\n\n"
    "**严格要求**：\n"
    "- 不得修改、删除、增加任何汉字或英文/数字\n"
    "- 不得改写、润色、总结\n"
    "- 不得添加任何解释、前言、后记\n"
    "- 直接输出加好标点+合理分段后的全文\n\n"
    "原文：\n{}"
)

def call_groq(text):
    body = json.dumps({
        "model": MODEL,
        "temperature": 0.2,
        "max_completion_tokens": 8192,
        "messages": [{"role": "user", "content": PROMPT_TMPL.format(text)}],
    }).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {KEY}",
            "Content-Type": "application/json",
            "User-Agent": "agent-reach-xiaoyuzhou/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("polish response exceeds 4 MiB safety limit")
    resp = json.loads(raw)
    return (
        resp["choices"][0]["message"]["content"].strip(),
        resp["choices"][0].get("finish_reason"),
    )

def polish(text, depth=0):
    try:
        out, fr = call_groq(text)
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"polish HTTP {e.code}: {e.read().decode(errors='replace')[:200]}\n")
        return text  # fallback to raw
    except Exception as e:
        sys.stderr.write(f"polish error: {e}\n")
        return text
    if fr != "length" or depth >= MAX_DEPTH:
        return out
    # 输出被截断：从中点切两半递归处理
    mid = len(text) // 2
    return polish(text[:mid], depth + 1) + polish(text[mid:], depth + 1)

content = IN_FILE.read_text(encoding="utf-8").strip()
result = polish(content)
OUT_FILE.write_text(result + "\n", encoding="utf-8")
print(f"✅ ({len(result)} 字)")
PY
    done
fi

# Step 7: 合并输出
echo "📄 正在合并文字稿..."

{
    echo "# $TITLE"
    echo ""
    echo "来源: $URL"
    echo "时长: ${DURATION_MIN}分${DURATION_SEC}秒"
    echo "转录时间: $(date '+%Y-%m-%d %H:%M')"
    if [ "$POLISH" = "1" ]; then
        echo "润色: Groq Llama 3.3 70B"
    fi
    echo ""
    echo "---"
    echo ""

    for ((i = 0; i < NUM_CHUNKS; i++)); do
        if [ "$POLISH" = "1" ] && [ -f "$WORK_DIR/polished_${i}.txt" ]; then
            cat "$WORK_DIR/polished_${i}.txt"
        else
            cat "$WORK_DIR/transcript_${i}.txt"
        fi
        echo ""
    done
} > "$OUTPUT"

TOTAL_CHARS=$(wc -m < "$OUTPUT")
echo ""
echo "✅ 完成！"
echo "📄 输出: $OUTPUT"
echo "📊 总字数: $TOTAL_CHARS"
echo "===================="
