"""知识库（公司资料库）：跨任务共享的投标资料层。

模块：
- types.py     类型注册表（封闭）+ 元数据抽取 prompt
- store.py     磁盘布局（workspace/knowledge/{files,parse}）
- segmenter.py 检索切段（outline 节点 → FTS 段）
- fts.py       jieba 双侧分词 + MATCH 表达式
- ingest.py    入库管线（解析 → 切段索引 → 元数据抽取；图片/扫描页走 VL）
"""
