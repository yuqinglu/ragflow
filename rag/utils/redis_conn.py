#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

import logging
import json
import uuid
import random
import time
import socket

import valkey as redis
from valkey.connection import ConnectionPool
from rag import settings
from rag.utils import singleton
from valkey.lock import Lock
import trio

# 定义ConnectionResetError，兼容Python 3.10
try:
    from socket import ConnectionResetError
except ImportError:
    # Python 3.10及以下版本没有ConnectionResetError，使用ConnectionError代替
    ConnectionResetError = ConnectionError

class RedisMsg:
    def __init__(self, consumer, queue_name, group_name, msg_id, message):
        self.__consumer = consumer
        self.__queue_name = queue_name
        self.__group_name = group_name
        self.__msg_id = msg_id
        self.__message = json.loads(message["message"])

    def ack(self):
        try:
            self.__consumer.xack(self.__queue_name, self.__group_name, self.__msg_id)
            return True
        except Exception as e:
            logging.warning("[EXCEPTION]ack" + str(self.__queue_name) + "||" + str(e))
        return False

    def get_message(self):
        return self.__message

    def get_msg_id(self):
        return self.__msg_id


@singleton
class RedisDB:
    lua_delete_if_equal = None
    LUA_DELETE_IF_EQUAL_SCRIPT = """
        local current_value = redis.call('get', KEYS[1])
        if current_value and current_value == ARGV[1] then
            redis.call('del', KEYS[1])
            return 1
        end
        return 0
    """

    def __init__(self):
        self.REDIS = None
        self.config = settings.REDIS
        self.__open__()

    def register_scripts(self) -> None:
        cls = self.__class__
        client = self.REDIS
        cls.lua_delete_if_equal = client.register_script(cls.LUA_DELETE_IF_EQUAL_SCRIPT)

    def __open__(self):
        try:
            # 构建连接参数
            connection_params = {
                'host': self.config["host"].split(":")[0],
                'port': int(self.config.get("host", ":6379").split(":")[1]),
                'db': int(self.config.get("db", 1)),
                'password': self.config.get("password"),
                'decode_responses': True,
                # 添加连接池配置，提高云环境稳定性
                'connection_pool': ConnectionPool(
                    host=self.config["host"].split(":")[0],
                    port=int(self.config.get("host", ":6379").split(":")[1]),
                    db=int(self.config.get("db", 1)),
                    password=self.config.get("password"),
                    decode_responses=True,
                    max_connections=20,  # 最大连接数
                    retry_on_timeout=True,  # 超时重试
                    socket_keepalive=True,  # 保持连接
                    socket_keepalive_options={},  # TCP keepalive
                    socket_connect_timeout=10,  # 连接超时
                    socket_timeout=30,  # 读写超时
                    health_check_interval=30,  # 健康检查间隔
                )
            }
            
            # 如果配置了user，使用用户名+密码认证
            if self.config.get("user"):
                connection_params['username'] = self.config.get("user")
                # 更新连接池配置
                connection_params['connection_pool'].connection_kwargs['username'] = self.config.get("user")
            
            self.REDIS = redis.StrictRedis(**connection_params)
            self.register_scripts()
        except Exception as e:
            logging.warning(f"Redis can't be connected: {e}")
        return self.REDIS

    def health(self):
        try:
            def _ping_operation():
                return self.REDIS.ping()
            
            if self._retry_operation(_ping_operation):
                # 使用规范的key命名进行健康检查
                health_check_key = "system/health/check"
                health_check_value = "ok"
                
                def _set_health_operation():
                    return self.REDIS.set(health_check_key, health_check_value, 3)
                
                if self._retry_operation(_set_health_operation):
                    def _get_health_operation():
                        return self.REDIS.get(health_check_key)
                    
                    return self._retry_operation(_get_health_operation) == health_check_value
            return False
        except Exception as e:
            logging.warning(f"Redis health check failed: {e}")
            return False

    def is_alive(self):
        return self.REDIS is not None and self.health()

    def exist(self, k):
        if not self.REDIS:
            return
        try:
            def _exists_operation():
                return self.REDIS.exists(k)
            
            return self._retry_operation(_exists_operation)
        except Exception as e:
            logging.warning(f"RedisDB.exist {k} got exception: {e}")
            self.__open__()

    def get(self, k):
        if not self.REDIS:
            return
        try:
            def _get_operation():
                return self.REDIS.get(k)
            
            return self._retry_operation(_get_operation)
        except Exception as e:
            logging.warning(f"RedisDB.get {k} got exception: {e}")
            self.__open__()

    def _retry_operation(self, operation, *args, **kwargs):
        """重试机制，处理连接异常"""
        max_retries = 3
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                return operation(*args, **kwargs)
            except (redis.ConnectionError, redis.TimeoutError, ConnectionResetError) as e:
                if attempt == max_retries - 1:
                    logging.warning(f"Redis operation failed after {max_retries} attempts: {e}")
                    raise
                logging.warning(f"Redis operation failed (attempt {attempt + 1}/{max_retries}): {e}")
                time.sleep(retry_delay)
                retry_delay *= 2  # 指数退避
                # 重新连接
                self.__open__()
        
        return None

    def set_obj(self, k, obj, exp=None):
        try:
            if exp is None:
                exp = settings.REDIS_DEFAULT_EXPIRE
            
            # 检查Value大小
            value_str = json.dumps(obj, ensure_ascii=False)
            if len(value_str.encode('utf-8')) > settings.REDIS_MAX_STRING_SIZE:
                logging.warning(f"RedisDB.set_obj {k} value too large: {len(value_str.encode('utf-8'))} bytes")
                return False
            
            # 添加随机化，防止雪崩
            random_exp = exp + random.randint(0, int(exp * 0.2))  # 增加0-20%的随机时间
            
            def _set_operation():
                return self.REDIS.set(k, value_str, random_exp)
            
            return self._retry_operation(_set_operation)
        except Exception as e:
            logging.warning(f"RedisDB.set_obj {k} got exception: {e}")
            self.__open__()
        return False

    def set(self, k, v, exp=None):
        try:
            if exp is None:
                exp = settings.REDIS_DEFAULT_EXPIRE
            
            # 检查Value大小
            if isinstance(v, str) and len(v.encode('utf-8')) > settings.REDIS_MAX_STRING_SIZE:
                logging.warning(f"RedisDB.set {k} value too large: {len(v.encode('utf-8'))} bytes")
                return False
            
            # 添加随机化，防止雪崩
            random_exp = exp + random.randint(0, int(exp * 0.2))  # 增加0-20%的随机时间
            
            def _set_operation():
                return self.REDIS.set(k, v, random_exp)
            
            return self._retry_operation(_set_operation)
        except Exception as e:
            logging.warning(f"RedisDB.set {k} got exception: {e}")
            self.__open__()
        return False

    def sadd(self, key: str, member: str):
        try:
            # 检查Set大小
            current_size = self.REDIS.scard(key)
            if current_size >= settings.REDIS_MAX_SET_SIZE:
                logging.warning(f"RedisDB.sadd {key} set too large: {current_size} elements")
                return False
            
            def _sadd_operation():
                return self.REDIS.sadd(key, member)
            
            return self._retry_operation(_sadd_operation)
        except Exception as e:
            logging.warning(f"RedisDB.sadd {key} got exception: {e}")
            self.__open__()
        return False

    def srem(self, key: str, member: str):
        try:
            def _srem_operation():
                return self.REDIS.srem(key, member)
            
            return self._retry_operation(_srem_operation)
        except Exception as e:
            logging.warning(f"RedisDB.srem {key} got exception: {e}")
            self.__open__()
        return False

    def smembers(self, key: str):
        try:
            def _smembers_operation():
                return self.REDIS.smembers(key)
            
            return self._retry_operation(_smembers_operation)
        except Exception as e:
            logging.warning(f"RedisDB.smembers {key} got exception: {e}")
            self.__open__()
        return None

    def zadd(self, key: str, member: str, score: float):
        try:
            # 检查ZSet大小
            current_size = self.REDIS.zcard(key)
            if current_size >= settings.REDIS_MAX_SET_SIZE:
                logging.warning(f"RedisDB.zadd {key} zset too large: {current_size} elements")
                return False
            
            def _zadd_operation():
                return self.REDIS.zadd(key, {member: score})
            
            return self._retry_operation(_zadd_operation)
        except Exception as e:
            logging.warning(f"RedisDB.zadd {key} got exception: {e}")
            self.__open__()
        return False

    def zcount(self, key: str, min: float, max: float):
        try:
            def _zcount_operation():
                return self.REDIS.zcount(key, min, max)
            
            return self._retry_operation(_zcount_operation)
        except Exception as e:
            logging.warning(f"RedisDB.zcount {key} got exception: {e}")
            self.__open__()
        return 0

    def zpopmin(self, key: str, count: int):
        try:
            def _zpopmin_operation():
                return self.REDIS.zpopmin(key, count)
            
            return self._retry_operation(_zpopmin_operation)
        except Exception as e:
            logging.warning(f"RedisDB.zpopmin {key} got exception: {e}")
            self.__open__()
        return None

    def zrangebyscore(self, key: str, min: float, max: float):
        try:
            def _zrangebyscore_operation():
                return self.REDIS.zrangebyscore(key, min, max)
            
            return self._retry_operation(_zrangebyscore_operation)
        except Exception as e:
            logging.warning(f"RedisDB.zrangebyscore {key} got exception: {e}")
            self.__open__()
        return None

    def transaction(self, key, value, exp=None):
        try:
            if exp is None:
                exp = settings.REDIS_DEFAULT_EXPIRE
            
            # 添加随机化，防止雪崩
            random_exp = exp + random.randint(0, int(exp * 0.2))  # 增加0-20%的随机时间
            
            def _transaction_operation():
                pipeline = self.REDIS.pipeline(transaction=True)
                pipeline.set(key, value, random_exp, nx=True)
                return pipeline.execute()
            
            return self._retry_operation(_transaction_operation)
        except Exception as e:
            logging.warning(f"RedisDB.transaction {key} got exception: {e}")
            self.__open__()
        return False

    def queue_product(self, queue, message) -> bool:
        try:
            def _queue_product_operation():
                payload = {"message": json.dumps(message)}
                return self.REDIS.xadd(queue, payload)
            
            return self._retry_operation(_queue_product_operation)
        except Exception as e:
            logging.warning(f"RedisDB.queue_product {queue} got exception: {e}")
            self.__open__()
        return False

    def queue_consumer(self, queue_name, group_name, consumer_name, msg_id=b">") -> RedisMsg:
        """https://redis.io/docs/latest/commands/xreadgroup/"""
        try:
            def _queue_consumer_operation():
                group_info = self.REDIS.xinfo_groups(queue_name)
                if not any(gi["name"] == group_name for gi in group_info):
                    self.REDIS.xgroup_create(queue_name, group_name, id="0", mkstream=True)
                args = {
                    "groupname": group_name,
                    "consumername": consumer_name,
                    "count": 1,
                    "block": 5,
                    "streams": {queue_name: msg_id},
                }
                messages = self.REDIS.xreadgroup(**args)
                if not messages:
                    return None
                stream, element_list = messages[0]
                if not element_list:
                    return None
                msg_id, payload = element_list[0]
                res = RedisMsg(self.REDIS, queue_name, group_name, msg_id, payload)
                return res
            
            return self._retry_operation(_queue_consumer_operation)
        except Exception as e:
            if str(e) == 'no such key':
                pass
            else:
                logging.warning(f"RedisDB.queue_consumer {queue_name} got exception: {e}")
        return None

    def get_unacked_iterator(self, queue_names: list[str], group_name, consumer_name):
        try:
            for queue_name in queue_names:
                try:
                    group_info = self.REDIS.xinfo_groups(queue_name)
                except Exception as e:
                    if str(e) == 'no such key':
                        logging.warning(f"RedisDB.get_unacked_iterator queue {queue_name} doesn't exist")
                        continue
                if not any(gi["name"] == group_name for gi in group_info):
                    logging.warning(f"RedisDB.get_unacked_iterator queue {queue_name} group {group_name} doesn't exist")
                    continue
                current_min = 0
                while True:
                    payload = self.queue_consumer(queue_name, group_name, consumer_name, current_min)
                    if not payload:
                        break
                    current_min = payload.get_msg_id()
                    logging.info(f"RedisDB.get_unacked_iterator {queue_name} {consumer_name} {current_min}")
                    yield payload
        except Exception:
            logging.exception(
                "RedisDB.get_unacked_iterator got exception: "
            )
            self.__open__()

    def get_pending_msg(self, queue, group_name):
        try:
            def _get_pending_msg_operation():
                return self.REDIS.xpending_range(queue, group_name, '-', '+', 10)
            
            return self._retry_operation(_get_pending_msg_operation)
        except Exception as e:
            if 'No such key' not in (str(e) or ''):
                logging.warning(f"RedisDB.get_pending_msg {queue} got exception: {e}")
        return []

    def requeue_msg(self, queue: str, group_name: str, msg_id: str):
        try:
            def _requeue_msg_operation():
                messages = self.REDIS.xrange(queue, msg_id, msg_id)
                if messages:
                    self.REDIS.xadd(queue, messages[0][1])
                    return self.REDIS.xack(queue, group_name, msg_id)
                return False
            
            return self._retry_operation(_requeue_msg_operation)
        except Exception as e:
            logging.warning(f"RedisDB.requeue_msg {queue} got exception: {e}")
        return False

    def queue_info(self, queue, group_name) -> dict | None:
        try:
            def _queue_info_operation():
                groups = self.REDIS.xinfo_groups(queue)
                for group in groups:
                    if group["name"] == group_name:
                        return group
                return None
            
            return self._retry_operation(_queue_info_operation)
        except Exception as e:
            if str(e) == 'no such key':
                # 队列不存在是正常情况，不需要warning
                pass
            else:
                logging.warning(f"RedisDB.queue_info {queue} got exception: {e}")
        return None

    def delete_if_equal(self, key: str, expected_value: str) -> bool:
        """
        Do follwing atomically:
        Delete a key if its value is equals to the given one, do nothing otherwise.
        """
        return bool(self.lua_delete_if_equal(keys=[key], args=[expected_value], client=self.REDIS))

    def delete(self, key) -> bool:
        try:
            def _delete_operation():
                return self.REDIS.delete(key)
            
            return self._retry_operation(_delete_operation)
        except Exception as e:
            logging.warning(f"RedisDB.delete {key} got exception: {e}")
            self.__open__()
        return False
    
    
REDIS_CONN = RedisDB()


class RedisDistributedLock:
    def __init__(self, lock_key, lock_value=None, timeout=10, blocking_timeout=1):
        self.lock_key = lock_key
        self.lock_value = lock_value or str(uuid.uuid4())
        self.timeout = timeout
        self.blocking_timeout = blocking_timeout

    def acquire(self):
        try:
            # 使用重试机制
            def _acquire_operation():
                return REDIS_CONN.delete_if_equal(self.lock_key, self.lock_value)
            
            return REDIS_CONN._retry_operation(_acquire_operation)
        except Exception as e:
            logging.warning(f"RedisDistributedLock.acquire {self.lock_key} got exception: {e}")
            return False

    async def spin_acquire(self):
        start_time = time.time()
        while time.time() - start_time < self.blocking_timeout:
            if self.acquire():
                return True
            await trio.sleep(0.1)
        return False

    def release(self):
        try:
            def _release_operation():
                return REDIS_CONN.delete_if_equal(self.lock_key, self.lock_value)
            
            return REDIS_CONN._retry_operation(_release_operation)
        except Exception as e:
            logging.warning(f"RedisDistributedLock.release {self.lock_key} got exception: {e}")
            return False
