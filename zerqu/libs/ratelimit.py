# coding: utf-8

import time
import logging
from .cache import cache
from .errors import LimitExceeded


logger = logging.getLogger('zerqu')


class Ratelimiter(object):
    """速率限制器"""
    def __init__(self, db):
        self.db = db

    def get_data(self):
        return self.db.get_many(self.count_key, self.reset_key)

    def create(self, remaining, expires_at, duration):
        self.db.set_many({
            self.count_key: remaining,
            self.reset_key: expires_at,
        }, duration)

    def remain(self, remaining, expires):
        if expires > 0:
            self.db.set(self.count_key, remaining, expires)

    def __call__(self, prefix, count=600, duration=300):
        logger.info('Rate limit on %s' % prefix)
        self.count_key = '%s$c' % prefix
        self.reset_key = '%s$r' % prefix

        remaining, resetting = self.get_data()
        if not remaining and not resetting:
            remaining = count - 1
            expires_at = duration + int(time.time())
            self.create(remaining, expires_at, duration)
            expires = duration
        else:
            if resetting is None:
                expires = 5
            else:
                expires = int(resetting) - int(time.time())

            if remaining is None:
                remaining = 5

            if remaining <= 0 and expires:
                return remaining, expires
            remaining = int(remaining) - 1
            self.remain(remaining, expires)
        return remaining, expires


limiter = Ratelimiter(cache)


def ratelimit(prefix, count=600, duration=300):
    """速率限制

    :param remaining:
    :param expires: 过期时间，单位秒？
    """
    remaining, expires = limiter(prefix, count, duration)
    if remaining <= 0 and expires:
        # 超过速率限制，expires秒后重试。
        description = 'Rate limit exceeded, retry in %is' % expires
        raise LimitExceeded(description=description)
    return remaining, expires
