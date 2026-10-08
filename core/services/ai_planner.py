import os
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY"),
    http_options=types.HttpOptions(
        timeout=60000,
        retry_options=types.HttpRetryOptions(
            attempts=1,
        ),
    ),
)

def generate_goal_plan(goal_text):
    prompt = f"""
You are the AI planning component of ExecutionIQ.

User goal:
{goal_text}

Break this goal into realistic, meaningful tasks.

For each task provide:
- title
- estimated_hours
- priority

Also calculate the total estimated hours.

Return ONLY valid JSON.
"""

    interaction = client.interactions.create(
        model="gemini-3.5-flash-lite",
        input=prompt,
    )

    return json.loads(interaction.output_text)