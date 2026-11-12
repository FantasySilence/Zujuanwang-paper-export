# =================================== #
# @Author: Fantasy_Silence            #
# @Time: 2026-11-12                   #
# @IDE: Visual Studio Code & PyCharm  #
# @Python: 3.9.7                      #
# =================================== #
# @Description:Scrapy Item 定义。     #
# =================================== #
from __future__ import annotations

import scrapy


class PaperItem(scrapy.Item):
    """一份试卷。"""

    paper_id = scrapy.Field()      # 例如 3p2856667
    url = scrapy.Field()
    title = scrapy.Field()
    fetched_at = scrapy.Field()
    # 解析结果整体塞进来，结构和 extractor.parse_paper() 的返回值一致
    payload = scrapy.Field()
