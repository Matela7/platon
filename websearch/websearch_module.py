from __future__ import annotations

from websearch.websearch_parameters import WebSearchParameters

from langchain_community.tools import DuckDuckGoSearchResults
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper


class WebSearch:
    def __init__(self, parameters: WebSearchParameters):
        self.parameters = parameters

        self.query = parameters.query
        self.max_results = parameters.max_results
        self.wrapper = DuckDuckGoSearchAPIWrapper(
            region=parameters.region,
            safesearch=parameters.safesearch,
            time=parameters.time,
            source=parameters.source,
            max_results=parameters.max_results,
        )

    def search(self) -> list[dict]:
        search_tool = DuckDuckGoSearchResults(
            api_wrapper=self.wrapper,
            output_format="list",
        )
        results = search_tool.invoke(self.query)
        return results