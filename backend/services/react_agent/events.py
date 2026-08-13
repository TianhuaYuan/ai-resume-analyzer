"""SSE 事件协议版本号。

实时 SSE 事件（agent_start / tool_call / tool_result / tool_stream /
answer_token / agent_done / approval_request 等）由 streaming.py 以裸 dict
构造并经 envelope() 附加协议元数据。本模块仅承载协议版本常量。

（存量 text/thinking/toolcall 事件族构造器从未在实时 SSE 路径使用，已移除。）
"""

PROTOCOL_VERSION = "1"
