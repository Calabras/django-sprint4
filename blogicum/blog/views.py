from django.contrib.auth import get_user_model, login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from .forms import CommentForm, PostForm, UserEditForm
from .models import Category, Comment, Post

User = get_user_model()
POSTS_PER_PAGE = 10


def published_posts(queryset):
    return queryset.filter(
        is_published=True,
        category__is_published=True,
        pub_date__lte=timezone.now(),
    )


def annotate_posts(queryset):
    return queryset.select_related(
        'author',
        'category',
        'location',
    ).annotate(
        comment_count=Count('comments'),
    ).order_by('-pub_date')


def post_is_visible(post, user):
    if user.is_authenticated and post.author_id == user.pk:
        return True
    if not post.is_published:
        return False
    category = post.category
    if category is None or not category.is_published:
        return False
    return post.pub_date <= timezone.now()


class AuthorRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.author_id != request.user.pk:
            return redirect(self.get_author_redirect_url(obj))
        return super().dispatch(request, *args, **kwargs)

    def get_author_redirect_url(self, obj):
        raise NotImplementedError


class IndexListView(ListView):
    model = Post
    template_name = 'blog/index.html'
    paginate_by = POSTS_PER_PAGE

    def get_queryset(self):
        return annotate_posts(published_posts(Post.objects.all()))


class CategoryListView(ListView):
    model = Post
    template_name = 'blog/category.html'
    paginate_by = POSTS_PER_PAGE

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.category = get_object_or_404(
            Category,
            slug=self.kwargs['category_slug'],
            is_published=True,
        )

    def get_queryset(self):
        return annotate_posts(
            published_posts(self.category.posts.all()),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['category'] = self.category
        return context


class ProfileListView(ListView):
    model = Post
    template_name = 'blog/profile.html'
    paginate_by = POSTS_PER_PAGE

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.author = get_object_or_404(
            User,
            username=self.kwargs['username'],
        )

    def get_queryset(self):
        return annotate_posts(Post.objects.filter(author=self.author))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['profile'] = self.author
        return context


class PostDetailView(DetailView):
    model = Post
    template_name = 'blog/detail.html'
    pk_url_kwarg = 'post_id'
    context_object_name = 'post'

    def get_queryset(self):
        return Post.objects.select_related(
            'author',
            'category',
            'location',
        )

    def get_object(self, queryset=None):
        post = super().get_object(queryset)
        if not post_is_visible(post, self.request.user):
            raise Http404
        return post

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = CommentForm()
        context['comments'] = self.object.comments.select_related(
            'author',
        )
        return context


class PostCreateView(LoginRequiredMixin, CreateView):
    model = Post
    form_class = PostForm
    template_name = 'blog/create.html'

    def form_valid(self, form):
        form.instance.author = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        return reverse(
            'blog:profile',
            args=[self.request.user.username],
        )


class PostUpdateView(LoginRequiredMixin, AuthorRequiredMixin, UpdateView):
    model = Post
    form_class = PostForm
    template_name = 'blog/create.html'
    pk_url_kwarg = 'post_id'

    def get_success_url(self):
        return reverse('blog:post_detail', args=[self.object.pk])

    def get_author_redirect_url(self, obj):
        return reverse('blog:post_detail', args=[obj.pk])


class PostDeleteView(LoginRequiredMixin, AuthorRequiredMixin, DeleteView):
    model = Post
    template_name = 'blog/create.html'
    pk_url_kwarg = 'post_id'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = PostForm(instance=self.object)
        return context

    def get_success_url(self):
        return reverse('blog:index')

    def get_author_redirect_url(self, obj):
        return reverse('blog:post_detail', args=[obj.pk])


class CommentCreateView(LoginRequiredMixin, CreateView):
    model = Comment
    form_class = CommentForm

    def dispatch(self, request, *args, **kwargs):
        self.post_object = get_object_or_404(
            Post,
            pk=kwargs['post_id'],
        )
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.author = self.request.user
        form.instance.post = self.post_object
        return super().form_valid(form)

    def form_invalid(self, form):
        comments = self.post_object.comments.select_related('author')
        return render(
            self.request,
            'blog/detail.html',
            {
                'post': self.post_object,
                'form': form,
                'comments': comments,
            },
        )

    def get_success_url(self):
        return reverse('blog:post_detail', args=[self.post_object.pk])


class CommentUpdateView(
    LoginRequiredMixin,
    AuthorRequiredMixin,
    UpdateView,
):
    model = Comment
    form_class = CommentForm
    template_name = 'blog/comment.html'
    context_object_name = 'comment'
    pk_url_kwarg = 'comment_id'

    def get_object(self, queryset=None):
        return get_object_or_404(
            Comment,
            pk=self.kwargs['comment_id'],
            post_id=self.kwargs['post_id'],
        )

    def get_success_url(self):
        return reverse('blog:post_detail', args=[self.object.post_id])

    def get_author_redirect_url(self, obj):
        return reverse('blog:post_detail', args=[obj.post_id])


class CommentDeleteView(
    LoginRequiredMixin,
    AuthorRequiredMixin,
    DeleteView,
):
    model = Comment
    template_name = 'blog/comment.html'
    context_object_name = 'comment'
    pk_url_kwarg = 'comment_id'

    def get_object(self, queryset=None):
        return get_object_or_404(
            Comment,
            pk=self.kwargs['comment_id'],
            post_id=self.kwargs['post_id'],
        )

    def get_success_url(self):
        return reverse('blog:post_detail', args=[self.object.post_id])

    def get_author_redirect_url(self, obj):
        return reverse('blog:post_detail', args=[obj.post_id])


class ProfileUpdateView(LoginRequiredMixin, UpdateView):
    model = User
    form_class = UserEditForm
    template_name = 'blog/user.html'

    def get_object(self, queryset=None):
        return self.request.user

    def get_success_url(self):
        return reverse(
            'blog:profile',
            args=[self.request.user.username],
        )


class UserRegisterView(CreateView):
    form_class = UserCreationForm
    template_name = 'registration/registration_form.html'
    success_url = reverse_lazy('blog:index')

    def form_valid(self, form):
        response = super().form_valid(form)
        login(
            self.request,
            self.object,
            backend='django.contrib.auth.backends.ModelBackend',
        )
        return response
