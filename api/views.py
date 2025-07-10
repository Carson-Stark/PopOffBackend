import os
from django.shortcuts import render, redirect
from .models import *
from django.db.models import Count, Sum
from django.http import HttpResponse
from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from rest_framework import status
from rest_framework.views import APIView
from django.contrib.auth import get_user_model
from api.serializers import CreateUserSerializer
from django.http import JsonResponse
from django.utils import timezone
from rest_framework import status
from django.conf import settings
import base64
from django.core.files.base import ContentFile
import boto3
from botocore.exceptions import NoCredentialsError
import urllib.parse
from django.utils.timezone import now
from django.conf import settings
from .rank_video import calculate_video_rank, update_user_data, calculate_engagement_score, output_user_preferences
import re
import numpy as np
from django.core.cache import cache  # For optional caching
from .tasks import process_video
import uuid

def main (request):
    return HttpResponse("Hello World")

class CreateUserAPIView(CreateAPIView):
    serializer_class = CreateUserSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        # We create a token than will be used for future auth
        token = Token.objects.create(user=serializer.instance)
        token_data = {"token": token.key}

        # Create a UserData instance for the new user
        UserData.objects.create(user=serializer.instance)

        return Response(
            {**serializer.data, **token_data},
            status=status.HTTP_201_CREATED,
            headers=headers
        )

class LogoutUserAPIView(APIView):
    queryset = get_user_model().objects.all()

    def get(self, request, format=None):
        # simply delete the token to force a login
        request.user.auth_token.delete()
        return Response(status=status.HTTP_200_OK)
    
class CheckAuthView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):
        username = request.user.username
        return JsonResponse({'username': username}, status=200)

class VideoUploadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Validate required parameters
        #print("Request data:", request.data)  # Debugging statement

        if 'fileName' in request.data and 'fileType' in request.data:
            file_name = request.data['fileName']
            content_type = request.data['fileType']
        else:
            return JsonResponse({'error': 'file_name and content_type are required.'}, status=400)

        # Construct a safe upload path
        try:
            safe_file_name = urllib.parse.quote(file_name)  # Ensure file name is URL-safe
            safe_file_name = safe_file_name.split('.')[0]  # Remove file extension
            timestamp = now().strftime('%Y%m%d%H%M%S')  # Format timestamp for filename
            video_upload_path = f"{request.user.username}/videos/{safe_file_name}-{timestamp}.mp4"
            thumbnail_upload_path = f"{request.user.username}/thumbnails/{safe_file_name}-{timestamp}.jpg"

            # Initialize the S3 client
            s3_client = boto3.client(
                's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )

            # Generate the presigned URL
            video_presigned_url = s3_client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': settings.AWS_BUCKET,
                    'Key': video_upload_path,
                    'ContentType': content_type,
                },
                ExpiresIn=3600  # URL valid for 1 hour
            )

            thumbnail_presigned_url = s3_client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': settings.AWS_BUCKET,
                    'Key': thumbnail_upload_path,
                    'ContentType': 'image/jpeg',
                },
                ExpiresIn=3600  # URL valid for 1 hour
            )

            return JsonResponse({"video_url" : video_presigned_url, "video_file_path": video_upload_path, "thumb_url" : thumbnail_presigned_url, "thumb_file_path" : thumbnail_upload_path}, status=200)

        except NoCredentialsError:
            return JsonResponse(
                {'error': 'AWS credentials not found.'}, 
                status=500
            )
        except Exception as e:
            #print (f"An error occurred: {str(e)}")
            return JsonResponse(
                {'error': f"An error occurred: {str(e)}"}, 
                status=500
            )

class HLSUploadView(APIView):
    """
    Generates presigned -PUT URLs for every HLS artifact (segments + master playlist)
    and a single thumbnail. The frontend should PUT each file to the returned URL
    using the indicated Content-Type.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # ------------------------------------------------------------------ #
        # 1. Validate input ------------------------------------------------- #
        # ------------------------------------------------------------------ #
        base_name = request.data.get("base_name")          # e.g. “myvideo”
        files = request.data.getlist("files[]")   # ["playlist.m3u8", "segment_000.ts", …]

        if not base_name or not files or not isinstance(files, list):
            return JsonResponse(
                {"error": "`base_name` (str) and `files` (list) are required."},
                status=400,
            )

        # ------------------------------------------------------------------ #
        # 2. Construct safe paths ------------------------------------------ #
        # ------------------------------------------------------------------ #
        safe_base = urllib.parse.quote(base_name.split(".")[0])
        timestamp = now().strftime("%Y%m%d%H%M%S")
        # Everything for this video lives in its own folder:
        video_root = f"{request.user.username}/videos/{safe_base}-{timestamp}/"

        thumb_key = f"{request.user.username}/thumbnails/{safe_base}-{timestamp}.jpg"
        playlist_path = f"{video_root}playlist.m3u8"       # what the DB will store

        # ------------------------------------------------------------------ #
        # 3. Init S3 client ------------------------------------------------- #
        # ------------------------------------------------------------------ #
        try:
            s3_client = boto3.client(
                "s3",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION,
            )
        except NoCredentialsError:
            return JsonResponse({"error": "AWS credentials not found."}, status=500)

        # ------------------------------------------------------------------ #
        # 4. Build presigned URLs ------------------------------------------ #
        # ------------------------------------------------------------------ #
        def _ctype(fname: str) -> str:
            """Return the correct MIME type for .m3u8 vs .ts."""
            if fname.endswith(".m3u8"):
                return "application/x-mpegURL"
            if fname.endswith(".ts"):
                return "video/MP2T"
            return "application/octet-stream"

        upload_urls = {}
        try:
            # HLS artifacts
            for fname in files:
                key = f"{video_root}{fname}"
                presigned = s3_client.generate_presigned_url(
                    "put_object",
                    Params={
                        "Bucket": settings.AWS_BUCKET,
                        "Key": key,
                        "ContentType": _ctype(fname),
                    },
                    ExpiresIn=3600,
                )
                upload_urls[fname] = presigned

            # Thumbnail
            thumb_url = s3_client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": settings.AWS_BUCKET,
                    "Key": thumb_key,
                    "ContentType": "image/jpeg",
                },
                ExpiresIn=3600,
            )

        except Exception as e:
            # Catch *all* boto3 errors here so the client gets context
            return JsonResponse({"error": str(e)}, status=500)

        # ------------------------------------------------------------------ #
        # 5. Respond -------------------------------------------------------- #
        # ------------------------------------------------------------------ #
        return JsonResponse(
            {
                "upload_urls": upload_urls,       # { "playlist.m3u8": "https://…", "segment_000.ts": "https://…" }
                "video_file_path": playlist_path, # master manifest path for DB
                "thumb_url": thumb_url,
                "thumb_file_path": thumb_key,
            },
            status=200,
        )    

def clean_caption(caption):
    #remove tag special characters
    caption = caption.replace("\\T", "")
    # remove censored words
    with open('api/data/censored_words.txt') as f:
        censored_words = f.read().splitlines()

        pattern = re.compile(rf"\b({'|'.join(map(re.escape, censored_words))})\b", flags=re.IGNORECASE)
        caption = pattern.sub("****", caption)

    return caption


class PostVideoView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):

        #print("Request data:", request.data)

        required_fields = ['file_path', 'file_size', 'length', 'width', 'height', 'description']
        for field in required_fields:
            if field not in request.data:
                return JsonResponse({'error': f'{field} is required.'}, status=400)
            
        public_url = f"https://d2siyp5dx1ck05.cloudfront.net/{request.data['file_path']}"
        thumbnail_url = f"https://d2siyp5dx1ck05.cloudfront.net/{request.data['thumbnail_path']}"

        tags = request.data.get('tags', "").split(",")

        try:
            video_record = PostRecord.objects.create(
                user=request.user,
                file_path=request.data['file_path'],
                thumbnail_path=request.data['thumbnail_path'],
                file_size=request.data['file_size'],
                length=request.data['length'],
                width=request.data['width'],
                height=request.data['height'],
                description=request.data['description'],
                tags=tags,
                link=public_url,
                thumbnail_link=thumbnail_url,
            )
            video_record.save()

            task_id = str(uuid.uuid4())
            process_video.apply_async(args=[video_record.video_id, task_id], countdown=10)

            return JsonResponse({'message': 'Video posted successfully.'}, status=201)

        except Exception as e:
            #print(f"An error occurred: {str(e)}")
            return JsonResponse({'error': f"An error occurred: {str(e)}"}, status=500)
        
def get_ranked_videos(user_data, watched_video_ids, batch_size):
    # Cache key for this user's ranked videos
    cache_key = f"user_{user_data}_ranked_videos"

    # Try to fetch ranked videos from cache
    rankings = cache.get(cache_key)
    if not rankings:
        # If not cached, compute rankings

        videos = PostRecord.objects.exclude(
            video_id__in=watched_video_ids
        )
        #print(f"Found {len(videos)} unwatched videos.") 

        if len(videos) < batch_size:
            #print ("Not enough unwatched videos")
            videos = PostRecord.objects.all()

        video_rankings = []
        for video in videos:
            interest_score, rank_score = calculate_video_rank(user_data, video)
            video_rankings.append({
                "video": video,
                "rank_score": rank_score,
                "interest_score": interest_score * 100,
            })

        # Sort videos by rank_score and cache the result
        ranked_videos = sorted(
            video_rankings, key=lambda item: item["rank_score"], reverse=True
        )
        rankings = {"videos": ranked_videos, "watched": watched_video_ids}
        cache.set(cache_key, rankings, 1800)  # Cache for 30 minutes

    ##print(rankings)

    return rankings["videos"], rankings["watched"]

class GetFeedView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            batch_size = min(int(request.GET.get('batch_size', 5)), 20)  # Limit to a maximum of 20 videos
            user_data, new = UserData.objects.get_or_create(user=request.user)

            # Accept a list of video ids currently in the feed to filter out
            exclude_ids = request.GET.getlist('exclude_ids[]')
            exclude_ids = set(map(int, exclude_ids)) if exclude_ids else set()

            # Optionally filter to only followed users' videos
            followers_only = request.GET.get('followers_only', 'false').lower() in ['true','1','yes']
            # print (f"followers_only: {followers_only}")
            if followers_only:
                following_ids = set(
                    Following.objects.filter(follower=request.user)
                    .values_list('following_id', flat=True)
                )
            else:
                following_ids = set()

            # print(f"exclude_ids: {exclude_ids}")

            # Get ranked videos for the user
            watched_video_ids = ViewedPosts.objects.filter(
                user=request.user
            ).values_list('video_id', flat=True)
            ranked_videos, last_watched_ids = get_ranked_videos(user_data, watched_video_ids, batch_size)

            existing_ids = set(PostRecord.objects.values_list('video_id', flat=True))
            reported_ids = set(
                ReportedVideo.objects.values('video_id')
                .annotate(num_reports=Count('id'))
                .filter(num_reports__gt=1)
                .values_list('video_id', flat=True)
            )
            blocked_user_ids = set(
                list(BlockedUser.objects.filter(blocker=request.user).values_list('blocked_id', flat=True)) +
                list(BlockedUser.objects.filter(blocked=request.user).values_list('blocker_id', flat=True))
            )

            # filter out unwatched, reported, blocked, own, excluded, and optionally non-followed videos
            unwatched_videos = [
                video for video in ranked_videos
                if (
                    video["video"].video_id not in watched_video_ids and
                    video["video"].video_id in existing_ids and
                    video["video"].video_id not in reported_ids and
                    video["video"].user.user_id not in blocked_user_ids and
                    video["video"].user.user_id != request.user.user_id and
                    video["video"].video_id not in exclude_ids and
                    (not followers_only or video["video"].user.user_id in following_ids)
                )
            ]

            def weighted_sample(videos, count):
                scores = np.array([item["rank_score"] for item in videos])
                if scores.sum() == 0:
                    indices = np.random.choice(videos, size=min(count, len(videos)), replace=False)
                else :
                    probabilities = scores / scores.sum()  # Normalize to probabilities
                    indices = np.random.choice(len(videos), size=min(count, len(videos)), replace=False, p=probabilities)
                return [videos[i] for i in indices]

            selected_videos = weighted_sample(unwatched_videos, batch_size)
            selected_video_records = [video["video"] for video in selected_videos]

            liked_video_ids = set(LikedPosts.objects.filter(user=request.user, video__in=selected_video_records).values_list('video_id', flat=True))

            # print("selected_videos", selected_videos)

            # Serialize the final feed
            feed_data = [
                {
                    "id": item["video"].video_id,
                    "user": item["video"].user.username,
                    "file_path": item["video"].file_path,
                    "file_size": item["video"].file_size,
                    "duration": item["video"].length,
                    "width": item["video"].width,
                    "height": item["video"].height,
                    "description": item["video"].description,
                    "link": item["video"].link,
                    "likes": item["video"].likes,
                    "comments": item["video"].comments,
                    "rank_score": item["rank_score"],
                    "interest_score": item["interest_score"],
                    "liked": item["video"].video_id in liked_video_ids
                }
                for item in selected_videos
            ]

            ##print(feed_data)
            return JsonResponse({'feed': feed_data}, status=200)

        except Exception as e:
            #print(f"An error occurred: {str(e)}")
            return JsonResponse({'error': f"An error occurred: {str(e)}"}, status=500)
        

class LikePostView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Validate required parameters
        if 'video_id' not in request.data:
            return JsonResponse({'error': 'video_id is required.'}, status=400)

        try:
            # Fetch the video record
            video = PostRecord.objects.get(video_id=request.data['video_id'])
            liked = request.data.get('like', "true") == "true"

            liked_post, created = LikedPosts.objects.get_or_create(user=request.user, video=video)

            if liked and not created:
                return JsonResponse({'message': 'Video already liked.'}, status=200)

            if liked:
                video.likes += 1
            else:
                video.likes -= 1
                liked_post.delete()

            video.save()

            return JsonResponse({'message': 'Video liked successfully.'}, status=200)

        except Exception as e:
            #print(f"An error occurred: {str(e)}")
            return JsonResponse({'error': f"An error occurred: {str(e)}"}, status=500)
        
class AddCommentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Validate required parameters
        if 'video_id' not in request.data or 'comment' not in request.data:
            return JsonResponse({'error': 'video_id and comment are required.'}, status=400)

        try:
            # Fetch the video record
            video = PostRecord.objects.get(video_id=request.data['video_id'])

            # Increment the comment count
            video.comments += 1
            video.save()

            cleaned_comment = clean_caption(request.data['comment'])
            #print("got comment", cleaned_comment)
            # Check if the comment is empty after cleaning
            if not cleaned_comment:
                return JsonResponse({'error': 'Comment cannot be empty.'}, status=400)

            # Create a new comment record
            comment = CommentRecord.objects.create(
                user=request.user,
                video=video,
                comment=cleaned_comment
            )
            comment.save()

            return JsonResponse({'message': 'Comment added successfully.'}, status=200)

        except Exception as e:
            #print(f"An error occurred: {str(e)}")
            return JsonResponse({'error': f"An error occurred: {str(e)}"}, status=500)
        
class GetCommentsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Validate required parameters
        if 'video_id' not in request.data:
            #print (request.data)
            return JsonResponse({'error': 'video_id is required.'}, status=400)

        try:
            # Exclude comments from blocked users
            blocked_user_ids = set(
                list(BlockedUser.objects.filter(blocker=request.user).values_list('blocked_id', flat=True)) +
                list(BlockedUser.objects.filter(blocked=request.user).values_list('blocker_id', flat=True))
            )
            # Fetch all comment records for the video, excluding blocked users
            comments = CommentRecord.objects.filter(
                video=request.data['video_id']
            ).exclude(user__user_id__in=blocked_user_ids)

            #print(f"Found {len(comments)} comments.")  # Debugging statement

            # Serialize the comment data
            comment_data = [
                {
                    "id": comment.comment_id,
                    "user": comment.user.username,
                    "video": comment.video.video_id,
                    "comment": comment.comment,
                    "likes": comment.likes,
                }
                for comment in comments
            ]

            return JsonResponse({'comments': comment_data}, status=200)
        
        except Exception as e:
            #print(f"An error occurred: {str(e)}")
            return JsonResponse({'error': f"An error occurred: {str(e)}"}, status=500)
        
class GetUserPostsView (APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            # Fetch all video records for the authenticated user
            if 'username' in request.query_params and len(request.query_params['username']) > 0:
                user = User.objects.get(username=request.query_params['username'])
            else:
                user = request.user
            videos = PostRecord.objects.filter(user=user).order_by('-date_uploaded')

            #print(f"Found {len(videos)} videos.")  # Debugging statement

            liked_video_ids = set(LikedPosts.objects.filter(user=request.user, video__in=videos).values_list('video_id', flat=True))

            # Serialize the video data
            video_data = [
                {
                    "id": video.video_id,
                    "user": video.user.username,
                    "file_path": video.file_path,
                    "thumbnail_path": video.thumbnail_path,
                    "file_size": video.file_size,
                    "length": video.length,
                    "width": video.width,
                    "height": video.height,
                    "description": video.description,
                    "link": video.link,
                    "thumbnail_link": video.thumbnail_link,
                    "likes": video.likes,
                    "views": video.views,
                    "comments": video.comments,
                    "liked": video.video_id in liked_video_ids
                }
                for video in videos
            ]

            total_likes = sum(video.likes for video in videos)
            total_followers = Following.objects.filter(following=user).count()
            is_following = Following.objects.filter(follower=request.user, following=user).exists()

            return JsonResponse({'username' : request.user.username, 'total_likes' : total_likes, 'total_followers' : total_followers, 'is_following' : is_following,
                                 'posts': video_data}, status=200)
        
        except Exception as e:
            #print(f"An error occurred: {str(e)}")
            return JsonResponse({'error': f"An error occurred: {str(e)}"}, status=500)

class DeletePostView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        # Validate required parameters
        if 'video_id' not in request.data:
            return JsonResponse({'error': 'video_id is required.'}, status=400)

        try:
            # Fetch the video record
            video = PostRecord.objects.get(video_id=request.data['video_id'], user=request.user)

            # Initialize the S3 client
            s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )

            # Delete the video and thumbnail from S3
            s3_client.delete_object(Bucket=settings.AWS_BUCKET, Key=video.file_path)
            s3_client.delete_object(Bucket=settings.AWS_BUCKET, Key=video.thumbnail_path)

            # Delete the video record
            video.delete()

            return JsonResponse({'message': 'Video deleted successfully.'}, status=200)

        except PostRecord.DoesNotExist:
            return JsonResponse({'error': 'Video not found or you do not have permission to delete this video.'}, status=404)
        except NoCredentialsError:
            return JsonResponse({'error': 'AWS credentials not found.'}, status=500)
        except Exception as e:
            #print(f"An error occurred: {str(e)}")
            return JsonResponse({'error': f"An error occurred: {str(e)}"}, status=500)


class UpdatePostsEngagementView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # update engagement for a list of videos
        #print("Request data:", request.data)  # Debugging statement

        if 'video_id' not in request.data:
            return JsonResponse({'error': 'video_id is required.'}, status=400)
        
        try:
            user_data = UserData.objects.get(user=request.user)

            video_id = request.data['video_id']
            watch_time = request.data.get('watch_time', 0)
            liked = request.data.get('liked', False)
            commented = request.data.get('commented', False)
            viewed_comments = request.data.get('viewed_comments', False)

            video = PostRecord.objects.get(video_id=video_id)
            viewed_post, created = ViewedPosts.objects.get_or_create(user=request.user, video=video)

            if created:
                # This is the first time the user is viewing the video
                if watch_time > 1:
                    video.views += 1
                    video.total_watch_time += watch_time
                    viewed_post.save()
                    video.save()

            #print("calculating engagement")
            engagement = calculate_engagement_score(video.length, watch_time, liked, commented, viewed_comments)

            #print("updating user data")
    
            update_user_data(video, user_data, engagement)

            #print("done")

            return JsonResponse({'message': 'Engagement updated successfully.'}, status=200)
        
        except Exception as e:
            #print(f"An error occurred: {str(e)}")
            return JsonResponse({'error': f"An error occurred: {str(e)}"}, status=500)


class ResetUserEngagementView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        
        try:
            UserData.objects.filter(user=request.user).delete()
            LikedPosts.objects.filter(user=request.user).delete()
            CommentRecord.objects.filter(user=request.user).delete()
            ViewedPosts.objects.filter(user=request.user).delete()

            return JsonResponse({'message': 'Engagement reset successfully.'}, status=200)
        
        except Exception as e:
            #print(f"An error occurred: {str(e)}")
            return JsonResponse({'error': f"An error occurred: {str(e)}"}, status=500)

class ReturnUserPreferences(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):

        try:
            user_data = UserData.objects.get(user=request.user)
            preferences = output_user_preferences(user_data)
            #print(preferences)
            return JsonResponse(preferences)

        except Exception as e:
            #print(f"An error occurred: {str(e)}")
            return JsonResponse({'error': f"An error occurred: {str(e)}"}, status=500)

class ReportVideoView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if 'video_id' not in request.data or 'reason' not in request.data:
            return JsonResponse({'error': 'video_id and reason are required.'}, status=400)
        try:
            video = PostRecord.objects.get(video_id=request.data['video_id'])
            reason = request.data['reason']
            ReportedVideo.objects.create(user=request.user, video=video, reason=reason)
            return JsonResponse({'message': 'Video reported successfully.'}, status=201)
        except PostRecord.DoesNotExist:
            return JsonResponse({'error': 'Video not found.'}, status=404)
        except Exception as e:
            return JsonResponse({'error': f"An error occurred: {str(e)}"}, status=500)

class AddFollowerView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if 'username' not in request.data:
            return JsonResponse({'error': 'username is required.'}, status=400)
        try:
            to_follow = User.objects.get(username=request.data['username'])
            if to_follow == request.user:
                return JsonResponse({'error': 'You cannot follow yourself.'}, status=400)
            obj, created = Following.objects.get_or_create(follower=request.user, following=to_follow)
            if not created:
                # remove the user from the following list
                Following.objects.filter(follower=request.user, following=to_follow).delete()
                # print ("unfollowed")
                return JsonResponse({'message': 'User unfollowed successfully.'}, status=201)

            return JsonResponse({'message': 'Now following user.'}, status=201)
        except User.DoesNotExist:
            return JsonResponse({'error': 'User not found.'}, status=404)
        except Exception as e:
            return JsonResponse({'error': f"An error occurred: {str(e)}"}, status=500)

class BlockUserView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if 'username' not in request.data:
            return JsonResponse({'error': 'username is required.'}, status=400)
        try:
            to_block = User.objects.get(username=request.data['username'])
            if to_block == request.user:
                return JsonResponse({'error': 'You cannot block yourself.'}, status=400)
            obj, created = BlockedUser.objects.get_or_create(blocker=request.user, blocked=to_block)
            if not created:
                return JsonResponse({'message': 'User already blocked.'}, status=200)
            return JsonResponse({'message': 'User blocked successfully.'}, status=201)
        except User.DoesNotExist:
            return JsonResponse({'error': 'User not found.'}, status=404)
        except Exception as e:
            return JsonResponse({'error': f"An error occurred: {str(e)}"}, status=500)

class DeleteAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        user = request.user
        try:
            user.delete()
            return JsonResponse({'message': 'Account deleted successfully.'}, status=200)
        except Exception as e:
            return JsonResponse({'error': f"An error occurred: {str(e)}"}, status=500)

class SearchUserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            query = request.query_params.get('query', '').strip()
            if not query:
                return JsonResponse({'error': 'Query parameter is required'}, status=400)

            matching_users = get_user_model().objects.filter(username__icontains=query)
            user_data = []

            for user in matching_users:
                total_posts = PostRecord.objects.filter(user=user).count()
                num_followers = Following.objects.filter(following=user).count()
                total_likes = PostRecord.objects.filter(user=user).aggregate(Sum('likes'))['likes__sum'] or 0
                is_following = Following.objects.filter(follower=request.user, following=user).exists()
                user_data.append({
                    'username': user.username,
                    'total_posts': total_posts,
                    'total_likes': total_likes,
                    'num_followers': num_followers,
                    'is_following': is_following,
                })

            return JsonResponse({'accounts': user_data}, status=200)
        except Exception as e:
            # print(f"An error occurred: {str(e)}")
            return JsonResponse({'error': f"An error occurred: {str(e)}"}, status=500)

class FollowingListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):

        try:
            following_users = Following.objects.filter(follower=request.user).select_related('following')
            user_data = []

            for follow in following_users:
                user = follow.following
                total_posts = PostRecord.objects.filter(user=user).count()
                num_followers = Following.objects.filter(following=user).count()
                total_likes = PostRecord.objects.filter(user=user).aggregate(Sum('likes'))['likes__sum'] or 0
                is_following = True  # Since these are all accounts the user is following
                user_data.append({
                    'username': user.username,
                    'total_posts': total_posts,
                    'num_followers': num_followers,
                    'total_likes': total_likes,
                    'is_following': is_following,
                })

            return JsonResponse({'accounts': user_data}, status=200)
    
        except Exception as e:
            # print(f"An error occurred: {str(e)}")
            return JsonResponse({'error': f"An error occurred: {str(e)}"}, status=500)


