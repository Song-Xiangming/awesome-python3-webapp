#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'Song Xiangming'

'''
async web application.
'''
#level设置日志的级别
import logging; logging.basicConfig(level=logging.INFO)

import asyncio, os, json, time
from datetime import datetime

from aiohttp import web
from jinja2 import Environment, FileSystemLoader

import orm
from coroweb import add_routes, add_static

from handlers import cookie2user, COOKIE_NAME

'''
一个middleware可以改变URL的输入、输出，甚至可以决定不继续处理而直接返回。
middleware的用处就在于把通用的功能从每个URL处理函数中拿出来，集中放到一个地方。
例如，一个记录URL日志的logger可以简单定义如下：
'''
async def logger_factory(app,handler):
    async def logger(request):
        logging.info('Request: %s %s' % (request.method, request.path))
        return (await handler(request))
    return logger

# 利用middle在处理URL之前，把cookie解析出来，并将登录用户绑定到request对象上，这样，后续的URL处理函数就可以直接拿到登录用户：    
# day15注释：把当前用户绑定到request上，并对URL/manage/进行拦截，检查当前用户是否是管理员身份：
async def auth_factory(app, handler):
    async def auth(request):
        logging.info('check user: %s %s' % (request.method, request.path))
        request.__user__ = None
        cookie_str = request.cookies.get(COOKIE_NAME)
        if cookie_str:
            user = await cookie2user(cookie_str)
            if user:
                logging.info('set current user: %s' % user.email)
                request.__user__ = user
        if request.path.startswith('/manage/') and (request.__user__ is None or not request.__user__.admin):
            return web.HTTPFound('/signin')
        return (await handler(request))
    return auth    

	
'''
可参考灰_手的回答：你可以参考我的data_factory的实现。
如果method == 'GET'时，参数就是查询字符串，也就是request.query_string
如果method == 'POST'时，有两种可能，Ajax的json和html的form(表单)，分别对应request.json()和request.post()。 
data_factory的主要作用就是把这些参数统一绑定在request.__data__上。
'''
#day5暂时未使用
async def data_factory(app, handler):
    async def parse_data(request):
        if request.method == 'POST':
            if request.content_type.startswith('application/json'):
                request.__data__ = await request.json()
                logging.info('request json: %s' % str(request.__data__))
            elif request.content_type.startswith('application/x-www-form-urlencoded'):
                request.__data__ = await request.post()
                logging.info('request form: %s' % str(request.__data__))

#response这个middleware把返回值转换为web.Response对象再返回，以保证满足aiohttp的要求：
async def response_factory(app, handler):
    async def response(request):
        logging.info('Response handler...')
        r = await handler(request)
        #A StreamReader instance, input stream for reading request’s BODY.官方文档中的标准返回值web.Response()的类型
        if isinstance(r, web.StreamResponse):
            return r
        #任意的二进制数据 application/octet-stream，要加上content_type
        if isinstance(r, bytes):
            resp = web.Response(body=r)
            resp.content_type = 'application/octet-stream'
            return resp
        if isinstance(r, str):
            #重定向请求，302已找到
            if r.startswith('redirect:'):
                return web.HTTPFound(r[9:])
            resp = web.Response(body=r.encode('utf-8'))
            resp.content_type = 'text/html;charset=utf-8'
            return resp
        # 没懂,懂一点如果有template,
        if isinstance(r, dict):
            template = r.get('__template__')
            if template is None:
                # json.dumps方法对简单数据类型encoding;  类的__dict__属性时，列出了类cls所包含的属性，包括一些类内置属性和类变量clsvar以及构造方法__init__
                resp = web.Response(body=json.dumps(r, ensure_ascii=False, default=lambda o: o.__dict__).encode('utf-8'))
                resp.content_type = 'application/json;charset=utf-8'
                return resp
            else:
                # 这里如何读取的模版？看完jinja2官方文档得知，详见笔记
                resp = web.Response(body=app['__templating__'].get_template(template).render(**r).encode('utf-8'))
                resp.content_type = 'text/html;charset=utf-8'
                return resp
        # Http Response Code状态码范围100~600
        if isinstance(r, int) and r >= 100 and r < 600:
            return web.Response(r)
        # 目测是状态码 + description
        if isinstance(r, tuple) and len(r) == 2:
            t, m = r
            if isinstance(t, int) and t >= 100 and t < 600:
                return web.Response(t, str(m))
        # default:
        resp = web.Response(body=str(r).encode('utf-8'))
        resp.content_type = 'text/plain;charset=utf-8'
        return resp
    return response

def datetime_filter(t):
    delta = int(time.time() - t)
    if delta < 60:
        return u'1分钟前'
    if delta < 3600:
        return u'%s分钟前' % (delta // 60)
    if delta < 86400:
        return u'%s小时前' % (delta // 3600)
    if delta < 604800:
        return u'%s天前' % (delta // 86400)
    dt = datetime.fromtimestamp(t)
    return u'%s年%s月%s日' % (dt.year, dt.month, dt.day)

# 初始化jinja2模板
def init_jinja2(app, **kw):
    logging.info('init jinja2...')
    options = dict(
        autoescape = kw.get('autoescape', True),
        block_start_string = kw.get('block_start_string', '{%'),
        block_end_string = kw.get('block_end_string', '%}'),
        variable_start_string = kw.get('variable_start_string', '{{'),
        variable_end_string = kw.get('variable_end_string', '}}'),
        auto_reload = kw.get('auto_reload', True)
    )
    path = kw.get('path', None)
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    logging.info('set jinja2 template path: %s' % path)
    # 在这里初始化模版配置
    env = Environment(loader=FileSystemLoader(path), **options)
    filters = kw.get('filters', None)
    if filters is not None:
        for name, f in filters.items():
            env.filters[name] = f
    app['__templating__'] = env
		
async def init(loop):
    await orm.create_pool(loop=loop, host='127.0.0.1', port=3306, user='root', password='123456', db='awesome')
    # Day5 在app.py中加入middleware、jinja2模板和自注册的支持
    # logger_factory, response_factory是两个拦截器，init_jinja2初始化jinja2，这3个都在上方实现
    # Day10 绑定了auth_factory拦截器，用于将登录用户绑定到request对象上
    app = web.Application(loop=loop, middlewares=[
        logger_factory, auth_factory, response_factory
    ])
    init_jinja2(app, filters=dict(datetime=datetime_filter))
    add_routes(app, 'handlers')
    add_static(app)

    srv = await loop.create_server(app.make_handler(),'127.0.0.1',8000)
    logging.info('Server started at http://127.0.0.1:8000...')
    return srv

loop = asyncio.get_event_loop()
loop.run_until_complete((init(loop)))
loop.run_forever()