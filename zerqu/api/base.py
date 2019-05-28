# coding: utf-8

from functools import wraps

from flask import request, session
from oauthlib.common import to_unicode
from flask_oauthlib.utils import decode_base64

from zerqu.libs.errors import NotAuth, NotConfidential, InvalidClient
from zerqu.libs.ratelimit import ratelimit
from zerqu.libs.cache import cache
from zerqu.models import oauth, current_user
from zerqu.models import UserSession, OAuthClient


class ApiBlueprint(object):
    """自定义API蓝本类

    Usage::

        users_api = ApiBlueprint('users')

        def init_app(app):
            users_api.register(bp)
            app.register_blueprint(bp, url_prefix='/api/1')

    """

    def __init__(self, name):
        self.name = name

        self.deferred = []
        """延迟注册路由队列，成员是一个三元组： (function, rule, options)
        调用 ApiBlueprint().route() 时候只是把相关函数挂在在这里，
        等调用 ApiBlueprint().register() 方法的时候才是真正注册到 flask.Blueprint
        """

    def route(self, rule, **options):
        def wrapper(f):
            self.deferred.append((f, rule, options))
            return f
        return wrapper

    def register(self, bp, url_prefix=None):
        """
        :param bp: flask.Blueprint
        :param url_prefix:
        """
        if url_prefix is None:
            url_prefix = '/' + self.name

        for f, rule, options in self.deferred:
            endpoint = options.pop("endpoint", f.__name__)
            # 注册到真正的 flask.Blueprint 上
            bp.add_url_rule(url_prefix + rule, endpoint, f, **options)


def oauth_limit_params(login, scopes):
    """获取oauth限制的参数

    :param login: bool， 是否需要登录
    :param scopes: list， 作用域

    返回 (prefix, count, duration) 元组
    """
    if scopes is None:
        scopes = []

    user = UserSession.get_current_user()
    if user:
        request._current_user = user
        return 'limit:sid:{0}'.format(session.get('id')), 600, 300

    # 验证登录和作用域
    # 自此 login 和 scopes 参数完成任务
    valid, req = oauth.verify_request(scopes)
    if login and (not valid or not req.user):
        # 未验证
        raise NotAuth()

    if valid:
        request.oauth_client = req.access_token.client
        request._current_user = req.user
        key = 'limit:tok:%s' % req.access_token.access_token
        return key, 600, 600

    # client_id
    client_id = request.values.get('client_id')
    if client_id:
        c = OAuthClient.query.filter_by(
            client_id=client_id
        ).first()
        if not c:
            description = 'Client of %s not found' % client_id
            raise InvalidClient(description=description)

        request.oauth_client = c
        return 'limit:client:{0}'.format(c.id), 600, 600
    # 如果什么都没有，则使用IP作为标识符
    return 'limit:ip:{0}'.format(request.remote_addr), 3600, 3600


def oauth_ratelimit(login, scopes):
    prefix, count, duration = oauth_limit_params(login, scopes)
    rv = ratelimit(prefix, count, duration)  # 速率限制
    # 挂到线程局部变量 request 下
    request._rate_remaining, request._rate_expires = rv


def cache_response(cache_time):
    """响应缓存装饰器

    :param cache_time: 需要缓存时间

    Usage::

        cache_response(cache_time)(f)(*args, **kwargs)

    """
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            # 如果是已登录用户或请求方法非GET方法，则不缓存
            if current_user or request.method != 'GET':
                return f(*args, **kwargs)

            key = 'api:%s' % request.full_path
            response = cache.get(key)  # 从缓存中获取
            if response:
                # 缓存命中
                return response
            # 缓存没命中则进入这里
            response = f(*args, **kwargs)
            cache.set(key, response, cache_time)  # 设置缓存
            return response
        return decorated
    return wrapper


def require_oauth(login=True, scopes=None, cache_time=None):
    """
    :param login: bool, 是否需要登录
    :param scopes: list, 作用域
    :param cache_time: 缓存时间
    """
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            oauth_ratelimit(login, scopes)

            if cache_time is not None:
                return cache_response(cache_time)(f)(*args, **kwargs)

            return f(*args, **kwargs)
        return decorated
    return wrapper


def require_confidential(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', None)
        if not auth:
            raise NotConfidential()
        try:
            _, s = auth.split(' ')
            client_id, client_secret = decode_base64(s).split(':')
            client_id = to_unicode(client_id, 'utf-8')
            client_secret = to_unicode(client_secret, 'utf-8')
        except:
            raise NotConfidential()
        client = oauth._clientgetter(client_id)
        if not client or client.client_secret != client_secret:
            raise NotConfidential()
        if not client.is_confidential:
            raise NotConfidential()
        return f(*args, **kwargs)
    return decorated
