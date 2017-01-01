# -*- coding: utf-8 -*-

__author__ = 'Song-Xiangming'

'''
选择MySQL作为网站的后台数据库
 
执行SQL语句进行操作，并将常用的SELECT、INSERT等语句进行函数封装
 
在异步框架的基础上，采用aiomysql作为数据库的异步IO驱动
 
将数据库中表的操作，映射成一个类的操作，也就是数据库表的一行映射成一个对象(ORM)
 
整个ORM也是异步操作
 
预备知识：Python协程和异步IO(yield from的使用)、SQL数据库操作、元类、面向对象知识、Python语法
 
# -*- -----  思路  ----- -*-
    如何定义一个user类，这个类和数据库中的表User构成映射关系，二者应该关联起来，user可以操作表User
     
    通过Field类将user类的属性映射到User表的列中，其中每一列的字段又有自己的一些属性，包括数据类型，列名，主键和默认值
'''

import asyncio, logging
import aiomysql

#打印SQL查询语句
def log(sql, args=()):
    logging.info('SQL: %s' % sql)
	
# 创建一个全局的连接池，每个HTTP请求都从池中获得数据库连接
async def create_pool(loop, **kw):
    logging.info('create database connection pool...')
    # 全局变量__pool用于存储整个连接池
    global __pool
    __pool = await aiomysql.create_pool(
        # **kw参数可以包含所有连接需要用到的关键字参数
        # 默认本机IP
        host = kw.get('host','localhost'),
        port = kw.get('port',3306),
        user = kw['user'],
        password = kw['password'],
        db = kw['db'],
        charset = kw.get('charset','utf8'),
        autocommit = kw.get('autocommit',True),
        # 默认最大连接数为10
        maxsize = kw.get('maxsize',10),
        minsize = kw.get('minsize',1),
        # 接收一个event_loop实例
        loop = loop
    ) 


async def destory_pool():
    global __pool
    if __pool is not None :
        __pool.close()
        await __pool.wait_closed()
	
# 封装SQL SELECT语句为select函数
async def select(sql, args, size=None):
    log(sql,args)
    global __pool

    # 这里与教程有了几处新的变化，协程中又调用很多子协程
    # -*- yield from 将会调用一个子协程，并直接返回调用的结果
    # yield from/await从连接池中返回一个连接
    async with __pool.get() as conn:
        # 原：cur = yield from conn.cursor(aiomysql.DictCursor)
        # DictCursor is a cursor which returns results as a dictionary
        # cur类似JDBC中的PreparedStatement
        async with conn.cursor(aiomysql.DictCursor) as cur:		
            # 执行SQL语句
            # SQL语句的占位符为?，MySQL的占位符为%s
            await cur.execute(sql.replace('?','%s'), args or ())
            # 根据指定返回的size，返回查询的结果
            if size:
                # 返回size条查询结果
                rs = await cur.fetchmany(size)
            else:
                # 返回所有查询结果
                rs = await cur.fetchall()
            logging.info('rows returned: %s' % len(rs))
            #用完conn必须关闭，不然报RuntimeError: Event loop is closed
            conn.close()
            return rs
			
# 封装INSERT, UPDATE, DELETE
# 语句操作参数一样，所以定义一个通用的执行函数
# 返回操作影响的行号
async def execute(sql, args, autocommit=True):
    log(sql)
    async with __pool.get() as conn:
        if not autocommit:
            await conn.begin()
        try:
            # (原版中)execute类型的SQL操作返回的结果只有行号，所以不需要用DictCursor，这里还是要了
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql.replace('?','%s'), args)
                affected = cur.rowcount
            if not autocommit:
                await conn.commit()
        except BaseException as e:
            if not autocommit:
                await conn.rollback()
            #错误向外抛
            raise
        finally:
            #防止event loop is closed错误，执行完SQL语句，要释放与数据库的连接。
            conn.close()
        return affected
	
# 根据输入的参数生成占位符列表
def create_args_string(num):
    L = []
    for n in range(num):
        L.append('?')
        # 以','为分隔符，将列表合成字符串
    return ','.join(L)
	
# 定义Field类，负责保存(数据库)表的字段名和字段类型
class Field(object):
    # 表的字段包含名字、类型、是否为表的主键和默认值
    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default
        
    # 打印输出(数据库)表的信息:类名，字段类型和名字
    def __str__(self):
        return '<%s, %s:%s>' % (self.__class__.__name__, self.column_type, self.name)

# -*- 定义不同类型的衍生Field -*-
# -*- 表的不同列的字段的类型不一样		
class StringField(Field):
	
    def __init__(self, name=None, primary_key=False, default=None, ddl='varchar(100)'):
        super().__init__(name, ddl, primary_key, default)

class BooleanField(Field):
	
    def __init__(self, name=None, default=False):
        super().__init__(name, 'boolean', False, default)

class IntegerField(Field):
	
    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'bigint', primary_key, default)

class FloatField(Field):
	
    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'real', primary_key, default)

class TextField(Field):
	
    def __init__(self, name=None, primary_key=False, default=None):
        super().__init__(name, 'text', primary_key, default)

# -*-定义Model的元类
 
# 所有的元类都继承自type
# ModelMetaclass元类定义了所有Model基类(继承ModelMetaclass)的子类实现的操作
 
# -*-ModelMetaclass的工作主要是为一个数据库表映射成一个封装的类做准备：
# ***读取具体子类(user)的映射信息
# 创造类的时候，排除对Model类的修改
# 在当前类中查找所有的类属性(attrs)，如果找到Field属性，就将其保存到__mappings__的dict中，同时从类属性中删除Field(防止实例属性遮住类的同名属性)
# 将数据库表名保存到__table__中
 
# 完成这些工作就可以在Model中定义各种数据库的操作方法

class ModelMetaclass(type):
	
    # __new__控制__init__的执行，所以在其执行之前
    # cls: 代表要__init__的类，此参数在实例化时由Python解释器自动提供(例如下文的User和Model),相当于实例对应self,类对应cls
    # name:	代表类名
    # bases：代表继承父类的集合
    # attrs：类的方法集合
    def __new__(cls, name, bases, attrs):		
        #排除对Model类的修改
        if name == 'Model':
            return type.__new__(cls, name, bases, attrs)
        
        #有表名用表名，没表名用类名
        tableName = attrs.get('__table__', None) or name
        logging.info('found model: %s (table: %s)' % (name, tableName))
        
        #获取Field和主键名
        mappings = dict()
        fields = []
        primaryKey = None
        for k, v in attrs.items():
            # v是Field对象或子对象
            if isinstance(v, Field):
                ## 此处打印的k是类的一个属性，v是这个属性在数据库中对应的Field列表属性
                logging.info('  found mapping: %s ==> %s' % (k, v))
                mappings[k] = v
                # 找到主键
                if v.primary_key:
                    # 如果此时类实例的以存在主键，说明主键重复了
                    if primaryKey:
                        raise StandardError('Duplicate primary key for field: %s' % k)
                    # 否则将此列设为列表的主键
                    primaryKey = k
                else:
                    fields.append(k)
        # end for
        
        if not primaryKey:
            raise StandardError('Primary key not found.')
            
        # 从类属性中删除Field属性
        for k in mappings.keys():
            attrs.pop(k)
        # 保存除主键外的属性名为``（运算出字符串）列表形式
        escaped_fields = list(map(lambda f: '`%s`' % f,fields))
        # 保存属性和列的映射关系
        attrs['__mappings__'] = mappings # 保存属性和列的映射关系
        # 保存表名
        attrs['__table__'] = tableName
        # 保存主键属性名
        attrs['__primary_key__'] = primaryKey 
        # 保存主键外的属性名
        attrs['__fields__'] = fields 
        # 构造默认的SELECT、INSERT、UPDATE、DELETE语句
        # ``反引号功能同repr()，详见笔记
        attrs['__select__'] = 'select `%s`, %s from `%s`' % (primaryKey, ', '.join(escaped_fields), tableName)
        attrs['__insert__'] = 'insert into `%s` (%s, `%s`) values (%s)' % (tableName, ', '.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields) + 1))
        attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (tableName, ', '.join(map(lambda f: '`%s`=?' % (mappings.get(f).name or f), fields)), primaryKey)
        attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (tableName, primaryKey)
        return type.__new__(cls, name, bases, attrs)
					
# 定义ORM所有映射的基类：Model
# Model类的任意子类可以映射一个数据库表
# Model类可以看作是对所有数据库表操作的基本定义的映射
 
 
# 基于字典查询形式
# Model从dict继承，拥有字典的所有功能，同时实现特殊方法__getattr__和__setattr__，能够实现属性操作
# 实现数据库操作的所有方法，定义为class方法，所有继承自Model都具有数据库操作方法				
class Model(dict, metaclass=ModelMetaclass):

    def __init__(self, **kw):
        super(Model, self).__init__(**kw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Model' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value

    def getValue(self, key):
        # 内建函数getattr会自动处理
        return getattr(self, key, None)
        
    #该方法获取某个属性的值，如果该对象的该属性还没有赋值，就去获取它对应的列的默认值。详解见笔记
    def getValueOrDefault(self, key):
        value = getattr(self, key, None)
        if value is None:
            field = self.__mappings__[key]
            if field.default is not None:
                #callable即可调用，需实现__call__()方法才可调用，default参数有时候是一个方法
                value = field.default() if callable(field.default) else field.default
                logging.debug('using default value for %s: %s' % (key, str(value)))
                setattr(self, key, value)
        return value

    # @classmethod是为了将方法变成类方法,async则是为了做异步处理。
    # 类方法有类变量cls传入，从而可以用cls做一些相关的处理。并且有子类继承时，调用该类方法时，传入的类变量cls是子类，而非父类。
    @classmethod
    async def findAll(cls, where=None, args=None, **kw):
        # 根据WHERE条件查找
        ' find objects by where clause. '
        sql = [cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args = []
        orderBy = kw.get('orderBy', None)
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        # select * from table limit m,n；指从第m+1条开始，取n条。
        limit = kw.get('limit', None)
        if limit is not None:
            sql.append('limit')
            if isinstance(limit, int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit, tuple) and len(limit) == 2:
                sql.append('?, ?')
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value: %s' % str(limit))
        rs = await select(' '.join(sql), args)
        return [cls(**r) for r in rs]

    @classmethod
    async def findNumber(cls, selectField, where=None, args=None):
        # 根据WHERE条件查找，但返回的是整数，适用于select count(*)类型的SQL
        ' find number by select and where. '
        sql = ['select %s _num_ from `%s`' % (selectField, cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        rs = await select(' '.join(sql), args, 1)
        if len(rs) == 0:
            return None
        return rs[0]['_num_']

    @classmethod
    async def find(cls, pk):
        # 通过类方法实现主键查找
        ' find object by primary key. '
        rs = await select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__), [pk], 1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])

    #依次增，改，删
    async def save(self):
        print('save begin!')
        args = list(map(self.getValueOrDefault, self.__fields__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = await execute(self.__insert__, args)
        if rows != 1:
            logging.warn('failed to insert record: affected rows: %s' % rows)

    async def update(self):
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = await execute(self.__update__, args)
        if rows != 1:
            logging.warn('failed to update by primary key: affected rows: %s' % rows)

    async def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = await execute(self.__delete__, args)
        if rows != 1:
            logging.warn('failed to remove by primary key: affected rows: %s' % rows)					
					
#测试
'''
class User(Model):

    __table__ = 'user'

    # 定义类的属性到列的映射：
    id = IntegerField('id',primary_key=True)
    name = StringField('username')
    email = StringField('email')
    password = StringField('password')
	
	
#创建异步事件的句柄
loop = asyncio.get_event_loop()

#创建实例
async def test():
    await create_pool(loop=loop, host='localhost', port=3306, user='root', password='123456', db='myorm')

    #1.save()通过
    #user = User(id=12, name='bob',email='544479929@qq.com',password='113006')
    #await user.save()

    #2.find()通过，但有异常
    r = await User.find('10')
    print(r)

    #3.findAll()通过，但有异常
    #r = await User.findAll()
    #print(r)

    #4.findAll()带where参,通过，但有异常
    #r = await User.findAll('id=12')
    #print(r)

    #5.remove()通过
    #a = User(id=13, name='tab',email='5000000@qq.com',password='00126')
    #await a.save()
    #print(a)
    #a = await User.find('13')
    #print(a)
    #await a.remove()


loop.run_until_complete(test())
loop.close()
#if loop.is_closed():
#    sys.exit(0)
'''					
					
					
					
					
					
					
					
					
					
					
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	





























