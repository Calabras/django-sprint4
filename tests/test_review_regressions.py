from datetime import timedelta
from http import HTTPStatus
from pathlib import Path

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.contrib.staticfiles import finders
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from blog.models import Comment, Post


@pytest.fixture(autouse=True)
def isolated_media(settings, tmp_path_factory):
    settings.MEDIA_ROOT = tmp_path_factory.mktemp('review-media')


@pytest.fixture
def visibility_posts(mixer, user, another_user, published_category):
    now = timezone.now()
    private_category = mixer.blend('blog.Category', is_published=False)
    common = {
        'author': user,
        'category': published_category,
        'is_published': True,
        'pub_date': now - timedelta(days=1),
        'image': None,
    }
    posts = {}
    for name, changes in (
        ('public', {}),
        ('draft', {'is_published': False}),
        ('future', {'pub_date': now + timedelta(days=1)}),
        ('private_category', {'category': private_category}),
        ('other_author', {'author': another_user}),
    ):
        posts[name] = mixer.blend(
            'blog.Post', title=f'visibility-{name}', **(common | changes)
        )
    return posts


@pytest.mark.django_db
@pytest.mark.parametrize(
    'viewer', ['user_client', 'another_user_client', 'client']
)
def test_profile_lists_only_posts_visible_to_viewer(
    request, viewer, user, visibility_posts
):
    response = request.getfixturevalue(viewer).get(
        reverse('blog:profile', args=[user.username])
    )
    assert response.status_code == HTTPStatus.OK
    actual = {post.pk for post in response.context['page_obj']}
    expected = {visibility_posts['public'].pk}
    if viewer == 'user_client':
        expected |= {
            visibility_posts[name].pk
            for name in ('draft', 'future', 'private_category')
        }
    assert actual == expected
    for name, post in visibility_posts.items():
        if name != 'other_author':
            assert (post.title in response.content.decode()) == (
                post.pk in expected
            )


@pytest.mark.django_db
@pytest.mark.parametrize('page', ['create', 'edit'])
def test_post_form_exposes_publication_checkbox(
    user_client, visibility_posts, page
):
    url = reverse('blog:create_post') if page == 'create' else reverse(
        'blog:edit_post', args=[visibility_posts['public'].pk]
    )
    response = user_client.get(url)
    assert response.status_code == HTTPStatus.OK
    assert 'is_published' in response.context['form'].fields
    assert 'name="is_published"' in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize('page', ['create', 'edit'])
def test_post_form_saves_unpublished_state(
    user_client, user, published_category, visibility_posts, page
):
    post = visibility_posts['public']
    url = reverse('blog:create_post') if page == 'create' else reverse(
        'blog:edit_post', args=[post.pk]
    )
    response = user_client.post(url, {
        'title': 'saved as draft',
        'text': 'draft text',
        'pub_date': '2020-01-01T12:00',
        'category': published_category.pk,
    })
    assert response.status_code == HTTPStatus.FOUND
    saved = Post.objects.get(author=user, title='saved as draft')
    assert saved.is_published is True
    assert saved.is_author_published is False
    if page == 'edit':
        assert saved.pk == post.pk


@pytest.mark.django_db
@pytest.mark.parametrize('kind', ['draft', 'future', 'private_category'])
@pytest.mark.parametrize(
    'payload', [{'text': 'not allowed'}, {'text': ''}],
    ids=['valid', 'invalid'],
)
def test_other_user_cannot_create_comments_on_hidden_posts(
    another_user_client, visibility_posts, kind, payload
):
    post = visibility_posts[kind]
    response = another_user_client.post(
        reverse('blog:add_comment', args=[post.pk]), payload
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert not Comment.objects.filter(post=post).exists()
    assert post.title not in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize(
    'kind', ['public', 'draft', 'future', 'private_category']
)
def test_author_can_comment_on_own_posts(
    user_client, user, visibility_posts, kind
):
    post = visibility_posts[kind]
    response = user_client.post(
        reverse('blog:add_comment', args=[post.pk]), {'text': 'author comment'}
    )
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse('blog:post_detail', args=[post.pk])
    assert Comment.objects.filter(
        post=post, author=user, text='author comment'
    ).exists()


@pytest.mark.django_db
def test_other_user_can_comment_on_public_post(
    another_user_client, another_user, visibility_posts
):
    post = visibility_posts['public']
    response = another_user_client.post(
        reverse('blog:add_comment', args=[post.pk]), {'text': 'public comment'}
    )
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse('blog:post_detail', args=[post.pk])
    assert Comment.objects.filter(
        post=post, author=another_user, text='public comment'
    ).exists()


@pytest.mark.django_db
def test_post_publication_date_defaults_to_current_time(
    user, published_category
):
    before = timezone.now()
    post = Post.objects.create(
        title='default date', text='text', author=user,
        category=published_category,
    )
    after = timezone.now()
    post.refresh_from_db()
    assert before <= post.pub_date <= after


@pytest.mark.django_db
@pytest.mark.parametrize('view', ['index', 'category', 'profile'])
@pytest.mark.parametrize('page', ['0', '-1', 'not-a-page', '999'])
def test_invalid_page_returns_404(
    client, user, published_category, view, page
):
    urls = {
        'index': reverse('blog:index'),
        'category': reverse(
            'blog:category_posts', args=[published_category.slug]
        ),
        'profile': reverse('blog:profile', args=[user.username]),
    }
    response = client.get(urls[view], {'page': page})
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
@pytest.mark.parametrize('view', ['index', 'category', 'profile'])
def test_pagination_has_stable_order_for_equal_dates(
    client, user, published_category, view
):
    pub_date = timezone.now() - timedelta(days=1)
    posts = [
        Post.objects.create(
            author=user,
            category=published_category,
            title=f'post-{index}',
            text='text',
            pub_date=pub_date,
        )
        for index in range(12)
    ]
    urls = {
        'index': reverse('blog:index'),
        'category': reverse(
            'blog:category_posts', args=[published_category.slug]
        ),
        'profile': reverse('blog:profile', args=[user.username]),
    }
    first = client.get(urls[view])
    last = client.get(urls[view], {'page': 'last'})
    assert first.status_code == last.status_code == HTTPStatus.OK
    assert list(first.context['page_obj']) == list(reversed(posts))[:10]
    assert list(last.context['page_obj']) == list(reversed(posts))[10:]


@pytest.mark.django_db
def test_author_can_see_post_after_category_is_removed(
    user_client, client, visibility_posts
):
    post = visibility_posts['public']
    post.category = None
    post.save(update_fields=['category'])
    detail_url = reverse('blog:post_detail', args=[post.pk])
    profile_url = reverse('blog:profile', args=[post.author.username])
    assert user_client.get(detail_url).status_code == HTTPStatus.OK
    assert user_client.get(profile_url).status_code == HTTPStatus.OK
    assert client.get(detail_url).status_code == HTTPStatus.NOT_FOUND
    assert post not in client.get(profile_url).context['page_obj']


@pytest.mark.django_db
@pytest.mark.parametrize('action', ['edit_comment', 'delete_comment'])
@pytest.mark.parametrize('method', ['get', 'post'])
def test_comment_author_cannot_access_hidden_post(
    another_user_client, another_user, visibility_posts, action, method
):
    post = visibility_posts['public']
    comment = Comment.objects.create(
        post=post, author=another_user, text='existing comment'
    )
    post.is_published = False
    post.save(update_fields=['is_published'])
    response = getattr(another_user_client, method)(
        reverse(f'blog:{action}', args=[post.pk, comment.pk]),
        {'text': 'changed'},
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    comment.refresh_from_db()
    assert comment.text == 'existing comment'


@pytest.mark.django_db
def test_user_can_change_username_and_profile_details(user_client, user):
    url = reverse('blog:edit_profile')
    response = user_client.get(url)
    assert 'username' in response.context['form'].fields
    response = user_client.post(url, {
        'username': 'new-username',
        'first_name': 'Nikita',
        'last_name': 'Shilin',
        'email': 'user@example.com',
    })
    user.refresh_from_db()
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse('blog:profile', args=['new-username'])
    assert user.username == 'new-username'
    assert user.first_name == 'Nikita'
    assert user.last_name == 'Shilin'
    assert user.email == 'user@example.com'


@pytest.mark.django_db
def test_user_cannot_change_username_to_an_existing_one(
    user_client, user, another_user
):
    old_username = user.username
    response = user_client.post(reverse('blog:edit_profile'), {
        'username': another_user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email,
    })
    user.refresh_from_db()
    assert response.status_code == HTTPStatus.OK
    assert 'username' in response.context['form'].errors
    assert user.username == old_username


@pytest.mark.django_db
def test_password_reset_email_is_written_to_file(
    client, user, settings, tmp_path
):
    settings.EMAIL_BACKEND = 'django.core.mail.backends.filebased.EmailBackend'
    settings.EMAIL_FILE_PATH = str(tmp_path)
    user.email = 'user@example.com'
    user.is_active = True
    user.set_password('A-secure-password-987!')
    user.save(update_fields=['email', 'is_active', 'password'])
    response = client.post(reverse('password_reset'), {'email': user.email})
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse('password_reset_done')
    messages = list(tmp_path.iterdir())
    assert len(messages) == 1
    content = messages[0].read_text(encoding='utf-8')
    assert user.email in content
    assert '/auth/reset/' in content


@pytest.mark.django_db
def test_invalid_password_reset_link_shows_explanation(client, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    url = reverse(
        'password_reset_confirm', kwargs={'uidb64': uid, 'token': 'bad-token'}
    )
    response = client.get(url)
    assert response.status_code == HTTPStatus.OK
    assert not response.context['validlink']
    assert 'ссылка' in response.content.decode().lower()
    assert 'name="new_password1"' not in response.content.decode()


@pytest.mark.django_db
def test_valid_password_reset_link_changes_password(client, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    url = reverse('password_reset_confirm', kwargs={
        'uidb64': uid,
        'token': default_token_generator.make_token(user),
    })
    response = client.get(url, follow=True)
    assert response.status_code == HTTPStatus.OK
    assert response.context['validlink']
    reset_url = response.redirect_chain[-1][0]
    response = client.post(reset_url, {
        'new_password1': 'A-secure-password-987!',
        'new_password2': 'A-secure-password-987!',
    })
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse('password_reset_complete')
    user.refresh_from_db()
    assert user.check_password('A-secure-password-987!')


def test_static_assets_available_with_legacy_directory(settings, tmp_path):
    (tmp_path / 'static' / 'css').mkdir(parents=True)
    settings.BASE_DIR = tmp_path
    assets_dir = Path(settings.STATICFILES_DIRS[0]).resolve()
    assert assets_dir.name == 'assets'
    for path in (
        'img/logo.png',
        'img/fav/favicon.ico',
        'img/fav/apple-touch-icon.png',
        'img/fav/favicon-16x16.png',
        'img/fav/favicon-32x32.png',
    ):
        found = finders.find(path)
        assert found
        assert Path(found).resolve() == (assets_dir / path).resolve()
