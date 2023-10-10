"""
Scrape Piazza data.
"""
import json
import logging
import os

from dotenv import load_dotenv
from piazza_api import Piazza

dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path)

PIAZZA_USERNAME = os.environ.get("PIAZZA_USERNAME")
PIAZZA_PASSWORD = os.environ.get("PIAZZA_PASSWORD")

# TODO(michaelfromyeg): setup a better logger with function names.
logger = logging.getLogger(__name__)

def piazza() -> Piazza:
    """
    Create an authenticated Piazza instance.

    TODO(michaelfromyeg): make Singleton.
    """
    p = Piazza()
    p.user_login(email=PIAZZA_USERNAME, password=PIAZZA_PASSWORD)

    return p

def is_course(course: str) -> bool:
    """
    Check if a string is a course like <DPRT> <NUM>.
    """
    if len(course.split(" ")) != 2:
        return False
    if not course.split(" ")[1].isdigit():
        return False
    return True

def download(course: str) -> None:
    """
    Download course data from Piazza.
    """
    if not is_course(course):
        raise ValueError("`download` expects a course like <DPRT> <NUM>")

    os.makedirs(f"data/{course}", exist_ok=True)

    p = piazza()

    user_profile = p.get_user_profile()

    course_ids_in_profile = []
    for course_id, course_object in user_profile["all_classes"].items():
        if course in course_object["num"]:
            course_ids_in_profile.append(course_id)

    for course_id in course_ids_in_profile:
        os.makedirs(f"data/{course}/{course_id}", exist_ok=True)

        course_object = p.network(course_id)
        posts = course_object.iter_all_posts(sleep=5)

        for post in posts:
            # TODO(michaelfromyeg): consider truncating the post
            with open(f"data/{course_id}/{post["nr"]}.json", "w", encoding="utf-8") as f:
                f.write(json.dumps(post))
            logger.info("[download] Wrote post %s/%s", course_id, post["nr"])

        logger.info("[download] Wrote course %s", course_id)

    return None

def transform(course: str) -> None:
    """
    Pre-process the Piazza post JSON files into something that's Cohere ready.

    Cohere requires a JSONL file with entries in the form:

    {"prompt": "This is example prompt #1", "completion": "This is the completion example #1"}
    {"prompt": "This is example prompt #2", "completion": "This is the completion example #2"}
    ...
    ...
    {"prompt": "This is example prompt #N", "completion": "This is the completion example #N"}

    See more at https://txt.cohere.com/generative-ai-part-4/.
    """
    if not is_course(course):
        raise ValueError("`transform` expects a course like <DPRT> <NUM>")

    if not os.path.exists(f"data/{course}"):
        raise ValueError(f"Course {course} not downloaded yet. Run `download` first.")

    p = piazza()

    user_profile = p.get_user_profile()

    course_ids_in_profile = []
    for course_id, course_object in user_profile["all_classes"].items():
        if course in course_object["num"]:
            course_ids_in_profile.append(course_id)

    for course_id in course_ids_in_profile:
        os.makedirs(f"data/{course_id}", exist_ok=True)

        course_object = p.network(course_id)
        posts = course_object.iter_all_posts(sleep=5)

        for post in posts:


def main() -> None:
    """
    Main function.
    """
    # TODO(michaelfromyeg): make command-line argument
    course = "CPSC 213"

    # download()

    transform(course)

    return None

if __name__ == "__main__":
    main()
