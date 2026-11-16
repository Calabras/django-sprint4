# Блогикум. Часть 3

Django-проект «Блогикум»: публикации, комментарии, профиль и страницы авторизации. Код частей 1 и 2 сохранён, поверх него добавлены формы, пагинация и права доступа из спринта 4.

## Запуск

```bash
cd django-sprint4
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd blogicum
python manage.py migrate
python manage.py loaddata ../db.json
python manage.py runserver
```

Письма сброса пароля сохраняются в `blogicum/sent_emails/` (каталог в `.gitignore`).

## Проверки

```bash
cd django-sprint4
source venv/bin/activate
pytest
flake8 blogicum
```
