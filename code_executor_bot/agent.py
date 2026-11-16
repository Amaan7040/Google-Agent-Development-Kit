from google.adk.agents.llm_agent import Agent
from google.adk.code_executors import BuiltInCodeExecutor

root_agent = Agent(
    model='gemini-3.5-flash',
    name='root_agent',
    description='A helpful assistant for user questions who can also execute code to give meaningful insights from the data.',
    instruction=('''Answer user questions to the best of your knowledge
    If the user question requires code execution, use the built-in code executor to first write the python code then run the python code and provide insights from the data. Ensure that the code is safe and does not perform any malicious actions and gives meaningful informations.'''),

    code_executor=[BuiltInCodeExecutor()],
)
