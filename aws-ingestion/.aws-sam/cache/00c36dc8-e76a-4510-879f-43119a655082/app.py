"""Track 1 - Video Frame Extractor Lambda
Invoked by ingest-trigger after dedup passes (for videos only).
Downloads the raw video, extracts 1 frame per second using ffmpeg,
uploads each frame to the frames bucket, returns the list.

Rubric line: 2.1.2 — extracts 1 frame per second (NOT all frames).

Input event:
{
  "src_bucket": "ecolens-raw-...",
  "src_key": "uploads/{user_sub}/{file_id}.mp4",
  "file_id": "uuid",
  "owner_sub": "...",
}

Returns:
{
  "frames": [
    {"second": 0, "s3_key": "frames/{file_id}/0000.jpg", "s3_bucket": "..."},
    {"second": 1, "s3_key": "frames/{file_id}/0001.jpg", "s3_bucket": "..."},
    ...
  ],
  "count": N,
}
"""
import os
import json
import shutil
import subprocess
import boto3

import imageio_ffmpeg

s3 = boto3.client("s3")

FRAMES_BUCKET = os.environ["FRAMES_BUCKET"]
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def extract_frames(local_video, frames_dir):
    """Run ffmpeg to extract 1 frame per second into frames_dir."""
    os.makedirs(frames_dir, exist_ok=True)
    out_pattern = os.path.join(frames_dir, "frame_%04d.jpg")

    # -y      : overwrite if exists (Lambda /tmp may be reused across invocations)
    # -i      : input video
    # -vf fps=1 : video filter — 1 frame per second
    # -q:v 3  : JPEG quality (1=best, 31=worst; 3 is high quality)
    cmd = [FFMPEG, "-y", "-i", local_video, "-vf", "fps=1", "-q:v", "3", out_pattern]
    print("Running:", " ".join(cmd))

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        # ffmpeg writes progress to stderr even on success, so only log on failure
        print("ffmpeg stderr:", proc.stderr[-2000:])
        raise RuntimeError(f"ffmpeg failed with code {proc.returncode}")

    return sorted(os.listdir(frames_dir))


def lambda_handler(event, context):
    print("VIDEO_FRAMES EVENT:", json.dumps(event))

    src_bucket = event["src_bucket"]
    src_key = event["src_key"]
    file_id = event["file_id"]

    # Local paths in Lambda /tmp (ephemeral storage)
    ext = src_key.rsplit(".", 1)[-1]
    local_video = f"/tmp/{file_id}.{ext}"
    frames_dir = f"/tmp/frames_{file_id}"

    try:
        # 1. Download the video from S3
        print(f"Downloading s3://{src_bucket}/{src_key}")
        s3.download_file(src_bucket, src_key, local_video)
        size_mb = os.path.getsize(local_video) / (1024 * 1024)
        print(f"Downloaded {size_mb:.1f} MB")

        # 2. Extract frames at 1 fps
        frame_files = extract_frames(local_video, frames_dir)
        print(f"Extracted {len(frame_files)} frames")

        # 3. Upload each frame to frames bucket
        # ffmpeg names them frame_0001.jpg, frame_0002.jpg, ...
        # We name them by second (0-indexed): 0000.jpg, 0001.jpg, ...
        frames = []
        for fname in frame_files:
            # frame_NNNN.jpg → second = NNNN - 1
            try:
                idx = int(fname.split("_")[1].split(".")[0])
            except (IndexError, ValueError):
                continue
            second = idx - 1
            frame_key = f"frames/{file_id}/{second:04d}.jpg"
            local_path = os.path.join(frames_dir, fname)
            s3.upload_file(
                local_path, FRAMES_BUCKET, frame_key,
                ExtraArgs={"ContentType": "image/jpeg"},
            )
            frames.append({
                "second": second,
                "s3_bucket": FRAMES_BUCKET,
                "s3_key": frame_key,
            })

        print(f"Uploaded {len(frames)} frames to s3://{FRAMES_BUCKET}/frames/{file_id}/")
        return {"frames": frames, "count": len(frames)}

    finally:
        # 4. Cleanup /tmp so subsequent invocations on the same container start clean
        for path in (local_video, frames_dir):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                elif os.path.exists(path):
                    os.remove(path)
            except OSError as e:
                print(f"Cleanup warning for {path}: {e}")
