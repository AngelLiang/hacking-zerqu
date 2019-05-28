# coding: utf-8

from flask import Blueprint
from flask import session, request, jsonify
from flask_oauthlib.utils import decode_base64

from zerqu.libs.ratelimit import ratelimit
from zerqu.models import User, UserSession
from zerqu.forms import EmailForm
from .sendmails import send_signup_email, send_change_password_email

bp = Blueprint('session', __name__)


@bp.route('', methods=['POST', 'DELETE'])
def login_session():
    # 用户登出
    if request.method == 'DELETE':
        if UserSession.logout():
            return '', 204
        return jsonify(status='error'), 400

    # 取参
    if request.mimetype == 'application/json':
        username, password = parse_auth_headers()
    else:
        username = request.form.username
        password = request.form.password

    # 验参
    if not username or not password:
        return jsonify(
            status='error',
            error_code='missing_required_field',
            error_description='Username and password are required.'
        ), 400

    # can only try login a user 5 times
    prefix = 'limit:login:{0}:{1}'.format(username, request.remote_addr)
    ratelimit(prefix, 5, 3600)  # 同一个用户名一小时内可以尝试登录5次

    prefix = 'limit:login:{0}'.format(request.remote_addr)
    ratelimit(prefix, 60, 3600)  # 同一个IP一小时内可以尝试登录5次

    if '@' in username:
        # 邮箱
        user = User.cache.filter_first(email=username)
    else:
        # 用户名
        user = User.cache.filter_first(username=username)

    # 验证密码
    if not user or not user.check_password(password):
        return handle_login_failed(username, user)

    data = request.get_json()
    permanent = data.get('permanent', False)  # 是否永久的
    UserSession.login(user, permanent)
    return jsonify(user), 201


@bp.route('/new', methods=['POST'])
def signup_session():
    form = EmailForm.create_api_form()
    send_signup_email(form.email.data)
    return jsonify(message='We have sent you an email for sign up.')


def handle_login_failed(username, user):
    last_username = session.get('login.username', None)

    if last_username != username:
        session['login.username'] = username
        session['login.count'] = 1
        count = 1
    else:
        count = session['login.count']
        count += 1
        session['login.count'] = count

    if count < 3:
        return jsonify(
            status='error',
            error_code='login_failed',
            error_description='Invalid username or password.'
        ), 400

    if user:
        send_change_password_email(user.email)
    elif '@' in username:
        send_signup_email(username)

    return jsonify(
        status='error',
        error_code='login_failed',
        error_description=(
            'We have sent you an email '
            'in case you forgot your password.'
        )
    ), 400


def parse_auth_headers():
    data = request.headers.get('Authorization')
    if not data:
        return None, None
    data = data.replace('Basic ', '').strip()
    return decode_base64(data).split(':', 1)
