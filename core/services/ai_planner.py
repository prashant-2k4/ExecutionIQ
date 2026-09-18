import os
import json
from dotenv import load_dotenv
from google import genai


load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


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
        model="gemini-3.7-flash",
        input=prompt,
    )

    return json.loads(interaction.output_text)