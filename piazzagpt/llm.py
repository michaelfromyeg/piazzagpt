from langchain.chat_models import ChatAnthropic
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

# use a crappy, free model for now!
model_name = "EleutherAI/gpt-neo-2.7B"

prompt = ChatPromptTemplate.from_messages(
    [
        ("system", "You're an assistant who's good at {ability}"),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{question}"),
    ]
)

chain = prompt | ChatAnthropic(model="claude-2")
