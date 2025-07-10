import os
import subprocess
import tempfile
from urllib.parse import urlparse

from django.conf import settings
import boto3

s3_client = boto3.client(
    "s3",
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
)

def tmp_path(suffix: str) -> str:
    """Return an absolute temp file path with the wanted suffix."""
    name = next(tempfile._get_candidate_names())
    return os.path.join(tempfile.gettempdir(), f"{name}{suffix}")

def download_asset(url: str) -> str | None:
    """
    • If the URL is inside your S3 bucket → download via boto3.
    • If it ends in `.m3u8`               → use ffmpeg to pull the HLS stream.
    • Otherwise                           → give up (return None).
    Returns the *local* file path or None on failure.
    """
    if url.endswith(".m3u8"):
        out_file = tmp_path(".mp4")
        cmd = [
            "ffmpeg",
            "-y",                # overwrite if exists
            "-i", url,           # input
            "-c", "copy",        # no re-encode → fast
            out_file,
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return out_file
        except subprocess.CalledProcessError:
            return None

    # --- S3 branch ----------------------------------------------------------
    bucket = settings.AWS_BUCKET
    prefix = f"https://{bucket}.s3.us-east-2.amazonaws.com/"
    if url.startswith(prefix):
        key = url[len(prefix):]
        out_file = tmp_path(".mp4")
        try:
            s3_client.download_file(bucket, key, out_file)
            return out_file
        except Exception:
            return None

    return None
