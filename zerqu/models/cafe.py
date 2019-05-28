# coding: utf-8

import datetime
from collections import defaultdict
from werkzeug.utils import cached_property
from sqlalchemy import Column
from sqlalchemy import String, Unicode, DateTime
from sqlalchemy import SmallInteger, Integer
from zerqu.libs.utils import EMPTY
from .base import db, Base, JSON

__all__ = ['Cafe', 'CafeMember', 'CafeTopic']


class Cafe(Base):
    __tablename__ = 'zq_cafe'

    # Cafe状态
    STATUSES = {
        0: 'closed',  # 已关闭
        1: 'active',  # 激活
        6: 'verified',  # 已验证
        9: 'official',  # 官方
    }
    STATUS_CLOSED = 0
    STATUS_ACTIVE = 1
    STATUS_VERIFIED = 6
    STATUS_OFFICIAL = 9

    # everyone can write
    # 所有人都可以编辑
    PERMISSION_PUBLIC = 0
    # write should be approved by members
    # 被认可的成员可以编辑
    PERMISSION_APPROVE = 3
    # only member can write
    # 只有成员可以编辑
    PERMISSION_MEMBER = 6

    PERMISSIONS = {
        'public': PERMISSION_PUBLIC,
        'approve': PERMISSION_APPROVE,
        'member': PERMISSION_MEMBER,
    }

    id = Column(Integer, primary_key=True)

    # basic information
    slug = Column(String(30), nullable=False, unique=True, index=True)
    name = Column(Unicode(30), nullable=False, unique=True)
    description = Column(Unicode(140))
    # refer to a topic ID as introduction
    intro = Column(Integer)

    style = Column(JSON, default={
        'logo': None,
        'color': None,
        'cover': None,
    })

    # defined above
    permission = Column(SmallInteger, default=PERMISSION_PUBLIC)

    # meta data
    status = Column(SmallInteger, default=STATUS_ACTIVE)
    user_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return '<Cafe:%s>' % self.slug

    def __str__(self):
        return self.name

    def keys(self):
        return (
            'id', 'slug', 'name', 'style', 'description', 'intro',
            'label', 'is_active', 'created_at', 'updated_at',
        )

    @cached_property
    def is_active(self):
        return self.status > 0

    @cached_property
    def label(self):
        label = self.STATUSES.get(self.status)
        if label == 'active':
            return None
        return label

    def has_write_permission(self, user_id, membership=EMPTY):
        """是否有编辑权限

        :param user_id:
        :param membership:
        """
        if not user_id:
            return False

        if self.permission == self.PERMISSION_PUBLIC:
            return True

        if self.user_id == user_id:
            return True

        if membership is EMPTY:
            membership = CafeMember.cache.get((self.id, user_id))

        if not membership:
            return False

        role = membership.role
        return role in (CafeMember.ROLE_MEMBER, CafeMember.ROLE_ADMIN)

    def has_admin_permission(self, user_id, membership=EMPTY):
        """是否有管理权限

        :param user_id:
        :param membership:
        """
        if not user_id:
            return False

        if self.user_id == user_id:
            return True

        if membership is EMPTY:
            membership = CafeMember.cache.get((self.id, user_id))

        if not membership:
            return False

        return membership.role == CafeMember.ROLE_ADMIN

    def create_cafe_topic(self, topic_id, user_id):
        has_permission = self.has_write_permission(user_id)

        status = CafeTopic.STATUS_PUBLIC
        if self.permission == self.PERMISSION_APPROVE:
            has_permission = True
            status = CafeTopic.STATUS_DRAFT

        if not has_permission:
            # TODO: raise error
            return None

        ct = CafeTopic(self.id, topic_id, user_id, status)
        db.session.add(ct)
        return ct


class CafeMember(Base):
    __tablename__ = 'zq_cafe_member'

    # not joined, but has topics or comments in this cafe
    ROLE_VISITOR = 0
    # subscribed a cafe
    ROLE_SUBSCRIBER = 2
    # authorized member of a private cafe
    ROLE_MEMBER = 3
    # people who can change cafe descriptions
    ROLE_ADMIN = 9

    ROLE_LABELS = {
        ROLE_VISITOR: 'visitor',
        ROLE_SUBSCRIBER: 'subscriber',
        ROLE_MEMBER: 'member',
        ROLE_ADMIN: 'admin',
    }

    cafe_id = Column(Integer, primary_key=True, autoincrement=False)
    user_id = Column(Integer, primary_key=True, autoincrement=False)
    role = Column('role', SmallInteger, default=ROLE_VISITOR)

    reputation = Column(Integer, default=0)
    description = Column(Unicode(140))

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

    def __init__(self, cafe_id, user_id, role=None):
        self.cafe_id = cafe_id
        self.user_id = user_id
        if role:
            self.role = role

    @cached_property
    def label(self):
        return self.ROLE_LABELS.get(self.role)

    def keys(self):
        return [
            'cafe_id', 'user_id', 'reputation', 'description',
            'label', 'created_at', 'updated_at',
        ]

    @classmethod
    def get_or_create(cls, cafe_id, user_id):
        m = cls.cache.get((cafe_id, user_id))
        if m:
            return m
        m = cls(cafe_id=cafe_id, user_id=user_id)
        db.session.add(m)
        return m

    @classmethod
    def get_user_following_cafe_ids(cls, user_id):
        # TODO: cache
        q = db.session.query(cls.cafe_id).filter_by(user_id=user_id)
        q = q.filter(cls.role >= cls.ROLE_SUBSCRIBER)
        return {cafe_id for cafe_id, in q}

    @classmethod
    def get_cafe_admin_ids(cls, cafe_id):
        q = db.session.query(cls.user_id).filter_by(cafe_id=cafe_id)
        q = q.filter_by(role=cls.ROLE_ADMIN)
        return {user_id for user_id, in q}


class CafeTopic(Base):
    __tablename__ = 'zq_cafe_topic'

    # 状态
    STATUS_DRAFT = 0
    STATUS_PUBLIC = 1

    cafe_id = Column(Integer, primary_key=True, autoincrement=False)
    topic_id = Column(Integer, primary_key=True, autoincrement=False)
    user_id = Column(Integer)

    status = Column(SmallInteger, default=STATUS_DRAFT)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

    def __init__(self, cafe_id, topic_id, user_id, status=None):
        self.cafe_id = cafe_id
        self.topic_id = topic_id
        self.user_id = user_id
        if status:
            self.status = status

    def approve(self):
        self.status = self.STATUS_PUBLIC
        self.updated_at = datetime.datetime.utcnow()
        db.session.add(self)

    @classmethod
    def get_topic_cafes(cls, topic_id, count=None):
        q = db.session.query(cls.cafe_id)
        q = q.filter_by(topic_id=topic_id, status=cls.STATUS_PUBLIC)
        if count:
            q = q.limit(count)
        return Cafe.cache.get_many([i for i, in q])

    @classmethod
    def get_topics_cafes(cls, topic_ids):
        q = db.session.query(cls.topic_id, cls.cafe_id)
        q = q.filter_by(status=cls.STATUS_PUBLIC)
        q = q.filter(cls.topic_id.in_(topic_ids)).all()
        cafe_ids = {i for _, i in q}
        cafes = Cafe.cache.get_dict(cafe_ids)
        topic_cafes = defaultdict(list)
        for tid, cid in q:
            cafe = cafes.get(str(cid))
            if cafe:
                topic_cafes[tid].append(cafe)
        return topic_cafes
