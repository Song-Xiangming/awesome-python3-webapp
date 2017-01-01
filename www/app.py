#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'Song Xiangming'

'''
async web application.
'''
#level������־�ļ���
import logging; logging.basicConfig(level=logging.INFO)

import asyncio, os, json, time
from datetime import datetime

from aiohttp import web
from jinja2 import Environment, FileSystemLoader

import orm
from coroweb import add_routes, add_static

'''
һ��middleware���Ըı�URL�����롢������������Ծ��������������ֱ�ӷ��ء�
middleware���ô������ڰ�ͨ�õĹ��ܴ�ÿ��URL���������ó��������зŵ�һ���ط���
���磬һ����¼URL��־��logger���Լ򵥶������£�
'''
async def logger_factory(app,handler):
	async def logger(request):
		logging.info('Request: %s %s' % (request.method, request.path))
		return (await handler(request))
	return logger
	
'''
�ɲο���_�ֵĻش�����Բο��ҵ�data_factory��ʵ�֡�
���method == 'GET'ʱ���������ǲ�ѯ�ַ�����Ҳ����request.query_string
���method == 'POST'ʱ�������ֿ��ܣ�Ajax��json��html��form(��)���ֱ��Ӧrequest.json()��request.post()�� 
data_factory����Ҫ���þ��ǰ���Щ����ͳһ����request.__data__�ϡ�
'''
#day5��ʱδʹ��
async def data_factory(app, handler):
	async def parse_data(request):
		if request.method == 'POST':
			if request.content_type.startswith('application/json'):
				request.__data__ = await request.json()
				logging.info('request json: %s' % str(request.__data__))
			elif request.content_type.startswith('application/x-www-form-urlencoded'):
				request.__data__ = await request.post()
				logging.info('request form: %s' % str(request.__data__))

#response���middleware�ѷ���ֵת��Ϊweb.Response�����ٷ��أ��Ա�֤����aiohttp��Ҫ��
async def response_factory(app, handler):
	async def response(request):
		logging.info('Response handler...')
		r = await handler(request)
		#A StreamReader instance, input stream for reading request��s BODY.�ٷ��ĵ��еı�׼����ֵweb.Response()������
		if isinstance(r, web.StreamResponse):
			return r
		#����Ķ��������� application/octet-stream��Ҫ����content_type
		if isinstance(r, bytes):
			resp = web.Response(body=r)
			resp.content_type = 'application/octet-stream'
			return resp
		if isinstance(r, str):
			#�ض�������302���ҵ�
			if r.startswith('redirect:'):
				return web.HTTPFound(r[9:])
			resp = web.Response(body=r.encode('utf-8'))
			resp.content_type = 'text/html;charset=utf-8'
			return resp
		#û��
		if isinstance(r, dict):
			template = r.get('__template__')
			if template is None:
				resp = web.Response(body=json.dumps(r, ensure_ascii=False, default=lambda o: o.__dict__).encode('utf-8'))
				resp.content_type = 'application/json;charset=utf-8'
				return resp
			else:
				resp = web.Response(body=app['__templating__'].get_template(template).render(**r).encode('utf-8'))
				resp.content_type = 'text/html;charset=utf-8'
				return resp
		#Http Response Code״̬�뷶Χ100~600
		if isinstance(r, int) and r >= 100 and r < 600:
			return web.Response(r)
		#Ŀ����״̬�� + description
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
			return u'1����ǰ'
		if delta < 3600:
			return u'%s����ǰ' % (delta // 60)
		if delta < 86400:
			return u'%sСʱǰ' % (delta // 3600)
		if delta < 604800:
			return u'%s��ǰ' % (delta // 86400)
		dt = datetime.fromtimestamp(t)
		return u'%s��%s��%s��' % (dt.year, dt.month, dt.day)

# ��ʼ��jinja2ģ��
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
	# �������ʼ��ģ������
	env = Environment(loader=FileSystemLoader(path), **options)
	filters = kw.get('filters', None)
	if filters is not None:
		for name, f in filters.items():
			env.filters[name] = f
	app['__templating__'] = env
		
'''
def index(request):
	# ���Ҫ�������ϴ��䣬���߱��浽�����ϣ�����Ҫ��str��Ϊ���ֽ�Ϊ��λ��bytes
	# ���������content_type��������ҳ���Զ������ļ���һ���ַ���<h1>Awesome</h1>��
	return web.Response(body=b'<h1>Awesome</h1>', content_type='text/html', charset='UTF-8')
'''
async def init(loop):
	await orm.create_pool(loop=loop, host='127.0.0.1', port=3306, user='root', password='123456', db='awesome')
	# Day5 ��app.py�м���middleware��jinja2ģ�����ע���֧��
	# logger_factory, response_factory��������������init_jinja2��ʼ��jinja2����3�������Ϸ�ʵ��
	app = web.Application(loop=loop, middlewares=[
		logger_factory, response_factory
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