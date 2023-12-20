"""
Scrape Piazza data.
"""
import argparse
import json
import logging
import os
from typing import Any

import html2text

# import chromadb
from dotenv import load_dotenv
from langchain import hub
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from langchain.chains import RetrievalQA
from langchain.chat_models import ChatOllama
from langchain.embeddings import OllamaEmbeddings
from langchain.vectorstores import Chroma
from langchain_core.documents import Document
from piazza_api import Piazza

from .piazzaloader import PiazzaLoader

h = html2text.HTML2Text()
h.ignore_links = True

CWD = os.getcwd()

dotenv_path = os.path.join(CWD, ".env")
load_dotenv(dotenv_path)

PIAZZA_USERNAME = os.environ.get("PIAZZA_USERNAME")
PIAZZA_PASSWORD = os.environ.get("PIAZZA_PASSWORD")

# TODO(michaelfromyeg): setup a better logger with function names.
logger = logging.getLogger(__name__)

# chroma_client = chromadb.PersistentClient(os.path.join(CWD, "vectorstore"))


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


def _transform_post(post: dict) -> list[dict]:
    """
    Transform a Piazza post into a Cohere prompt-completion pair.
    """
    transformed_posts: list[dict[str, Any]] = []

    # Extract the original question and its ID
    original_question_info: dict[str, Any] = next(
        (item for item in post.get("history", []) if item.get("subject")), {}
    )
    original_question_title = original_question_info.get("subject", "")
    original_question_content = original_question_info.get("content", "")
    original_question_id = post.get("id", "original")

    # Original question metadata
    original_question_metadata = {
        "is_follow_up": False,
        "upvotes": post.get("num_favorites", 0),  # Assuming 'num_favorites' as upvotes
    }

    # Check if the original question has an instructor answer
    instructor_answer = next(
        (
            child.get("history", [{}])[0].get("content", None)
            for child in post.get("children", [])
            if child.get("type", "") == "i_answer"
        ),
        None,
    )

    # Original question entry
    transformed_post = {
        "question_id": original_question_id,
        "subject": original_question_title,
        "question": original_question_content,
        "answer": instructor_answer,
        "metadata": original_question_metadata,
    }
    transformed_posts.append(transformed_post)

    for child in post.get("children", []):
        if child.get("type", "") == "i_answer":
            continue

        follow_up_question_content = child.get("subject", "")
        follow_up_question_id = child.get("id", f"followup_{len(transformed_post)}")

        # Extract follow-up answer if any
        follow_up_answer = next(
            (
                child_answer.get("subject", "")
                for child_answer in child.get("children", [])
            ),
            None,
        )

        # Follow-up question metadata
        follow_up_question_metadata = {
            "is_follow_up": True,
            "upvotes": child.get("num_favorites", 0),
            "original_question_id": original_question_id,
        }

        # Follow-up question entry
        transformed_posts.append(
            {
                "question_id": follow_up_question_id,
                "question": follow_up_question_content,
                "answer": follow_up_answer,
                "metadata": follow_up_question_metadata,
            }
        )

    return transformed_posts


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

    transformed_course_path = os.path.join(CWD, "transformed_data", tidy_course)

    remove_all_files_in_folder(transformed_course_path)

    for course_id in course_ids_in_profile:
        logger.debug("[transform] Transforming course instance %s", course_id)

        course_instance_path = os.path.join(course_path, course_id)
        if not (
            os.path.exists(course_instance_path) or os.path.isdir(course_instance_path)
        ):
            raise ValueError(
                f"Course instance {course_id} not downloaded yet. Run `download` first."
            )

        transformed_course_instance_path = os.path.join(
            transformed_course_path, course_id
        )
        os.makedirs(transformed_course_instance_path, exist_ok=True)
        for piazza_file in os.listdir(course_instance_path):
            piazza_file_path = os.path.join(course_instance_path, piazza_file)
            with open(piazza_file_path, "r", encoding="utf-8") as f:
                post = json.load(f)

                transformed_posts = _transform_post(post)

            for i, transformed_post in enumerate(transformed_posts):
                if (
                    transformed_post.get("question", "") == ""
                    or transformed_post.get("answer", "") == ""
                ):
                    continue

                basename = os.path.splitext(piazza_file)[0]
                transformed_piazza_file_path = os.path.join(
                    transformed_course_instance_path, f"{basename}-{i}.json"
                )
                with open(transformed_piazza_file_path, "w", encoding="utf-8") as f:
                    f.write(json.dumps(transformed_post))

    logger.info("[transform] Wrote transformed course %s", course)


def answer(course: str, question: str, should_vectorize: bool = False) -> None:
    """
    Answer a question about a course.
    """
    vectorstore_path = os.path.join(CWD, "vectorstore")
    # collection = chroma_client.get_or_create_collection("vectorstore")

    if should_vectorize:
        loader = PiazzaLoader(tidy(course))

        sessions = loader.load()

        # Hard reset cause LLM be weird
        remove_all_files_in_folder("vectorstore")

        # print(sessions)

        all_splits: list[str] = []
        for session in sessions:
            for message in session["messages"]:  # type: ignore
                all_splits.append(h.handle((str(message.content))))

        # print(all_splits)

        vectorstore = Chroma.from_documents(
            documents=[Document(page_content=split) for split in all_splits],
            embedding=OllamaEmbeddings(model="mistral"),
            persist_directory=vectorstore_path,
        )
    else:
        vectorstore = Chroma(
            embedding=OllamaEmbeddings(model="mistral"),
            persist_directory=vectorstore_path,
        )

    rag_prompt: str = hub.pull("rlm/rag-prompt")
    llm = ChatOllama(model="mistral", callbacks=[StreamingStdOutCallbackHandler()])

    qa_chain = RetrievalQA.from_chain_type(
        llm,
        retriever=vectorstore.as_retriever(search_kwargs={"k": 3}),
        chain_type_kwargs={"prompt": rag_prompt},
    )
    return qa_chain({"query": question})["result"]


def remove_all_files_in_folder(folder: str) -> None:
    """
    Remove all files in a folder.
    """
    for filename in os.listdir(folder):
        if filename == ".gitkeep":
            continue

        file_path = os.path.join(folder, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.remove(file_path)
            elif os.path.isdir(file_path):
                remove_all_files_in_folder(file_path)
                os.rmdir(file_path)
        except Exception as e:
            print(f"Failed to delete {file_path} due to {e}")


def main() -> None:
    """
    Main function.
    """
    parser = argparse.ArgumentParser(description="Process course data.")

    parser.add_argument("course", type=str, help="Specify the course (e.g., CPSC 213)")
    parser.add_argument("--download", action="store_true", help="Download files")
    parser.add_argument("--transform", action="store_true", help="Transform files")
    parser.add_argument("--vectorize", action="store_true", help="Vectorize files")

    args = parser.parse_args()

    course = args.course
    should_download, should_transform, should_vectorize = (
        args.download,
        args.transform,
        args.vectorize,
    )

    if should_download:
        download(course)

    if should_transform:
        transform(course)

    answer(course, "What is a pointer?", should_vectorize)

    return None


if __name__ == "__main__":
    main()
