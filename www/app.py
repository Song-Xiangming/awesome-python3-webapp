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

def index(request):
	#如果要在网络上传输，或者保存到磁盘上，就需要把str变为以字节为单位的bytes
	#如果不加上content_type，进入网页会自动下载文件（一行字符：<h1>Awesome</h1>）
	return web.Response(body=b'<h1>Awesome</h1>', content_type='text/html', charset='UTF-8')
	
async def init(loop):
	app = web.Application(loop=loop)
	app.router.add_route('GET','/',index)
	srv = await loop.create_server(app.make_handler(),'127.0.0.1',8000)
	logging.info('Server started at http://127.0.0.1:8000...')
	return srv

loop = asyncio.get_event_loop()
loop.run_until_complete((init(loop)))
loop.run_forever()