#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
command -v python3 >/dev/null 2>&1 || { echo 'Python 3 required: https://www.python.org/downloads/'; exit 1; }
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo 'FFmpeg missing. Attempting install only with an existing supported package manager.'
  if command -v brew >/dev/null 2>&1; then brew install ffmpeg
  elif command -v apt-get >/dev/null 2>&1; then
    echo 'Linux: please run sudo apt-get install ffmpeg (administrator permission required).'
    exit 1
  else
    echo 'Install ffmpeg and ffprobe before rendering: https://ffmpeg.org/download.html'
    exit 1
  fi
fi
if [ ! -e "$ROOT/.venv/bin/python" ]; then
  python3 -m venv "$ROOT/.venv" || { echo 'Python venv unavailable; install python3-venv'; exit 1; }
fi
"$ROOT/.venv/bin/python" -m pip install --disable-pip-version-check --upgrade 'Pillow>=10,<13'
echo 'READY. Use this interpreter:'
echo "  $ROOT/.venv/bin/python"
echo "Example: \"$ROOT/.venv/bin/python\" \"$ROOT/scripts/render.py\" --preview"
