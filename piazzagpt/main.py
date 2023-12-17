"""
Scrape Piazza data.
"""
import argparse
import json
import logging
import os

from dotenv import load_dotenv
from piazza_api import Piazza

CWD = os.getcwd()

dotenv_path = os.path.join(CWD, ".env")
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


def tidy(course: str) -> str:
    """
    Convert a course like <DPRT> <NUM> to <dprt><num>
    """
    return course.replace(" ", "").lower()


def download(course: str) -> None:
    """
    Download course data from Piazza.
    """
    if not is_course(course):
        raise ValueError("`download` expects a course like <DPRT> <NUM>")

    course_tidy = tidy(course)

    course_path = os.path.join(CWD, "data", course_tidy)
    os.makedirs(course_path, exist_ok=True)

    p = piazza()

    user_profile = p.get_user_profile()

    course_ids_in_profile = []
    for course_id, course_object in user_profile["all_classes"].items():
        if course in course_object["num"]:
            course_ids_in_profile.append(course_id)

    for course_id in course_ids_in_profile:
        course_id_path = os.path.join(course_path, course_id)
        os.makedirs(course_id_path, exist_ok=True)

        course_object = p.network(course_id)
        posts = course_object.iter_all_posts(sleep=5)

        for post in posts:
            # TODO(michaelfromyeg): consider truncating the post on initial save
            post_path = os.path.join(course_id_path, f"{post['nr']}.json")
            with open(post_path, "w", encoding="utf-8") as f:
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

    tidy_course = tidy(course)
    course_path = os.path.join(CWD, "data", tidy_course)

    if not os.path.exists(course_path):
        raise ValueError(f"Course {course} not downloaded yet. Run `download` first.")

    p = piazza()

    user_profile = p.get_user_profile()

    course_ids_in_profile = []
    for course_id, course_object in user_profile["all_classes"].items():
        if course in course_object["num"]:
            course_ids_in_profile.append(course_id)

    for course_id in course_ids_in_profile:
        print(course_id)

        # TODO(michaelfromyeg): process course's json posts into better format


def main() -> None:
    """
    Main function.
    """
    parser = argparse.ArgumentParser(description="Process course data.")

    parser.add_argument("course", type=str, help="Specify the course (e.g., CPSC 213)")
    parser.add_argument(
        "--download", action="store_true", help="Specify to download files"
    )

    args = parser.parse_args()

    course = args.course
    should_download = args.download

    if should_download:
        download(course)

    transform(course)

    return None


if __name__ == "__main__":
    main()
