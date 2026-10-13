import os

# LiteLLM fetches its model price list from the internet on import unless told not to.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
