#!/bin/bash

# Function to check if a video is already compressed (libx264, no audio)
is_likely_compressed() {
    local input="$1"

    local has_audio
    has_audio=$(ffprobe -v error -select_streams a -show_entries stream=codec_type -of csv=p=0 "$input")

    local video_codec
    video_codec=$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of default=noprint_wrappers=1:nokey=1 "$input")

    local encoder
    encoder=$(ffprobe -v error -select_streams v:0 -show_entries format_tags=encoder -of default=nokey=1:noprint_wrappers=1 "$input")

    # You can adjust this logic if needed
    if [[ "$video_codec" == "h264" && -z "$has_audio" && "$encoder" == *"Lavf"* ]]; then
        return 0  # already compressed
    else
        return 1  # needs compression
    fi
}

# Function to compress and replace the original file
compress_and_replace() {
    local input="$1"
    local crf="${2:-28}"

    local dir
    dir=$(dirname "$input")
    local filename
    filename=$(basename "$input")
    
    # Create a unique temp file in the same directory
    local tmp_output
    tmp_output=$(mktemp --tmpdir="$dir" "tmp_${filename}.XXXXXX.mp4")

    echo "Compressing: $input"
    if ffmpeg -y -i "$input" -vcodec libx264 -crf "$crf" -preset slow -an -movflags +faststart "$tmp_output"; then
        mv "$tmp_output" "$input"
        echo "✅ Replaced original with compressed: $input"
    else
        echo "❌ Compression failed for $input"
        rm -f "$tmp_output"
    fi
}

# Main loop: find all .mp4 files
export -f is_likely_compressed
export -f compress_and_replace

find . -type f -iname "*.mp4" -exec bash -c '
    for file; do
        echo "🔍 Checking: $file"
        if is_likely_compressed "$file"; then
            echo "➡️ Already compressed, skipping."
        else
            compress_and_replace "$file" 28
        fi
        echo ""
    done
' _ {} +
