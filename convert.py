#!/usr/bin/env python
from argparse import ArgumentParser
from datetime import datetime
from os import listdir
from os.path import join as ospj
import re

import bs4

AUTHOR_INFO = re.compile(r'(?P<name>\w+) \| (?P<month>\d{2})/(?P<day>\d{2})/'
    r'(?P<year>\d{4}) - (?P<hour>\d{2}):(?P<minute>\d{2})')
AUTHOR_DATE_FIELDS = ['year', 'month', 'day', 'hour', 'minute']

class Story:
    def __init__(self, text, author, date):
        self.text = text
        self.author = author
        self.date = date

HTML_FILE_EXTENSION = '.html'
def find_html_files(directory):
    # I'm inclined to use a generator for os.walk usage, but listdir
    # already returns a list so there isn't much benefit here
    return [ospj(directory, filename) for filename in listdir(directory)
        if filename.endswith(HTML_FILE_EXTENSION)]

def parse_story_file(filename):
    print('Parsing {}'.format(filename))
    with open(filename) as f:
        s = bs4.BeautifulSoup(f)
    # The first div with class nodeContents contains the story;
    # the first p element inside here is the actual story text.
    story_paragraphs = s.find('div', {'class': 'nodeContents'}).find_all('p')[:-1]
    story_text = '\n'.join(str(p) for p in story_paragraphs)
    raw_author_data = s.find('div', {'class': 'nodeCredits'}).text
    m = AUTHOR_INFO.match(raw_author_data)
    if m:
        author_name = m.group('name')
        date_data = [int(m.group(field)) for field in AUTHOR_DATE_FIELDS]
        print('Date data: {!r}'.format(date_data))
        date = datetime(*date_data)
        return Story(story_text, author_name, date)

if __name__ == '__main__':
    p = ArgumentParser()
    p.add_argument('directory')
    args = p.parse_args()
    stories = []
    for html_file in find_html_files(args.directory):
        s = parse_story_file(html_file)
        if s:
            stories.append(s)
    print('Parsed {} stories'.format(len(stories)))
