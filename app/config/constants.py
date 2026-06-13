"""
Application constants — Alpha Bot AI / Winners Paradise Trading Subscription Agent.
"""

import random

# ─── Company / Brand Configuration ────────────────────────────────────────
BRAND_NAME = "Winners Paradise"          # Brand the agent represents
PRODUCT_NAME = "Alpha Bot AI"            # Product being sold
COMPANY_PHONE = "+91 98456 54231"
COMPANY_EMAIL = "support@alphabotai.com"
COMPANY_WEBSITE = "https://alphabotai.com"

# Keep COMPANY_NAME as alias for legacy references
COMPANY_NAME = BRAND_NAME

# ─── Agent Name Pools ──────────────────────────────────────────────────────
# The agent introduces herself/himself by one of these Indian names randomly.
AGENT_FEMALE_NAMES = [
    "Priya", "Ananya", "Sneha", "Kavya", "Divya",
    "Riya", "Pooja", "Meera", "Ishita", "Nandini",
    "Shruti", "Aditi", "Simran", "Neha", "Pallavi",
]

AGENT_MALE_NAMES = [
    "Arjun", "Rohan", "Vikram", "Karthik", "Aditya",
    "Rahul", "Suresh", "Nikhil", "Amit", "Siddharth",
    "Varun", "Dev", "Kabir", "Shubham", "Manish",
]

# ─── TTS Voice Options (Sarvam Bulbul v3) ─────────────────────────────────
# Official valid speaker list for bulbul:v3 (from Sarvam docs):
# Male: shubh, aditya, rahul, rohan, amit, dev, ratan, varun, manan, sumit,
#       kabir, aayan, ashutosh, advait, anand, tarun, sunny, mani, gokul,
#       vijay, mohit, rehan, soham
# Female: ritu, priya, neha, pooja, simran, kavya, ishita, shreya, roopa,
#         tanya, shruti, suhani, kavitha, rupali
# Source: https://docs.sarvam.ai/api-reference-docs/api-guides-tutorials/text-to-speech/how-to/change-the-speaker-voice

# Female voices (warm, soft — for male customers)
TTS_FEMALE_VOICES = [
    "ritu", "priya", "neha", "pooja", "simran", "kavya",
    "ishita", "shreya", "roopa", "tanya", "shruti",
    "suhani", "kavitha", "rupali",
]

# Male voices (confident, warm — for female customers)
TTS_MALE_VOICES = [
    "shubh", "aditya", "rahul", "rohan", "amit", "dev",
    "ratan", "varun", "manan", "sumit", "kabir", "aayan",
    "ashutosh", "advait", "anand", "tarun", "sunny", "mani",
    "gokul", "vijay", "mohit", "rehan", "soham",
]

# Legacy alias
AVAILABLE_VOICES = {
    "female": TTS_FEMALE_VOICES,
    "male":   TTS_MALE_VOICES,
}

# ─── Gender Detection ──────────────────────────────────────────────────────
# Common Indian male name endings/patterns (heuristic, good enough for routing)
_MALE_NAME_ENDINGS = (
    "raj", "rajan", "ram", "deep", "jit", "nath", "esh", "esh",
    "dev", "kar", "han", "pal", "oor", "var", "mil",
)
_KNOWN_MALE_NAMES = {
    "rahul", "rohan", "arjun", "vikram", "karthik", "aditya", "suresh",
    "nikhil", "amit", "siddharth", "varun", "dev", "kabir", "shubham",
    "manish", "pruthvi", "veeru", "raj", "rajesh", "manoj", "sandeep",
    "deepak", "ramesh", "suresh", "mahesh", "ganesh", "naresh", "mukesh",
    "dinesh", "ritesh", "hitesh", "umesh", "yogesh", "kamlesh", "devesh",
    "rakesh", "lokesh", "nilesh", "brijesh", "jayesh", "paresh", "rajesh",
    "ravi", "sanjay", "vijay", "ajay", "uday", "akshay", "abhay", "mohan",
    "sohan", "roshan", "kishan", "krishan", "bharat", "gaurav", "pranav",
    "arnav", "aniket", "anurag", "anubhav", "anand", "ankit", "ankur",
    "harsh", "hemant", "himanshu", "hiren", "ishan", "jatin", "jeet",
    "kapil", "kunal", "lalit", "mayur", "neeraj", "nitin", "pankaj",
    "parth", "parag", "prakash", "praveen", "preet", "puneet", "sachin",
    "sahil", "salil", "samir", "sameer", "sharad", "shivam", "shiv",
    "tanmay", "tarun", "tushar", "uday", "umang", "vikas", "vinay",
    "vivek", "yash", "abhishek", "akash", "alok", "avinash",
}
_KNOWN_FEMALE_NAMES = {
    "priya", "ananya", "sneha", "kavya", "divya", "riya", "pooja",
    "meera", "ishita", "nandini", "shruti", "aditi", "simran", "neha",
    "pallavi", "preeti", "puja", "rekha", "sushma", "usha", "vandana",
    "varsha", "vimala", "sunita", "seema", "savita", "sarita", "sangita",
    "sonal", "sonia", "swati", "tanvi", "tanya", "trisha", "uma",
    "priti", "preethi", "rashmi", "radha", "revathi", "rupal", "rupali",
    "manisha", "madhuri", "lata", "lakshmi", "lalitha", "komal", "kiran",
    "kajal", "jyoti", "jyothi", "indu", "hema", "geeta", "geetha",
    "gayatri", "deepa", "deepika", "deeksha", "chitra", "chaya", "bhavna",
    "bhavana", "asha", "archana", "aradhana", "ankita", "anita", "anjali",
    "anisha", "anusha", "aparna", "aarti", "aaradhya",
}


def detect_customer_gender(name: str) -> str:
    """
    Heuristic gender detection from Indian customer names.
    Returns 'male', 'female', or 'unknown'.
    """
    if not name:
        return "unknown"
    n = name.strip().lower().split()[0]   # use first name only
    if n in _KNOWN_MALE_NAMES:
        return "male"
    if n in _KNOWN_FEMALE_NAMES:
        return "female"
    # Fallback: name-ending heuristic
    for ending in _MALE_NAME_ENDINGS:
        if n.endswith(ending):
            return "male"
    return "unknown"


def pick_agent_persona(customer_gender: str) -> dict:
    """
    Pick a random agent name and TTS voice.
    - Prefers OPPOSITE gender voice for the agent (sounds more natural).
    - Falls back to any voice if gender is unknown (50/50 random).

    Returns dict with keys: agent_name, agent_gender, tts_speaker
    """
    if customer_gender == "male":
        # Customer is male → prefer female agent voice
        agent_gender = "female"
        agent_name   = random.choice(AGENT_FEMALE_NAMES)
        tts_speaker  = random.choice(TTS_FEMALE_VOICES)
    elif customer_gender == "female":
        # Customer is female → prefer male agent voice
        agent_gender = "male"
        agent_name   = random.choice(AGENT_MALE_NAMES)
        tts_speaker  = random.choice(TTS_MALE_VOICES)
    else:
        # Gender unknown → random 70% female / 30% male (female voice generally
        # perceived as warmer for sales)
        if random.random() < 0.70:
            agent_gender = "female"
            agent_name   = random.choice(AGENT_FEMALE_NAMES)
            tts_speaker  = random.choice(TTS_FEMALE_VOICES)
        else:
            agent_gender = "male"
            agent_name   = random.choice(AGENT_MALE_NAMES)
            tts_speaker  = random.choice(TTS_MALE_VOICES)

    return {
        "agent_name":   agent_name,
        "agent_gender": agent_gender,
        "tts_speaker":  tts_speaker,
    }


# ─── Subscription Plan Facts ───────────────────────────────────────────────
SUBSCRIPTION_FACTS = {
    "price": "One-time lifetime subscription: $100 (USD) or ₹10,000 (INR)",
    "profit_sharing": "50/50 profit split between client and program",
    "setup_time": "5 minutes to 24 hours",
    "starting_capital": "$500 to $1,000 on a cent account",
    "operation": "24 hours a day, 5 days a week",
    "daily_growth": "0.75% to 1.5% targeted daily growth",
    "monthly_returns": "15% to 25% historical monthly returns",
    "accuracy": "~60% approximate accuracy",
    "drawdown": "5% to 10% drawdown control",
    "risk_cap": "4% to 5% risk cap",
}

# ─── Risk Disclaimer ───────────────────────────────────────────────────────
RISK_DISCLAIMER = (
    "Past performance does not guarantee future results, "
    "and trading always carries risk."
)
RISK_DISCLAIMER_HI = (
    "पिछला प्रदर्शन भविष्य के परिणामों की गारंटी नहीं देता, "
    "और ट्रेडिंग में हमेशा जोखिम रहता है।"
)

# ─── Language Configuration ────────────────────────────────────────────────
SUPPORTED_LANGUAGES = {
    "hi-IN": "Hindi",
    "en-IN": "English (India)",
    "kn-IN": "Kannada",
    "te-IN": "Telugu",
    "ml-IN": "Malayalam",
    "ta-IN": "Tamil",
    "mr-IN": "Marathi",
    "hi-EN": "Hinglish (Hindi-English mix)",
    "unknown": "Auto-detect",
}

DEFAULT_LANGUAGE = "en-IN"
DEFAULT_TTS_SPEAKER = "ritu"  # valid bulbul:v3 default

# ─── Placeholder names that mean "name is unknown" ─────────────────────────
UNKNOWN_NAME_PLACEHOLDERS = {
    "customer", "test customer", "browser user", "user", "unknown", "",
}

# ─── Opening Greeting — Always Kannada first, then ask preferred language ────────
# Winners Paradise is based in Bengaluru — every call opens in Kannada.
# Two-sentence opener: (1) warm intro + hook, (2) ask language preference.
# Semi-formal, professional and warm. {customer_name} and {agent_name} injected at runtime.

OPENING_GREETING_WITH_NAME = (
    "Say exactly this opening in warm semi-formal Bengaluru-style Kannada with natural English mixing. "
    "Sound genuinely enthusiastic and conversational. "
    "'{customer_name} ಅವರೇ, ನಮಸ್ಕಾರ! ನಾನು {agent_name}, Winners Paradise ನಿಂದ ಮಾತಾಡ್ತಿದ್ದೇನೆ. "
    "ನಿಮಗೊಂದು really exciting Gold and Forex trading opportunity ಬಗ್ಗೆ ಹೇಳಕ್ಕೆ call ಮಾಡಿದ್ದೇನೆ — ಒಂದ್ minute ಮಾತಾಡಬಹುದಾ?' "
    "— say exactly these sentences in warm Kannada, nothing more. Wait for their response."
)

OPENING_GREETING_NO_NAME = (
    "Say exactly this in warm semi-formal Bengaluru-style Kannada with natural English mixing. "
    "Sound genuinely warm and enthusiastic. "
    "'ನಮಸ್ಕಾರ! ನಾನು {agent_name}, Winners Paradise ನಿಂದ ಮಾತಾಡ್ತಿದ್ದೇನೆ. "
    "ನಿಮಗೊಂದು really exciting opportunity ಬಗ್ಗೆ ಹೇಳಕ್ಕೆ call ಮಾಡಿದ್ದೇನೆ — "
    "ಮೋದಲು ನಿಮ್ಮ ಹೆಸರು ಹೇಳ್ತೀರಾ please?' "
    "— say only these sentences, sound warm and professional, then wait for their name."
)

# ─── Language-acknowledgement lines (used internally after language switch) ───────────
GREETINGS = {
    "hi-IN": (
        "The customer chose Hindi. Warmly acknowledge in semi-formal Hinglish and ask how they are: "
        "'{customer_name} जी, बहुत अच्छा! Hindi में बात करते हैं — आप कैसे हैं?' "
        "— say only this one line, warm and professional."
    ),
    "en-IN": (
        "The customer chose English. Warmly acknowledge in semi-formal Indian English and ask how they are: "
        "'Great {customer_name}! Let's talk in English — how are you doing today?' "
        "— say only this one line, warm and professional."
    ),
    "kn-IN": (
        "The customer chose Kannada. Warmly acknowledge in semi-formal Bengaluru Kannada and ask how they are: "
        "'{customer_name} ಅವರೇ, ತುಂಬಾ ಧನ್ಯವಾದ! Kannada ನಲ್ಲಿ ಮಾತಾಡೋಣ — ಹೇಗಿದ್ದೀರಾ?' "
        "— say only this one line, warm and professional."
    ),
    "te-IN": (
        "The customer chose Telugu. Warmly acknowledge in semi-formal Telugu and ask how they are: "
        "'{customer_name} గారೂ, చాలా సరే! Telugu లో మాట్లాడదాం — ఎలా ఉన్నారు?' "
        "— say only this one line, warm and professional."
    ),
    "ml-IN": (
        "The customer chose Malayalam. Warmly acknowledge in semi-formal Malayalam and ask how they are: "
        "'{customer_name}, വളരെ നന്നി! Malayalam ഥ് സംസാരിക്കാം — എങ്ങനെ ഉണ്ട്?' "
        "— say only this one line, warm and professional."
    ),
    "ta-IN": (
        "The customer chose Tamil. Warmly acknowledge in semi-formal Tamil and ask how they are: "
        "'{customer_name}, மிக்க எழிலானது! Tamil ல பேசலாம் — எப்படி இருக்கீங்க?' "
        "— say only this one line, warm and professional."
    ),
    "mr-IN": (
        "The customer chose Marathi. Warmly acknowledge in simple Marathi and ask how they are: "
        "'{customer_name}, namaskar! Marathi madhye bolu ya - tumhi kase aahat?' "
        "- say only this one line, warm and professional."
    ),
    "hi-EN": (
        "The customer chose Hinglish. Warmly acknowledge in semi-formal Hinglish and ask how they are: "
        "'{customer_name} जी, perfect! Hinglish में बात करते हैं — आप कैसे हैं?' "
        "— say only this one line, warm and professional."
    ),
}

# ─── Language-Aware Silence Prompts ──────────────────────────────────────────
SILENCE_PROMPTS = {
    "hi-IN": "Customer is silent. Say ONE warm short line in Hindi: 'Hello, aap call pe hain na? Mujhe sunai de raha hai kya?'",
    "en-IN": "Customer is silent. Say ONE warm short line in English: 'Hello, are you still on the call? Can you hear me?'",
    "kn-IN": "Customer is silent. Say ONE warm short line in Kannada: 'Hello, neevu call nalli iddira? Nanage kelista idya?'",
    "te-IN": "Customer is silent. Say ONE warm short line in Telugu: 'Hello, meeru call lo unnara? Naaku vinipistunda?'",
    "ml-IN": "Customer is silent. Say ONE warm short line in Malayalam: 'Hello, ningal call-il undo? Enikku kelkkaanundo?'",
    "ta-IN": "Customer is silent. Say ONE warm short line in Tamil: 'Hello, neengal call-la irukkingala? Enakku ketkudha?'",
    "mr-IN": "Customer is silent. Say ONE warm short line in Marathi: 'Hello, tumhi call var aahat ka? Mala aikoo yeta ka?'",
    "hi-EN": "Customer is silent. Say ONE warm short line in Hindi: 'Hello, aap call pe hain na? Mujhe sunai de raha hai kya?'",
}

# ─── Language-Aware Max-Duration Wrap-Up ─────────────────────────────────────────
WRAPUP_PROMPTS = {
    "hi-IN": "Wrap up in ONE warm Hinglish line: 'जी, details अभी WhatsApp पे भेज देती/देता हूँ — आपका वक़्त लेने के लिए बहुत शुक्रिया!' Then stop.",
    "en-IN": "Wrap up in ONE warm English line: 'I'll send you all the details on WhatsApp right now — thank you so much for your time today!' Then stop.",
    "kn-IN": "Wrap up in ONE warm Kannada line: 'Details ಈಗಲೇ WhatsApp ಲ್ಲಿ ಕಳಿಸ್ತೇನೆ — ನಿಮಗೆ time ಕೊಟ್ಟಿದ್ದಕ್ಕೆ ತುಂಬಾ ಧನ್ಯವಾದಗಳು!' Then stop.",
    "te-IN": "Wrap up in ONE warm Telugu line: 'Details ఇప్పుడే WhatsApp లో పంపిస్తాను — సమయం ఇచ్చారికి చాలా ధన్యవాదాలు!' Then stop.",
    "ml-IN": "Wrap up in ONE warm Malayalam line: 'Details ഇപ്പോൾ WhatsApp ഥ് അയക്കാം — സമയം തന്നതിന് വളരെ നന്ദി!' Then stop.",
    "ta-IN": "Wrap up in ONE warm Tamil line: 'Details இப்போவே WhatsApp-ல அனுப்புறேன் — உஙகள நேரத்தைக்கு மிக்க நன்றி!' Then stop.",
    "mr-IN": "Wrap up in ONE warm Marathi line: 'Details mi WhatsApp var pathvto - tumcha vel dilyabaddal khup dhanyavad!' Then stop.",
    "hi-EN": "Wrap up in ONE warm Hinglish line: 'जी, details अभी WhatsApp पे भेज देती/देता हूँ — आपका वक़्त लेने के लिए बहुत शुक्रिया!' Then stop.",
}

# ─── Call Outcome Enums ────────────────────────────────────────────────────
VALID_OUTCOMES = [
    "interested_demo_scheduled",
    "callback_requested",
    "not_interested_now",
    "dnc_requested",
    "customer_busy_reschedule",
    "wrong_number",
    "existing_customer",
    "subscribed",
]

# ─── Agent Timing Configuration ───────────────────────────────────────────
MAX_CALL_DURATION_SECONDS = 300
SILENCE_TIMEOUT_SECONDS = 30
CONVERSATION_INACTIVITY_TIMEOUT_SECONDS = 90
INACTIVITY_WATCHDOG_INTERVAL_SECONDS = 5
BATCH_STAGGER_MIN_SECONDS = 5
BATCH_STAGGER_MAX_SECONDS = 300
BATCH_STAGGER_DEFAULT_SECONDS = 30
REMINDER_CHECK_INTERVAL_SECONDS = 300

# ─── Inactive-room reaper ──────────────────────────────────────────────────
ROOM_INACTIVITY_TIMEOUT_SECONDS = 300
ROOM_REAPER_INTERVAL_SECONDS = 60
MANAGED_ROOM_PREFIXES = ("call-", "web-")
