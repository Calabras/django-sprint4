from django import forms
from django.contrib.auth import get_user_model

from .models import Comment, Post

User = get_user_model()

PUB_DATE_FORMATS = (
    '%Y-%m-%dT%H:%M',
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%d %H:%M:%S.%f',
    '%Y-%m-%d %H:%M:%S.%f%z',
    '%Y-%m-%d %H:%M:%S%z',
    '%Y-%m-%d %H:%M',
    '%Y-%m-%d',
)


class PostForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = (
            'title',
            'text',
            'pub_date',
            'category',
            'location',
            'image',
        )
        widgets = {
            'pub_date': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={'type': 'datetime-local'},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['pub_date'].input_formats = list(PUB_DATE_FORMATS)


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ('text',)


class UserEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email')
