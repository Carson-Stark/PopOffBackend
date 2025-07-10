"""
Utility script to process videos by converting them to HLS format and uploading to AWS S3.

This script connects to the PostgreSQL database using environment variables for credentials,
fetches video records with .mp4 files, downloads them from S3, converts to HLS using ffmpeg,
uploads the HLS files back to S3, and updates the database with new paths.

Usage:
    python video_convert.py
"""

import os
import subprocess
import psycopg2
import boto3
from decouple import config

DB_CONFIG = {
    "host": config('DB_HOST', default='database-1.c9k6y8qk8zdq.us-east-2.rds.amazonaws.com'),
    "dbname": config('DB_NAME', default='popoffdb'),
    "user": config('DB_USER', default='postgres'),
    "password": config('DB_PASSWORD', default='replace-this-with-your-db-password'),
    "port": int(config('DB_PORT', default='5432'))
}

S3_BUCKET = "byteverse"
HLS_OUTPUT_PREFIX = "hls"  # where to upload new HLS videos
CLOUDFRONT_URL = f"https://{S3_BUCKET}.s3.us-east-2.amazonaws.com"
TMP_DIR = "./tmp_video"
TABLE_NAME = "api_postrecord"
VIDEO_ID_FIELD = "video_id"
VIDEO_FILE_PATH_FIELD = "file_path"  # originally the .mp4
VIDEO_LINK_FIELD = "link"  # public full URL

os.makedirs(TMP_DIR, exist_ok=True)

s3 = boto3.client('s3')

def get_videos_to_process():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute(
        f"SELECT {VIDEO_ID_FIELD}, {VIDEO_FILE_PATH_FIELD} FROM {TABLE_NAME} WHERE {VIDEO_FILE_PATH_FIELD} LIKE '%.mp4'"
    )
    results = cur.fetchall()
    cur.close()
    conn.close()
    return results

def update_video_record(video_id, s3_key, public_url):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute(
        f"""
        UPDATE {TABLE_NAME}
        SET {VIDEO_FILE_PATH_FIELD} = %s,
            {VIDEO_LINK_FIELD} = %s
        WHERE {VIDEO_ID_FIELD} = %s
        """,
        (s3_key, public_url, video_id)
    )
    conn.commit()
    cur.close()
    conn.close()

def download_from_s3(s3_key, local_path):
    s3.download_file(S3_BUCKET, s3_key, local_path)

def upload_directory_to_s3(local_dir, s3_prefix):
    for root, _, files in os.walk(local_dir):
        for file in files:
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, local_dir)
            s3_key = f"{s3_prefix}/{rel_path}"
            s3.upload_file(full_path, S3_BUCKET, s3_key)

def convert_to_hls(input_path, output_dir, base_name):
    output_path = os.path.join(output_dir, f"{base_name}.m3u8")
    subprocess.run([
        "ffmpeg", "-i", input_path,
        "-profile:v", "baseline", "-level", "3.0", "-start_number", "0",
        "-hls_time", "10", "-hls_list_size", "0", "-f", "hls",
        output_path
    ], check=True)

def process_video(video_id, file_path):
    print(f"\n▶️  Processing video {video_id}: {file_path}")
    base_name = os.path.basename(file_path).replace(".mp4", "")
    input_path = os.path.join(TMP_DIR, f"{base_name}.mp4")
    output_dir = os.path.join(TMP_DIR, base_name)
    s3_output_prefix = f"{HLS_OUTPUT_PREFIX}/{base_name}"
    m3u8_key = f"{s3_output_prefix}/{base_name}.m3u8"
    public_url = f"{CLOUDFRONT_URL}/{m3u8_key}"

    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Download original .mp4
    download_from_s3(file_path, input_path)

    # Step 2: Convert to HLS
    convert_to_hls(input_path, output_dir, base_name)

    # Step 3: Upload all output files to S3
    upload_directory_to_s3(output_dir, s3_output_prefix)

    # Step 4: Update DB
    update_video_record(video_id, m3u8_key, public_url)

    # Step 5: Cleanup
    os.remove(input_path)
    for f in os.listdir(output_dir):
        os.remove(os.path.join(output_dir, f))
    os.rmdir(output_dir)

    print(f"✅ Updated video {video_id} → {public_url}")

def main():
    videos = get_videos_to_process()
    print(f"🧠 Found {len(videos)} videos to process.")

    for video_id, file_path in videos:
        try:
            process_video(video_id, file_path)
        except Exception as e:
            print(f"❌ Error processing video {video_id}: {e}")

if __name__ == "__main__":
    main()
