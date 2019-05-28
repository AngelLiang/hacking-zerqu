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
        """获取数据"""
        return self.db.get_many(self.count_key, self.reset_key)

    def create(self, remaining, expires_at, duration):
        """创建数据

        :param remaining: 剩余次数
        :param expires_at: int, 重置次数的过期时间
        :param duration: int, 缓存过期时间
        """
        self.db.set_many({
            self.count_key: remaining,
            self.reset_key: expires_at,
        }, duration)

    def remain(self, remaining, expires):
        """剩余次数缓存

        :param remaining: int, 剩余次数
        :param expires: int, 过期时间
        """
        if expires > 0:
            self.db.set(self.count_key, remaining, expires)

    def __call__(self, prefix, count=600, duration=300):
        """
        :param prefix: str, key前缀
        :param count: int, 次数
        :param duration: int, 过期时间
        """
        logger.info('Rate limit on %s' % prefix)
        self.count_key = '%s$c' % prefix
        self.reset_key = '%s$r' % prefix

        remaining, resetting = self.get_data()
        if not remaining and not resetting:
            # 缓存中没有数据，可能是没有创建或已经过期
            remaining = count - 1
            expires_at = duration + int(time.time())  # 过期时间
            self.create(remaining, expires_at, duration)
            expires = duration
        else:
            # 缓存中有数据
            if resetting is None:
                expires = 5  # 5秒
            else:
                # 计算剩余时间，单位秒
                expires = int(resetting) - int(time.time())

            if remaining is None:
                remaining = 5  # 5次

            if remaining <= 0 and expires:
                return remaining, expires
            remaining = int(remaining) - 1  # 剩余次数减1
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
        raise LimitExceeded(description=description)  # 抛出异常
    return remaining, expires
