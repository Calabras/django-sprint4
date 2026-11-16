from django.shortcuts import render
from django.urls import ResolverMatch
from django.views.generic import TemplateView


class AboutPage(TemplateView):
    template_name = 'pages/about.html'


class RulesPage(TemplateView):
    template_name = 'pages/rules.html'


def _render_error(request, template, status):
    if getattr(request, 'resolver_match', None) is None:
        request.resolver_match = ResolverMatch(
            func=_render_error,
            args=(),
            kwargs={},
            url_name='error',
        )
    return render(request, template, status=status)


def csrf_failure(request, reason=''):
    return _render_error(request, 'pages/403csrf.html', 403)


def page_not_found(request, exception):
    return _render_error(request, 'pages/404.html', 404)


def server_error(request):
    return _render_error(request, 'pages/500.html', 500)
