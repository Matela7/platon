from langchain_community.tools import DuckDuckGoSearchResults
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper

wrapper = DuckDuckGoSearchAPIWrapper(
    max_results=20
)

search = DuckDuckGoSearchResults(
    api_wrapper=wrapper,
    output_format="list"
)

results = search.invoke("latest python 3.14 features")

for result in results:
    print(result)