# coding: utf-8

import datetime
from collections import defaultdict
from flask import current_app
from sqlalchemy import func
from sqlalchemy import Column
from sqlalchemy import String, Unicode, DateTime
from sqlalchemy import SmallInteger, Integer, UnicodeText
from zerqu.libs.cache import cache, redis
from zerqu.libs.renderer import markup
from .webpage import WebPage
from .utils import current_user
from .base import db, Base, JSON, ARRAY, CACHE_TIMES, RedisStat


class Topic(Base):
    """主题"""
    __tablename__ = 'zq_topic'

    # 主题状态
    STATUS_DRAFT = 0
    STATUS_PUBLIC = 1
    STATUS_CLOSED = 2
    STATUS_FEATURED = 3

    # 状态映射
    STATUSES = {
        STATUS_DRAFT: 'draft',
        STATUS_PUBLIC: 'public',
        STATUS_CLOSED: 'closed',
        STATUS_FEATURED: 'featured',
    }

    id = Column(Integer, primary_key=True)
    title = Column(Unicode(140), nullable=False)
    webpage = Column(String(34))
    content = Column(UnicodeText, default=u'')

    user_id = Column(Integer, nullable=False, index=True)
    tags = Column(ARRAY(String))

    status = Column(SmallInteger, default=STATUS_PUBLIC)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )

    def __init__(self, title, content, user_id, link=None):
        self.title = title
        self.content = content
        self.user_id = user_id
        if link:
            self.update_link(link, user_id)

    def __repr__(self):
        return '<Topic:%d>' % self.id

    def keys(self):
        return (
            'id', 'title', 'label', 'editable', 'tags',
            'created_at', 'updated_at',
        )

    def update_link(self, link, user_id):
        if not link:
            return self
        webpage = WebPage.get_or_create(link, user_id)
        if webpage:
            self.webpage = webpage.uuid
        return self

    @property
    def editable(self):
        """可编辑"""
        if not current_user:
            return False
        if current_user.id != self.user_id:
            return False
        valid_time = current_app.config.get('ZERQU_VALID_MODIFY_TIME')
        if not valid_time:
            return True
        delta = datetime.datetime.utcnow() - self.created_at
        return delta.total_seconds() < valid_time

    @property
    def label(self):
        return self.STATUSES.get(self.status)

    @property
    def html(self):
        return markup(self.content)

    def get_statuses(self, user_id=None):
        status = TopicStat(self.id) or {}
        rv = {
            'view_count': int(status.get('views', 0)),
            'like_count': int(status.get('likes', 0)),
            'comment_count': int(status.get('comments', 0)),
            'read_count': int(status.get('reads', 0)),
        }
        if not user_id:
            return rv

        key = (self.id, user_id)
        rv['liked_by_me'] = bool(TopicLike.cache.get(key))
        read = TopicRead.cache.get(key)
        if read:
            rv['read_by_me'] = read.percent
        else:
            rv['read_by_me'] = '0%'
            read = TopicRead(topic_id=self.id, user_id=user_id)
            with db.auto_commit(throw=False):
                db.session.add(read)
        return rv


class TopicStat(RedisStat):
    """主题状态"""
    KEY_PREFIX = 'topic_stat:{}'
    TOPIC_FLAGS = 'topic_flags'

    def flag(self):
        with redis.pipeline() as pipe:
            pipe.hincrby(self._key, 'flags')
            pipe.zincrby(self.TOPIC_FLAGS, self.ident)
            pipe.execute()

    def keys(self):
        return (
            'views', 'reads', 'flags', 'likes',
            'comments', 'reputation', 'timestamp',
        )

    def calculate(self):
        def query_count(model):
            q = model.query.filter_by(topic_id=self.ident)
            return q.with_entities(func.count(1)).scalar()
        redis.hmset(self._key, dict(
            likes=query_count(TopicLike),
            reads=query_count(TopicRead),
            comments=query_count(Comment),
        ))


class TopicLike(Base):
    """喜欢的主题"""
    __tablename__ = 'zq_topic_like'

    topic_id = Column(Integer, primary_key=True, autoincrement=False)
    user_id = Column(Integer, primary_key=True, autoincrement=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    def __init__(self, topic_id, user_id):
        self.topic_id = topic_id
        self.user_id = user_id

    @classmethod
    def topics_liked_by_user(cls, user_id, topic_ids):
        return fetch_current_user_items(cls, user_id, topic_ids)


class TopicRead(Base):
    """已读主题？"""
    __tablename__ = 'zq_topic_read'

    topic_id = Column(Integer, primary_key=True, autoincrement=False)
    user_id = Column(Integer, primary_key=True, autoincrement=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    # reading status
    _percent = Column('percent', SmallInteger, default=0)

    def __init__(self, topic_id, user_id):
        self.topic_id = topic_id
        self.user_id = user_id

    @property
    def percent(self):
        return '%d%%' % self._percent

    @percent.setter
    def percent(self, num):
        if self._percent == 100:
            # finished already
            return
        if 0 < num <= 100:
            self._percent = num

    @classmethod
    def topics_read_by_user(cls, user_id, topic_ids):
        return fetch_current_user_items(cls, user_id, topic_ids)


class Comment(Base):
    """评论"""
    __tablename__ = 'zq_comment'

    id = Column(Integer, primary_key=True)
    content = Column(UnicodeText, nullable=False)

    topic_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    # comment reply to another comment
    reply_to = Column(Integer)

    status = Column(SmallInteger, default=0)
    flag_count = Column(Integer, default=0)
    like_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )

    def __init__(self, content, topic_id, user_id, reply_to=None):
        self.content = content
        self.topic_id = topic_id
        self.user_id = user_id
        if reply_to:
            reply = Comment.cache.get(reply_to)
            if reply and reply.topic_id == topic_id:
                self.reply_to = reply_to

    def keys(self):
        return (
            'id', 'topic_id', 'user_id', 'content', 'reply_to',
            'created_at', 'updated_at', 'flag_count', 'like_count',
        )

    def reset_like_count(self):
        q = CommentLike.query.filter_by(comment_id=self.id)
        self.like_count = q.with_entities(func.count(1)).scalar()
        db.session.add(self)
        return self.like_count

    @staticmethod
    def get_multi_statuses(comment_ids, user_id):
        liked = CommentLike.comments_liked_by_user(user_id, comment_ids)
        rv = defaultdict(dict)
        for cid in comment_ids:
            cid = str(cid)
            item = liked.get(cid)
            rv[cid]['liked_by_me'] = bool(item)
        return rv


class CommentLike(Base):
    """喜欢的评论"""
    __tablename__ = 'zq_comment_like'

    comment_id = Column(Integer, primary_key=True, autoincrement=False)
    user_id = Column(Integer, primary_key=True, autoincrement=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    def __init__(self, comment_id, user_id):
        self.comment_id = comment_id
        self.user_id = user_id

    @classmethod
    def comments_liked_by_user(cls, user_id, comment_ids):
        return fetch_current_user_items(
            cls, user_id, comment_ids, key='comment_id'
        )


def fetch_current_user_items(cls, user_id, ref_ids, key='topic_id'):
    if not ref_ids:
        return {}

    prefix = cls.generate_cache_prefix('get')

    def gen_key(tid):
        return prefix + '-'.join(map(str, [tid, user_id]))

    def get_key(key):
        return key.lstrip(prefix).split('-')[0]

    rv = cache.get_dict(*[gen_key(tid) for tid in ref_ids])
    missed = {i for i in ref_ids if rv[gen_key(i)] is None}
    rv = {get_key(k): rv[k] for k in rv}
    if not missed:
        return rv

    to_cache = {}
    q = cls.cache.filter_by(user_id=user_id)
    for item in q.filter(getattr(cls, key).in_(missed)):
        rv[str(getattr(item, key))] = item
        to_cache[gen_key(getattr(item, key))] = item

    cache.set_many(to_cache, CACHE_TIMES['get'])
    return rv


def iter_topics_with_statuses(topics, user_id):
    """Update topic list with statuses.

    :param topics: A list of topic dict.
    :param user_id: Current user ID.
    """
    tids = [t['id'] for t in topics]
    stats = TopicStat.get_dict(tids)

    if user_id:
        liked = TopicLike.topics_liked_by_user(user_id, tids)
        reads = TopicRead.topics_read_by_user(user_id, tids)
    else:
        liked = None
        reads = None

    for t in topics:
        tid = t['id']
        status = stats.get(tid, {})
        t['view_count'] = int(status.get('views', 0))
        t['like_count'] = int(status.get('likes', 0))
        t['comment_count'] = int(status.get('comments', 0))
        t['read_count'] = int(status.get('reads', 0))

        tid = str(tid)
        if liked:
            t['liked_by_me'] = bool(liked.get(tid))
        if reads:
            read = reads.get(tid)
            if read:
                t['read_by_me'] = read.percent
        yield t
