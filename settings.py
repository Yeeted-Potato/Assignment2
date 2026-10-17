#local configuration loaded from .env, which is not committed
#copy .env.example to .env and fill in the values
#dotenv is optional, so the values can also be set in the shell instead
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()
