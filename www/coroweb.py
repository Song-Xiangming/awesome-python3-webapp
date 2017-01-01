# -*- coding: utf-8 -*-

__author__ = 'Song-Xiangming'

import asyncio, os, inspect, logging, functools

from urllib import parse
from aiohttp import web
#apis.py还未编写
from apis import APIError

def get(path):
    '''
    Define decorator @get('/path')
    '''
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'GET'
        wrapper.__route__ = path
        return wrapper
    return decorator

def post(path):
    '''
    Define decorator @post('/path')
    '''
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'POST'
        wrapper.__route__ = path
        return wrapper
    return decorator

'''
廖大的意思是想把URL参数和GET、POST方法得到的参数彻底分离。

1. GET、POST方法的参数必需是KEYWORD_ONLY
2. URL参数是POSITIONAL_OR_KEYWORD
3. REQUEST参数要位于最后一个POSITIONAL_OR_KEYWORD之后的任何地方
'''	
	
# 获取所有没有默认值的关键字参数
def get_required_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    #inspect模块从函数fn中获取参数信息，name:变量名，param.kind:变量类型
    for name, param = in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default == inspect.Parameter.empty:
            args.append(name)
    return tuple(args)
	
# 获取所有关键字参数
def get_named_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            args.append(name)
    return tuple(args)
	
# 是否存在关键字参数
def has_named_kw_args(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            return True
			
# 是否有变长字典参数
def has_var_kw_arg(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True
			
# 是否有request参数	
def has_request_arg(fn):
    sig = inspect.signature(fn)
    params = sig.parameters
    found = False
    for name, param in params.items():
        if name == 'request':
            found = True
            continue
        if found and (param.kind != inspect.Parameter.VAR_POSITIONAL and param.kind != inspect.Parameter.KEYWORD_ONLY and param.kind != inspect.Parameter.VAR_KEYWORD):
            raise ValueError('request parameter must be after the last POSITIONAL_OR_KEYWORD in function: %s%s' % (fn.__name__, str(sig)))
    return found	
	
# 用RequestHandler()来封装一个URL处理函数
# RequestHandler是一个类，由于定义了__call__()方法，因此可以将其实例视为函数。
# RequestHandler目的就是从URL函数中分析其需要接收的参数，从request中获取必要的参数，调用URL函数，然后把结果转换为web.Response对象，这样，就完全符合aiohttp框架的要求：	
class RequestHandler(object):
	
    def __init__(self, app, fn):
        self._app = app
        self._func = fn
        self._has_request_arg = has_request_arg(fn)           # 是否有request参数
        self._has_var_kw_arg = has_var_kw_arg(fn)             # 是否有变长字典参数
        self._has_named_kw_args = has_named_kw_args(fn)       # 是否存在关键字参数
        self._named_kw_args = get_named_kw_args(fn)           # 所有关键字参数
        self._required_kw_args = get_required_kw_args(fn)     # 所有没有默认值的关键字参数

    #request是aiohttp中的request，注意观察后面怎么传入的
    async def __call__(self, request):
        kw = None
        # required_kw_args是named_kw_args的真子集，第三个条件多余
        if self._has_var_kw_arg or self._has_named_kw_args or self._required_kw_args:
            if request.method == 'POST':
                if not request.content_type:
                    return web.HTTPBadRequest('Missing Content-Type.')
                ct = request.content_type.lower()
                if ct.startswith('application/json'):
                    #request.json()可能是返回请求中json
                    params = request.json()
                    if not isinstance(params, dict):
                        return web.HTTPBadRequest('JSON body must be object.')
                        kw = params
                # 见笔记：http-关于application/x-www-form-urlencoded等字符编码的解释说明
                elif ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'):
                    params = await request.post()
                    kw = dict(**params)
                else:
                    return web.HTTPBadRequest('Unsupported Content-Type: %s' % request.content_type)
            if request.method == 'GET':
                qs = request.query_string
                if qs:
                    kw = dict()
                    for k, v in parse.parse_qs(qs, True).items():
                        kw[k] = v[0]
                        
        # 如果没有在GET或POST取得参数，直接把match_info的所有参数提取到kw
        if kw is None:
            kw = dict(**request.match_info)
        else:
            # 如果没有变长字典参数且有关键字参数，把所有关键字参数提取出来，忽略所有变长字典参数
            if not self._has_var_kw_arg and self._named_kw_args:
                # remove all unamed kw:
                copy = dict()
                for name in self._named_kw_args:
                    if name in kw:
                        copy[name] = kw[name]
                kw = copy
            # 把match_info的参数提取到kw，检查URL参数和HTTP方法得到的参数是否有重合
            # check named arg:
            for k, v in request.match_info.items():
                if k in kw:
                    logging.warning('Duplicate arg name in named arg and kw args: %s' % k)
                kw[k] = v
                
        # 把request参数提取到kw
        if self._has_request_arg:
            kw['request'] = request
            
        # 检查没有默认值的关键字参数是否已赋值
        # check required kw:
        if self._required_kw_args:
            for name in self._required_kw_args:
                if not name in kw:
                    return web.HTTPBadRequest('Missing argument: %s' % name)
        logging.info('call with args: %s' % str(kw))
        try:
            r = await self._func(**kw)
            return r
        except APIError as e:
            return dict(error=e.error, data=e.data, message=e.message)
	
# handle static files (images, JavaScripts, CSS files etc.
# 见aiohttp官方文档中Static file handling，搜add_static
def add_static(app):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    app.router.add_static('/static/', path)
    logging.info('add static %s => %s' % ('/static/', path))

#add_route函数，用来注册一个URL处理函数
def add_route(app, fn):
    method = getattr(fn, '__method__', None)
    path = getattr(fn, '__route__', None)
    if path is None or method is None:
        raise ValueError('@get or @post not defined in %s.' % str(fn))
    if not asyncio.iscoroutinefunction(fn) and not inspect.isgeneratorfunction(fn):
        fn = asyncio.coroutine(fn)
    logging.info('add route %s %s => %s(%s)' % (method, path, fn.__name__, ', '.join(inspect.signature(fn).parameters.keys())))
    app.router.add_route(method, path, RequestHandler(app, fn))	
	
'''
最后一步，把很多次add_route()注册的调用：

add_route(app, handles.index)
add_route(app, handles.blog)
add_route(app, handles.create_comment)
...
变成自动扫描：

# 自动把handler模块的所有符合条件的函数注册了:
add_routes(app, 'handlers')
'''
#add_routes()定义如下：
def add_routes(app, module_name):
    #获取目录中最后一个.的索引值, 未找到时默认返回-1
    n = module_name.rfind('.')
    if n == (-1)：
        mod = __import__(module_name, globals(), locals())
    else:
        #提取最后一个.前面的目录,并从中获取目标文件，具体用法参看笔记中博客
        name = module_name[n=1:]
        mod = getattr(__import__(module_name[:n], globals(), locals(), [name]),name)
    #dir(mod)返回mod中的属性、方法列表
    for attr in dir(mod):
        if attr.startswith('_'):
            continue
        fn = getattr(mod, attr)
        if callable(fn):
            method = getattr(fn, '__method__', None)
            path = getattr(fn, '__route__', None)
            if method and path:
                add_route(app, fn)
                
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	