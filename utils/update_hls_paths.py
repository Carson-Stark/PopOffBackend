"""
Utility script to update HLS video paths in the database, manage S3 file migrations, and update thumbnails to use CloudFront URLs.
"""

import boto3
import psycopg2
import os


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

HLS_PREFIX = "hls/"
TARGET_PREFIX = "videos"
# =============== #

# S3 + DB Clients
s3 = boto3.resource("s3")
bucket = s3.Bucket(S3_BUCKET)

def get_all_video_records():
    """
    Fetch all video records from the database along with associated usernames and file paths.

    Returns:
        dict: A dictionary mapping video_id (str) to a dict with keys 'username' and 'original_path'.
    """
    print("🔍 Fetching videos from DB...")
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    cur.execute("""
        SELECT p.video_id, u.username, p.file_path
        FROM api_postrecord p
        JOIN api_user u ON p.user_id = u.user_id
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    video_data = {}
    for video_id, user, file_path in rows:
        video_id = str(video_id)
        print(user)
        video_data[video_id] = {
            "username": user,
            "original_path": file_path,
        }

    print(f"✅ Retrieved {len(video_data)} video records.")
    print(video_data)
    return video_data


def update_video_path_in_db(video_id, s3_key, public_url):
    print(f"📝 Updating DB for video {video_id}")
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE api_postrecord
        SET file_path = %s,
            link = %s
        WHERE video_id = %s
        """,
        (s3_key, public_url, video_id)
    )
    conn.commit()
    cur.close()
    conn.close()


def move_hls_and_cleanup(video_data):
    print("📦 Starting HLS file migration...")

    for video_id, data in video_data.items():
        username = data["username"]
        original_key = data["original_path"]

        if not original_key:
            continue

        # Get the original directory prefix (e.g., hls/video123/)
        base_name = os.path.basename(original_key)
        video_name = os.path.splitext(base_name)[0]
        directory_prefix = "hls/" + video_name
        new_base_prefix = f"{username}/{TARGET_PREFIX}/{video_name}"

        print(f"📁 Moving all files from: {directory_prefix}/")

        # List all objects in the same directory
        objects = list(bucket.objects.filter(Prefix=f"{directory_prefix}/"))

        if not objects:
            print(f"⚠️ No files found for: {directory_prefix}/")
            continue

        for obj in objects:
            old_key = obj.key
            filename = os.path.basename(old_key)
            new_key = f"{new_base_prefix}/{filename}"

            print(f"🔁 Moving {old_key} → {new_key}")
            copy_source = {"Bucket": S3_BUCKET, "Key": old_key}
            bucket.copy(copy_source, new_key)
            s3.Object(S3_BUCKET, old_key).delete()

            # Update DB if this is the .m3u8 file
            if filename.endswith(".m3u8"):
                public_url = f"https://d2siyp5dx1ck05.cloudfront.net/{new_key}"
                update_video_path_in_db(video_id, new_key, public_url)

    print("✅ HLS migration complete.")


def delete_old_mp4_files(video_data):
    print("🧹 Deleting old .mp4 files...")

    for video_id, data in video_data.items():
        path = data["original_path"]
        if path and path.endswith(".mp4"):
            print(f"❌ Deleting {path}")
            try:
                s3.Object(S3_BUCKET, path).delete()
            except Exception as e:
                print(f"⚠️ Failed to delete {path}: {e}")

    print("✅ .mp4 cleanup complete.")

def revert_video_files(video_data):
    print("⏪ Reverting HLS files...")

    for video_id, data in video_data.items():
        user = data["username"]
        key = data["original_path"]
        filename = key.split("/")[-1]
        filename = filename.split(".")[0]
        current_prefix = f"/{user}/{TARGET_PREFIX}/{video_id}/"
        new_prefix = f"hls/{filename}/"

        print(f"🔍 Scanning: {current_prefix}")

        objects = list(bucket.objects.filter(Prefix=key))
        if not objects:
            print(f"⚠️ No files found for {video_id} at {key}")
            continue

        for obj in objects:
            old_key = obj.key
            new_filename = os.path.basename(old_key)
            new_key = f"{new_prefix}{new_filename}"

            print(f"🔁 Moving {old_key} → {new_key}")
            copy_source = {'Bucket': S3_BUCKET, 'Key': old_key}
            bucket.copy(copy_source, new_key)
            s3.Object(S3_BUCKET, old_key).delete()

            # Update DB if this is the .m3u8 file
            if filename.endswith(".m3u8"):
                new_url = f"https://d2siyp5dx1ck05.cloudfront.net/{new_key}"
                update_video_path_in_db(video_id, new_key, new_url)

    print("✅ All videos reverted successfully.")


def convert_thumbnail_url(s3_url):
    """
    Convert an S3 thumbnail URL to a CloudFront URL.
    """
    if not s3_url or "s3" not in s3_url:
        return s3_url  # Already converted or invalid

    try:
        s3_key = s3_url.split(".com/")[1]
    except IndexError:
        print(f"⚠️ Couldn't parse S3 key from: {s3_url}")
        return s3_url

    return f"https://d2siyp5dx1ck05.cloudfront.net/{s3_key}"


def update_thumbnails():
    print("🔍 Connecting to database...")
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # Get all post records with thumbnails
    cur.execute("SELECT video_id, thumbnail_link FROM api_postrecord")
    rows = cur.fetchall()
    print(f"✅ Retrieved {len(rows)} thumbnail records.")

    updated = 0

    for record_id, thumbnail in rows:
        new_thumbnail = convert_thumbnail_url(thumbnail)

        if new_thumbnail != thumbnail:
            print(f"🔁 Updating thumbnail for post ID {record_id}")
            cur.execute(
                "UPDATE api_postrecord SET thumbnail_link = %s WHERE video_id = %s",
                (new_thumbnail, record_id)
            )
            updated += 1

    conn.commit()
    cur.close()
    conn.close()

    print(f"✅ Updated {updated} thumbnails to CloudFront URLs.")

def main():
    #video_data = get_all_video_records()
    #revert_video_files(video_data)
    #move_hls_and_cleanup(video_data)
    #delete_old_mp4_files(video_data)
    update_thumbnails()


if __name__ == "__main__":
    main()
