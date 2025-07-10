from django.db import models
from django.contrib.auth.models import UserManager, PermissionsMixin, AbstractBaseUser


# Tables in RDS's Postgresql database

class CustomUserManager(UserManager):
    
    def _create_user(self, username, email, password, **extra_fields):
        if not email:
            raise ValueError('The user must have an email address')
        if not username:
            raise ValueError('The user must have a username')
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save()
        return user
    
    def create_user(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)

        return self._create_user(username, email, password, **extra_fields)
    
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        
        return self._create_user(username, email, password, **extra_fields)


# User table
# General house keeping information about the user and its statuses in the system
class User(AbstractBaseUser, PermissionsMixin):

    # unique id number, can be used for hashing
    user_id = models.AutoField(primary_key=True)                     
    
    username = models.CharField('Username', max_length=30, unique=True)
    email = models.EmailField('Email', unique=True)
    phone_number = models.CharField('Phone Number', max_length=15, blank=True)

    first_name = models.CharField('First Name', max_length=30, blank=True)
    last_name = models.CharField('Last Name', max_length=30, blank=True)

    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_superuser = models.BooleanField(default=False)

    date_joined = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(auto_now=True)             
    
    USERNAME_FIELD = 'username'
    EMAIL_FIELD = 'email'
    REQUIRED_FIELDS = ['email']
    
    objects = CustomUserManager()

    class Meta:
        verbose_name = 'user'
        verbose_name_plural = 'users'

    def get_full_name(self):
        full_name = f'{self.first_name} {self.last_name}'
        return full_name.strip()
    
    def get_short_name(self):
        return self.username
    
    def __str__(self):
        return self.username
    

class UserData(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
    #create array of floats
    user_preference_embeddings = models.JSONField(default=list, blank=True)
    
    def __str__(self):
        return self.user.username
    
class ViewedPosts(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    video = models.ForeignKey('PostRecord', on_delete=models.CASCADE)
    date = models.DateTimeField(auto_now_add=True)

class LikedPosts(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    video = models.ForeignKey('PostRecord', on_delete=models.CASCADE)
    date = models.DateTimeField(auto_now_add=True)

# Video metadata table
class PostRecord(models.Model):
    video_id = models.AutoField(primary_key = True, unique=True)      # unique id number, can be used for hashing
    user = models.ForeignKey(User, on_delete=models.CASCADE) # user who uploaded the video
    file_path = models.CharField(max_length=500)         # file directory path (on S3) for this single specific file
    thumbnail_path = models.CharField(max_length=500)    # file directory path (on S3) for the thumbnail of the video
    file_size = models.IntegerField()                    # size of file
    length = models.FloatField()                         # length of video in seconds
    width = models.IntegerField()                        # width of video in pixels
    height = models.IntegerField()                       # height of video in pixels
    views = models.IntegerField(default=0)               # number of views
    likes = models.IntegerField(default=0)               # number of likes
    comments = models.IntegerField(default=0)                       # number of comments
    total_watch_time = models.IntegerField(default=0)  # total watch time in seconds
    date_uploaded = models.DateTimeField(auto_now_add=True)         # date and time of upload
    description = models.TextField()                                # description of video
    tags = models.JSONField(default=list, blank=True)                # tags for the video
    link = models.CharField(max_length=500, null=True, blank=True)             # link to the video
    thumbnail_link = models.CharField(max_length=500, null=True, blank=True)  # link to the thumbnail
    transcription = models.TextField(null=True, blank=True)                   # transcription of the video
    summary = models.TextField(null=True, blank=True)               # description of the video
    embedding = models.JSONField(default=list, blank=True)                        # video embedding

class CommentRecord(models.Model):
    comment_id = models.AutoField(primary_key = True, unique=True)    # unique id number, can be used for hashing
    user = models.ForeignKey(User, on_delete=models.CASCADE) # user who uploaded the video
    video = models.ForeignKey(PostRecord, on_delete=models.CASCADE) # video that the comment is on
    comment = models.TextField()                    # comment text
    date_uploaded = models.DateTimeField(auto_now_add=True)         # date and time of upload
    likes = models.IntegerField(default=0)           # number of likes

class ReportedVideo(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    video = models.ForeignKey(PostRecord, on_delete=models.CASCADE)
    date_reported = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.user.username} reported {self.video.video_id} for {self.reason}"

class Following(models.Model):
    follower = models.ForeignKey(User, related_name='following', on_delete=models.CASCADE)
    following = models.ForeignKey(User, related_name='followers', on_delete=models.CASCADE)
    date_followed = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('follower', 'following')

    def __str__(self):
        return f"{self.follower.username} follows {self.following.username}"

class BlockedUser(models.Model):
    blocker = models.ForeignKey(User, related_name='blocked_users', on_delete=models.CASCADE)
    blocked = models.ForeignKey(User, related_name='blocked_by', on_delete=models.CASCADE)
    date_blocked = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('blocker', 'blocked')

    def __str__(self):
        return f"{self.blocker.username} blocked {self.blocked.username}"
