"""M1: embedding cache get_embedding 无锁读取"""
import inspect
from core.cache import get_embedding


def test_m1_get_embedding_should_acquire_lock():
    """get_embedding 应在读取 _cache 前获取 _lock，防止并发修改时的 RuntimeError"""
    src = inspect.getsource(get_embedding)

    uses_lock = "_lock" in src or "acquire" in src

    assert uses_lock, (
        "get_embedding 应在读取 _cache 前获取 _lock。"
        "当前 set_embedding 和 clear_resume 使用锁，但 get_embedding 没有，"
        "并发读/写可能导致 dict changed size during iteration 错误。"
    )