# coding: utf-8


import re
from flask import Blueprint, request
from . import front, users, topics, cafes

VERSION_URL = re.compile(r'^/api/\d/')
VERSION_ACCEPT = re.compile(r'application/vnd\.zerqu\+json;\s+version=(\d)')
CURRENT_VERSION = '1'

# 这才是真正的 flask.Blueprint
bp = Blueprint('api', __name__)


@bp.after_request
def headers_hook(response):
    """蓝本的请求之后的钩子函数，处理请求头部"""
    remaining = getattr(request, '_rate_remaining', None)
    if remaining:
        response.headers['X-Rate-Limit'] = str(remaining)

    expires = getattr(request, '_rate_expires', None)
    if expires:
        response.headers['X-Rate-Expires'] = str(expires)

    # javascript can request API
    if request.method == 'GET':
        response.headers['Access-Control-Allow-Origin'] = '*'

    # api not available in iframe
    response.headers['X-Frame-Options'] = 'deny'
    # security protection
    response.headers['Content-Security-Policy'] = "default-src 'none'"
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


def find_version(environ):
    accept = environ.get('HTTP_ACCEPT')
    if not accept:
        return CURRENT_VERSION
    rv = VERSION_ACCEPT.findall(accept)
    if rv:
        return rv[0]
    return CURRENT_VERSION


class ApiVersionMiddleware(object):
    """API版本中间件"""
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO')
        if not path.startswith('/api/'):
            return self.app(environ, start_response)
        if VERSION_URL.match(path):
            return self.app(environ, start_response)

        version = find_version(environ)
        environ['PATH_INFO'] = path.replace('/api/', '/api/%s/' % version)
        return self.app(environ, start_response)


def init_app(app):
    app.wsgi_app = ApiVersionMiddleware(app.wsgi_app)

    # 把自定义 Blueprint 注册到 bp 上
    front.api.register(bp)
    users.api.register(bp)
    cafes.api.register(bp)
    topics.api.register(bp)

    # 给 flask app 注册 Blueprint
    app.register_blueprint(bp, url_prefix='/api/1')
