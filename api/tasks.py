import os
import json
import cv2
import boto3
import tempfile
from celery import shared_task
from moviepy import VideoFileClip
from PIL import Image
import base64
from django.core.files.storage import default_storage
from django.conf import settings
from openai import OpenAI

import numpy as np
from .models import PostRecord, ViewedPosts, LikedPosts, CommentRecord
import logging
logger = logging.getLogger(__name__)

from .download import download_asset   # new helper


#settings.configure()
#from decouple import config

client = OpenAI(api_key=settings.OPENAI_API_KEY)

# Initialize S3 Client
s3_client = boto3.client("s3", aws_access_key_id=settings.AWS_ACCESS_KEY_ID, aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY)
#AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID')
#AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY')
#AWS_BUCKET = config('AWS_BUCKET')
#s3_client = boto3.client("s3", aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY)

def generate_embedding(text):
    embedding = client.embeddings.create(input=[text], model="text-embedding-3-small").data[0].embedding
    return np.array(embedding)

@shared_task
def process_video(video_id, task_id):
    """Processes video from an S3 URL and extracts captions & transcription."""
    # check if the video_id is valid
    if not PostRecord.objects.filter(video_id=video_id).exists():
        return {"status": "failed", "message": "Video record not found"}
    video_record = PostRecord.objects.get(video_id=video_id)
    video_s3_url = video_record.link
    temp_file = download_asset(video_s3_url)
    if not temp_file:
        return {"status": "failed", "message": "Video download failed"}

    logger.info(f"[INFO] Processing video: {temp_file}")

    # Extract frames and captions
    transcript = transcribe_audio(temp_file)
    frames, timestamps = extract_frames(temp_file)
    summary = describe_video_with_gpt4(frames, transcript=transcript)

    username = video_record.user.username
    tags = video_record.tags
    tag_string = ""
    for tag in tags:
        tag_string += f"\\T {tag} "
    caption = video_record.description
    video_embedding_text = \
        f"@{username} {tag_string} Caption: {caption}\n Video Summary: {summary}"
    embedding = generate_embedding(video_embedding_text)

    video_record.transcription = transcript
    video_record.summary = summary
    video_record.embedding = embedding.tolist()
    video_record.save()

    logger.info(f"[INFO] Video processing completed: {temp_file}")

    cleanup(temp_file)

    result = {
        "status": "success",
        "summary": summary,
        "transcript": transcript,
        "embedding": embedding.tolist(),
        "task_id": task_id,
    }

    return result

def download_video_from_s3(video_s3_url):
    """Downloads video from S3 and saves it locally."""
    bucket_name = settings.AWS_BUCKET
    key = video_s3_url.split(f"https://{bucket_name}.s3.us-east-2.amazonaws.com/")[-1]

    logger.info(video_s3_url)

    temp_file = get_temp_file_path("mp4")
    logger.info(temp_file)
    logger.info(key)
    try:
        s3_client.download_file(bucket_name, key, temp_file)
        return temp_file
    except Exception as e:
        logger.info(f"[ERROR] Failed to download video: {e}")
        return None

def extract_frames(video_path, frame_interval=10):
    """Extracts frames from a video at a given interval."""
    cap = cv2.VideoCapture(video_path)
    frames = []
    timestamps = []
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    for i in range(frame_count):
        ret, frame = cap.read()
        if not ret:
            break
        if i % (frame_interval * int(fps)) == 0:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(frame_rgb)
            frames.append(image)
            timestamps.append(i / fps)

    cap.release()
    return frames, timestamps

# 3. Ask GPT-4V to describe the video from multiple frames
def describe_video_with_gpt4(frames, transcript=None, prompt=None):
    input_content = [
        {"type": "input_text", "text": prompt or "Please summarize what’s happening in this video based on the frames."}
    ]

    if transcript:
        input_content.append({"type": "input_text", "text": f"The audio transcript is: {transcript}"})

    for img in frames:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            img.save(f.name)
            with open(f.name, "rb") as image_file:
                b64_image = base64.b64encode(image_file.read()).decode("utf-8")
            input_content.append({
                "type": "input_image",
                "image_url": f"data:image/png;base64,{b64_image}"
            })

    response = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {
                "role": "user",
                "content": input_content,
            }
        ],
    )

    return response.output_text

def get_temp_file_path(extension):
    temp_dir = "tmp"
    name = next(tempfile._get_candidate_names())
    temp_file = os.path.join(temp_dir, f"{name}.{extension}")
    return temp_file

def transcribe_audio(video_path):
    """Extracts and transcribes audio using Whisper."""
    video = VideoFileClip(video_path)
    audio_path = get_temp_file_path(".mp3")
    video.audio.write_audiofile(audio_path)

    logger.info("[INFO] Uploading audio to OpenAI Whisper...")
    with open(audio_path, "rb") as f:
        transcript = client.audio.transcriptions.create(model="whisper-1", file=f)

    cleanup(audio_path)

    video.close()
    
    return transcript.text

def cleanup(video_path):
    if os.path.exists(video_path):
        os.remove(video_path)  # Delete file after processing
        logger.info(f"[INFO] Deleted temp file: {video_path}")

@shared_task
def update_post_records():
    """Ensures consistency by updating each PostRecord's views, likes, and comments based on actual records in the database."""

    logger.info("[INFO] Preforming consistency check on PostRecords...")
    
    posts = PostRecord.objects.all()

    for post in posts:
        # Update views based on ViewedPosts
        post.views = ViewedPosts.objects.filter(video=post).count()

        # Update likes based on LikedPosts
        post.likes = LikedPosts.objects.filter(video=post).count()

        # Update comments based on CommentRecord
        post.comments = CommentRecord.objects.filter(video=post).count()

        # Save the updated post record
        post.save()

    logger.info("[INFO] Post records updated successfully.")

