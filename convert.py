#!/usr/bin/env python
from argparse import ArgumentParser
from datetime import datetime
from os import listdir
import re

import bs4

AUTHOR_INFO = re.compile(r'(?P<name>\w+) \| (?P<day>\d{2})/(?P<month>\d{2})/'
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
    return [filename for filename in listdir(directory)
        if filename.endswith(HTML_FILE_EXTENSION)]

def parse_story_file(filename):
    with open(filename) as f:
        s = bs4.BeautifulSoup(f.read())
        # The first div with class nodeContents contains the story;
        # the first p element inside here is the actual story text.
        story_text = s.find('div', {'class': 'nodeContents'}).p.text
        raw_author_data = s.find('div', {'class': 'nodeCredits'}).text
        m = AUTHOR_INFO.match(raw_author_data)
        if m:
            author_name = m.group('name')
            date_data = [int(m.group(field)) for field in AUTHOR_DATE_FIELDS]
            date = datetime(*date_data)
            return Story(story_text, author_name, date)

if __name__ == '__main__':
    p = ArgumentParser()
    p.add_argument('directory')
    args = p.parse_args()
