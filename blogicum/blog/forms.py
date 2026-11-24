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
    is_published = forms.BooleanField(
        required=False, label='Опубликовано автором', initial=True,
    )

    class Meta:
        model = Post
        fields = (
            'title',
            'text',
            'pub_date',
            'category',
            'location',
            'image',
            'is_published',
        )
        exclude = ('is_published',)
        widgets = {
            'pub_date': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={'type': 'datetime-local'},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['pub_date'].input_formats = list(PUB_DATE_FORMATS)
        if self.instance.pk:
            self.initial['is_published'] = self.instance.is_author_published

    def save(self, commit=True):
        post = super().save(commit=False)
        post.is_author_published = self.cleaned_data['is_published']
        if commit:
            if post.pk:
                post.save(update_fields=(
                    'title', 'text', 'pub_date', 'category', 'location',
                    'image', 'is_author_published',
                ))
            else:
                post.save()
            self.save_m2m()
        return post


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ('text',)


class UserEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email')
