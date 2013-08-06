#!/usr/bin/env python
from argparse import ArgumentParser
from datetime import datetime
from os import listdir
from os.path import join as ospj
import re
import unicodedata

import bs4

AUTHOR_INFO = re.compile(r'(?P<name>\w+) \| (?P<month>\d{2})/(?P<day>\d{2})/'
    r'(?P<year>\d{4}) - (?P<hour>\d{2}):(?P<minute>\d{2})')
AUTHOR_DATE_FIELDS = ['year', 'month', 'day', 'hour', 'minute']

class Author:
    def __init__(self, name):
        self.name = name
        self.stories = []

class AuthorDict(dict):
    def __missing__(self, author_name):
        author = self[author_name] = Author(author_name)
        return author

class Story:
    def __init__(self, text, author, date):
        self.text = text
        self.author = author
        self.date = date
        # Stand-in for a database PK
        self.index = None

HTML_FILE_EXTENSION = '.html'
def find_html_files(directory):
    # I'm inclined to use a generator for os.walk usage, but listdir
    # already returns a list so there isn't much benefit here
    return [ospj(directory, filename) for filename in listdir(directory)
        if filename.endswith(HTML_FILE_EXTENSION)]

def looks_like_story_file(s):
    """
    :param s: BeautifulSoup object
    """
    credits_nodes = s.find_all('div', {'class': 'nodeCredits'})
    return credits_nodes is not None and len(credits_nodes) == 1

def safe_unicode_name(char):
    try:
        return unicodedata.name(char)
    except ValueError:
        return '<no name>'

SURROGATE_ESCAPES = re.compile('([\udc80-\udcff])')
def surrogate_cp1252_replace(match):
    byte = match.group(1).encode(errors='surrogateescape')
    char = byte.decode('cp1252')
    print('Replacing raw byte {} with character {} ({})'.format(hex(byte[0]),
        char, safe_unicode_name(char)))
    return char

def tolerant_decode(story_data):
    """
    Most story files are valid UTF-8. However, many files have truncated UTF-8
    sequences for U+201D RIGHT DOUBLE QUOTATION MARK, and these will show up
    as '\udce2\udc80' with the 'surrogateescape' error handler. This is by far
    the most common encoding problem, so manually replace these sequences with
    the correct quote character.

    The UTF-8 encoding of U+00E0 LATIN SMALL LETTER A WITH GRAVE also seems to
    have some problems: the second byte of b'\xc3\xa0' is missing. I have manually
    verified that the cp1252 interpretation of b'\xc3' doesn't make sense in
    any of these places, so replace '\udcc3' with '\xe0' also.

    After this, replace any remaining high surrogate characters with the cp1252
    mapping of that byte.
    """
    raw_decoded = story_data.decode(errors='surrogateescape')
    fixed_quotes = raw_decoded.replace('\udce2\udc80', '\u201d')
    fixed_letter_a_grave = fixed_quotes.replace('\udcc3', '\xe0')
    # No other special cases: replace all surrogate escape chars with
    # their cp1252 interpretation
    surrogate_decoded = SURROGATE_ESCAPES.sub(surrogate_cp1252_replace,
        fixed_letter_a_grave)
    return surrogate_decoded

def parse_story_file(filename):
    print('Parsing {}'.format(filename))
    with open(filename, 'rb') as f:
        s = bs4.BeautifulSoup(tolerant_decode(f.read()))
    if not looks_like_story_file(s):
        return
    # The first div with class nodeContents contains the story;
    # the first p element inside here is the actual story text.
    story_paragraphs = s.find('div', {'class': 'nodeContents'}).find_all('p')[:-1]
    story_text = '\n'.join(str(p) for p in story_paragraphs)
    raw_author_data = s.find('div', {'class': 'nodeCredits'}).text
    m = AUTHOR_INFO.match(raw_author_data)
    if m:
        author_name = m.group('name')
        date_data = [int(m.group(field)) for field in AUTHOR_DATE_FIELDS]
        date = datetime(*date_data)
        return Story(story_text, author_name, date)

def get_stories(directory):
    for html_file in find_html_files(directory):
        s = parse_story_file(html_file)
        if s:
            yield s

if __name__ == '__main__':
    p = ArgumentParser()
    p.add_argument('directory')
    args = p.parse_args()
    i = -1
    # Maps author names to Author objects, each of which
    # keeps a list of Story objects
    story_data = AuthorDict()
    for i, story in enumerate(get_stories(args.directory)):
        story.index = i
        story_data[story.author].stories.append(story)
    print('Parsed {} stories'.format(i + 1))
    print('Author count: {}'.format(len(story_data)))
