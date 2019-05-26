# coding: utf-8

from flask import request, jsonify

from zerqu.models import db, current_user, User
from zerqu.models import CafeTopic, WebPage
from zerqu.models import Topic, TopicLike, TopicRead, TopicStat
from zerqu.models import Comment, CommentLike
from zerqu.models import iter_items_with_users
from zerqu.models.topic import iter_topics_with_statuses
from zerqu.rec.timeline import get_timeline_topics, get_all_topics
from zerqu.forms import TopicForm, CommentForm
from zerqu.libs.renderer import markup
from zerqu.libs.cache import cache
from zerqu.libs.errors import APIException, Conflict, NotFound, Denied
from .base import ApiBlueprint
from .base import require_oauth
from .utils import cursor_query, pagination_query, int_or_raise

api = ApiBlueprint('topics')


@api.route('')
@api.route('/timeline')
@require_oauth(login=False, cache_time=600)
def timeline():
    """时间线
    GET /topics
    GET /topics/timeline
    """
    cursor = int_or_raise('cursor', 0)
    if request.args.get('show') == 'all':
        topics, cursor = get_all_topics(cursor)
    else:
        topics, cursor = get_timeline_topics(cursor, current_user.id)

    topics_cafes = CafeTopic.get_topics_cafes([t.id for t in topics])
    data = []
    for d in iter_items_with_users(topics):
        d['cafes'] = topics_cafes.get(d['id'])
        data.append(d)
    data = list(iter_topics_with_statuses(data, current_user.id))
    return jsonify(data=data, cursor=cursor)


@api.route('', methods=['POST'])
@require_oauth(login=True, scopes=['topic:write'])
def create_topic():
    """创建主题
    POST /topics
    """
    form = TopicForm.create_api_form()
    topic = form.create_topic(current_user.id)
    data = make_topic_response(topic)
    return jsonify(data)


@api.route('/<int:tid>')
@require_oauth(login=False)
def view_topic(tid):
    """查看主题
    GET /topics/<int:tid>
    """
    topic = Topic.cache.get_or_404(tid)
    data = make_topic_response(topic)

    # /api/topic/:id?content=raw vs ?content=html
    content_format = request.args.get('content')
    if content_format == 'raw':
        data['content'] = topic.content
    else:
        data['content'] = topic.html
        TopicStat(tid).increase('views')

    data['cafes'] = CafeTopic.get_topic_cafes(tid, 1)
    data['user'] = User.cache.get(topic.user_id)
    return jsonify(data)


@api.route('/<int:tid>', methods=['POST'])
@require_oauth(login=True, scopes=['topic:write'])
def update_topic(tid):
    """更新主题
    POST /topics/<int:tid>
    """
    topic = Topic.query.get(tid)
    if not topic:
        raise NotFound('Topic')

    if not topic.editable:
        raise Denied('updating this topic')

    form = TopicForm.create_api_form(obj=topic)
    topic = form.update_topic(current_user.id)
    data = make_topic_response(topic)
    data['user'] = dict(current_user)
    data['content'] = topic.html
    return jsonify(data)


@api.route('/<int:tid>/read', methods=['POST'])
@require_oauth(login=True)
def write_read_percent(tid):
    """
    POST /topics/<int:tid>/read
    """
    topic = Topic.cache.get_or_404(tid)
    percent = request.get_json().get('percent')
    if not isinstance(percent, int):
        raise APIException(description='Invalid payload "percent"')
    read = TopicRead.query.get((topic.id, current_user.id))
    if not read:
        read = TopicRead(topic_id=topic.id, user_id=current_user.id)
    read.percent = percent

    with db.auto_commit():
        db.session.add(read)
    return jsonify(percent=read.percent)


@api.route('/<int:tid>/flag', methods=['POST'])
@require_oauth(login=True)
def flag_topic(tid):
    key = 'flag:%d:t-%d' % (current_user.id, tid)
    if cache.get(key):
        return '', 204
    cache.inc(key)
    TopicStat(tid).flag()
    return '', 204


@api.route('/<int:tid>/comments')
@require_oauth(login=False, cache_time=600)
def view_topic_comments(tid):
    """查看主题评论"""
    topic = Topic.cache.get_or_404(tid)
    comments, cursor = cursor_query(
        Comment, lambda q: q.filter_by(topic_id=topic.id)
    )
    data = []

    if current_user:
        statuses = Comment.get_multi_statuses(
            [c['id'] for c in comments],
            current_user.id
        )
    else:
        statuses = {}
    for d in iter_items_with_users(comments):
        d['content'] = markup(d['content'])
        # update status
        d.update(statuses.get(str(d['id']), {}))
        data.append(d)
    return jsonify(data=data, cursor=cursor)


@api.route('/<int:tid>/comments', methods=['POST'])
@require_oauth(login=True, scopes=['comment:write'])
def create_topic_comment(tid):
    """创建主题评论"""
    topic = Topic.cache.get_or_404(tid)
    form = CommentForm.create_api_form()
    comment = form.create_comment(current_user.id, topic.id)
    rv = dict(comment)
    rv['content'] = markup(rv['content'])
    rv['user'] = dict(current_user)
    return jsonify(rv), 201


@api.route('/<int:tid>/likes')
@require_oauth(login=False, cache_time=600)
def view_topic_likes(tid):
    topic = Topic.cache.get_or_404(tid)

    data, pagination = pagination_query(
        TopicLike, TopicLike.created_at, topic_id=topic.id
    )
    user_ids = [o.user_id for o in data]

    # make current user at the very first position of the list
    current_info = current_user and pagination.page == 1
    if current_info and current_user.id in user_ids:
        user_ids.remove(current_user.id)

    data = User.cache.get_many(user_ids)
    if current_info and TopicLike.cache.get((topic.id, current_user.id)):
        data.insert(0, current_user)
    return jsonify(data=data, pagination=dict(pagination))


@api.route('/<int:tid>/likes', methods=['POST'])
@require_oauth(login=True)
def like_topic(tid):
    data = TopicLike.query.get((tid, current_user.id))
    if data:
        raise Conflict(description='You already liked it')

    topic = Topic.cache.get_or_404(tid)
    like = TopicLike(topic_id=topic.id, user_id=current_user.id)
    with db.auto_commit():
        db.session.add(like)
    return '', 204


@api.route('/<int:tid>/likes', methods=['DELETE'])
@require_oauth(login=True)
def unlike_topic(tid):
    data = TopicLike.query.get((tid, current_user.id))
    if not data:
        raise Conflict(description='You already unliked it')
    with db.auto_commit():
        db.session.delete(data)

    TopicStat(tid).calculate()
    return '', 204


@api.route('/<int:tid>/comments/<int:cid>', methods=['DELETE'])
@require_oauth(login=True, scopes=['comment:write'])
def delete_topic_comment(tid, cid):
    """删除主题评论"""
    comment = get_comment_or_404(tid, cid)
    if comment.user_id != current_user.id:
        raise Denied('deleting this comment')
    with db.auto_commit():
        db.session.delete(comment)

    TopicStat(tid).calculate()
    return '', 204


@api.route('/<int:tid>/comments/<int:cid>/flag', methods=['POST'])
@require_oauth(login=True)
def flag_topic_comment(tid, cid):
    key = 'flag:%d:c-%d' % (current_user.id, cid)
    if cache.get(key):
        return '', 204
    comment = get_comment_or_404(tid, cid)
    # here is a concurrency bug, but it doesn't matter
    comment.flag_count += 1
    with db.auto_commit():
        db.session.add(comment)
    # one person, one flag
    cache.inc(key)
    return '', 204


@api.route('/<int:tid>/comments/<int:cid>/likes', methods=['POST'])
@require_oauth(login=True)
def like_topic_comment(tid, cid):
    like = CommentLike.query.get((cid, current_user.id))
    if like:
        raise Conflict(description='You already liked it')

    comment = get_comment_or_404(tid, cid)
    # here is a concurrency bug, but it doesn't matter
    if comment.like_count:
        comment.like_count += 1
    else:
        comment.like_count = 1
    like = CommentLike(comment_id=comment.id, user_id=current_user.id)
    with db.auto_commit():
        db.session.add(like)
        db.session.add(comment)
    return '', 204


@api.route('/<int:tid>/comments/<int:cid>/likes', methods=['DELETE'])
@require_oauth(login=True)
def unlike_topic_comment(tid, cid):
    like = CommentLike.query.get((cid, current_user.id))
    if not like:
        raise Conflict(description='You already unliked it')

    comment = get_comment_or_404(tid, cid)
    with db.auto_commit():
        db.session.delete(like)

    with db.auto_commit(False):
        comment.reset_like_count()
    return '', 204

####################################################################


def get_comment_or_404(tid, cid):
    comment = Comment.query.get(cid)
    if not comment or comment.topic_id != tid:
        raise NotFound('Comment')
    return comment


def make_topic_response(topic):
    data = dict(topic)
    data.update(topic.get_statuses(current_user.id))
    if not topic.webpage:
        return data
    webpage = WebPage.cache.get(topic.webpage)
    if webpage:
        data['webpage'] = dict(webpage)
        data['link'] = webpage.link
    return data
