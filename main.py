"""
Scrape Piazza data.
"""
import json
import os

from dotenv import load_dotenv
from piazza_api import Piazza

os.makedirs("data", exist_ok=True)

dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path)


PIAZZA_USERNAME = os.environ.get("PIAZZA_USERNAME")
PIAZZA_PASSWORD = os.environ.get("PIAZZA_PASSWORD")

p = Piazza()
p.user_login(email=PIAZZA_USERNAME, password=PIAZZA_PASSWORD)

user_profile = p.get_user_profile()

# Find CPSC 210 instances from user profile
cpsc213_ids = []
for course_id, course_object in user_profile["all_classes"].items():
    if "CPSC 213" in course_object["num"]:
        cpsc213_ids.append(course_id)

for cpsc213_id in cpsc213_ids:
    os.makedirs(f"data/{cpsc213_id}", exist_ok=True)

    cpsc213 = p.network(cpsc213_id)
    posts = cpsc213.iter_all_posts(sleep=5)

    for post in posts:
        # post_truncated = {
        #     "content": post["history"][0]["content"],
        #     "created": post["created"],
        #     "nr": post["nr"],
        #     "subject": post["history"][0]["subject"],
        # }

        with open(f"data/{cpsc213_id}/{post["nr"]}.json", "w", encoding="utf-8") as f:
            f.write(json.dumps(post))
