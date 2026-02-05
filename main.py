import os
import asyncio
from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient
from dotenv import load_dotenv

load_dotenv()

async def main():
    # Create specialized agents
    writer = ChatAgent(
        chat_client=AzureOpenAIChatClient(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            deployment_name=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        ),
        name="Writer",
        instructions="You are a creative content writer. Generate and refine slogans based on feedback.",
    )

    reviewer = ChatAgent(
        chat_client=AzureOpenAIChatClient(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            deployment_name=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        ),
        name="Reviewer",
        instructions="You are a critical reviewer. Provide detailed feedback on proposed slogans."
    )

    # Sequential workflow: Writer creates, Reviewer provides feedback
    while True:
        task = input("\nEnter your task (or 'exit' to quit): ").strip()
        
        if task.lower() == "exit":
            print("Goodbye!")
            break
        
        if not task:
            print("Please enter a valid task.")
            continue

        # Step 1: Writer creates initial slogan
        initial_result = await writer.run(task)
        print(f"\nWriter: {initial_result}")

        # Step 2: Reviewer provides feedback
        feedback_request = f"Please review this slogan: {initial_result}"
        feedback = await reviewer.run(feedback_request)
        print(f"\nReviewer: {feedback}")

        # Step 3: Writer refines based on feedback
        refinement_request = f"Please refine this slogan based on the feedback: {initial_result}\nFeedback: {feedback}"
        final_result = await writer.run(refinement_request)
        print(f"\nFinal Slogan: {final_result}")

if __name__ == "__main__":
    asyncio.run(main())