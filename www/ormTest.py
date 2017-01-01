# -*- coding: utf-8 -*-
# 数据库访问代码--测试orm

import orm, asyncio
from models import User, Blog, Comment

loop = asyncio.get_event_loop()
async def test():
	#schema.sql偷么建了个www-data用户我都没注意 
	await orm.create_pool(loop=loop, user='www-data', password='www-data', db='awesome')
	
	u = User(name='Test2', email='test@example.com', passwd='123456', image='about:blank')
	
	await u.save()

loop.run_until_complete(test())
loop.close()