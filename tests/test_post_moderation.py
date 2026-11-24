import json

import pytest
from django.contrib.auth import get_user_model
from django.core import serializers
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.urls import reverse
from django.utils import timezone

from blog.models import Category, Post


@pytest.fixture
def moderation_post(db):
    author = get_user_model().objects.create_user(username='moderation_author')
    category = Category.objects.create(title='Category', slug='moderation')
    return Post.objects.create(
        title='Moderated post', text='Text', author=author, category=category,
        pub_date=timezone.now(), is_published=False,
    )


def post_data(post, published):
    data = {
        'title': post.title,
        'text': post.text,
        'pub_date': post.pub_date.strftime('%Y-%m-%d %H:%M:%S'),
        'category': post.category_id,
    }
    if published:
        data['is_published'] = 'on'
    return data


@pytest.mark.django_db
def test_author_cannot_remove_moderation_by_republishing(
    client, moderation_post
):
    post = moderation_post
    client.force_login(post.author)
    response = client.post(
        reverse('blog:edit_post', args=[post.pk]), post_data(post, True)
    )
    assert response.status_code == 302
    post.refresh_from_db()
    assert post.is_published is False
    assert post.is_author_published is True
    client.logout()
    detail_url = reverse('blog:post_detail', args=[post.pk])
    profile_url = reverse('blog:profile', args=[post.author.username])
    category_url = reverse('blog:category_posts', args=[post.category.slug])
    assert client.get(detail_url).status_code == 404
    assert post not in client.get(reverse('blog:index')).context['page_obj']
    assert post not in client.get(profile_url).context['page_obj']
    assert post not in client.get(category_url).context['page_obj']


@pytest.mark.django_db
@pytest.mark.parametrize('view', ['detail', 'profile'])
@pytest.mark.parametrize(
    'admin_published,author_published,message',
    [
        (False, True, 'Пост снят с публикации администратором'),
        (True, False, 'Пост снят с публикации автором'),
        (False, False, 'Пост снят с публикации администратором'),
    ],
)
def test_author_sees_reason_post_is_hidden(
    client, moderation_post, view, admin_published, author_published, message
):
    post = moderation_post
    post.is_published = admin_published
    post.is_author_published = author_published
    post.save(update_fields=['is_published', 'is_author_published'])
    client.force_login(post.author)
    url = (
        reverse('blog:post_detail', args=[post.pk])
        if view == 'detail'
        else reverse('blog:profile', args=[post.author.username])
    )
    response = client.get(url)
    assert response.status_code == 200
    assert message in response.content.decode()


@pytest.mark.django_db
def test_admin_can_restore_author_published_post(client, moderation_post):
    post = moderation_post
    Post.objects.filter(pk=post.pk).update(is_published=True)
    response = client.get(reverse('blog:post_detail', args=[post.pk]))
    assert response.status_code == 200
    assert post in client.get(reverse('blog:index')).context['page_obj']


@pytest.mark.django_db
def test_author_can_change_draft_while_blocked(client, moderation_post):
    post = moderation_post
    client.force_login(post.author)
    url = reverse('blog:edit_post', args=[post.pk])
    assert client.post(url, post_data(post, False)).status_code == 302
    post.refresh_from_db()
    assert post.is_published is False
    assert post.is_author_published is False
    assert client.post(url, post_data(post, True)).status_code == 302
    post.refresh_from_db()
    assert post.is_published is False
    assert post.is_author_published is True
    detail_url = reverse('blog:post_detail', args=[post.pk])
    assert client.get(detail_url).status_code == 200


@pytest.mark.django_db
def test_draft_remains_hidden_after_admin_unblocks(client, moderation_post):
    post = moderation_post
    client.force_login(post.author)
    assert client.post(
        reverse('blog:edit_post', args=[post.pk]), post_data(post, False),
    ).status_code == 302
    Post.objects.filter(pk=post.pk).update(is_published=True)
    client.logout()
    detail_url = reverse('blog:post_detail', args=[post.pk])
    assert client.get(detail_url).status_code == 404
    assert post not in client.get(reverse('blog:index')).context['page_obj']


@pytest.mark.django_db
def test_stale_author_form_cannot_overwrite_admin_block(moderation_post):
    from blog.forms import PostForm

    post = moderation_post
    Post.objects.filter(pk=post.pk).update(is_published=True)
    post.refresh_from_db()
    form = PostForm(post_data(post, True), instance=post)
    assert form.is_valid(), form.errors
    Post.objects.filter(pk=post.pk).update(is_published=False)
    form.save()
    post.refresh_from_db()
    assert post.is_published is False
    assert post.is_author_published is True


@pytest.mark.django_db
def test_admin_moderation_and_author_draft_are_independent(
    client, moderation_post
):
    post = moderation_post
    Post.objects.filter(pk=post.pk).update(is_published=True)
    admin = get_user_model().objects.create_superuser(
        'moderator', 'admin@example.com', 'password'
    )
    client.force_login(admin)
    response = client.post(reverse('admin:blog_post_change', args=[post.pk]), {
        'title': post.title, 'text': post.text,
        'pub_date_0': post.pub_date.strftime('%Y-%m-%d'),
        'pub_date_1': post.pub_date.strftime('%H:%M:%S'),
        'author': post.author_id, 'category': post.category_id,
        'is_author_published': 'on', '_save': 'Save',
    })
    assert response.status_code == 302
    post.refresh_from_db()
    assert post.is_published is False
    assert post.is_author_published is True


@pytest.mark.django_db
def test_old_serialized_post_defaults_author_status(moderation_post):
    serialized = json.loads(serializers.serialize('json', [moderation_post]))
    serialized[0]['fields'].pop('is_author_published')
    serialized[0]['pk'] = None
    restored = next(serializers.deserialize('json', json.dumps(serialized)))
    restored.save()
    assert restored.object.is_published is False
    assert restored.object.is_author_published is True


@pytest.mark.django_db(transaction=True)
def test_migration_preserves_existing_publication_flags():
    executor = MigrationExecutor(connection)
    before = [('blog', '0003_alter_post_pub_date')]
    after = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate(before)
        old_apps = executor.loader.project_state(before).apps
        User = old_apps.get_model('auth', 'User')
        OldPost = old_apps.get_model('blog', 'Post')
        author = User.objects.create(username='legacy_author')
        ids = [OldPost.objects.create(
            title=str(flag), text='Text', author_id=author.pk,
            pub_date=timezone.now(), is_published=flag,
        ).pk for flag in (False, True)]
        executor = MigrationExecutor(connection)
        executor.migrate(after)
        new_apps = executor.loader.project_state(after).apps
        NewPost = new_apps.get_model('blog', 'Post')
        posts = NewPost.objects.filter(pk__in=ids).order_by('pk')
        assert list(posts.values_list(
            'is_published', 'is_author_published',
        )) == [(False, True), (True, True)]
    finally:
        MigrationExecutor(connection).migrate(after)
