#!/usr/bin/env bash
# «Кубик и сортер» — финальная сборка: кадры render/frames/f_%04d.png (30 fps, 450 шт.)
# + audio/mix.wav → final.mp4. Грейд direction §2.8, экспорт §8.4, проверка ffprobe/ebur128.
#
#   ./render.sh                 полный ролик → final.mp4 (нужны все 450 кадров)
#   ./render.sh --test OUTDIR   слайдшоу из 11 тестовых кадров test/f_*.png с тем же грейдом,
#                               звуком и параметрами экспорта → OUTDIR/test_slideshow.mp4
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

MODE=full
OUTDIR="$HERE"
if [[ "${1:-}" == "--test" ]]; then
  MODE=test
  OUTDIR="${2:?укажи папку для тестового вывода (не production/)}"
  mkdir -p "$OUTDIR"
fi

FPS=30
NFRAMES=450
AUDIO="audio/mix.wav"

# --- звук: если микса нет — собрать (все генераторы детерминированы, seed 2610)
if [[ ! -f "$AUDIO" ]]; then
  echo "== mix.wav нет — синтез музыки, SFX и сведение"
  (cd audio && python3 gen_music.py && python3 gen_sfx.py && python3 mix.py)
fi

# --- грейд (direction §2.8): едва заметная виньетка (PI/12, а не PI/6: у ffmpeg
# PI/6 даёт −44 % в углу — это не «едва заметно»; PI/12 ≈ −13 % в углу, −4 % у края), +4 % насыщенности, зерно 2 ед.
# (temporal, против бандинга мятного градиента), затем bt709 и yuv420p.
GRADE="scale=1080:1920:flags=lanczos,vignette=angle=PI/12,eq=saturation=1.04,noise=alls=2:allf=t,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"

ENC=(-c:v libx264 -profile:v high -preset slow -tune animation -crf 18 -pix_fmt yuv420p
     -r "$FPS" -fps_mode cfr -g 60
     -color_primaries bt709 -color_trc bt709 -colorspace bt709 -color_range tv
     -c:a aac -b:a 320k -ar 48000 -ac 2
     -movflags +faststart)

if [[ "$MODE" == full ]]; then
  have=$(ls render/frames/f_*.png 2>/dev/null | wc -l)
  if [[ "$have" -ne "$NFRAMES" ]]; then
    echo "ОШИБКА: в render/frames/ $have кадров, нужно $NFRAMES (f_0000…f_0449)." >&2
    echo "Сначала: cd render && node render.js --range 0-449" >&2
    exit 1
  fi
  OUT="$OUTDIR/final.mp4"
  ffmpeg -hide_banner -y \
    -framerate "$FPS" -start_number 0 -i render/frames/f_%04d.png \
    -i "$AUDIO" \
    -map 0:v:0 -map 1:a:0 -vf "$GRADE" -frames:v "$NFRAMES" "${ENC[@]}" -shortest "$OUT"
else
  # слайдшоу: каждый тестовый кадр держится до следующего тестового (по номеру кадра),
  # чтобы картинка шла примерно синхронно со звуком; итог — те же 15.0 с и 450 кадров
  LIST="$OUTDIR/frames.txt"
  : > "$LIST"
  mapfile -t FILES < <(ls test/f_*.png | sort)
  for i in "${!FILES[@]}"; do
    f="${FILES[$i]}"
    k=$((10#$(basename "$f" .png | sed 's/f_//')))
    if (( i + 1 < ${#FILES[@]} )); then
      kn=$((10#$(basename "${FILES[$((i+1))]}" .png | sed 's/f_//')))
    else
      kn=$NFRAMES
    fi
    echo "file '$HERE/$f'" >> "$LIST"
    echo "duration $(python3 -c "print(($kn-$k)/$FPS)")" >> "$LIST"
  done
  echo "file '$HERE/${FILES[-1]}'" >> "$LIST"
  OUT="$OUTDIR/test_slideshow.mp4"
  ffmpeg -hide_banner -y -f concat -safe 0 -i "$LIST" -i "$AUDIO" \
    -map 0:v:0 -map 1:a:0 -vf "fps=$FPS,$GRADE" -frames:v "$NFRAMES" "${ENC[@]}" "$OUT"
fi

# --- проверка
echo "== ffprobe: $OUT"
ffprobe -v error -select_streams v:0 -count_frames \
  -show_entries stream=codec_name,profile,width,height,pix_fmt,r_frame_rate,nb_read_frames,color_space,color_primaries,color_transfer \
  -of default=nw=1 "$OUT"
ffprobe -v error -select_streams a:0 \
  -show_entries stream=codec_name,sample_rate,channels,bit_rate -of default=nw=1 "$OUT"
ffprobe -v error -show_entries format=duration,size -of default=nw=1 "$OUT"

nb=$(ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=nb_read_frames -of csv=p=0 "$OUT")
w=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 "$OUT")
h=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 "$OUT")
pf=$(ffprobe -v error -select_streams v:0 -show_entries stream=pix_fmt -of csv=p=0 "$OUT")
fail=0
[[ "$nb" == "$NFRAMES" ]] || { echo "ПРОВАЛ: кадров $nb ≠ $NFRAMES"; fail=1; }
[[ "$w" == 1080 && "$h" == 1920 ]] || { echo "ПРОВАЛ: размер ${w}×${h}"; fail=1; }
[[ "$pf" == yuv420p ]] || { echo "ПРОВАЛ: pix_fmt $pf"; fail=1; }

echo "== громкость звука в $OUT (ebur128, true peak)"
ffmpeg -hide_banner -nostats -i "$OUT" -map 0:a:0 -af ebur128=peak=true -f null - 2>&1 \
  | sed -n '/Summary/,$p' | grep -E "I:|Peak:" | tee "$OUTDIR/.loud.txt"
I=$(awk '/I:/{print $2}' "$OUTDIR/.loud.txt")
TP=$(awk '/Peak:/{print $2}' "$OUTDIR/.loud.txt")
rm -f "$OUTDIR/.loud.txt"
python3 - "$I" "$TP" <<'EOF' || fail=1
import sys
i, tp = float(sys.argv[1]), float(sys.argv[2])
ok = -15.0 <= i <= -13.0 and tp <= -1.0
print(f"I = {i} LUFS (цель −14 ±1), TP = {tp} dBTP (≤ −1.0): {'OK' if ok else 'ПРОВАЛ'}")
sys.exit(0 if ok else 1)
EOF

if [[ "$MODE" == full ]]; then
  echo "== шов петли: final.mp4 × 2 → loop_check.mp4 (смотреть 14.9–15.1 с: кадр 449 → 0)"
  printf "file '%s'\nfile '%s'\n" "$OUT" "$OUT" > "$OUTDIR/.loop.txt"
  ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i "$OUTDIR/.loop.txt" -c copy "$OUTDIR/loop_check.mp4"
  rm -f "$OUTDIR/.loop.txt"
fi

[[ "$fail" == 0 ]] && echo "== ГОТОВО: $OUT" || { echo "== ЕСТЬ ПРОВАЛЫ, см. выше"; exit 1; }
