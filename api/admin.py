from django.contrib import admin
from .models import *

admin.site.register(User)
admin.site.register(PostRecord)
admin.site.register(CommentRecord)
admin.site.register(UserData)
admin.site.register(LikedPosts)
admin.site.register(ViewedPosts)
admin.site.register(ReportedVideo)
admin.site.register(BlockedUser)
admin.site.register(Following)
