from django.contrib.auth import get_user_model, login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import InvalidPage
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
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
        is_author_published=True,
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
    ).order_by('-pub_date', '-pk')


def get_paginator_page(paginator, page):
    try:
        page_number = int(page)
    except ValueError:
        if page == 'last':
            page_number = paginator.num_pages
        else:
            raise Http404(
                _('Page is not “last”, nor can it be converted to an int.')
            )
    try:
        return paginator.page(page_number)
    except InvalidPage as exc:
        raise Http404(
            _('Invalid page (%(page_number)s): %(message)s')
            % {'page_number': page_number, 'message': str(exc)}
        ) from exc


def post_is_visible(post, user):
    if user.is_authenticated and post.author_id == user.pk:
        return True
    if not post.is_published or not post.is_author_published:
        return False
    category = post.category
    if category is None or not category.is_published:
        return False
    return post.pub_date <= timezone.now()


class AuthorRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.author_id != request.user.pk:
            return redirect(
                'blog:post_detail',
                post_id=self.get_author_redirect_post_id(obj),
            )
        return super().dispatch(request, *args, **kwargs)

    def get_author_redirect_post_id(self, obj):
        return obj.pk


class PostListView(ListView):
    model = Post
    paginate_by = POSTS_PER_PAGE

    def paginate_queryset(self, queryset, page_size):
        paginator = self.get_paginator(
            queryset,
            page_size,
            orphans=self.get_paginate_orphans(),
            allow_empty_first_page=self.get_allow_empty(),
        )
        page_number = (
            self.kwargs.get(self.page_kwarg)
            or self.request.GET.get(self.page_kwarg)
            or 1
        )
        page = get_paginator_page(paginator, page_number)
        return paginator, page, page.object_list, page.has_other_pages()


class IndexListView(PostListView):
    template_name = 'blog/index.html'

    def get_queryset(self):
        return annotate_posts(published_posts(Post.objects.all()))


class CategoryListView(PostListView):
    template_name = 'blog/category.html'

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


class ProfileListView(PostListView):
    template_name = 'blog/profile.html'

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.author = get_object_or_404(
            User,
            username=self.kwargs['username'],
        )

    def get_queryset(self):
        queryset = Post.objects.filter(author=self.author)
        if self.request.user.pk != self.author.pk:
            queryset = published_posts(queryset)
        return annotate_posts(queryset)

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


class CommentCreateView(LoginRequiredMixin, CreateView):
    model = Comment
    form_class = CommentForm

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.post_object = get_object_or_404(
            Post.objects.select_related('category'),
            pk=kwargs['post_id'],
        )
        if not post_is_visible(self.post_object, request.user):
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        return redirect('blog:post_detail', post_id=self.post_object.pk)

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


class CommentAuthorRequiredMixin(AuthorRequiredMixin):
    def get_object(self, queryset=None):
        comment = get_object_or_404(
            Comment.objects.select_related('post__category'),
            pk=self.kwargs['comment_id'],
            post_id=self.kwargs['post_id'],
        )
        if not post_is_visible(comment.post, self.request.user):
            raise Http404
        return comment

    def get_author_redirect_post_id(self, obj):
        return obj.post_id


class CommentUpdateView(
    LoginRequiredMixin,
    CommentAuthorRequiredMixin,
    UpdateView,
):
    model = Comment
    form_class = CommentForm
    template_name = 'blog/comment.html'
    context_object_name = 'comment'
    pk_url_kwarg = 'comment_id'

    def get_success_url(self):
        return reverse('blog:post_detail', args=[self.object.post_id])


class CommentDeleteView(
    LoginRequiredMixin,
    CommentAuthorRequiredMixin,
    DeleteView,
):
    model = Comment
    template_name = 'blog/comment.html'
    context_object_name = 'comment'
    pk_url_kwarg = 'comment_id'

    def get_success_url(self):
        return reverse('blog:post_detail', args=[self.object.post_id])


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
