#!/usr/bin/env python
from argparse import ArgumentParser
from datetime import datetime
from functools import reduce
from operator import attrgetter
from os import listdir, makedirs
from os.path import isfile, join as ospj
import pickle
import re
import unicodedata

import bs4
import jinja2

PICKLE_FILENAME = 'stories.pickle'
OUTPUT_DIR = 'output'

AUTHOR_INFO = re.compile(r'(?P<name>\w+) \| (?P<month>\d{2})/(?P<day>\d{2})/'
    r'(?P<year>\d{4}) - (?P<hour>\d{2}):(?P<minute>\d{2})')
AUTHOR_DATE_FIELDS = ['year', 'month', 'day', 'hour', 'minute']

class Author:
    def __init__(self, name):
        self.name = name
        self.stories = []
        self.index = None

class AuthorDict(dict):
    def __missing__(self, author_name):
        author = self[author_name] = Author(author_name)
        return author

class Story:
    def __init__(self, text, title, author_name, date):
        self.text = text
        self.title = title
        self.author_name = author_name
        self.date = date
        self.author = None
        # Stand-in for a database PK
        self.index = None

    def __repr__(self):
        return '<{} {}: "{}", {}>'.format(self.__class__.__name__,
            self.author_name, self.title, self.date)

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
    title = s.find('h2', {'class': 'title'}).text
    raw_author_data = s.find('div', {'class': 'nodeCredits'}).text
    m = AUTHOR_INFO.match(raw_author_data)
    if m:
        author_name = m.group('name')
        date_data = [int(m.group(field)) for field in AUTHOR_DATE_FIELDS]
        date = datetime(*date_data)
        return Story(story_text, title, author_name, date)

def get_stories(directory):
    for html_file in find_html_files(directory):
        s = parse_story_file(html_file)
        if s:
            yield s

class StoryRenderer:
    def __init__(self, story_data):
        self.story_data = story_data
        self.env = jinja2.Environment(loader=jinja2.FileSystemLoader('templates'),
            keep_trailing_newline=True)
        self.sorted_authors = sorted(story_data.values(), key=attrgetter('index'))

    def render_author_list(self):
        filename = 'authors.html'
        template = self.env.get_template(filename)
        with open(ospj(OUTPUT_DIR, filename), 'w') as f:
            print(template.render(authors=enumerate(self.sorted_authors)), file=f)

    def render_all_stories(self):
        filename = 'stories_all.html'
        template = self.env.get_template(filename)
        stories = []
        for author in self.story_data.values():
            stories.extend(author.stories)
        stories.sort(key=attrgetter('date'))
        with open(ospj(OUTPUT_DIR, filename), 'w') as f:
            print(template.render(stories=stories), file=f)

    def render_stories_by_author(self):
        pass

    def render_story(self, story):
        pass

def convert_html_files(directory):
 # Maps author names to Author objects, each of which
    # keeps a list of Story objects
    story_data = AuthorDict()
    i = j = -1
    for i, story in enumerate(get_stories(directory)):
        story.index = i
        story_data[story.author_name].stories.append(story)
        story.author = story_data[story.author_name]
    for j, author in enumerate(sorted(story_data, key=lambda s: s.lower())):
        author.index = j
    print('Parsed {} stories by {} authors'.format(i + 1, j + 1))
    return story_data

def render_output(story_data):
    renderer = StoryRenderer(story_data)
    renderer.render_author_list()
    renderer.render_all_stories()
    renderer.render_stories_by_author()

if __name__ == '__main__':
    if isfile(PICKLE_FILENAME):
        print('Loading story data from {}'.format(PICKLE_FILENAME))
        with open(PICKLE_FILENAME, 'rb') as f:
            story_data = pickle.load(f)
    else:
        p = ArgumentParser()
        p.add_argument('directory')
        args = p.parse_args()
        story_data = convert_html_files(args.directory)
        print('Saving story data to {}'.format(PICKLE_FILENAME))
        with open(PICKLE_FILENAME, 'wb') as f:
            pickle.dump(story_data, f)
    makedirs(OUTPUT_DIR, exist_ok=True)
    render_output(story_data)
