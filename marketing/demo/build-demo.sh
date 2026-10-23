#!/usr/bin/env bash
# Assembles the submission video: main take → Android offline segment → closing card.
# Inputs come from record-demo.mjs, android-offline.mjs and record-android-segment.mjs.
set -euo pipefail
cd "$(dirname "$0")"
CLOSE=$(node -p "require('./raw/markers.json').close")
START=$(node -p "Math.max(0, require('./raw/android-segment.json').start - 0.2)")
ffmpeg -loglevel error -y -i raw/take.webm -i raw/android-segment.webm \
  -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000 -filter_complex "
  [0:v]trim=0:${CLOSE},setpts=PTS-STARTPTS,fps=30,scale=1280:800,setsar=1[a];
  [1:v]trim=start=${START},setpts=PTS-STARTPTS,fps=30,scale=1280:800,setsar=1[b];
  [0:v]trim=start=${CLOSE},setpts=PTS-STARTPTS,fps=30,scale=1280:800,setsar=1[c];
  [a][b][c]concat=n=3:v=1:a=0[v]" \
  -map "[v]" -map 2:a -shortest -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p \
  -c:a aac -b:a 64k -movflags +faststart utsav-demo.mp4
ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 utsav-demo.mp4 \
  | awk '{ printf "utsav-demo.mp4: %d:%02d (limit 4:00)\n", $1/60, $1%60; exit ($1 >= 240) }'
