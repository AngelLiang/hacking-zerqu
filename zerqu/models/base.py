# coding: utf-8

from contextlib import contextmanager

from flask import current_app, abort
from sqlalchemy import event, func
from sqlalchemy.orm import Query, class_mapper
from sqlalchemy.orm.exc import UnmappedClassError
# 使用了 postgresql 的 JSON 和 ARRAY
from sqlalchemy.dialects.postgresql import JSON, ARRAY
from werkzeug.utils import cached_property
from flask_sqlalchemy import SQLAlchemy as _SQLAlchemy

from zerqu.libs.utils import is_json
from zerqu.libs.cache import cache, redis, ONE_DAY, FIVE_MINUTES
from zerqu.libs.errors import NotFound

__all__ = ['db', 'CACHE_TIMES', 'Base', 'JSON', 'ARRAY']

# 缓存超时时间映射
CACHE_TIMES = {
    'get': ONE_DAY,
    'count': ONE_DAY,
    'ff': FIVE_MINUTES,
    'fc': FIVE_MINUTES,
}
CACHE_MODEL_PREFIX = 'db'


class SQLAlchemy(_SQLAlchemy):
    @contextmanager
    def auto_commit(self, throw=True):
        """自动提交
        :param throw: bool, 是否抛出异常
        """
        try:
            yield
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            current_app.logger.exception('%r' % e)
            if throw:
                raise e


db = SQLAlchemy(session_options={
    'expire_on_commit': False,
    'autoflush': False,
})


class CacheQuery(Query):
    def get(self, ident):
        """覆写 ``Query.get()`` 方法"""

        # 获取模型的mapper
        # 相当于 sqlalchemy.inspect(Model) 和 sqlalchemy.orm.class_mapper(Model)
        # 只不过 _only_full_mapper_zero('get') 是 Query 的私有方法
        mapper = self._only_full_mapper_zero('get')

        # 生成后缀
        if isinstance(ident, (list, tuple)):
            # 多个主键，例如：get((5, 10))
            # https://docs.sqlalchemy.org/en/13/orm/query.html#sqlalchemy.orm.query.Query.get
            suffix = '-'.join(map(str, ident))
        else:
            suffix = str(ident)

        # 生成cache key
        # mapper.class_ 即获取该 mapper 的模型
        # generate_cache_prefix 方法是在 BaseMixin 类里
        key = mapper.class_.generate_cache_prefix('get') + suffix
        # 从缓存中获取数据
        rv = cache.get(key)
        if rv:
            return rv
        rv = super(CacheQuery, self).get(ident)
        if rv is None:
            return None
        # 设置缓存
        cache.set(key, rv, CACHE_TIMES['get'])
        return rv

    def get_dict(self, idents):
        if not idents:
            return {}

        mapper = self._only_full_mapper_zero('get')
        if len(mapper.primary_key) != 1:
            raise NotImplemented

        # 生成前缀
        prefix = mapper.class_.generate_cache_prefix('get')
        # 生成keys
        keys = {prefix + str(i) for i in idents}
        # 获取缓存数据
        rv = cache.get_dict(*keys)
        # 缓存数据是否命中
        missed = {i for i in idents if rv[prefix + str(i)] is None}

        rv = {k.lstrip(prefix): rv[k] for k in rv}
        # 全都命中
        if not missed:
            return rv

        # 获取第一个主键
        pk = mapper.primary_key[0]
        # 主键in_查询
        missing = self.filter(pk.in_(missed)).all()
        to_cache = {}
        for item in missing:
            ident = str(getattr(item, pk.name))
            to_cache[prefix + ident] = item
            rv[ident] = item

        cache.set_many(to_cache, CACHE_TIMES['get'])
        return rv

    def get_many(self, idents, clean=True):
        d = self.get_dict(idents)
        if clean:
            return list(_itervalues(d, idents))
        return [d[str(k)] for k in idents]

    def filter_first(self, **kwargs):
        mapper = self._only_mapper_zero()
        # 生成缓存key的前缀， 这里使用 mapper 之后就不需要 mapper 了
        prefix = mapper.class_.generate_cache_prefix('ff')
        # 生成缓存key，example: <prefix> + 'username$admin-rolename$admin'
        key = prefix + '-'.join(['%s$%s' % (k, kwargs[k]) for k in kwargs])
        # 获取缓存
        rv = cache.get(key)
        # 缓存命中
        if rv:
            return rv
        # 缓存没命中
        rv = self.filter_by(**kwargs).first()
        if rv is None:
            return None
        # 设置缓存
        # it is hard to invalidate this cache, expires in 2 minutes
        cache.set(key, rv, CACHE_TIMES['ff'])
        return rv

    def filter_count(self, **kwargs):
        mapper = self._only_mapper_zero()
        model = mapper.class_  # 获取模型
        if not kwargs:
            # 没有 filter 条件
            key = model.generate_cache_prefix('count')
            rv = cache.get(key)
            if rv is not None:
                return rv
            q = self.select_from(model).with_entities(func.count(1))
            rv = q.scalar()
            cache.set(key, rv, CACHE_TIMES['count'])
            return rv

        # 有 filter 条件
        # 生成前缀
        prefix = model.generate_cache_prefix('fc')
        # 生成缓存key
        key = prefix + '-'.join(['%s$%s' % (k, kwargs[k]) for k in kwargs])
        # 从缓存中获取数据
        rv = cache.get(key)
        # 缓存命中
        if rv:
            return rv
        # 缓存没命中，数据库查询
        q = self.select_from(model).with_entities(func.count(1))
        rv = q.filter_by(**kwargs).scalar()
        # 设置缓存
        cache.set(key, rv, CACHE_TIMES['fc'])
        return rv

    def get_or_404(self, ident):
        data = self.get(ident)
        if data:
            return data

        if is_json():
            mapper = self._only_full_mapper_zero('get')
            key = '%s "%r"' % (mapper.class_.__name__, ident)
            raise NotFound(key)
        abort(404)

    def first_or_404(self, **kwargs):
        data = self.filter_first(**kwargs)
        if data:
            return data

        if is_json():
            mapper = self._only_full_mapper_zero('get')
            key = mapper.class_.__name__
            if len(kwargs) == 1:
                key = '%s "%s"' % (key, list(kwargs.values())[0])
            raise NotFound(key)
        abort(404)


class CacheProperty(object):
    """属性缓存"""

    def __init__(self, sa):
        self.sa = sa

    def __get__(self, obj, type):
        try:
            mapper = class_mapper(type)
            if mapper:
                return CacheQuery(mapper, session=self.sa.session())
        except UnmappedClassError:
            return None


class BaseMixin(object):
    def __getitem__(self, key):
        return getattr(self, key)

    @classmethod
    def generate_cache_prefix(cls, name):
        """生成缓存的前缀

        因为需要包括数据表名称，所以只能放在这里
        """
        # prefix example:
        # - `db:get:zq_user`
        # - `db:count:zq_user`
        prefix = '%s:%s:%s' % (CACHE_MODEL_PREFIX, name, cls.__tablename__)
        if hasattr(cls, '__cache_version__'):
            # example: `db:get:zq_user|<__cache_version__>:`
            return '%s|%s:' % (prefix, cls.__cache_version__)
        # example: `db:get:zq_user:`
        return '%s:' % prefix

    @classmethod
    def __declare_last__(cls):
        """给Mapper注册事件"""
        @event.listens_for(cls, 'after_insert')
        def receive_after_insert(mapper, conn, target):
            """注册Mapper事件，监听insert之后

            :param target: 模型
            """
            # 更新统计
            cache.inc(target.generate_cache_prefix('count'))

        @event.listens_for(cls, 'after_update')
        def receive_after_update(mapper, conn, target):
            """注册Mapper事件，监听update之后

            :param target: 模型
            """
            key = _unique_key(target, mapper.primary_key)
            # 设置缓存
            cache.set(key, target, CACHE_TIMES['get'])

        @event.listens_for(cls, 'after_delete')
        def receive_after_delete(mapper, conn, target):
            """注册Mapper事件，监听delete之后

            :param target: 模型
            """
            key = _unique_key(target, mapper.primary_key)
            # 更新统计
            cache.delete_many(key, target.generate_cache_prefix('count'))


class Base(db.Model, BaseMixin):
    __abstract__ = True
    cache = CacheProperty(db)  # cache query


def _unique_suffix(target, primary_key):
    """
    getattr(target, k.name)：如果模型的属性名称和数据表名称不一致，这里会报错

    可以改为::

        from sqlalchemy import inspect

        def _get_primary_keys(mapper):
            return [key for key, column in inspect(mapper).columns.items() if column.primary_key]


        def _unique_suffix(target, mapper):
            pks = _get_primary_keys(mapper)
            return '-'.join(pks)

    """
    return '-'.join(map(lambda k: str(getattr(target, k.name)), primary_key))


def _unique_key(target, primary_key):
    key = _unique_suffix(target, primary_key)
    return target.generate_cache_prefix('get') + key


def _itervalues(data, idents):
    for k in idents:
        item = data[str(k)]
        if item is not None:
            yield item

####################################################################


class RedisStat(object):
    """Redis状态类"""
    KEY_PREFIX = 'stat:{}'

    def __init__(self, ident):
        self.ident = ident
        self._key = self.KEY_PREFIX.format(ident)

    def increase(self, field, step=1):
        redis.hincrby(self._key, field, step)

    def get(self, key, default=0):
        return self.value.get(key, default)

    def __getitem__(self, item):
        return self.value[item]

    def __setitem__(self, item, value):
        redis.hset(self._key, item, int(value))

    @cached_property
    def value(self):
        return redis.hgetall(self._key)

    @classmethod
    def get_many(cls, ids):
        with redis.pipeline() as pipe:
            for i in ids:
                pipe.hgetall(cls.KEY_PREFIX.format(i))
            return pipe.execute()

    @classmethod
    def get_dict(cls, ids):
        rv = cls.get_many(ids)
        return dict(zip(ids, rv))
