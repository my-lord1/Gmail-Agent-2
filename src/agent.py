import os
from 
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()
llm_model = "gemini-2.5-pro"
llm = ChatGoogleGenerativeAI(model = llm_model, api_key = os.getenv("GOOGLE_API_KEY"), temperature = 0)
result = llm.invoke("what is 2+4")
print(result.content)