# coding: utf-8

import datetime
from flask import json
from zerqu.libs.cache import redis
from zerqu.libs.utils import Pagination
from .topic import Topic
from .user import User


class Notification(object):
    """通知"""

    # 通知分类
    CATEGORY_COMMENT = 'comment'    # 评论
    CATEGORY_MENTION = 'mention'    # 提及
    CATEGORY_REPLY = 'reply'        # 回复
    CATEGORY_LIKE_TOPIC = 'like_topic'  # 喜欢主题
    CATEGORY_LIKE_COMMENT = 'like_comment'  # 喜欢评论

    def __init__(self, user_id):
        self.user_id = user_id
        # 通知队列的缓存key
        self.key = 'notification_list:{}'.format(user_id)

    def add(self, sender_id, category, topic_id, **kwargs):
        """添加通知，只保存相关id、通知分类和创建时间"""
        kwargs['sender_id'] = sender_id
        kwargs['topic_id'] = topic_id
        kwargs['category'] = category
        kwargs['created_at'] = datetime.datetime.utcnow()
        # 添加进 redis 队列
        redis.lpush(self.key, json.dumps(kwargs))

    def count(self):
        """通知总数"""
        return redis.llen(self.key)

    def get(self, index):
        # 从 redis 队列获取
        rv = redis.lrange(self.key, index, index)
        if rv:
            return rv[0]
        return None

    def flush(self):
        redis.delete(self.key)

    def paginate(self, page=1, perpage=20):
        """获取通知的分页"""
        total = self.count()
        p = Pagination(total, page=page, perpage=perpage)
        start = (p.page - 1) * p.perpage
        stop = start + p.perpage
        return redis.lrange(self.key, start, stop), p

    @staticmethod
    def process_notifications(items):
        """静态方法，处理通知

        retType: list, [{'sender': <sender>, 'topic': <topic>}, ... ]
        """
        topic_ids = set()
        user_ids = set()
        data = []
        for d in items:
            d = json.loads(d)
            user_ids.add(d['sender_id'])
            topic_ids.add(d['topic_id'])
            data.append(d)

        topics = Topic.cache.get_dict(topic_ids)
        users = User.cache.get_dict(user_ids)

        for d in data:
            d['sender'] = users.get(str(d.pop('sender_id')))
            d['topic'] = topics.get(str(d.pop('topic_id')))
        return data
