#!/bin/zsh
# Raw demo footage: one clip per take, 1920x1080 @ 30 fps H.264, cursor and clicks shown, no audio (set BIZOS_MIC=0 to record the microphone too).
#   demo/record.sh start 03-ask-and-plan     start a clip (returns immediately)
#   demo/record.sh stop                      finish it cleanly (the file is only valid after this)
#   demo/record.sh list                      clips so far, with duration and size
# Needs Screen Recording permission for the terminal app that runs it (System Settings > Privacy & Security).
# Files go to ~/Movies/bizos-demo-raw (override with BIZOS_RAW_DIR); times are logged to clips.log for the editor.
OUT="${BIZOS_RAW_DIR:-$HOME/Movies/bizos-demo-raw}"
PIDFILE="$OUT/.recording"
mkdir -p "$OUT"

# The screen is 16:10; crop a 16:9 band below the menu bar (menu bar = 80 px of the 1800 px Retina height).
FILTER="crop=iw:iw*9/16:0:80,scale=1920:1080:flags=lanczos"

screen_index() {  # avfoundation numbers cameras first; find "Capture screen 0" by name
  ffmpeg -hide_banner -f avfoundation -list_devices true -i "" 2>&1 | sed -n 's/.*\[\([0-9]*\)\] Capture screen 0.*/\1/p' | head -1
}

case "$1" in
  start)
    [[ -n "$2" ]] || { echo "usage: $0 start <clip-name>"; exit 1; }
    [[ -f "$PIDFILE" ]] && { echo "already recording: $(cut -d' ' -f2- "$PIDFILE")"; exit 1; }
    name="$(date +%H%M%S)-$2"; file="$OUT/$name.mp4"
    idx="$(screen_index)"; [[ -n "$idx" ]] || { echo "no screen capture device"; exit 1; }
    # BIZOS_MIC=<audio device index> also records that microphone (list: ffmpeg -f avfoundation -list_devices true -i ""); default: no audio
    audio=(-an); src="$idx:none"
    [[ -n "$BIZOS_MIC" ]] && { src="$idx:$BIZOS_MIC"; audio=(-c:a aac -b:a 160k -ar 48000); }
    ffmpeg -hide_banner -loglevel error -y -f avfoundation -framerate 30 -capture_cursor 1 -capture_mouse_clicks 1 \
      -pixel_format uyvy422 -i "$src" -vf "$FILTER" -r 30 -c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p \
      "${audio[@]}" -movflags +faststart "$file" </dev/null >"$OUT/.ffmpeg.log" 2>&1 &
    echo "$! $file" > "$PIDFILE"
    sleep 1.5
    kill -0 "$(cut -d' ' -f1 "$PIDFILE")" 2>/dev/null || { echo "ffmpeg did not start:"; cat "$OUT/.ffmpeg.log"; rm -f "$PIDFILE"; exit 1; }
    echo "$(date '+%F %T') start $name" >> "$OUT/clips.log"; echo "recording $file" ;;
  stop)
    [[ -f "$PIDFILE" ]] || { echo "not recording"; exit 1; }
    pid="$(cut -d' ' -f1 "$PIDFILE")"; file="$(cut -d' ' -f2- "$PIDFILE")"
    kill -INT "$pid"; while kill -0 "$pid" 2>/dev/null; do sleep 0.2; done   # SIGINT lets ffmpeg finalize the file
    rm -f "$PIDFILE"; echo "$(date '+%F %T') stop  $(basename "$file")" >> "$OUT/clips.log"
    ffprobe -v error -show_entries stream=width,height,r_frame_rate:format=duration -of default=nw=1 "$file" | tr '\n' ' '; echo; echo "$file" ;;
  list)
    for f in "$OUT"/*.mp4(N); do printf "%s  %s  %s\n" "$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f" | cut -c1-5)s" "$(du -h "$f" | cut -f1)" "$(basename "$f")"; done ;;
  *) echo "usage: $0 start <name> | stop | list"; exit 1 ;;
esac
