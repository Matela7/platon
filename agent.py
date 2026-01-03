from langchain_google_genai import ChatGoogleGenerativeAI
from agents_tools import create_search_tools
from client_manager import ClientManager
# from langchain.memory import ConversationSummaryBufferMemory
from langchain.chat_models import init_chat_model
import os
from dotenv import load_dotenv

# # load .env file to environment
# load_dotenv()

# model = ChatGoogleGenerativeAI(
#     model="gemini-1.5-flash",
#     temperature=0.2
# )

# tools = [
#     search_collection,
#     search_all_collections,
#     get_searchapi_tool()
# ]

# # short_memory = ConversationSummaryBufferMemory(
# #     llm=llm,
# #     memory_key="chat_history",
# #     return_messages=True,
# #     max_token_limit=2000,
# # )


# cm = ClientManager(persist_dir="./chroma_data")

# agent = init_chat_model(
#     llm=model,
#     tools=tools,    
#     prompt=(
#         "You are an intelligent agent that can search document collections "
#         "and the web to provide accurate and relevant information. "
#         "Use the tools at your disposal to find the best answers."
#         "Write in a user language."
#     ),
#     verbose=True,
# )

# result = agent.invoke({
#     "input": "Find information about duda andrzej'environment' collection and provide recent web search results."
# })
# load .env file to environment
load_dotenv()

model = ChatGoogleGenerativeAI(
    model="gemini-flash-lite-latest",
    temperature=0.2
)

cm = ClientManager(persist_dir="./chroma_data")
tools = create_search_tools(cm)

# Bind tools directly to the model
agent = model.bind_tools(tools)

result = agent.invoke(
    "Find information about duda andrzej'environment' collection and provide recent web search results."
)

print(result)