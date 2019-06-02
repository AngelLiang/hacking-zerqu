# coding: utf-8

from flask import request, current_app, url_for
from flask import copy_current_request_context
try:
    import gevent
except ImportError:
    gevent = None

# 爬虫浏览器
ROBOT_BROWSERS = ('google', 'msn', 'yahoo', 'ask', 'aol')
# 爬虫关键词
ROBOT_KEYWORDS = ('spider', 'bot', 'crawler', '+http')
# 手机平台
MOBILE_PLATFORMS = ('iphone', 'android', 'wii')


def run_task(func, *args, **kwargs):
    """运行任务"""
    # 如果配置了 gevent ，则使用 gevent 异步运行任务。
    if gevent and current_app.config.get('ZERQU_ASYNC'):
        gevent.spawn(copy_current_request_context(func), *args, **kwargs)
    else:
        # 否则以同步方式直接运行
        func(*args, **kwargs)


def xmldatetime(date):
    return date.strftime('%Y-%m-%dT%H:%M:%SZ')


def build_url(baseurl, endpoint, **kwargs):
    """构建URL"""
    if baseurl:
        baseurl = baseurl.rstrip('/')
        urlpath = url_for(endpoint, **kwargs)
        return '%s%s' % (baseurl, urlpath)
    kwargs['_external'] = True
    return url_for(endpoint, **kwargs)


def full_url(endpoint, **kwargs):
    baseurl = current_app.config.get('SITE_URL')
    return build_url(baseurl, endpoint, **kwargs)


def canonical_url(endpoint, **kwargs):
    """标准URL"""
    baseurl = current_app.config.get('SITE_CANONICAL_URL')
    if not baseurl:
        baseurl = current_app.config.get('SITE_URL')
    return build_url(baseurl, endpoint, **kwargs)


def is_robot():
    """是否是爬虫"""
    ua = str(request.user_agent).lower()
    for key in ROBOT_KEYWORDS:
        if key in ua:
            return True
    return request.user_agent.browser in ROBOT_BROWSERS


def is_mobile():
    """是否是手机端"""
    return request.user_agent.platform in MOBILE_PLATFORMS


def is_json():
    if request.is_xhr:
        return True

    if request.path.startswith('/api/'):
        return True

    if hasattr(request, 'oauth_client'):
        return True

    if request.accept_mimetypes.accept_json:
        return True

    return False


class Pagination(object):
    def __init__(self, total, page=1, perpage=20):
        self.total = total
        self.page = page
        self.perpage = perpage

        pages = int((total - 1) / perpage) + 1
        self.pages = pages

        if page > 1:
            self.prev = page - 1
        else:
            self.prev = None
        if page < pages:
            self.next = page + 1
        else:
            self.next = None

    def __getitem__(self, item):
        return getattr(self, item)

    def keys(self):
        return ['total', 'page', 'perpage', 'prev', 'next', 'pages']

    def fetch(self, q):
        offset = (self.page - 1) * self.perpage
        if offset:
            q = q.offset(offset)
        return q.limit(self.perpage).all()


class Empty(object):
    def __eq__(self, other):
        return isinstance(other, Empty)

    def __ne__(self, other):
        return not self == other

    def __nonzero__(self):
        return False

    def __bool__(self):
        return False

    def __str__(self):
        return "Empty"

    def __repr__(self):
        return '<Empty>'

EMPTY = Empty()
