import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup

from notes_data import notes, book_path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATE_PATTERN_TO_REMOVE = "\\b\\d{1,2}\\s+(January|February|March|April|May|June|July|August|September|October|November|December)\\s+\\d{4}\\b"
NUM_FIRST_CHARS_TO_LOOKUP = 55
total_not_found = 0


def remove_dates(notes):
    lines = []
    skipped_lines = set()
    for line in notes.splitlines():
        if re.findall(DATE_PATTERN_TO_REMOVE, line[:20]):
            skipped_lines.add(line)
            continue

        lines.append(line)

    logger.info(f"skipped: {skipped_lines}")
    return lines


@dataclass
class SearchResult:
    chapter_title: str = ''
    txt_idx: int = -1
    file_idx: int = -1
    file_name: str = ''


class EpubUtils:
    @classmethod
    def find_chapter_containing_text_in_epub(cls, text, zip_ref, file_start_idx=0) -> SearchResult:
        global total_not_found

        # iterate files in the epub
        namelist = zip_ref.namelist()
        for file_idx in range(file_start_idx, len(namelist)):
            file_name = namelist[file_idx]
            if not file_name.endswith(('.html', '.xhtml')):
                continue

            with zip_ref.open(file_name) as file:
                soup = BeautifulSoup(file.read(), 'html.parser')
                # soup_text = soup.get_text()
                # find_txt_idx = soup_text.find(text)

                soup_text = soup.get_text(separator=" ")
                normalized_soup_text = re.sub(r'\s+', ' ', soup_text).strip()
                normalized_soup_text = re.sub(r'\s+([.,:;!?’\'])', r'\1', normalized_soup_text)
                normalized_target = re.sub(r'\s+', ' ', text).strip()
                find_txt_idx = normalized_soup_text.find(normalized_target)
                # logger.info(normalized_soup_text)

                if find_txt_idx != -1:
                    chapter_titles = []

                    # note: chapter title in some books may be in 'h1',
                    # in others in 'title' (though sometimes 'title' is the book title)

                    # if book title is printed - may comment this out
                    title_from_head = soup.find('title')
                    if title_from_head and title_from_head.text:
                        chapter_titles.append(title_from_head.text)

                    # add chapter title from h tags
                    h_tags = soup.find_all(['h1', 'h2', 'h3'])
                    chapter_titles.extend([title.text for title in h_tags])

                    chapter_title = " | ".join(chapter_titles)
                    search_res = SearchResult(chapter_title, find_txt_idx, file_idx, file_name.split('/')[-1])
                    # logger.info(f"{text}, {chapter_title}, {find_txt_idx}, {file_idx} {file_name}")
                    return search_res

        total_not_found += 1
        logger.warning(f"Could not find chapter containing text (start idx: {file_start_idx}):\n{text}")
        return SearchResult()


def process_notes(notes, book_path):
    if not Path(book_path).exists():
        logger.error(f"book_path not found: {book_path}")
        return
    if not notes.strip():
        logger.error("empty notes")
        return

    lines = remove_dates(notes)

    result = []
    prev_chapter_title = ''

    # a chapter might be spread on multiple files, e.g 'ch04.xhtml' and 'ch04a.xhtml'
    chapter_to_paragraphs = dict()

    with zipfile.ZipFile(book_path, 'r') as zip_ref:
        for line in lines:
            if not line:
                continue

            lookup_txt = line[:NUM_FIRST_CHARS_TO_LOOKUP]
            # file_start_idx = max(0, prev_file_idx - 1) # this optimization attempt is not working well
            file_start_idx = 0
            search_res = EpubUtils.find_chapter_containing_text_in_epub(lookup_txt, zip_ref, file_start_idx)

            chapter_name = search_res.chapter_title

            if search_res.txt_idx > 0:
                if not chapter_name:
                    logger.warning(
                        f"no chapter_name found. lookup_txt='{lookup_txt}', {search_res}. using prev_chapter_title='{prev_chapter_title}'")
                    chapter_name = prev_chapter_title
                    line = f"? {line}"
                    # if len(chapter_to_paragraphs[chapter_name]) <= 1:
                    #     # if only one paragraph for prev chapter, maybe current line is from prev chapter

                if chapter_name not in chapter_to_paragraphs:
                    chapter_to_paragraphs[chapter_name] = []

                chapter_to_paragraphs[chapter_name].append([line, search_res.txt_idx, search_res.file_name])

                prev_chapter_title = chapter_name
            else:
                # handle not found
                if prev_chapter_title:
                    # append to previous known chapter
                    logger.warning(
                        f"add to prev_chapter_title='{prev_chapter_title}', lookup_txt={lookup_txt}, {search_res}")
                    chapter_to_paragraphs[prev_chapter_title].append([f"? {line}", -1, ''])
                else:
                    logger.warning(f"add to unknown lookup_txt='{lookup_txt}', {search_res}")
                    unknown = 'unknown'
                    if not unknown in chapter_to_paragraphs:
                        chapter_to_paragraphs[unknown] = []
                    chapter_to_paragraphs[unknown].append([f"? {line}", -1, ''])

    # add all chapters
    for chapter_name, curr_chapter_paragraphs in chapter_to_paragraphs.items():
        logger.info(f"Chapter: {chapter_name}")
        result.append(f"\n\n{chapter_name}\n")

        # add paragraphs
        _add_sorted_chapter_paragraphs(curr_chapter_paragraphs, result)

    logger.info(f"total not found: {total_not_found}")
    print("\n".join(result))
    return result


def _add_sorted_chapter_paragraphs(curr_chapter_paragraphs, result):
    # sort by file name, then by index
    curr_chapter_paragraphs.sort(key=lambda x: (x[2], x[1]))
    # logger.info(curr_chapter_paragraphs)

    # log file names
    filenames = set([x[2] for x in curr_chapter_paragraphs])
    logger.info(f"filenames={filenames}")

    # result.append("\n")
    result.append("\n\n".join([f"{x[0]}" for x in curr_chapter_paragraphs]))


if __name__ == '__main__':
    process_notes(notes, book_path)
