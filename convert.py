#!/usr/bin/env python3
from argparse import ArgumentParser
from datetime import datetime
from math import ceil, log10
from operator import attrgetter
from os import listdir, makedirs
from os.path import isfile, join as ospj
import pickle
import re
import sys
import unicodedata

import bs4
import jinja2

PICKLE_FILENAME = 'stories.pickle'
OUTPUT_DIR = 'output'

AUTHOR_INFO = re.compile(r'(?P<name>.+?) \| (?P<month>\d{2})/(?P<day>\d{2})/'
    r'(?P<year>\d{4}) - (?P<hour>\d{2}):(?P<minute>\d{2})')
AUTHOR_DATE_FIELDS = ['year', 'month', 'day', 'hour', 'minute']
INTEGER_PATTERN = re.compile(r'(\d+)')
WHITESPACE = re.compile(r'\s+')
LEADING_NON_DIGITS = re.compile(r'^([^\d]+)')

def find_integer(string):
    s = INTEGER_PATTERN.search(string)
    if s:
        return int(s.group(1))

def story_title_sort_key(title):
    """
    Returns a 3-tuple sort key for story titles:

    [0] is any leading non-digit characters
    [1] is the first integer that can be parsed from the title, to make
        80 sort before 9
    [2] is the unchanged title, in case of a tie in the first two items
    """
    title = title.lower().strip()
    maybe_leading_non_digits = LEADING_NON_DIGITS.search(title)
    if maybe_leading_non_digits is None:
        leading_non_digits = ''
    else:
        leading_non_digits = maybe_leading_non_digits.group(0)
    integer = find_integer(title) or 0
    return leading_non_digits, integer, title

def is_valid_filesystem_char(char: str):
    """
    Preserve anything that's a letter, number or whitepsace. There are
    many more valid characters than this, but I want to be conservative
    so that these filenames work on Windows.
    """
    return unicodedata.category(char)[0] in {'L', 'N', 'Z'}

def sanitize_for_filesystem(text: str):
    underscores_removed = text.replace('_', ' ')
    normalized = unicodedata.normalize('NFKC', underscores_removed)
    filtered = ''.join(filter(is_valid_filesystem_char, normalized)).strip()
    return WHITESPACE.sub('_', filtered)

class Author:
    def __init__(self, name):
        self.name = name
        self.stories = []
        # "Filesystem name"
        self.fs_name = sanitize_for_filesystem(self.name)

    @property
    def name_sort_key(self):
        return self.name.lower()

class AuthorDict(dict):
    def __missing__(self, author_name):
        author = self[author_name] = Author(author_name)
        return author

class Comment:
    def __init__(self, text, title, author_name, date):
        self.author_name = author_name
        self.author = None
        self.text = text
        self.title = title
        self.date = date
        self.depth = 0
        # List of Comment objects
        # Was called 'children' but calling this 'comments' makes it
        # easier to recurse in the templates. This name makes sense
        # as well since comments can be in response to other comments
        # in addition to the story
        self.comments = []

    def __repr__(self):
        return '<{} {}: "{}", {}, depth {}>'.format(self.__class__.__name__,
            self.author_name, self.title, self.date, self.depth)

class Story:
    def __init__(self, text, title, author_name, date):
        self.text = text
        self.title = title
        self.author_name = author_name
        self.date = date
        self.author = None
        # Story objects to support prev/next links in templates
        self.prev = None
        self.next = None
        self.comments = None
        # "Filesystem name": assigned in bulk, once we know how many stories each author has
        self.fs_name = None

    def __repr__(self):
        return '<{} {}: "{}", {}>'.format(self.__class__.__name__,
            self.author_name, self.title, self.date)

    @property
    def title_sort_key(self):
        return story_title_sort_key(self.title)

    @property
    def date_sort_key(self):
        """
        Return a chronological sort key, used in ordering the list of
        all stories. Fall back to the story title if dates are equal.
        """
        return self.date, self.title_sort_key

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
    if credits_nodes is None or len(credits_nodes) != 1:
        return False
    if s.find_all('link', {'type': 'application/rss+xml'}):
        return False
    if s.find_all('div', {'class': 'nodeTaxonomy'}):
        return False
    if s.find_all('div', {'class': 'poll'}):
        return False
    return True

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
    fixed_quotes_1 = raw_decoded.replace('\udce2\udc80?', '\u201d')
    fixed_quotes_2 = fixed_quotes_1.replace('\udce2\udc80', '\u201d')
    fixed_letter_a_grave = fixed_quotes_2.replace('\udcc3', '\xe0')
    fixed_unknown_sequence = fixed_letter_a_grave.replace('\udcef\udcbc', '\ufffd')
    # No other special cases: replace all surrogate escape chars with
    # their cp1252 interpretation
    surrogate_decoded = SURROGATE_ESCAPES.sub(surrogate_cp1252_replace,
        fixed_unknown_sequence)
    return surrogate_decoded

def get_comment(hr_node):
    author_info_node = hr_node.nextSibling
    title = author_info_node.nextSibling.text
    m = AUTHOR_INFO.search(str(author_info_node).strip())
    if not m:
        raise ValueError("Couldn't decode author/date of comment '{}'".format(author_info_node))
    author_name = m.group('name')
    date_data = [int(m.group(field)) for field in AUTHOR_DATE_FIELDS]
    date = datetime(*date_data)
    # Comment text seems to always be in <p> tags after the second <br/> of this div
    # node, and continues until another <br/>. Grab the second <br/> and append
    # successive nodes until finding another <br/>.
    comment_contents = []
    second_br = hr_node.findNextSiblings('br')[1]
    node = second_br.nextSibling
    while node is not None and node.name != 'br':
        if node.name is not None:
            comment_contents.append(node)
        node = node.nextSibling
    text = '\n'.join(str(c) for c in comment_contents)
    depth = 0
    if 'style' in hr_node.parent.attrs:
        margin_px = find_integer(hr_node.parent.attrs['style'])
        depth = margin_px // 25
    c = Comment(text, title, author_name, date)
    c.depth = depth
    return c

def parse_comments(comments_div_node):
    comments = [get_comment(node) for node in comments_div_node.findAll('hr')]
    # Using a list (instead of a collections.deque) as a stack here is okay since
    # we're only ever going to append and pop from the end
    stack = []
    top_level_comments = []
    for comment in comments:
        # Discard anything in the stack with a depth greater than
        # the current comment's. If we had the following depths:

        # 0
        #   1
        #   1
        #      2

        # and the current comment has depth 1, it's a child of the
        # most recent comment with depth 0 and we should discard
        # stack[1:]. If the current comment has depth 0, it by definition
        # has no parent and the entire stack should be discarded.
        del stack[comment.depth:]
        if comment.depth:
            # Now, the last element in the stack should be the parent of
            # this comment, so we should assign this as a  child of the
            # last element. It's an error for the stack to be empty if
            # the current comment's depth is nonzero, though
            assert stack, 'empty stack with depth > 0'
            stack[-1].comments.append(comment)
        else:
            # depth = 0 implies that it's a top-level comment
            top_level_comments.append(comment)
        stack.append(comment)
    return top_level_comments

def normalize_title(title):
    return WHITESPACE.sub(' ', title.strip())

def parse_story_file(filename):
    print('Parsing {}'.format(filename))
    with open(filename, 'rb') as f:
        s = bs4.BeautifulSoup(tolerant_decode(f.read()))
    if not looks_like_story_file(s):
        return
    # The first div with class nodeContents contains the story;
    # the first p element inside here is the actual story text.
    story_paragraphs = s.find('div', {'class': 'nodeContents'}).find_all('p')[:-1]
    story_text = '\n'.join(str(p).strip() for p in story_paragraphs)
    title = normalize_title(s.find('h2', {'class': 'title'}).text)
    raw_author_data = s.find('div', {'class': 'nodeCredits'}).text.strip()
    comments_parent = s.findAll('form', {'action': '?q=comment'})
    if len(comments_parent) > 1:
        comments = parse_comments(comments_parent[1].find('div'))
    else:
        comments = []
    m = AUTHOR_INFO.match(raw_author_data)
    if m:
        author_name = m.group('name')
        date_data = [int(m.group(field)) for field in AUTHOR_DATE_FIELDS]
        date = datetime(*date_data)
        story = Story(story_text, title, author_name, date)
        story.comments = comments
        return story

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
        self.sorted_authors = sorted(story_data.values(), key=attrgetter('name_sort_key'))

    def render_author_list(self):
        filename = 'authors.html'
        template = self.env.get_template(filename)
        with open(ospj(OUTPUT_DIR, filename), 'w') as f:
            print(template.render(authors=self.sorted_authors, depth=0), file=f)

    def render_story_list_all(self):
        filename = 'stories_all.html'
        template = self.env.get_template(filename)
        stories = []
        for author in self.story_data.values():
            stories.extend(author.stories)
        with open(ospj(OUTPUT_DIR, 'stories_all_date.html'), 'w') as f:
            print(template.render(stories=sorted(stories, key=attrgetter('date_sort_key')), depth=0), file=f)
        with open(ospj(OUTPUT_DIR, 'stories_all_title.html'), 'w') as f:
            print(template.render(stories=sorted(stories, key=attrgetter('title_sort_key')), depth=0), file=f)

    def render_story_list_by_author(self, author):
        subdir = ospj(OUTPUT_DIR, 'authors')
        makedirs(subdir, exist_ok=True)
        filename = '{}.html'.format(author.fs_name)
        template = self.env.get_template('stories_by_author.html')
        stories = sorted(author.stories, key=attrgetter('date_sort_key'))
        with open(ospj(subdir, filename), 'w') as f:
            print(template.render(author=author, stories=stories, depth=1), file=f)

    def render_story(self, story):
        subdir = ospj(OUTPUT_DIR, 'stories', story.author.fs_name)
        makedirs(subdir, exist_ok=True)
        filename = '{}.html'.format(story.fs_name)
        template = self.env.get_template('story.html')
        with open(ospj(subdir, filename), 'w') as f:
            print(template.render(story=story, depth=2), file=f)

def assign_comments(story_data, entry):
    for comment in entry.comments:
        if comment.author_name in story_data:
            comment.author = story_data[comment.author_name]
        assign_comments(story_data, comment)

def convert_html_files(directory):
    """
    Parses HTML files found in 'directory', populating
    internal data structures with the text read from each.
    """
    # Maps author names to Author objects, each of which
    # keeps a list of Story objects
    story_data = AuthorDict()
    i = j = -1
    for i, story in enumerate(get_stories(directory)):
        story_data[story.author_name].stories.append(story)
        story.author = story_data[story.author_name]
    for j, author_name in enumerate(sorted(story_data, key=str.lower)):
        s = sorted(story_data[author_name].stories, key=attrgetter('date'))
        digits = ceil(log10(len(s) + 1))
        for k, story in enumerate(s, 1):
            story.fs_name = '{:0{}}-{}'.format(k, digits, sanitize_for_filesystem(story.title))
        # Assign prev/next as appropriate
        # TODO generalize this to avoid len == 2 vs. len > 2
        if len(s) >= 2:
            s[0].next = s[1]
            s[-1].prev = s[-2]
            if len(s) > 2:
                for prev, cur, next in zip(s[:-2], s[1:-1], s[2:]):
                    cur.prev = prev
                    cur.next = next
    for j, author in enumerate(story_data.values()):
        for story in author.stories:
            assign_comments(story_data, story)
    print('Parsed {} stories by {} authors'.format(i + 1, j + 1))
    return story_data

def render_output(story_data):
    # TODO refactor this
    renderer = StoryRenderer(story_data)
    renderer.render_author_list()
    renderer.render_story_list_all()
    for author in story_data.values():
        renderer.render_story_list_by_author(author)
        for story in author.stories:
            renderer.render_story(story)

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
            # HACK: the addition of prev/next links in the Story
            # objects has added a ton of recursion in the pickle
            # module. Increase the recursion limit to allow this.
            sys.setrecursionlimit(25000)
            pickle.dump(story_data, f)
    makedirs(OUTPUT_DIR, exist_ok=True)
    render_output(story_data)
