# firebase_init.py
import os
import firebase_admin
from firebase_admin import credentials

# Path to your downloaded JSON file
CREDENTIALS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),  # project root
    'mohmt-f7d7c-firebase-adminsdk-fbsvc-859f537833.json'
)

if not firebase_admin._apps:  # only initialize once
    cred = credentials.Certificate(CREDENTIALS_PATH)
    firebase_admin.initialize_app(cred)
    print("Firebase Admin SDK initialized successfully")
else:
    print("Firebase Admin SDK already initialized")