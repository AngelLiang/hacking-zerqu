# coding: utf-8

from flask import redirect, request, current_app
from flask import url_for as flask_url_for
from werkzeug.urls import url_encode, url_join
from flask_admin import Admin, AdminIndexView
from flask_admin.contrib.sqla import ModelView as _ModelView
from zerqu.models import db, current_user
from zerqu.models import User, Cafe, Topic


class LoginMixin(object):
    """for flask_admin"""
    def is_accessible(self):
        if not current_user:
            return False
        roles = [User.ROLE_ADMIN, User.ROLE_STAFF, User.ROLE_SUPER]
        return current_user.role in roles

    def inaccessible_callback(self, name, **kwargs):
        return redirect(flask_url_for('account.login', next_url=request.url))


class IndexView(LoginMixin, AdminIndexView):
    pass


class ModelView(LoginMixin, _ModelView):
    can_delete = False
    column_display_pk = True


class UserModelView(ModelView):
    column_sortable_list = ['id', 'username']
    column_searchable_list = ['username']
    column_exclude_list = ['_password', '_avatar_url']
    form_choices = {
        'role': [
            (User.ROLE_ADMIN, 'Admin'),
            (User.ROLE_STAFF, 'Staff',),
            (User.ROLE_VERIFIED, 'Verified'),
            (User.ROLE_SPAMMER, 'Spammer'),
            (User.ROLE_ACTIVE, 'Active'),
        ]
    }
    form_args = {
        'role': {
            'coerce': int,
        }
    }
    form_excluded_columns = ['updated_at', 'created_at']


class CafeModelView(ModelView):
    column_sortable_list = ['id', 'slug']
    column_searchable_list = ['slug']
    column_list = [
        'id', 'slug', 'name', 'description', 'label',
        'user_id', 'created_at', 'updated_at',
    ]
    form_excluded_columns = ['slug', 'created_at', 'updated_at', 'user_id']


class TopicModelView(ModelView):
    column_sortable_list = ['id', 'user_id']
    column_searchable_list = ['title']
    column_list = [
        'id', 'title', 'tags', 'label', 'info',
        'user_id', 'created_at', 'updated_at',
    ]
    form_excluded_columns = ['created_at', 'updated_at', 'webpage', 'user_id']
    form_choices = {
        'status': [
            (Topic.STATUS_DRAFT, 'draft'),
            (Topic.STATUS_PUBLIC, 'public'),
            (Topic.STATUS_CLOSED, 'closed'),
            (Topic.STATUS_FEATURED, 'featured'),
        ]
    }
    form_args = {
        'status': {
            'coerce': int,
        }
    }


def url_for(endpoint, **values):
    if endpoint == 'admin.static':
        filename = values.pop('filename')
        query = url_encode(values)
        url_prefix = current_app.config['ADMIN_STATIC_URL']
        return '{}?{}'.format(url_join(url_prefix, filename), query)
    return flask_url_for(endpoint, **values)


def init_app(app):
    admin = Admin(
        app, name='Dashboard',
        template_mode='bootstrap3',
        endpoint='admin',
        index_view=IndexView(),
    )
    admin.add_view(UserModelView(User, db.session))
    admin.add_view(CafeModelView(Cafe, db.session))
    admin.add_view(TopicModelView(Topic, db.session))

    if app.config.get('ADMIN_STATIC_URL'):
        app.jinja_env.globals['url_for'] = url_for
