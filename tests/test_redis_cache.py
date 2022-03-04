import uuid
import time

from redis import StrictRedis
from redis_cache import RedisCache

import pickle
import pytest
import zlib


redis_host = "redis-test-host"
client = StrictRedis(host=redis_host, decode_responses=True)
client_no_decode = StrictRedis(host=redis_host)


@pytest.fixture(scope="session", autouse=True)
def clear_cache(request):
    client.flushall()


@pytest.fixture()
def cache():
    return RedisCache(redis_client=client)


def add_func(n1, n2):
    """ Add function
    Add n1 to n2 and return a uuid4 unique verifier

    Returns:
        tuple(int, str(uuid.uuid4))
    """
    return n1 + n2, str(uuid.uuid4())


def test_basic_check(cache):
    @cache.cache()
    def add_basic(arg1, arg2):
        return add_func(arg1, arg2)

    r_3_4, v_3_4 = add_basic(3, 4)
    r_3_4_cached, v_3_4_cached = add_basic(3, 4)
    r_5_5, v_5_5 = add_basic(5, 5)

    assert 7 == r_3_4 == r_3_4_cached and v_3_4 == v_3_4_cached
    assert 10 == r_5_5 and v_5_5 != r_3_4


def test_ttl(cache):
    @cache.cache(ttl=1)
    def add_ttl(arg1, arg2):
        return add_func(arg1, arg2)

    r_1, v_1 = add_ttl(3, 4)
    r_2, v_2 = add_ttl(3, 4)
    time.sleep(2)

    r_3, v_3 = add_ttl(3, 4)

    assert 7 == r_1 == r_2 == r_3
    assert v_1 == v_2 != v_3


def test_limit(cache):
    @cache.cache(limit=2)
    def add_limit(arg1, arg2):
        return add_func(arg1, arg2)

    r_3_4, v_3_4 = add_limit(3, 4)
    # cache_queue [add_limit(3, 4)]

    r_5_5, v_5_5 = add_limit(5, 5)
    # cache_queue [add_limit(3, 4), add_limit(5, 5)]

    r_6_5, v_6_5 = add_limit(6, 5)  # limit hitted rotating
    # cache_queue [add_limit(5, 5), add_limit(6, 5)]

    r2_3_4, v2_3_4 = add_limit(3, 4)  # new cache generated
    # cache_queue [add_limit(6, 5), add_limit(3, 4)]

    # cache was rotated the first call needed to be re-executed/re-cached
    assert r_3_4 == r2_3_4 and v_3_4 != v2_3_4

    r2_6_5, v2_6_5 = add_limit(6, 5)  # still cached
    # cache_queue [add_limit(6, 5), add_limit(3, 4)]
    assert r_6_5 == r2_6_5 and v_6_5 == v2_6_5

    r3_3_4, v3_3_4 = add_limit(3, 4)  # still cached
    # cache_queue [add_limit(6, 5), add_limit(3, 4)]
    assert r2_3_4 == r3_3_4 and v2_3_4 == v3_3_4


def test_invalidate_not_in_cache(cache):
    @cache.cache()
    def add_invalidate_not_in_cache(arg1, arg2):
        return add_func(arg1, arg2)

    r_3_4, v_3_4 = add_invalidate_not_in_cache(3, 4)
    r_4_4, v_4_4 = add_invalidate_not_in_cache(4, 4)

    # calling invalidate with params that was never
    # passed should not change the cache status
    add_invalidate_not_in_cache.invalidate(5, 5)

    r2_3_4, v2_3_4 = add_invalidate_not_in_cache(3, 4)
    r2_4_4, v2_4_4 = add_invalidate_not_in_cache(4, 4)

    assert r_3_4 == r2_3_4 and v_3_4 == v2_3_4
    assert r_4_4 == r2_4_4 and v_4_4 == v2_4_4


def test_invalidate_in_cache(cache):
    @cache.cache()
    def add_invalidate_in_cache(arg1, arg2):
        return add_func(arg1, arg2)

    r_3_4, v_3_4 = add_invalidate_in_cache(3, 4)
    r_4_4, v_4_4 = add_invalidate_in_cache(4, 4)

    # we are invalidating 4, 4 so it should be re-executed next time
    add_invalidate_in_cache.invalidate(4, 4)

    r2_3_4, v2_3_4 = add_invalidate_in_cache(3, 4)
    r2_4_4, v2_4_4 = add_invalidate_in_cache(4, 4)

    assert r_3_4 == r2_3_4 and v_3_4 == v2_3_4
    # 4, 4 was invalidated a new verifier should be generated
    assert r_4_4 == r2_4_4 and v_4_4 != v2_4_4


def test_invalidate_all():
    cache = RedisCache(redis_client=client)

    @cache.cache()
    def f1_invalidate_all(arg1, arg2):
        return add_func(arg1, arg2)

    @cache.cache()
    def f2222_invalidate_all(arg1, arg2):
        return add_func(arg1, arg2)

    r_3_4, v_3_4 = f1_invalidate_all(3, 4)
    r_4_4, v_4_4 = f1_invalidate_all(4, 4)
    r_5_5, v_5_5 = f2222_invalidate_all(5, 5)

    # invalidating all caches to the function f1_invalidate_all
    f1_invalidate_all.invalidate_all()

    r2_3_4, v2_3_4 = f1_invalidate_all(3, 4)
    r2_4_4, v2_4_4 = f1_invalidate_all(4, 4)
    r2_5_5, v2_5_5 = f2222_invalidate_all(5, 5)

    # all caches related to f1_invalidate_all were invalidated
    assert r_3_4 == r2_3_4 and v_3_4 != v2_3_4
    assert r_4_4 == r2_4_4 and v_4_4 != v2_4_4

    # caches of f2222_invalidate_all should stay stored
    assert r_5_5 == r2_5_5 and v_5_5 == v2_5_5


class Result:
    def __init__(self, arg1, arg2):
        self.sum = arg1 + arg2
        self.verifier = str(uuid.uuid4())


class Arg:
    def __init__(self, value):
        self.value = value


def test_custom_serializer():
    cache = RedisCache(
        redis_client=client_no_decode,
        serializer=pickle.dumps,
        deserializer=pickle.loads,
    )

    @cache.cache()
    def add_custom_serializer(arg1, arg2):
        return Result(arg1.value, arg2.value)

    r1 = add_custom_serializer(Arg(2), Arg(3))
    r2 = add_custom_serializer(Arg(2), Arg(3))

    assert r1.sum == r2.sum and r1.verifier == r2.verifier


def test_custom_serializer_with_compress():
    def dumps(value):
        return zlib.compress(pickle.dumps(value))

    def loads(value):
        return pickle.loads(zlib.decompress(value))

    cache = RedisCache(
        redis_client=client_no_decode, serializer=dumps, deserializer=loads,
    )

    @cache.cache()
    def add_compress_serializer(arg1, arg2):
        return Result(arg1.value, arg2.value)

    r1 = add_compress_serializer(Arg(2), Arg(3))
    r2 = add_compress_serializer(Arg(2), Arg(3))

    assert r1.sum == r2.sum and r1.verifier == r2.verifier

def test_custom_key_serializer():
    def key_serializer(args, kwargs):
        return f'{args}.{kwargs}'

    cache = RedisCache(
        redis_client=client_no_decode,
        serializer=pickle.dumps,
        deserializer=pickle.loads,
        key_serializer=key_serializer
    )

    @cache.cache()
    def add_custom_key_serializer(arg1, arg2):
        return arg1 + arg2

    r1 = add_custom_key_serializer(2, 3)
    r2 = add_custom_key_serializer(2, 3)

    assert r1 == r2
    assert client.exists('rc:test_redis_cache.test_custom_key_serializer.<locals>.add_custom_key_serializer:(2, 3).{}')


def test_basic_mget(cache):
    @cache.cache()
    def add_basic_get(arg1, arg2):
        return add_func(arg1, arg2)

    r_3_4, v_3_4 = cache.mget({"fn": add_basic_get, "args": (3, 4)})[0]
    r2_3_4, v2_3_4 = add_basic_get(3, 4)

    assert r_3_4 == r2_3_4 and v_3_4 == v2_3_4


def test_same_name_method(cache):
    class A:
        @staticmethod
        @cache.cache()
        def static_method():
            return 'A'
    
    class B:
        @staticmethod
        @cache.cache()
        def static_method():
            return 'B'
    
    A.static_method() # Store the value in the cache
    B.static_method()

    key_a = A.static_method.instance.get_key([], {})
    key_b = B.static_method.instance.get_key([], {})

    # 1. Check that both keys exists
    assert client.exists(key_a)
    assert client.exists(key_b)
    
    # 2. They are different
    assert key_a != key_b
    
    # 3. And stored values are different
    assert A.static_method() != B.static_method()


def test_same_name_inner_function(cache):
    def a():
        @cache.cache()
        def inner_function():
            return 'A'
        return inner_function
    
    def b():
        @cache.cache()
        def inner_function():
            return 'B'
        return inner_function
    
    first_func = a()
    second_func = b()

    first_func() # Store the value in the cache
    second_func()
    
    first_key = first_func.instance.get_key([], {})
    second_key = second_func.instance.get_key([], {})
    
    # 1. Check that both keys exists
    assert client.exists(first_key)
    assert client.exists(second_key)
    
    # 2. They are different
    assert first_key != second_key
    
    # 3. And stored values are different
    assert first_func() != second_func()


def test_copy_old_keys(cache):
    @cache.cache(namespace='test_redis_cache.some_function') # we imitate the old behavior
    def some_function(value):
        return value
    
    @cache.cache()
    def another_function(value):
        return value
    
    # set some keys in the db with the old format
    
    some_function(1)
    some_function(2)
    some_function(3)
    another_function(1)
    another_function(2)
    another_function(3)

    assert client.exists(some_function.instance.get_key([1], {}))
    
    some_function.instance.namespace = f'{some_function.__module__}.{some_function.__qualname__}' # restore the new key format
    some_function.copy_old_keys()

    # check if the migrate keys exists and the value is correct
    assert client.exists(some_function.instance.get_key([1], {})) and some_function(1) == 1
    assert client.exists(some_function.instance.get_key([2], {})) and some_function(2) == 2
    assert client.exists(some_function.instance.get_key([3], {})) and some_function(3) == 3
    
    # check if other keys are intact
    assert client.exists(another_function.instance.get_key([1], {})) and another_function(1) == 1
    assert client.exists(another_function.instance.get_key([2], {})) and another_function(2) == 2
    assert client.exists(another_function.instance.get_key([3], {})) and another_function(3) == 3


def test_delete_old_keys(cache):
    @cache.cache(namespace='test_redis_cache.some_function') # we imitate the old behavior
    def some_function(value):
        return value
    
    @cache.cache()
    def another_function(value):
        return value
    
    some_function(1)
    some_function(2)
    some_function(3)
    another_function(1)
    another_function(2)
    another_function(3)

    assert client.exists(some_function.instance.get_key([1], {}))
    assert client.exists(another_function.instance.get_key([1], {}))

    some_function.copy_old_keys() # already tested
    some_function.delete_old_keys()

    assert not client.exists(some_function.instance.get_key([1], {}))
    assert not client.exists(some_function.instance.get_key([2], {}))
    assert not client.exists(some_function.instance.get_key([3], {}))

    # check if other keys are intact
    assert client.exists(another_function.instance.get_key([1], {}))
    assert client.exists(another_function.instance.get_key([2], {}))
    assert client.exists(another_function.instance.get_key([3], {}))
