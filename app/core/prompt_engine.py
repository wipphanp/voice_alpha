"""
Prompt engine — loads and hydrates the system prompt with runtime variables.
Supports multi-language instructions for Hindi, English, Kannada, Telugu, Malayalam, Tamil.
Injects customer memory context and the randomly-selected agent persona.
"""

from pathlib import Path

from .context import get_runtime_context

PROMPT_FILE = Path(__file__).parent.parent.parent / "prompts" / "system_prompt.md"


class PromptEngine:
    """Loads the system prompt template and injects runtime variables."""

    @staticmethod
    def get_prompt(
        customer_name: str,
        customer_phone: str,
        customer_memory: str = "",
        agent_name: str = "Priya",
        agent_gender: str = "female",
    ) -> str:
        """
        Build the fully hydrated system prompt for a specific customer call.

        Args:
            customer_name:  Customer's display name
            customer_phone: Customer's phone number with country code
            customer_memory: Formatted previous conversation history (optional)
            agent_name:     Randomly chosen agent name for this call
            agent_gender:   Agent gender ('female' or 'male')

        Returns:
            Complete system prompt string with all variables replaced
        """
        if not PROMPT_FILE.exists():
            raise FileNotFoundError(
                f"System prompt not found at {PROMPT_FILE}. "
                "Ensure prompts/system_prompt.md exists."
            )

        template = PROMPT_FILE.read_text(encoding="utf-8")
        ctx = get_runtime_context()

        # Format customer memory section
        if customer_memory:
            memory_section = (
                f"This is a returning customer. Previous interaction details:\n{customer_memory}\n"
                "Use this context to personalize the conversation — reference what they mentioned before."
            )
        else:
            memory_section = "This is the first call with this customer. No previous history available."

        # Agent self-reference pronoun hints for Hindi/Hinglish gendered verbs
        agent_hindi_verb = "रही हूँ" if agent_gender == "female" else "रहा हूँ"

        replacements = {
            "{{customer_name}}": customer_name,
            "{{customer_phone}}": customer_phone,
            "{{agent_name}}": agent_name,
            "{{agent_gender}}": agent_gender,
            "{{agent_hindi_verb}}": agent_hindi_verb,
            "{{brand_name}}": ctx["brand_name"],
            "{{product_name}}": ctx["product_name"],
            "{{company_phone}}": ctx["company_phone"],
            "{{today_human}}": ctx["today_human"],
            "{{customer_memory}}": memory_section,
            # Legacy alias kept for any remaining references
            "{{company_name}}": ctx["brand_name"],
        }

        prompt = template
        for placeholder, value in replacements.items():
            prompt = prompt.replace(placeholder, value)

        return prompt
