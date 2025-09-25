# src/tools/search_tools.py
from langchain_tavily import TavilySearch
from langchain_core.tools import tool
from ..core.rate_limiter import rate_limited


class SearchTools:
    """搜索工具集合"""

    def __init__(self):
        self.tavily = TavilySearch(max_results=3)

    @rate_limited('tavily')
    async def search(self, query: str):
        """带限流的搜索"""
        try:
            return await self.tavily.ainvoke(query)
        except Exception as e:
            print(f"⚠️ 搜索失败: {e}")
            return None

    @tool(parse_docstring=True)
    def think_tool(self, reflection: str) -> str:
        """战略反思工具（不需要限流）"""
        return f"Reflection recorded: {reflection}"